import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compute_heatmap import compute_official, summarize, CST


class HeatmapTests(unittest.TestCase):
    def test_uses_official_total_and_daily_buckets(self):
        now = datetime.now(CST)
        ts = int(datetime(now.year, 1, 1, tzinfo=CST).timestamp())
        api = Mock()
        api.call.side_effect = [
            {'registTime': ts, 'totalReadTime': 5000, 'readDays': 1},
            {'dailyReadTimes': {str(ts): 120}, 'totalReadTime': 5000},
        ]
        result = compute_official(api)
        self.assertEqual(result['totalSeconds'], 5000)
        self.assertEqual(result['days'][f'{now.year}-01-01'], 120)
        self.assertEqual(result['totalDays'], 1)
        self.assertEqual(result['dataSource'], 'weread_official_readdata')
        self.assertIn('updatedAt', result)

    def test_monthly_fallback_does_not_use_annual_month_buckets(self):
        now = datetime.now(CST)
        ts = int(datetime(now.year, 1, 1, tzinfo=CST).timestamp())
        def call(name, **params):
            if params['mode'] == 'overall':
                return {'registTime': ts, 'totalReadTime': 9000}
            if params['mode'] == 'annually':
                return {'readTimes': {str(ts): 9000}, 'totalReadTime': 9000}
            return {'readTimes': {str(params['baseTime']): 60}}
        api = Mock()
        api.call.side_effect = call
        result = compute_official(api)
        self.assertEqual(result['totalSeconds'], 9000)
        self.assertEqual(len(result['days']), now.month)
        self.assertEqual(result['days'][f'{now.year}-01-01'], 60)

    def test_missing_daily_data_fails(self):
        now = datetime.now(CST)
        api = Mock()
        api.call.side_effect = [{'registTime': int(datetime(now.year, 1, 1, tzinfo=CST).timestamp()), 'totalReadTime': 60}, {}, {}]
        with self.assertRaises(RuntimeError):
            compute_official(api)

    def test_zero_reading_year_does_not_fetch_twelve_empty_months(self):
        now = datetime.now(CST)
        ts = int(datetime(now.year, 1, 1, tzinfo=CST).timestamp())
        api = Mock()
        api.call.side_effect = [{'registTime': ts, 'totalReadTime': 0}, {'totalReadTime': 0}]
        self.assertEqual(compute_official(api)['days'], {})
        self.assertEqual(api.call.call_count, 2)

    def test_streak_requires_one_minute(self):
        result = summarize({'2026-01-01': 60, '2026-01-02': 30, '2026-01-03': 60}, 150, 1, 'test')
        self.assertEqual(result['totalDays'], 2)
        self.assertEqual(result['longestStreak'], 1)

    def test_incremental_refresh_replaces_recent_months_in_three_calls(self):
        now = datetime.now(CST)
        current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_month = (current - timedelta(days=1)).replace(day=1)
        historical = previous_month - timedelta(days=10)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cache = {'dataSource': 'weread_official_readdata',
                 'updatedAt': (now - timedelta(minutes=5)).isoformat(),
                 'days': {historical.strftime('%Y-%m-%d'): 120,
                          previous_month.strftime('%Y-%m-%d'): 999}}
        api = Mock()
        api.call.side_effect = [
            {'registTime': int(current.timestamp()), 'totalReadTime': 777, 'readDays': 9},
            {'readTimes': {}},
            {'readTimes': {str(int(today.timestamp())): 60}},
        ]
        result = compute_official(api, cache)
        self.assertEqual(api.call.call_count, 3)
        self.assertEqual(result['days'], {historical.strftime('%Y-%m-%d'): 120, today.strftime('%Y-%m-%d'): 60})
        self.assertEqual(result['totalSeconds'], 777)
        self.assertEqual(result['totalDays'], 9)
        self.assertEqual(result['historyVerifiedAt'], cache['updatedAt'])
        self.assertIn(previous_month.strftime('%Y-%m-%d'), cache['days'])

    def test_expired_or_legacy_history_forces_full_verification(self):
        now = datetime.now(CST)
        ts = int(datetime(now.year, 1, 1, tzinfo=CST).timestamp())
        for source, age in [('legacy_shelf_read_detail', 1), ('weread_official_readdata', 31)]:
            with self.subTest(source=source, age=age):
                api = Mock()
                api.call.side_effect = [{'registTime': ts, 'totalReadTime': 60},
                                        {'dailyReadTimes': {str(ts): 60}}]
                cache = {'dataSource': source, 'updatedAt': (now - timedelta(days=age)).isoformat(),
                         'days': {'2015-01-01': 999}}
                result = compute_official(api, cache)
                self.assertNotIn('2015-01-01', result['days'])
                self.assertEqual(api.call.call_args.kwargs['mode'], 'annually')
                self.assertEqual(result['historyVerifiedAt'], result['updatedAt'])

    def test_incremental_source_failure_does_not_return_partial_data(self):
        now = datetime.now(CST)
        cache = {'dataSource': 'weread_official_readdata', 'updatedAt': now.isoformat(), 'days': {}}
        api = Mock()
        api.call.side_effect = [{'registTime': int(now.timestamp()), 'totalReadTime': 60},
                                {'readTimes': {}}, RuntimeError('source failed')]
        with self.assertRaisesRegex(RuntimeError, 'source failed'):
            compute_official(api, cache)
        self.assertEqual(cache['days'], {})
