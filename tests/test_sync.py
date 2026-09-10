import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from weread_gateway import WeReadGateway, create_weread_client
from weread_api import WeReadAPI
import weread_notion_sync_api as sync
from weread_notion_sync import build_props, build_update_props, upsert_page


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.slot_patch = patch.object(WeReadGateway, '_wait_for_slot')
        self.slot_patch.start()
        self.addCleanup(self.slot_patch.stop)
        self.api = WeReadGateway('wrk-test')
        self.api.session = Mock()

    def response(self, data, status=200):
        response = Mock(status_code=status)
        response.json.return_value = data
        return response

    def test_flat_versioned_request(self):
        self.api.session.post.return_value = self.response({'books': []})
        self.api.call('/shelf/sync', count=20)
        kwargs = self.api.session.post.call_args.kwargs
        self.assertEqual(kwargs['json'], {'api_name': '/shelf/sync', 'skill_version': '1.0.4', 'count': 20})
        self.assertEqual(kwargs['timeout'], 30)

    def test_business_errors_and_upgrade_stop(self):
        for data in [{'errcode': -2012}, {'errCode': -2013}, {'upgrade_info': {}}, []]:
            with self.subTest(data=data):
                self.api.session.post.return_value = self.response(data)
                with self.assertRaises(RuntimeError):
                    self.api.call('/shelf/sync')

    def test_rate_limit_retry(self):
        self.api.session.post.side_effect = [self.response({}, 429), self.response({'books': []})]
        with patch('weread_gateway.time.sleep'):
            self.assertEqual(self.api.get_shelf()[1], [])
        self.assertEqual(self.api.session.post.call_count, 2)

    def test_official_499_quota_error_retries(self):
        self.api.session.post.side_effect = [
            self.response({'errcode': -2014}, 499), self.response({'books': []})]
        with patch.object(WeReadGateway, '_cool_down') as cooldown:
            self.assertEqual(self.api.get_shelf()[1], [])
            cooldown.assert_called_once_with(60)

    def test_repeated_quota_error_fails(self):
        self.api.session.post.return_value = self.response({'errcode': -2014}, 499)
        with patch.object(WeReadGateway, '_cool_down'):
            with self.assertRaisesRegex(RuntimeError, 'quota exceeded'):
                self.api.get_shelf()
        self.assertEqual(self.api.session.post.call_count, 4)

    def test_server_retry_after_is_respected(self):
        limited = self.response({'errcode': -2014}, 499)
        limited.headers = {'Retry-After': '180'}
        self.api.session.post.side_effect = [limited, self.response({'ok': True})]
        with patch.object(WeReadGateway, '_cool_down') as cooldown:
            self.api.call('/readdata/detail')
            cooldown.assert_called_once_with(180)

    def test_repeated_throttling_increases_backoff(self):
        limited = self.response({'errcode': -2014}, 499)
        limited.headers = {}
        self.api.session.post.side_effect = [limited, limited, limited, self.response({'ok': True})]
        with patch.object(WeReadGateway, '_cool_down') as cooldown:
            self.api.call('/readdata/detail')
            self.assertEqual([c.args[0] for c in cooldown.call_args_list], [60, 120, 240])

    def test_progress_and_unknown_fields(self):
        for percent, status in [(0, 'To Be Read'), (1, 'Currently Reading'), (100, 'Read')]:
            self.api.call = Mock(side_effect=[
                {'title': 'Book', 'wordCount': 550000, 'newRating': 98},
                {'book': {'progress': percent, 'recordReadingTime': 0, 'updateTime': 1788798600}},
                {'updated': [], 'chapters': []}, {'reviews': []},
            ])
            data = self.api.get_single_book_data('1')
            self.assertEqual(data['percent'], percent)
            self.assertEqual(data['status'], status)
            self.assertEqual(data['reading_time'], '0时0分')
            self.assertEqual(data['total_words'], 550000)
            self.assertEqual(data['total_page'], 1000)
            self.assertEqual(data['current_page'], percent * 10)
            for key in ['started_at', 'date_finished', 'rating']:
                self.assertIsNone(data[key])

    def test_missing_progress_fails(self):
        for progress in [{}, {'progress': None}, {'progress': 101}, {'progress': True}]:
            self.api.call = Mock(return_value={'book': progress})
            with self.assertRaises(RuntimeError):
                self.api.get_read_info('1')

    def test_chapter_resolves_uid_instead_of_using_array_position(self):
        self.api.call = Mock(return_value={'chapters': [
            {'chapterUid': 102, 'chapterIdx': 0, 'title': 'Foreword'},
            {'chapterUid': 7, 'chapterIdx': 9, 'title': 'Chapter 3: Practice'},
        ]})
        title = self.api.get_current_chapter('book', {'chapterUid': '7'}, {}, 'Currently Reading')
        self.assertEqual(title, 'Chapter 3: Practice')
        self.api.call.assert_called_once_with('/book/chapterinfo', bookId='book')

    def test_note_chapter_metadata_avoids_extra_request(self):
        self.api.call = Mock()
        notes = {'chapter_info': {7: {'chapterUid': 7, 'title': 'Chapter 3'}}}
        self.assertEqual(self.api.get_current_chapter('book', {'chapterUid': 7}, notes, 'Read'), 'Chapter 3')
        self.api.call.assert_not_called()

    def test_no_position_and_missing_chapter_are_explicit(self):
        self.api.call = Mock(return_value={'chapters': []})
        self.assertEqual(self.api.get_current_chapter('book', {'chapterUid': 7}, {}, 'To Be Read'), '未开始阅读')
        self.api.call.assert_not_called()
        self.assertEqual(self.api.get_current_chapter('book', {}, {}, 'Read'), '已读完')
        self.assertEqual(self.api.get_current_chapter('book', {'chapterUid': 7}, {}, 'Currently Reading'), '章节名称暂不可用')
        self.api.call.return_value = {}
        with self.assertRaisesRegex(RuntimeError, 'missing chapter list'):
            self.api.get_current_chapter('book', {'chapterUid': 7}, {}, 'Currently Reading')

    def test_invalid_word_counts_do_not_invent_estimated_pages(self):
        for value in [None, -1, True, '10000', 3.5, 0, 120000]:
            with self.subTest(value=value):
                self.api.call = Mock(side_effect=[{'title': 'Book', 'wordCount': value}, {'chapters': []}])
                self.api.get_read_info = Mock(return_value={'progress': 0})
                self.api.get_notes = Mock(return_value={'bookmarks': [], 'summary_reviews': []})
                fields = self.api.get_single_book_data('book')
                expected = value if type(value) is int and value >= 0 else None
                self.assertEqual(fields['total_words'], expected)
                if expected and expected > 0:
                    self.assertEqual(fields['current_page'], 0)
                    self.assertEqual(fields['total_page'], max(1, round(expected / 550)))
                else:
                    self.assertIsNone(fields['current_page'])
                    self.assertIsNone(fields['total_page'])

    def test_start_time_is_optional_and_uses_shanghai_year(self):
        for value in [None, 0, True, 'unknown', float('nan'), float('inf'), 1735662600]:
            with self.subTest(value=value):
                self.api.call = Mock(side_effect=[
                    {'title': 'Book', 'wordCount': 5500},
                    {'book': {'progress': 5, 'startReadingTime': value, 'updateTime': 1788798600}},
                    {'updated': []}, {'reviews': []},
                ])
                fields = self.api.get_single_book_data('1')
                if value == 1735662600:  # 2024-12-31 16:30 UTC = 2025 in Shanghai
                    self.assertEqual(fields['started_at'].date().isoformat(), '2025-01-01')
                    self.assertEqual(fields['year_started'], 2025)
                else:
                    self.assertIsNone(fields['started_at'])
                    self.assertIsNone(fields['year_started'])

    def test_missing_book_word_count_uses_complete_directory_once(self):
        for uid, expected_title in [(7, 'Chapter 3'), (99, '章节名称暂不可用')]:
            with self.subTest(uid=uid):
                self.api.call = Mock(side_effect=[{'title': 'Book'}, {'chapters': [
                    {'chapterUid': 102, 'title': 'Foreword', 'wordCount': 317},
                    {'chapterUid': 7, 'title': 'Chapter 3', 'wordCount': 181028},
                    {'chapterUid': 9, 'title': 'End', 'wordCount': 0},
                ]}])
                self.api.get_read_info = Mock(return_value={'progress': 6, 'chapterUid': uid})
                self.api.get_notes = Mock(return_value={'bookmarks': [], 'summary_reviews': [],
                    'chapter_info': {7: {'chapterUid': 7, 'title': 'Old title', 'wordCount': 999}}})
                fields = self.api.get_single_book_data('book')
                self.assertEqual(fields['total_words'], 181345)
                self.assertEqual(fields['total_page'], 330)
                self.assertEqual(fields['current_page'], 20)
                self.assertEqual(fields['current_chapter'], expected_title)
                self.assertEqual(self.api.call.call_count, 2)
                self.api.call.assert_called_with('/book/chapterinfo', bookId='book')

    def test_incomplete_directory_does_not_publish_partial_word_total(self):
        for count in [None, True, -1, '100', 2.5]:
            with self.subTest(count=count):
                self.api.call = Mock(side_effect=[{'title': 'Book'}, {'chapters': [
                    {'chapterUid': 1, 'wordCount': 5500}, {'chapterUid': 2, 'wordCount': count}
                ]}])
                self.api.get_read_info = Mock(return_value={'progress': 0})
                self.api.get_notes = Mock(return_value={'bookmarks': [], 'summary_reviews': []})
                fields = self.api.get_single_book_data('book')
                for key in ['total_words', 'total_page', 'current_page']:
                    self.assertIsNone(fields[key])

    def test_new_book_start_date_fallback(self):
        cases = [
            ({'readingTime': 0}, [], [], None, None, 'To Be Read'),
            ({'readingTime': 2}, [], [], 1735835400, '最早可核验阅读记录（替代）', 'Currently Reading'),
            ({'readingTime': 20}, [{'createTime': 1735749000}], [{'review': {'createTime': 1735662600}}], 1735662600, '最早可核验阅读记录（替代）', 'Currently Reading'),
            ({'startReadingTime': 1735835400, 'readingTime': 20}, [{'createTime': 1735662600}], [], 1735835400, '微信读书开始时间', 'Currently Reading'),
        ]
        for extra, marks, reviews, expected, source, status in cases:
            with self.subTest(extra=extra, marks=marks):
                self.api.call = Mock(return_value={'title': 'New book', 'wordCount': 5500})
                self.api.get_read_info = Mock(return_value={'progress': 0, 'updateTime': 1735835400, **extra})
                self.api.get_notes = Mock(return_value={'bookmarks': marks, 'summary_reviews': reviews})
                fields = self.api.get_single_book_data('new')
                self.assertEqual(fields['started_at'], self.api.timestamp(expected))
                self.assertEqual(fields['start_date_source'], source)
                self.assertEqual(fields['status'], status)
                schema = {'Title': {'type': 'title'}, 'Date Started': {'type': 'date'}, 'Year Started': {'type': 'select'}, 'Start Date Source': {'type': 'rich_text'}}
                with patch('weread_notion_sync.PROP_STARTED_AT', 'Date Started'):
                    props = build_props(schema, fields)
                if expected:
                    self.assertEqual(props['Year Started']['select']['name'], '2025')
                    self.assertEqual(props['Start Date Source']['rich_text'][0]['text']['content'], source)
                else:
                    self.assertNotIn('Date Started', props)

    def test_review_pagination_and_dedup(self):
        self.api.call = Mock(side_effect=[
            {'reviews': [{'review': {'reviewId': 'a', 'content': 'one'}}], 'hasMore': 1, 'synckey': 22},
            {'reviews': [{'review': {'reviewId': 'a'}}, {'review': {'reviewId': 'b'}}], 'hasMore': 0},
        ])
        self.assertEqual(len(self.api.get_reviews('1')), 2)
        self.assertEqual(self.api.call.call_args.kwargs['synckey'], 22)
        self.assertEqual(self.api.call.call_args.kwargs['bookid'], '1')

    def test_stuck_pagination_fails(self):
        self.api.call = Mock(return_value={'reviews': [], 'hasMore': 1, 'synckey': 0})
        with self.assertRaises(RuntimeError):
            self.api.get_reviews('1')

    def test_notebooks_paginate_and_include_removed_shelf_books(self):
        self.api.get_shelf = Mock(return_value=({}, [{'bookId': '1', 'title': 'On shelf'}], []))
        self.api.call = Mock(side_effect=[
            {'books': [{'bookId': '1', 'sort': 22}], 'hasMore': 1},
            {'books': [{'bookId': '1'}, {'bookId': '2', 'book': {'title': 'Removed'}}], 'hasMore': 0},
        ])
        books = self.api.get_sync_books()[1]
        self.assertEqual(len(books), 2)
        self.assertEqual(books[1]['book'], {'bookId': '2', 'title': 'Removed'})
        self.assertEqual(self.api.call.call_args.kwargs, {'count': 100, 'lastSort': 22})

    def test_notebook_pagination_failure_is_not_silently_truncated(self):
        for page in [
            {'books': [], 'hasMore': 1},
            {'books': [{'bookId': '1', 'sort': 22}], 'hasMore': 1},
        ]:
            self.api.call = Mock(return_value=page)
            with self.assertRaisesRegex(RuntimeError, 'pagination'):
                self.api.get_notebooks()

    def test_key_preferred_over_cookies(self):
        with patch.dict(os.environ, {'WEREAD_API_KEY': 'wrk-test'}):
            self.assertIsInstance(create_weread_client('invalid cookies'), WeReadGateway)


