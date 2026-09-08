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
from weread_notion_sync import build_props, build_update_props


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
                {'book': {'progress': percent, 'recordReadingTime': 3660, 'updateTime': 1788798600}},
                {'updated': [], 'chapters': []}, {'reviews': []},
            ])
            data = self.api.get_single_book_data('1')
            self.assertEqual(data['percent'], percent)
            self.assertEqual(data['status'], status)
            self.assertEqual(data['reading_time'], '1时1分')
            for key in ['current_page', 'total_page', 'started_at', 'date_finished', 'rating']:
                self.assertIsNone(data[key])

    def test_missing_progress_fails(self):
        for progress in [{}, {'progress': None}, {'progress': 101}, {'progress': True}]:
            self.api.call = Mock(return_value={'book': progress})
            with self.assertRaises(RuntimeError):
                self.api.get_read_info('1')

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

    def test_legacy_does_not_invent_dates_or_pages(self):
        api = WeReadAPI('')
        self.assertIsNone(api._calc_total_pages({1: {'wordCount': 550000}}, {}))
        self.assertEqual(api._extract_dates(None, {'updateTime': 1788798600}, 'Read'), (None, None, None))

    def test_legacy_http200_auth_failure(self):
        response = Mock(url='https://weread.qq.com/web/shelf/sync')
        response.json.return_value = {'errCode': -2012}
        with self.assertRaises(Exception):
            WeReadAPI._check_response(response)


if __name__ == '__main__':
    unittest.main()
