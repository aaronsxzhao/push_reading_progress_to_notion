#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute heatmap data from WeRead and push the result to a GitHub Gist.

Designed to run locally (where cookies are always fresh) so we can
fetch readDetail for every book without the Vercel serverless timeout.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from weread_api import WeReadAPI

CST = timezone(timedelta(hours=8))


def compute(cookies: str) -> dict:
    api = WeReadAPI(cookies, auto_refresh=False)
    _, _, progress = api.get_shelf()
    books_with_time = [p for p in progress if p.get("readingTime", 0) > 0]

    total_seconds = sum(p.get("readingTime", 0) for p in books_with_time)
    days: dict[str, int] = {}

    def fetch_read_detail(bp):
        book_id = str(bp.get("bookId", ""))
        try:
            info = api.get_read_info(book_id)
            if not info:
                return {}
            entries = info.get("readDetail", {}).get("data", [])
            result = {}
            for e in entries:
                ts, secs = e.get("readDate", 0), e.get("readTime", 0)
                if ts and secs:
                    ds = datetime.fromtimestamp(ts, tz=CST).strftime("%Y-%m-%d")
                    result[ds] = result.get(ds, 0) + secs
            return result
        except Exception:
            return {}

    print(f"Fetching daily reading data for {len(books_with_time)} books ...")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(fetch_read_detail, bp): bp for bp in books_with_time}
        done = 0
        for f in as_completed(futs):
            for ds, secs in f.result().items():
                days[ds] = days.get(ds, 0) + secs
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{len(books_with_time)} books processed")

    sorted_dates = sorted(days.keys())
    current_streak = longest_streak = 0

    if sorted_dates:
        today = datetime.now(CST).strftime("%Y-%m-%d")
        yesterday = (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")

        streak, prev = 0, None
        for d in sorted_dates:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            streak = streak + 1 if prev and (dt - prev).days == 1 else 1
            longest_streak = max(longest_streak, streak)
            prev = dt

        streak = 0
        check = today
        while check in days:
            streak += 1
            check = (datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        if streak == 0:
            check = yesterday
            while check in days:
                streak += 1
                check = (datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        current_streak = streak

    result = {
        "days": days,
        "totalSeconds": total_seconds,
        "totalDays": len(days),
        "currentStreak": current_streak,
        "longestStreak": longest_streak,
        "booksWithTime": len(books_with_time),
    }
    print(f"Done: {len(days)} days, {total_seconds // 3600}h total, "
          f"streak {current_streak}d, longest {longest_streak}d")
    return result


def push_to_gist(data: dict) -> bool:
    gh_token = os.environ.get("GH_TOKEN", "")
    gist_id = os.environ.get("COOKIE_GIST_ID", "")
    if not gh_token or not gist_id:
        print("GH_TOKEN or COOKIE_GIST_ID not set — skipping Gist push")
        return False
    try:
        import requests
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {gh_token}",
                     "Accept": "application/vnd.github.v3+json"},
            json={"files": {"heatmap_data.json": {
                "content": json.dumps(data, ensure_ascii=False)
            }}},
            timeout=15,
        )
        if r.status_code == 200:
            print("Heatmap data pushed to Gist")
            return True
        print(f"Gist update failed: {r.status_code}")
    except Exception as e:
        print(f"Gist update error: {e}")
    return False


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    except ImportError:
        pass

    cookies = os.environ.get("WEREAD_COOKIES", "")
    if not cookies:
        print("WEREAD_COOKIES not set")
        sys.exit(1)

    data = compute(cookies)
    push_to_gist(data)


if __name__ == "__main__":
    main()
