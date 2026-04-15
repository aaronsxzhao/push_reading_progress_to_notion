#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serverless function for Vercel — serves aggregated daily reading time
from WeRead for the heatmap visualization.

Returns JSON: {
  "days": {"2026-01-15": 3600, ...},   // date -> seconds
  "totalSeconds": 726299,
  "totalDays": 115,
  "currentStreak": 3,
  "longestStreak": 12,
  "booksWithTime": 115
}
"""

import os
import sys
import json
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler

src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from weread_api import WeReadAPI

_cache = {"data": None, "ts": 0}
CACHE_TTL = 3600


def _fetch_heatmap_data(cookies: str) -> dict:
    now = _time.time()
    if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    api = WeReadAPI(cookies, auto_refresh=False)
    shelf_data, books, progress = api.get_shelf()

    books_with_time = [
        p for p in progress if p.get("readingTime", 0) > 0
    ]

    # Use the authoritative per-book total from the shelf — the daily
    # breakdown (readDetail.data) doesn't include very short sessions and
    # has minor per-day rounding, so its sum is always slightly lower.
    total_seconds_from_shelf = sum(
        p.get("readingTime", 0) for p in books_with_time
    )

    days: dict[str, int] = {}

    def fetch_read_detail(book_progress):
        book_id = str(book_progress.get("bookId", ""))
        try:
            info = api.get_read_info(book_id)
            if not info:
                return {}
            detail = info.get("readDetail", {})
            data = detail.get("data", [])
            result = {}
            for entry in data:
                ts = entry.get("readDate", 0)
                secs = entry.get("readTime", 0)
                if ts and secs:
                    dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
                    date_str = dt.strftime("%Y-%m-%d")
                    result[date_str] = result.get(date_str, 0) + secs
            return result
        except Exception:
            return {}

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(fetch_read_detail, bp): bp
            for bp in books_with_time
        }
        for future in as_completed(futures):
            book_days = future.result()
            for date_str, secs in book_days.items():
                days[date_str] = days.get(date_str, 0) + secs

    total_days = len(days)

    sorted_dates = sorted(days.keys())
    current_streak = 0
    longest_streak = 0

    if sorted_dates:
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        yesterday = (
            datetime.now(timezone(timedelta(hours=8))) - timedelta(days=1)
        ).strftime("%Y-%m-%d")

        streak = 0
        prev = None
        for d in sorted_dates:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            if prev and (dt - prev).days == 1:
                streak += 1
            else:
                streak = 1
            longest_streak = max(longest_streak, streak)
            prev = dt

        streak = 0
        check = today
        while check in days:
            streak += 1
            check = (
                datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)
            ).strftime("%Y-%m-%d")
        if streak == 0:
            check = yesterday
            while check in days:
                streak += 1
                check = (
                    datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)
                ).strftime("%Y-%m-%d")
        current_streak = streak

    result = {
        "days": days,
        "totalSeconds": total_seconds_from_shelf,
        "totalDays": total_days,
        "currentStreak": current_streak,
        "longestStreak": longest_streak,
        "booksWithTime": len(books_with_time),
    }

    _cache["data"] = result
    _cache["ts"] = now
    return result


class handler(BaseHTTPRequestHandler):
    """Vercel serverless handler."""

    def do_GET(self):
        cookies = os.environ.get("WEREAD_COOKIES", "")
        if not cookies:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing WEREAD_COOKIES"}).encode())
            return

        try:
            data = _fetch_heatmap_data(cookies)
            body = json.dumps(data, ensure_ascii=False)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=3600, s-maxage=3600")
            self.end_headers()
            self.wfile.write(body.encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": str(e)}, ensure_ascii=False).encode()
            )

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
