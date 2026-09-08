import sys
import unittest
from datetime import datetime
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

    def test_streak_requires_one_minute(self):
        result = summarize({'2026-01-01': 60, '2026-01-02': 30, '2026-01-03': 60}, 150, 1, 'test')
        self.assertEqual(result['totalDays'], 2)
        self.assertEqual(result['longestStreak'], 1)
