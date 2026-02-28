#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WeRead (微信读书) API client.

Uses cookie-based auth. The WeRead web API has these endpoints:
  GET  /web/shelf/sync            — all books on shelf
  GET  /web/book/info             — single book detail
  GET  /web/book/readinfo         — reading progress, time, dates
  GET  /web/book/bookmarklist     — highlights (划线)
  GET  /web/review/list           — notes/reviews (笔记)
  POST /web/book/chapterInfos     — chapter structure
"""

import functools
import math
import os
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import dateutil.tz
import requests
from dateutil import parser as dtparser

from config import (
    env,
    translate_genres,
    WEREAD_API_BASE,
    WEREAD_SHELF_API,
    WEREAD_BOOK_INFO_API,
    WEREAD_READ_INFO_API,
    WEREAD_BOOKMARKLIST_API,
    WEREAD_REVIEW_LIST_API,
    WEREAD_CHAPTER_INFO_API,
)


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def _retry(max_attempts: int = 3, wait_seconds: float = 5.0):
    """
    Retry on network or HTTP errors.
    Before each attempt, visit the WeRead homepage to refresh the session.
    This is required — without it, endpoints like bookmarklist return empty.
    (Matches weread2notion's retry_on_exception=refresh_token pattern.)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    self.session.get(WEREAD_API_BASE, timeout=10)
                except Exception:
                    pass
                try:
                    return func(self, *args, **kwargs)
                except requests.exceptions.HTTPError as e:
                    last_exc = e
                    if getattr(e.response, "status_code", None) == 401:
                        self._handle_auth_error(e.response, func.__name__)
                    if attempt < max_attempts - 1:
                        time.sleep(wait_seconds)
                except requests.exceptions.RequestException as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        time.sleep(wait_seconds)
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# WeReadAPI
# ---------------------------------------------------------------------------

class WeReadAPI:
    """Direct API client for WeRead."""

    def __init__(self, cookies: str, auto_refresh: bool = False):
        """
        Args:
            cookies: Cookie string (e.g. "wr_skey=xxx; wr_vid=xxx; wr_rt=xxx")
            auto_refresh: If True, open a browser to re-login when cookies expire.
        """
        self.auto_refresh = auto_refresh
        self.session = requests.Session()
        # Do NOT set Referer — WeRead's bookmarklist API returns empty when
        # a Referer header is present. The weread2notion project sets no
        # custom headers at all; we only keep a minimal User-Agent.

        self.cookie_dict: Dict[str, str] = {}
        if cookies:
            self.cookie_dict = self._parse_cookie_string(cookies)
            self.session.cookies.update(self.cookie_dict)

            required = ["wr_skey", "wr_vid", "wr_rt"]
            missing = [c for c in required if c not in self.cookie_dict]
            if missing:
                msg = (
                    f"Missing required cookies: {', '.join(missing)}\n"
                    f"Required: wr_skey (auth key), wr_vid (session), wr_rt (refresh)\n"
                    f"Get them from browser DevTools → Application → Cookies → weread.qq.com"
                )
                raise ValueError(msg)

            print(f"[API] Loaded {len(self.cookie_dict)} cookies: "
                  f"{', '.join(self.cookie_dict.keys())}")

    # ------------------------------------------------------------------
    # Cookie helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_cookie_string(raw: str) -> Dict[str, str]:
        raw = raw.strip().strip("\"'")
        result: Dict[str, str] = {}
        for item in raw.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                key, value = key.strip(), value.strip()
                if "%" in value:
                    try:
                        value = urllib.parse.unquote(value)
                    except Exception:
                        pass
                result[key] = value
        return result

    def get_cookie_string(self) -> str:
        """Return current cookies as a semicolon-separated string."""
        return "; ".join(f"{k}={v}" for k, v in sorted(self.cookie_dict.items()))

    # ------------------------------------------------------------------
    # Auth / validation
    # ------------------------------------------------------------------

    def validate_cookies(self) -> bool:
        """Quick check — hit the shelf endpoint and see if we're authenticated."""
        try:
            resp = self.session.get(
                WEREAD_SHELF_API,
                params={"synckey": 0, "lectureSynckey": 0},
                timeout=10,
            )
            if resp.status_code == 401:
                self._handle_auth_error(resp, "validate_cookies")
                return False

            data = resp.json()
            err = data.get("errCode")
            if err in (-2010, -2012, -1, 401, 403):
                print(f"[API] Cookie validation failed (errCode={err})")
                self._handle_auth_error(resp, "validate_cookies")
                return False

            # Persist any refreshed cookies from Set-Cookie headers
            if self._update_cookies_from_response(resp):
                self._persist_cookies_to_env()

            print("[API] Cookie validation OK")
            return resp.status_code == 200

        except requests.exceptions.RequestException as e:
            print(f"[API] Cookie validation error: {e}")
            return False

    def _handle_auth_error(self, response, caller: str) -> bool:
        """
        Called when an API response looks like an auth failure.
        Returns True only if cookies were successfully refreshed (caller should retry).
        """
        err_code = err_msg = None
        try:
            data = response.json()
            err_code = data.get("errCode")
            err_msg = data.get("errMsg", "")
        except Exception:
            pass

        print(f"\n[AUTH] Cookie expired — detected in {caller}")
        if err_code:
            print(f"[AUTH] errCode={err_code}  errMsg={err_msg}")

        if self.auto_refresh:
            print("[AUTH] Attempting automatic browser-based cookie refresh...")
            if self._refresh_cookies_from_browser():
                print("[AUTH] Refresh succeeded")
                return True
            print("[AUTH] Refresh failed")

        print("[AUTH] Update WEREAD_COOKIES in .env (wr_skey, wr_vid, wr_rt)")
        return False

    # ------------------------------------------------------------------
    # Cookie persistence
    # ------------------------------------------------------------------

    def _update_cookies_from_response(self, response) -> bool:
        """Extract wr_* cookies from Set-Cookie headers and update session."""
        header = response.headers.get("set-cookie") or response.headers.get("Set-Cookie")
        if not header:
            return False

        updated = False
        for segment in header.split(","):
            part = segment.strip().split(";")[0]
            if "=" in part:
                name, value = part.split("=", 1)
                name, value = name.strip(), value.strip()
                if name.startswith("wr_") and value:
                    self.session.cookies.set(name, value)
                    self.cookie_dict[name] = value
                    updated = True
        return updated

    def _persist_cookies_to_env(self) -> bool:
        """Write current wr_* cookies back to .env and optionally to a GitHub Gist."""
        try:
            wr_cookies = {k: v for k, v in self.cookie_dict.items() if k.startswith("wr_")}
            for name, value in self.session.cookies.items():
                if name.startswith("wr_"):
                    wr_cookies.setdefault(name, value)
            if not wr_cookies:
                return False

            cookie_str = "; ".join(f"{k}={v}" for k, v in sorted(wr_cookies.items()))

            env_path = Path(__file__).parent.parent / ".env"
            if not env_path.exists():
                return False

            lines = env_path.read_text(encoding="utf-8").split("\n")
            new_lines, replaced = [], False
            for line in lines:
                s = line.strip()
                if s.startswith("WEREAD_COOKIES=") or s.startswith("#WEREAD_COOKIES="):
                    new_lines.append(f'WEREAD_COOKIES="{cookie_str}"')
                    replaced = True
                else:
                    new_lines.append(line)
            if not replaced:
                new_lines.append(f'WEREAD_COOKIES="{cookie_str}"')
            env_path.write_text("\n".join(new_lines), encoding="utf-8")

            self._update_gist_cookies(cookie_str)
            return True
        except Exception as e:
            print(f"[API] Failed to persist cookies: {e}")
            return False

    def _update_gist_cookies(self, cookie_str: str) -> bool:
        gh_token = os.environ.get("GH_TOKEN") or env("GH_TOKEN")
        gist_id = os.environ.get("COOKIE_GIST_ID") or env("COOKIE_GIST_ID")
        if not gh_token or not gist_id:
            return False
        try:
            r = requests.patch(
                f"https://api.github.com/gists/{gist_id}",
                headers={"Authorization": f"token {gh_token}",
                         "Accept": "application/vnd.github.v3+json"},
                json={"files": {"weread_cookies.txt": {"content": cookie_str}}},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def _refresh_cookies_from_browser(self) -> bool:
        """Run scripts/fetch_cookies_auto.py and reload cookies."""
        try:
            import subprocess, sys
            script = Path(__file__).parent.parent / "scripts" / "fetch_cookies_auto.py"
            if not script.exists():
                return False

            print("[AUTH] Opening browser for login...")
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return False

            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                try:
                    from dotenv import load_dotenv
                    load_dotenv(env_path, override=True)
                except ImportError:
                    pass

                new = env("WEREAD_COOKIES", "")
                if new:
                    self.cookie_dict = self._parse_cookie_string(new)
                    self.session.cookies.update(self.cookie_dict)
                    self._persist_cookies_to_env()
                    return True
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # API methods — each maps to exactly one WeRead endpoint
    # ------------------------------------------------------------------

    @_retry(max_attempts=3, wait_seconds=5.0)
    def get_shelf(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        GET /web/shelf/sync
        Returns (full_response, books_list, book_progress_list).
        """
        resp = self.session.get(
            WEREAD_SHELF_API,
            params={"synckey": 0, "lectureSynckey": 0},
        )
        resp.raise_for_status()
        data = resp.json()

        err = data.get("errCode")
        if err and err in (-2010, -2012, -1, 401, 403):
            self._handle_auth_error(resp, "get_shelf")
            return {}, [], []

        books = data.get("books", [])
        progress = data.get("bookProgress", [])
        print(f"[API] Shelf: {len(books)} books, {len(progress)} with progress")
        return data, books, progress

    @_retry(max_attempts=3, wait_seconds=5.0)
    def get_book_info(self, book_id: str) -> Optional[Dict[str, Any]]:
        """
        GET /web/book/info?bookId=…
        Returns book metadata dict or None.
        """
        resp = self.session.get(WEREAD_BOOK_INFO_API, params={"bookId": book_id})
        resp.raise_for_status()
        return resp.json() or None

    @_retry(max_attempts=3, wait_seconds=5.0)
    def get_read_info(self, book_id: str) -> Optional[Dict[str, Any]]:
        """
        GET /web/book/readinfo?bookId=…&readingDetail=1&readingBookIndex=1&finishedDate=1
        Returns reading progress, time, dates.
        """
        resp = self.session.get(
            WEREAD_READ_INFO_API,
            params={"bookId": book_id, "readingDetail": 1,
                    "readingBookIndex": 1, "finishedDate": 1},
        )
        resp.raise_for_status()
        return resp.json() or None

    @_retry(max_attempts=3, wait_seconds=5.0)
    def get_bookmark_list(self, book_id: str) -> List[Dict[str, Any]]:
        """
        GET /web/book/bookmarklist?bookId=…
        Returns sorted list of highlight/bookmark items (划线).
        """
        resp = self.session.get(WEREAD_BOOKMARKLIST_API, params={"bookId": book_id})
        resp.raise_for_status()
        updated = resp.json().get("updated")
        if not updated:
            return []
        return sorted(
            updated,
            key=lambda x: (
                x.get("chapterUid", 1),
                int(x.get("range", "0-0").split("-")[0]) if x.get("range") else 0,
            ),
        )

    @_retry(max_attempts=3, wait_seconds=5.0)
    def get_review_list(self, book_id: str) -> Tuple[
        List[Dict[str, Any]], List[Dict[str, Any]],
        List[Dict[str, Any]], List[Dict[str, Any]],
    ]:
        """
        GET /web/review/list?bookId=…&listType=11&mine=1&syncKey=0
        Returns (summary_reviews, regular_reviews, page_notes, chapter_notes).

        Review types: 1=划线笔记  2=页面笔记  3=章节笔记  4=书评
        """
        resp = self.session.get(
            WEREAD_REVIEW_LIST_API,
            params={"bookId": book_id, "listType": 11, "mine": 1, "syncKey": 0},
        )
        resp.raise_for_status()

        summary, regular, page, chapter = [], [], [], []
        for item in resp.json().get("reviews", []):
            review = item.get("review", {})
            t = review.get("type")
            if t == 4:
                summary.append(item)
            elif t == 1:
                transformed = {**review, "markText": review.pop("content", "")}
                regular.append(transformed)
            elif t == 2:
                page.append(review)
            elif t == 3:
                chapter.append(review)
        return summary, regular, page, chapter

    @_retry(max_attempts=3, wait_seconds=5.0)
    def get_chapter_info(self, book_id: str) -> Optional[Dict[int, Dict[str, Any]]]:
        """
        POST /web/book/chapterInfos
        Returns {chapterUid: chapter_data, …} or None.
        """
        body = {"bookIds": [book_id], "synckeys": [0], "teenmode": 0}
        resp = self.session.post(WEREAD_CHAPTER_INFO_API, json=body)
        resp.raise_for_status()
        data = resp.json()
        if (data and "data" in data
                and len(data["data"]) == 1
                and "updated" in data["data"][0]):
            return {item["chapterUid"]: item for item in data["data"][0]["updated"]}
        return None

    # ------------------------------------------------------------------
    # High-level: single book processing
    # ------------------------------------------------------------------

    def get_single_book_data(
        self, book_id: str, book_item: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch and assemble all data for one book.
        ``book_item`` is the shelf entry (already has book info + progress).
        """
        try:
            # --- Book info (from shelf or /web/book/info) ---
            book_info, progress = self._extract_book_info(book_id, book_item)

            # --- Read info (progress, dates, reading time) ---
            try:
                read_info = self.get_read_info(book_id)
            except Exception:
                read_info = None

            # --- Bookmarks + reviews ---
            try:
                bookmarks = self.get_bookmark_list(book_id)
            except Exception:
                bookmarks = []
            try:
                summary_reviews, regular_reviews, page_notes, chapter_notes = \
                    self.get_review_list(book_id)
            except Exception:
                summary_reviews, regular_reviews, page_notes, chapter_notes = [], [], [], []

            # --- Chapter info ---
            try:
                chapter_info = self.get_chapter_info(book_id)
            except Exception:
                chapter_info = None

            # --- Merge bookmarks + type-1 reviews, sort by position ---
            all_bookmarks = bookmarks + regular_reviews
            if all_bookmarks:
                all_bookmarks = sorted(
                    all_bookmarks,
                    key=lambda x: (
                        x.get("chapterUid", 1),
                        int(x.get("range", "0-0").split("-")[0])
                        if x.get("range") else 0,
                    ),
                )

            # --- Progress & pages ---
            percent = progress
            reading_progress = None
            if read_info:
                reading_progress = read_info.get("readingProgress")
                if not percent:
                    percent = reading_progress

            total_page = self._calc_total_pages(chapter_info, book_info)

            # --- Status ---
            is_finished = self._check_finished(book_info, book_item, read_info)
            if is_finished:
                status = "Read"
            elif percent is not None and percent >= 5:
                status = "Currently Reading"
            else:
                status = "To Be Read"

            # --- Current page ---
            current_page = None
            if total_page:
                if status == "Read":
                    current_page = total_page
                elif reading_progress and reading_progress > 0:
                    current_page = math.ceil((reading_progress / 100.0) * total_page)
                elif percent and percent > 0:
                    current_page = math.ceil((percent / 100.0) * total_page)

            # --- Dates ---
            started_at, last_read_at, date_finished = self._extract_dates(
                read_info, book_item, status,
            )

            # --- Reading time ---
            reading_time = None
            if read_info and read_info.get("readingTime"):
                secs = read_info["readingTime"]
                h, m = secs // 3600, (secs % 3600) // 60
                if h > 0:
                    reading_time = f"{h}时{m}分" if m else f"{h}时"
                elif m > 0:
                    reading_time = f"{m}分"

            title = book_info.get("title", f"Book {book_id}")
            author = book_info.get("author", "")

            return {
                "title": title,
                "author": author,
                "current_page": int(current_page) if current_page else None,
                "total_page": int(total_page) if total_page else None,
                "percent": float(percent) if percent is not None else None,
                "status": status,
                "started_at": started_at,
                "last_read_at": last_read_at,
                "date_finished": date_finished,
                "source": "WeRead",
                "cover_image": book_info.get("cover"),
                "genre": translate_genres(book_info.get("categories")),
                "year_started": started_at.year if started_at else None,
                "rating": float(book_info["rating"]) if book_info.get("rating") else None,
                "bookmarks": all_bookmarks,
                "summary_reviews": summary_reviews,
                "page_notes": page_notes,
                "chapter_notes": chapter_notes,
                "chapter_info": chapter_info,
                "read_info": read_info,
                "reading_time": reading_time,
            }
        except Exception as e:
            print(f"[ERROR] Failed to get data for book {book_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ------------------------------------------------------------------
    # Internal helpers for get_single_book_data
    # ------------------------------------------------------------------

    def _extract_book_info(
        self, book_id: str, book_item: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], int]:
        """Pull book metadata from the shelf entry, falling back to /web/book/info."""
        book_info: Dict[str, Any] = {}
        progress = 0

        if book_item:
            if "book" in book_item:
                book_info = book_item["book"]
            elif "bookInfo" in book_item:
                book_info = book_item["bookInfo"]
            elif "title" in book_item:
                book_info = book_item
            progress = book_item.get("progress", 0)

        if not book_info.get("title"):
            try:
                detail = self.get_book_info(book_id)
                if detail:
                    if book_info:
                        book_info.update(detail)
                    else:
                        book_info = detail
            except Exception:
                pass

        if not book_info:
            book_info = {"bookId": book_id}

        return book_info, progress

    @staticmethod
    def _calc_total_pages(
        chapter_info: Optional[Dict[int, Dict[str, Any]]],
        book_info: Dict[str, Any],
    ) -> Optional[int]:
        """Derive total page count from chapter word counts or book metadata."""
        if chapter_info:
            words = sum(
                ch.get("wordCount", 0)
                for ch in chapter_info.values()
                if isinstance(ch.get("wordCount"), (int, float))
            )
            if words > 0:
                return round(words / 550)

        return book_info.get("pageCount") or None

    @staticmethod
    def _check_finished(
        book_info: Dict[str, Any],
        book_item: Optional[Dict[str, Any]],
        read_info: Optional[Dict[str, Any]],
    ) -> bool:
        if book_info.get("finishReading") == 1:
            return True
        if book_item:
            if book_item.get("finishReading") == 1:
                return True
            if book_item.get("book", {}).get("finishReading") == 1:
                return True
        if read_info and read_info.get("finishReading") == 1:
            return True
        return False

    def _extract_dates(
        self,
        read_info: Optional[Dict[str, Any]],
        book_item: Optional[Dict[str, Any]],
        status: str,
    ) -> Tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
        started_at = last_read_at = date_finished = None

        if read_info:
            detail = read_info.get("readDetail") or {}
            started_at = self._ts(detail.get("beginReadingDate"))
            if not started_at:
                started_at = self._ts(read_info.get("readingBookDate"))
            date_finished = self._ts(read_info.get("finishedDate"))

            last_from_detail = self._ts(detail.get("lastReadingDate"))
            if last_from_detail:
                last_read_at = last_from_detail

        if book_item:
            t = self._ts(book_item.get("readUpdateTime") or book_item.get("updateTime"))
            if t and (not last_read_at or t > last_read_at):
                last_read_at = t

        if not date_finished and status == "Read" and last_read_at:
            date_finished = last_read_at
        if status == "To Be Read" and not started_at and last_read_at:
            started_at = last_read_at

        return started_at, last_read_at, date_finished

    @staticmethod
    def _ts(value: Any) -> Optional[datetime]:
        """Parse a timestamp (unix seconds/ms) or date string."""
        if value is None:
            return None
        try:
            tz = dateutil.tz.tzlocal()
            if isinstance(value, (int, float)):
                if value > 1e10:
                    return datetime.fromtimestamp(value / 1000, tz=tz)
                return datetime.fromtimestamp(value, tz=tz)
            parsed = dtparser.parse(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
            return parsed
        except Exception:
            return None
