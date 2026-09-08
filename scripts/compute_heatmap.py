#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute heatmap data from WeRead and push the result to a GitHub Gist.

Runs in GitHub Actions or locally. Official historical data is reused between
periodic full checks, while the latest two months are refreshed on each run.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from weread_api import WeReadAPI
from weread_gateway import WeReadGateway
from config import env

CST = timezone(timedelta(hours=8))


def compute(cookies: str, previous=None) -> dict:
    if env("WEREAD_API_KEY"):
        api = WeReadGateway(env("WEREAD_API_KEY"))
        result = compute_official(api, previous)
        print(f"[API] Heatmap official requests: {api.request_count}")
        return result
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
                raise RuntimeError("Missing daily reading data")
            entries = info.get("readDetail", {}).get("data", [])
            result = {}
            for e in entries:
                ts, secs = e.get("readDate", 0), e.get("readTime", 0)
                if ts and secs:
                    ds = datetime.fromtimestamp(ts, tz=CST).strftime("%Y-%m-%d")
                    result[ds] = result.get(ds, 0) + secs
            return result
        except Exception as exc:
            raise RuntimeError(f"Daily reading data failed for book {book_id}; old heatmap retained") from exc

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

    return summarize(days, total_seconds, len(books_with_time), "legacy_shelf_read_detail")


def reusable_history(previous, now):
    if not isinstance(previous, dict) or previous.get("dataSource") != "weread_official_readdata":
        return False
    try:
        # Before incremental sync existed, every official result was a full scan.
        checked = datetime.fromisoformat(previous.get("historyVerifiedAt", previous["updatedAt"]))
        updated = datetime.fromisoformat(previous["updatedAt"])
        if not checked.tzinfo or not updated.tzinfo or not 0 <= (now - checked).total_seconds() < 30 * 86400:
            return False
        if not checked <= updated <= now or not isinstance(previous["days"], dict):
            return False
        for day, seconds in previous["days"].items():
            date = datetime.strptime(day, "%Y-%m-%d").date()
            if date > updated.astimezone(CST).date() or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
                return False
        return True
    except (KeyError, ValueError, TypeError):
        return False


def read_month(api, year, month):
    data = api.call("/readdata/detail", mode="monthly",
                    baseTime=int(datetime(year, month, 1, tzinfo=CST).timestamp()))
    if not isinstance(data.get("readTimes"), dict):
        raise RuntimeError("Official daily buckets missing; old heatmap retained")
    days = {}
    for timestamp, seconds in data["readTimes"].items():
        date = datetime.fromtimestamp(int(timestamp), CST)
        if date.year != year or date.month != month or date.date() > datetime.now(CST).date() or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
            raise RuntimeError("Invalid official monthly bucket; old heatmap retained")
        if seconds:
            days[date.strftime("%Y-%m-%d")] = seconds
    return days


def compute_official(api, previous=None):
    """Use official totals; annual daily data or monthly daily buckets for heatmap."""
    overall = api.call("/readdata/detail", mode="overall", baseTime=0)
    if "totalReadTime" not in overall or not overall.get("registTime"):
        raise RuntimeError("Official totals/registration date missing; old heatmap retained")
    now = datetime.now(CST)
    first_year = datetime.fromtimestamp(overall["registTime"], CST).year
    if not 2010 <= first_year <= now.year:
        raise RuntimeError("Invalid registration year")
    if reusable_history(previous, now):
        this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month = (this_month - timedelta(days=1)).replace(day=1)
        months = [(last_month.year, last_month.month), (this_month.year, this_month.month)]
        prefixes = tuple(f"{year}-{month:02d}-" for year, month in months)
        days = {day: value for day, value in previous["days"].items() if not day.startswith(prefixes)}
        for year, month in months:
            days.update(read_month(api, year, month))
        result = summarize(days, overall["totalReadTime"], None, "weread_official_readdata")
        result["totalDays"] = overall.get("readDays", result["totalDays"])
        result["historyVerifiedAt"] = previous.get("historyVerifiedAt", previous["updatedAt"])
        print("[CACHE] Reused official history; refreshed current and previous month")
        return result
    days = {}
    for year in range(first_year, now.year + 1):
        annual = api.call("/readdata/detail", mode="annually",
                          baseTime=int(datetime(year, 1, 1, tzinfo=CST).timestamp()))
        buckets = annual.get("dailyReadTimes")
        if not buckets and annual.get("totalReadTime") == 0:
            buckets = {}
        if not isinstance(buckets, dict) or (not buckets and annual.get("totalReadTime", 0) > 0):
            buckets = {}
            for month in range(1, (now.month if year == now.year else 12) + 1):
                data = api.call("/readdata/detail", mode="monthly",
                                baseTime=int(datetime(year, month, 1, tzinfo=CST).timestamp()))
                if not isinstance(data.get("readTimes"), dict):
                    raise RuntimeError("Official daily buckets missing; old heatmap retained")
                for timestamp, seconds in data["readTimes"].items():
                    date = datetime.fromtimestamp(int(timestamp), CST)
                    if date.year != year or date.month != month:
                        raise RuntimeError("Official daily bucket outside requested period")
                    buckets[timestamp] = seconds
        for timestamp, seconds in buckets.items():
            date = datetime.fromtimestamp(int(timestamp), CST)
            if date.year != year or date.date() > now.date() or not isinstance(seconds, (int, float)) or seconds < 0:
                raise RuntimeError("Invalid official daily reading bucket")
            if seconds:
                days[date.strftime("%Y-%m-%d")] = seconds
    result = summarize(days, overall["totalReadTime"], None, "weread_official_readdata")
    result["totalDays"] = overall.get("readDays", result["totalDays"])
    result["historyVerifiedAt"] = result["updatedAt"]
    print("[CACHE] Completed full official history verification")
    return result


def load_previous_heatmap():
    gh_token, gist_id = os.environ.get("GH_TOKEN"), os.environ.get("COOKIE_GIST_ID")
    if not gh_token or not gist_id:
        return None
    import requests
    response = requests.get(f"https://api.github.com/gists/{gist_id}",
                            headers={"Authorization": f"token {gh_token}",
                                     "Accept": "application/vnd.github.v3+json"}, timeout=15)
    if response.status_code != 200:
        raise RuntimeError(f"Cannot read heatmap Gist (HTTP {response.status_code}); check GH_TOKEN and COOKIE_GIST_ID")
    content = response.json().get("files", {}).get("heatmap_data.json", {}).get("content")
    try:
        return json.loads(content) if content else None
    except (ValueError, TypeError):
        return None


def summarize(days, total_seconds, books_count, source):
    sorted_dates = sorted(d for d, seconds in days.items() if seconds >= 60)
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
        while days.get(check, 0) >= 60:
            streak += 1
            check = (datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        if streak == 0:
            check = yesterday
            while days.get(check, 0) >= 60:
                streak += 1
                check = (datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        current_streak = streak

    result = {
        "days": days,
        "updatedAt": datetime.now(CST).isoformat(),
        "dataSource": source,
        "totalSeconds": total_seconds,
        "totalDays": len(sorted_dates),
        "currentStreak": current_streak,
        "longestStreak": longest_streak,
        "booksWithTime": books_count,
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
    if not cookies and not env("WEREAD_API_KEY"):
        print("WEREAD_API_KEY or WEREAD_COOKIES not set")
        sys.exit(1)

    previous = load_previous_heatmap() if env("WEREAD_API_KEY") else None
    data = compute(cookies, previous)
    if not push_to_gist(data):
        sys.exit(1)


if __name__ == "__main__":
    main()