class SyncTests(unittest.TestCase):
    def setUp(self):
        # Personal .env aliases must not change test schemas.
        for name, value in [('PROP_STARTED_AT', 'Date Started'), ('PROP_YEAR_STARTED', 'Year Started')]:
            setting = patch('weread_notion_sync.' + name, value)
            setting.start()
            self.addCleanup(setting.stop)

    def test_reading_details_are_created_and_updated_without_touching_progress(self):
        schema = {'Current Chapter': {'type': 'rich_text'}, 'Total Words': {'type': 'number'},
                  'Reading Progress': {'type': 'number'}, 'Page Count': {'type': 'formula'}}
        fields = {'current_chapter': '第二章 方法', 'total_words': 120345}
        expected = {'Current Chapter': {'rich_text': [{'text': {'content': '第二章 方法'}}]},
                    'Total Words': {'number': 120345}}
        self.assertEqual(build_props(schema, fields), expected)
        self.assertEqual(build_update_props(Mock(), 'page', schema, fields), expected)
        self.assertEqual(build_update_props(Mock(), 'page', schema, {'total_words': None}), {})
        self.assertEqual(build_props(schema, {'total_words': 0}), {'Total Words': {'number': 0}})

    def test_reading_detail_schema_only_adds_missing_fields(self):
        notion = Mock()
        schema = {'Reading Progress': {'type': 'formula'}, 'Start Date Source': {'type': 'rich_text'}}
        with patch.object(sync, 'get_db_properties', return_value={'refreshed': True}):
            self.assertEqual(sync.ensure_sync_properties(notion, 'db', schema), {'refreshed': True})
        notion.databases.update.assert_called_once_with(database_id='db', properties={
            'Current Chapter': {'rich_text': {}}, 'Total Words': {'number': {}}})
        notion.databases.update.reset_mock()
        with self.assertRaisesRegex(ValueError, 'Total Words'):
            sync.ensure_sync_properties(notion, 'db', {'Total Words': {'type': 'formula'}})
        notion.databases.update.assert_not_called()

    def test_long_chapter_titles_respect_notion_text_limit(self):
        title = '字' * 2100
        props = build_props({'Current Chapter': {'type': 'rich_text'}}, {'current_chapter': title})
        items = props['Current Chapter']['rich_text']
        self.assertTrue(all(len(item['text']['content']) <= 2000 for item in items))
        self.assertEqual(''.join(item['text']['content'] for item in items), title)

    def test_start_date_and_year_are_updated_together(self):
        schema = {'Date Started': {'type': 'date'}, 'Year Started': {'type': 'select'}}
        for existing, expected in [(None, '2024-02-03'), ('2023-12-01', '2023-12-01'), ('2025-01-01', '2024-02-03')]:
            with self.subTest(existing=existing):
                notion = Mock()
                notion.pages.retrieve.return_value = {'properties': {'Date Started': {'date': {'start': existing} if existing else None}}}
                props = build_update_props(notion, 'p', schema, {'started_at': datetime(2024, 2, 3), 'year_started': 2024})
                self.assertEqual(props['Year Started']['select']['name'], expected[:4])
                if existing == expected:
                    self.assertNotIn('Date Started', props)
                else:
                    self.assertEqual(props['Date Started']['date']['start'], expected)

    def test_failed_date_read_does_not_overwrite_existing_date(self):
        notion = Mock()
        notion.pages.retrieve.side_effect = RuntimeError('read failed')
        with self.assertRaisesRegex(RuntimeError, 'read failed'):
            build_update_props(notion, 'p', {'Date Started': {'type': 'date'}}, {'started_at': datetime(2024, 2, 3)})

    def test_start_date_provenance_and_repeated_sync(self):
        official, estimate = '微信读书开始时间', '最早可核验阅读记录（替代）'
        schema = {'Date Started': {'type': 'date'}, 'Year Started': {'type': 'select'}, 'Start Date Source': {'type': 'rich_text'}}
        cases = [(estimate, estimate, '2024-02-03', False),
                 (estimate, official, '2025-01-01', True),
                 (official, estimate, '2024-02-03', False),
                 ('', estimate, '2024-02-03', False)]
        for old_source, incoming_source, expected, changed in cases:
            with self.subTest(old=old_source, incoming=incoming_source):
                notion = Mock()
                notion.pages.retrieve.return_value = {'properties': {'Date Started': {'date': {'start': '2024-02-03'}}, 'Start Date Source': {'rich_text': [{'plain_text': old_source}]}}}
                props = build_update_props(notion, 'p', schema, {'started_at': datetime(2025, 1, 1), 'start_date_source': incoming_source})
                self.assertEqual(props['Year Started']['select']['name'], expected[:4])
                self.assertEqual('Date Started' in props, changed)
                if changed:
                    self.assertEqual(props['Date Started']['date']['start'], expected)
                    self.assertEqual(props['Start Date Source']['rich_text'][0]['text']['content'], official)

    def test_new_book_is_created_once_and_later_activity_keeps_start(self):
        schema = {'Title': {'type': 'title'}, 'Date Started': {'type': 'date'}, 'Year Started': {'type': 'select'}, 'Start Date Source': {'type': 'rich_text'}}
        notion = Mock()
        notion.pages.create.return_value = {'id': 'new-page'}
        notion.pages.retrieve.return_value = {'properties': {'Date Started': {'date': {'start': '2024-02-03'}}, 'Start Date Source': {'rich_text': [{'plain_text': '最早可核验阅读记录（替代）'}]}}}
        fields = {'title': 'New book', 'author': 'Author', 'started_at': datetime(2024, 2, 3), 'year_started': 2024, 'start_date_source': '最早可核验阅读记录（替代）'}
        with patch('weread_notion_sync.find_page_by_title_and_author', side_effect=[None, {'id': 'new-page'}]), redirect_stdout(io.StringIO()):
            self.assertEqual(upsert_page(notion, 'db', schema, fields), ('new-page', True))
            self.assertEqual(upsert_page(notion, 'db', schema, {**fields, 'started_at': datetime(2025, 1, 1), 'year_started': 2025}), ('new-page', False))
        notion.pages.create.assert_called_once()
        notion.pages.update.assert_called_once()
        updated = notion.pages.update.call_args.kwargs['properties']
        self.assertNotIn('Date Started', updated)
        self.assertEqual(updated['Year Started']['select']['name'], '2024')

    def test_failed_source_never_writes(self):
        api = Mock()
        api.get_shelf.side_effect = RuntimeError('expired')
        with patch.object(sync, 'create_weread_client', return_value=api), patch.object(sync, 'upsert_page') as upsert:
            with self.assertRaises(RuntimeError), redirect_stdout(io.StringIO()):
                sync.sync_books_from_api(Mock(), 'db', {}, '')
            upsert.assert_not_called()

    def test_empty_shelf_is_not_success(self):
        api = Mock()
        api.get_shelf.return_value = ({'books': []}, [], [])
        with patch.object(sync, 'create_weread_client', return_value=api):
            with self.assertRaises(RuntimeError), redirect_stdout(io.StringIO()):
                sync.sync_books_from_api(Mock(), 'db', {}, '')

    def test_per_book_failure_propagates(self):
        api = Mock()
        api.get_shelf.return_value = ({}, [{'bookId': '1', 'title': 'Book'}], [])
        api.get_single_book_data.side_effect = RuntimeError('Notion or WeRead failure')
        with patch.object(sync, 'create_weread_client', return_value=api):
            with self.assertRaisesRegex(RuntimeError, '1 failed'), redirect_stdout(io.StringIO()):
                sync.sync_books_from_api(Mock(), 'db', {}, '')

    def test_notion_write_failure_propagates(self):
        api = Mock()
        api.get_shelf.return_value = ({}, [{'bookId': '1', 'title': 'Book'}], [])
        api.get_single_book_data.return_value = {'title': 'Book', 'status': 'Read', 'bookmarks': [{'markText': 'note'}]}
        with patch.object(sync, 'create_weread_client', return_value=api), patch.object(sync, 'upsert_page', return_value=('page', False)), patch.object(sync, 'sync_blocks_to_page', side_effect=RuntimeError('write failed')):
            with self.assertRaisesRegex(RuntimeError, '1 failed'), redirect_stdout(io.StringIO()):
                sync.sync_books_from_api(Mock(), 'db', {}, '')

    def test_notion_pagination(self):
        notion = Mock()
        notion.blocks.children.list.side_effect = [
            {'results': [], 'has_more': True, 'next_cursor': 'next'},
            {'results': [], 'has_more': False},
        ]
        sync.get_existing_blocks(notion, 'page')
        self.assertEqual(notion.blocks.children.list.call_args.kwargs['start_cursor'], 'next')

    def test_append_notes_preserves_manual_content_and_nests_quotes(self):
        notion = Mock()
        existing_note = sync.get_callout('old')
        signature = sync.get_block_signature(existing_note)
        with patch.object(sync, 'get_existing_blocks', return_value={signature: 'existing', 'manual': 'manual'}), patch.object(sync, 'add_children', return_value=[{'id': 'new'}]) as append:
            result = sync.sync_blocks_to_page(notion, 'page', [existing_note, sync.get_callout('new')], {1: sync.get_quote('abstract')}, clear_existing=True)
            self.assertEqual(result, (1, 0, 2))
            children = append.call_args.args[2]
            self.assertEqual(len(children), 1)
            self.assertEqual(children[0]['callout']['children'][0]['type'], 'quote')
            notion.blocks.delete.assert_not_called()

    def test_existing_numeric_progress_property(self):
        with patch.dict(os.environ, {'PROP_PROGRESS': 'Reading Progress'}):
            for fmt, expected in [('number', 1), ('percent', .01)]:
                props = {'Reading Progress': {'type': 'number', 'number': {'format': fmt}}}
                self.assertEqual(build_props(props, {'percent': 1})['Reading Progress']['number'], expected)
                self.assertEqual(build_update_props(Mock(), 'p', props, {'percent': 1})['Reading Progress']['number'], expected)
            self.assertEqual(build_props({'Reading Progress': {'type': 'formula'}}, {'percent': 1}), {})

    def test_existing_thought_repairs_missing_quote_without_repeating_text(self):
        notion = Mock()
        block = sync.get_callout('my thought', review_id='r')
        old_quote = sync.get_quote('preserved original')
        missing_quote = sync.get_quote('missing original')
        with patch.object(sync, 'get_existing_blocks', side_effect=[
            {sync.get_block_signature(block): 'parent'},
            {sync.get_block_signature(old_quote): 'child'},
        ]), patch.object(sync, 'add_children', side_effect=[[{'id': 'new-quote'}], []]) as append:
            self.assertEqual(sync.sync_blocks_to_page(notion, 'page', [block], {0: missing_quote})[0], 1)
            self.assertEqual(append.call_args_list[0].args, (notion, 'parent', [missing_quote]))
            self.assertEqual(append.call_args_list[1].args, (notion, 'page', []))
            notion.blocks.delete.assert_not_called()

    def test_same_thought_text_preserves_distinct_quotes(self):
        block = sync.get_callout('same thought', review_id='r')
        with patch.object(sync, 'get_existing_blocks', return_value={}), patch.object(sync, 'add_children', return_value=[{}]) as append:
            sync.sync_blocks_to_page(Mock(), 'page', [block, block],
                                     {0: sync.get_quote('first'), 1: sync.get_quote('second')})
            new_blocks = append.call_args.args[2]
            self.assertEqual(len(new_blocks), 1)
            self.assertEqual(len(new_blocks[0]['callout']['children']), 2)

    def test_legacy_restores_word_based_pages_without_inventing_dates(self):
        api = WeReadAPI('')
        self.assertEqual(api._calc_total_pages({1: {'wordCount': 550000}}, {}), 1000)
        self.assertEqual(api._calc_total_pages({}, {'wordCount': 275000}), 500)
        self.assertIsNone(api._calc_total_pages({}, {}))
        self.assertEqual(api._extract_dates(None, {'updateTime': 1788798600}, 'Read'), (None, None, None))

    def test_original_progress_formula_inputs_create_and_update_including_zero(self):
        schema = {'Current Page': {'type': 'number'}, 'Total Page': {'type': 'number'}, 'Page Count': {'type': 'formula'}}
        for current in (0, 38, 100):
            with self.subTest(current=current):
                fields = {'current_page': current, 'total_page': 100}
                with patch('weread_notion_sync.PROP_CURRENT_PAGE', 'Current Page'), patch('weread_notion_sync.PROP_TOTAL_PAGE', 'Total Page'):
                    created = build_props(schema, fields)
                    updated = build_update_props(Mock(), 'book', schema, fields)
                expected = {'Current Page': {'number': current}, 'Total Page': {'number': 100}}
                self.assertEqual(created, expected)
                self.assertEqual(updated, expected)

    def test_legacy_http200_auth_failure(self):
        response = Mock(url='https://weread.qq.com/web/shelf/sync')
        response.json.return_value = {'errCode': -2012}
        with self.assertRaises(Exception):
            WeReadAPI._check_response(response)


if __name__ == '__main__':
    unittest.main()
