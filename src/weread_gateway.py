"""Official WeRead Skills 1.0.4 gateway, independent of browser cookies.

Contract: https://github.com/Tencent/WeChatReading/tree/main/skills
Only documented personal data is used; missing pages/dates stay unknown.
"""

import time
from threading import Lock
from datetime import datetime, timedelta, timezone

import requests

from config import env, translate_genres

GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
SKILL_VERSION = "1.0.4"
CST = timezone(timedelta(hours=8))


class WeReadGateway:
    # Local pacing policy, not an official published quota. Shared within a process.
    _request_lock = Lock()
    _next_request = 0.0
    _adaptive_interval = 1.1

    @classmethod
    def _wait_for_slot(cls):
        with cls._request_lock:
            delay = cls._next_request - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            cls._next_request = time.monotonic() + max(cls._adaptive_interval, float(env("WEREAD_REQUEST_INTERVAL", "1.1")))

    @classmethod
    def _cool_down(cls, seconds):
        with cls._request_lock:
            cls._adaptive_interval = min(30.0, cls._adaptive_interval * 2)
            cls._next_request = max(cls._next_request, time.monotonic() + seconds)

    def __init__(self, api_key):
        if not api_key or not api_key.startswith("wrk-"):
            raise ValueError("WEREAD_API_KEY must be an official wrk- key")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        self.request_count = 0

    def call(self, api_name, **params):
        payload = {**params, "api_name": api_name, "skill_version": SKILL_VERSION}
        for attempt in range(4):
            self._wait_for_slot()
            self.request_count += 1
            response = self.session.post(GATEWAY, json=payload, timeout=30)
            try:
                data = response.json()
            except ValueError:
                data = None
            # The official gateway reports quota errors as HTTP 499 / -2014.
            limited = response.status_code == 429 or (
                isinstance(data, dict) and data.get("errcode", data.get("errCode")) in (-2014, "-2014")
            )
            if limited:
                if attempt < 3:
                    delay = 60 * (2 ** attempt)
                    retry_after = response.headers.get("Retry-After")
                    if isinstance(retry_after, str):
                        try:
                            delay = max(delay, float(retry_after))
                        except ValueError:
                            from email.utils import parsedate_to_datetime
                            try:
                                delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                            except (ValueError, TypeError, OverflowError):
                                pass
                    print(f"[API] {api_name} rate limited (HTTP {response.status_code}); "
                          f"waiting {delay:g} seconds and slowing subsequent requests")
                    self._cool_down(delay)
                    continue
                raise RuntimeError("WeRead request quota exceeded after retries; try again later")
            if response.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            if not isinstance(data, dict):
                raise RuntimeError(f"WeRead {api_name}: invalid response")
            if "upgrade_info" in data:
                raise RuntimeError("WeRead Skills upgrade required; update the official contract before syncing")
            for key in ("errcode", "errCode"):
                if data.get(key) not in (None, 0, "0"):
                    raise RuntimeError(f"WeRead {api_name}: {key}={data[key]}")
            return data

    def get_shelf(self):
        data = self.call("/shelf/sync")
        if not isinstance(data.get("books"), list):
            raise RuntimeError("WeRead shelf response missing books array")
        print(f"[API] Official shelf: {len(data['books'])} book entries, "
              f"{len(data.get('albums', []))} audio albums, "
              f"{int(bool(data.get('mp')))} article collection. Syncing book entries.")
        return data, data["books"], []

    def get_read_info(self, book_id):
        data = self.call("/book/getprogress", bookId=book_id)
        progress = data.get("book")
        if not isinstance(progress, dict) or "progress" not in progress:
            raise RuntimeError(f"WeRead {book_id}: missing reading progress")
        value = progress["progress"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise RuntimeError(f"WeRead {book_id}: invalid reading progress")
        return progress

    def get_notebooks(self):
        books, seen_ids, seen_cursors = [], set(), set()
        params = {"count": 100}
        while True:
            data = self.call("/user/notebooks", **params)
            page = data.get("books")
            if not isinstance(page, list):
                raise RuntimeError("WeRead: missing notebooks array")
            for item in page:
                book_id = str(item.get("bookId", ""))
                if not book_id:
                    raise RuntimeError("WeRead: notebook missing book ID")
                if book_id not in seen_ids:
                    books.append(item)
                    seen_ids.add(book_id)
            if data.get("hasMore") not in (1, True, "1"):
                return books
            cursor = page[-1].get("sort") if page else None
            if cursor is None or cursor in seen_cursors:
                raise RuntimeError("WeRead: notebook pagination did not advance")
            seen_cursors.add(cursor)
            params["lastSort"] = cursor

    def get_sync_books(self):
        data, shelf, progress = self.get_shelf()
        books = list(shelf)
        ids = {str(item.get("book", item.get("bookInfo", item)).get("bookId")) for item in books}
        for item in self.get_notebooks():
            book_id = str(item["bookId"])
            if book_id not in ids:
                books.append({"book": {**item.get("book", {}), "bookId": book_id}})
                ids.add(book_id)
        print(f"[API] Including {len(books) - len(shelf)} books with notes outside the shelf")
        return data, books, progress

    def get_reviews(self, book_id):
        items, seen_cursors, seen_ids = [], {0}, set()
        cursor = 0
        while True:
            data = self.call("/review/list/mine", bookid=book_id, synckey=cursor, count=100)
            if not isinstance(data.get("reviews"), list):
                raise RuntimeError("WeRead: missing personal reviews array")
            for item in data["reviews"]:
                review = item.get("review", {})
                review_id = review.get("reviewId")
                if not review_id:
                    raise RuntimeError("WeRead: personal review missing ID")
                if review_id not in seen_ids:
                    items.append(review)
                    seen_ids.add(review_id)
            if data.get("hasMore") not in (1, True, "1"):
                return items
            cursor = data.get("synckey")
            if cursor is None or cursor in seen_cursors:
                raise RuntimeError("WeRead: personal review pagination did not advance")
            seen_cursors.add(cursor)

    @staticmethod
    def timestamp(value):
        if not isinstance(value, (int, float)) or value <= 0:
            return None
        return datetime.fromtimestamp(value, CST)

    def get_notes(self, book_id):
        highlights = self.call("/book/bookmarklist", bookId=book_id)
        if not isinstance(highlights.get("updated"), list):
            raise RuntimeError(f"WeRead {book_id}: missing highlights array")
        reviews = self.get_reviews(book_id)
        chapters = {c["chapterUid"]: c for c in highlights.get("chapters", [])}
        # The personal review contract does not promise the old numeric type field.
        # Preserve every personal thought, with its abstract and chapter if present.
        bookmarks = list(highlights["updated"])
        summaries = []
        for review in reviews:
            if review.get("chapterUid") is not None or review.get("abstract"):
                bookmarks.append({**review, "markText": review.get("content", "")})
            else:
                summaries.append({"review": review})
        return {"bookmarks": bookmarks, "summary_reviews": summaries,
                "page_notes": [], "chapter_notes": [], "chapter_info": chapters}

    def get_single_book_data(self, book_id, book_item=None):
        info = self.call("/book/info", bookId=book_id)
        if not info.get("title"):
            raise RuntimeError(f"WeRead {book_id}: missing book title")
        progress = self.get_read_info(book_id)
        notes = self.get_notes(book_id)
        percent = progress["progress"]  # 1 means 1%, never 100%.
        finished_at = self.timestamp(progress.get("finishTime")) if percent == 100 else None
        status = ("Read" if percent == 100 else "Currently Reading"
                  if percent > 0 or progress.get("isStartReading") else "To Be Read")
        seconds = progress.get("recordReadingTime")
        category = info.get("category")
        genres = translate_genres([{"title": category}]) if isinstance(category, str) else []
        return {
            "book_id": book_id, "title": info["title"], "author": info.get("author", ""),
            "percent": percent, "status": status, "source": "WeRead",
            "current_page": None, "total_page": None, "started_at": None,
            "last_read_at": self.timestamp(progress.get("updateTime")),
            "date_finished": finished_at, "cover_image": info.get("cover"),
            "genre": genres, "rating": None, "year_started": None,
            **notes,
            "read_info": progress, "reading_time_seconds": seconds,
            "reading_time": f"{seconds // 3600}时{seconds % 3600 // 60}分" if seconds is not None else None,
            "data_source": "weread_official_gateway",
        }


def create_weread_client(cookies="", auto_refresh=False):
    key = env("WEREAD_API_KEY")
    if key:
        return WeReadGateway(key)
    if not cookies:
        raise ValueError("Missing WEREAD_API_KEY (recommended) or WEREAD_COOKIES")
    from weread_api import WeReadAPI
    return WeReadAPI(cookies, auto_refresh=auto_refresh)
