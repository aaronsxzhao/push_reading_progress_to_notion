#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Direct WeRead API client
Fetches reading data directly from WeRead (微信读书) without needing Obsidian.

Authentication: Uses cookie-based auth (get cookies from browser after logging into weread.qq.com)
"""

import os
import json
import time
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

import requests
from dateutil import parser as dtparser


def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        if default is None:
            return ""
        return default
    return str(v).strip()


# WeRead API endpoints
WEREAD_API_BASE = "https://weread.qq.com"
WEREAD_NOTEBOOKS_API = f"{WEREAD_API_BASE}/web/notebooks"
WEREAD_SHELF_API = f"{WEREAD_API_BASE}/web/shelf/sync"
WEREAD_BOOK_INFO_API = f"{WEREAD_API_BASE}/web/book/bookDetail"
WEREAD_BOOK_INFO_API_V2 = f"{WEREAD_API_BASE}/web/book/info"
WEREAD_READING_DATA_API = f"{WEREAD_API_BASE}/web/readingData"
WEREAD_BOOK_LIST_API = f"{WEREAD_API_BASE}/web/shelf/bookList"
# Alternative endpoints to try for reading data
WEREAD_READ_INFO_API = f"{WEREAD_API_BASE}/web/book/readInfo"
WEREAD_BOOK_READING_API = f"{WEREAD_API_BASE}/web/book/reading"
WEREAD_USER_READING_API = f"{WEREAD_API_BASE}/web/user/reading"


class WeReadAPI:
    """Direct API client for WeRead"""
    
    def __init__(self, cookies: str):
        """
        Initialize with WeRead cookies.
        
        To get cookies:
        1. Open weread.qq.com in browser
        2. Log in
        3. Open DevTools (F12) -> Application/Storage -> Cookies
        4. Copy all cookies as a string, or use browser extension to export
        """
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://weread.qq.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        
        # Parse cookies string into dict
        if cookies:
            cookie_dict = {}
            # Remove outer quotes if present
            cookies = cookies.strip()
            if cookies.startswith('"') and cookies.endswith('"'):
                cookies = cookies[1:-1]
            if cookies.startswith("'") and cookies.endswith("'"):
                cookies = cookies[1:-1]
            
            # Handle both formats: "key=value; key2=value2" and "key=value;key2=value2"
            for item in cookies.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    # URL decode if needed (for values like web%40...)
                    try:
                        # Only decode if it contains % encoded characters
                        if '%' in value:
                            value = urllib.parse.unquote(value)
                    except:
                        pass
                    cookie_dict[key] = value
            
            self.session.cookies.update(cookie_dict)
            
            # Validate cookies
            required_cookies = ["wr_skey", "wr_vid", "wr_rt"]
            missing = [c for c in required_cookies if c not in cookie_dict]
            if missing:
                print(f"[WARNING] Missing cookies: {', '.join(missing)}")
            if "wr_skey" not in cookie_dict:
                print("[WARNING] wr_skey cookie not found. This is the most important cookie for authentication.")
            else:
                print(f"[API] Found wr_skey cookie (length: {len(cookie_dict['wr_skey'])})")
            print(f"[API] Loaded {len(cookie_dict)} cookies: {', '.join(cookie_dict.keys())}")
    
    def get_shelf(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Get all books from shelf (all books in account).
        Returns tuple of (full_response_data, all_books_list, book_progress_list)
        """
        try:
            response = self.session.get(
                WEREAD_SHELF_API,
                params={"synckey": 0, "lectureSynckey": 0}
            )
            print(f"[DEBUG] Shelf API status code: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            # Check for error response FIRST
            if "errCode" in data:
                err_code = data.get("errCode")
                err_msg = data.get("errMsg", "Unknown error")
                print(f"[API ERROR] Shelf API returned error: errCode={err_code}, errMsg={err_msg}")
                print(f"[DEBUG] Full error response:")
                print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
                
                # If it's an auth error, suggest checking cookies
                if err_code in [-2010, -1, 401, 403]:
                    print(f"[TROUBLESHOOTING] This looks like an authentication error.")
                    print(f"[TROUBLESHOOTING] Your cookies may be expired. Get fresh cookies from browser.")
                
                return {}, [], []
            
            # Print full response for debugging (only if successful)
            print(f"[DEBUG] Shelf API full response (first 3000 chars):")
            response_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
            print(response_str[:3000])
            if len(response_str) > 3000:
                print(f"... (truncated, total length: {len(response_str)} chars)")
            
            # Debug: show what fields are in the response
            print(f"[DEBUG] Shelf API response keys: {list(data.keys())}")
            if "bookCount" in data:
                print(f"[DEBUG] Total book count: {data.get('bookCount')}")
            if "pureBookCount" in data:
                print(f"[DEBUG] Pure book count: {data.get('pureBookCount')}")
            
            # Shelf API returns data directly, not wrapped in errcode/errmsg
            # The 'books' field contains ALL books with full info (title, author, etc.)
            all_books = []
            if "books" in data:
                all_books = data.get("books", [])
                print(f"[API] Found {len(all_books)} books in 'books' field (with full info)")
                # Debug first book structure
                if all_books:
                    first_book = all_books[0]
                    print(f"[DEBUG] First book in 'books' field keys: {list(first_book.keys())}")
                    if "bookInfo" in first_book:
                        print(f"[DEBUG] First book bookInfo keys: {list(first_book['bookInfo'].keys())}")
            
            # bookProgress contains reading progress for books that have been read
            book_progress = []
            if "bookProgress" in data:
                book_progress = data.get("bookProgress", [])
                print(f"[API] Found {len(book_progress)} books with progress data")
            
            # Return the full data, all_books list, and progress list
            return data, all_books, book_progress
            
        except requests.exceptions.HTTPError as e:
            print(f"[API ERROR] Shelf HTTP error: {e}")
            if hasattr(e.response, 'text'):
                print(f"[DEBUG] Response text: {e.response.text[:500]}")
            return {}, [], []
        except Exception as e:
            print(f"[API ERROR] Failed to fetch shelf: {e}")
            import traceback
            traceback.print_exc()
            return {}, [], []
        except requests.exceptions.HTTPError as e:
            print(f"[API ERROR] Shelf HTTP error: {e}")
            if hasattr(e.response, 'text'):
                print(f"[DEBUG] Response text: {e.response.text[:500]}")
            return []
        except Exception as e:
            print(f"[API ERROR] Failed to fetch shelf: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_notebooks(self) -> List[Dict[str, Any]]:
        """
        Get all notebooks (books with notes/highlights).
        Returns list of book data.
        """
        try:
            response = self.session.get(
                WEREAD_NOTEBOOKS_API,
                params={"count": 1000}  # Get up to 1000 books
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("errcode") == 0:
                books = data.get("books", [])
                return books
            else:
                print(f"[API ERROR] Notebooks: {data.get('errmsg', 'Unknown error')}")
                return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"[API WARNING] Notebooks endpoint not found (404). Trying shelf endpoint...")
                return []
            print(f"[API ERROR] Failed to fetch notebooks: {e}")
            return []
        except Exception as e:
            print(f"[API ERROR] Failed to fetch notebooks: {e}")
            return []
    
    def get_book_detail(self, book_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed book information - try multiple endpoints"""
        # Try the new info endpoint first
        try:
            response = self.session.get(
                WEREAD_BOOK_INFO_API_V2,
                params={"bookId": book_id}
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("errcode") == 0:
                book_info = data.get("bookInfo") or data.get("book", {})
                if book_info:
                    return book_info
        except:
            pass
        
        # Try the old bookDetail endpoint
        try:
            response = self.session.get(
                WEREAD_BOOK_INFO_API,
                params={"bookId": book_id}
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("errcode") == 0:
                return data.get("book", {})
        except:
            pass
        
        # Try getting from bookList endpoint
        try:
            response = self.session.get(
                WEREAD_BOOK_LIST_API,
                params={"bookIds": book_id, "synckey": 0}
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("errcode") == 0:
                book_list = data.get("bookList", [])
                if book_list:
                    return book_list[0].get("book", {})
        except:
            pass
        
        return None
    
    def get_reading_data(self, book_id: str) -> Optional[Dict[str, Any]]:
        """Get reading progress and statistics - tries multiple endpoints"""
        # List of endpoints to try in order
        endpoints_to_try = [
            ("/web/book/readInfo", {"bookId": book_id}),
            ("/web/book/reading", {"bookId": book_id}),
            ("/web/user/reading", {"bookId": book_id}),
            ("/web/readingData", {"bookId": book_id}),
            ("/web/book/bookProgress", {"bookId": book_id}),
            ("/web/shelf/bookProgress", {"bookId": book_id}),
        ]
        
        for endpoint_path, params in endpoints_to_try:
            try:
                url = f"{WEREAD_API_BASE}{endpoint_path}"
                print(f"[DEBUG] Trying reading data endpoint: {endpoint_path} for book {book_id}")
                response = self.session.get(url, params=params)
                print(f"[DEBUG] {endpoint_path} - status: {response.status_code}")
                
                # Skip 404s silently (endpoint doesn't exist)
                if response.status_code == 404:
                    print(f"[DEBUG] {endpoint_path} - 404 Not Found, trying next endpoint...")
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                print(f"[DEBUG] {endpoint_path} response keys: {list(data.keys())}")
                
                # Check for error response
                if "errCode" in data:
                    err_code = data.get("errCode")
                    if err_code != 0:
                        err_msg = data.get("errMsg", "Unknown")
                        print(f"[DEBUG] {endpoint_path} error: errCode={err_code}, errMsg={err_msg}")
                        continue  # Try next endpoint
                
                if "errcode" in data:
                    err_code = data.get("errcode")
                    if err_code != 0:
                        err_msg = data.get("errmsg", "Unknown")
                        print(f"[DEBUG] {endpoint_path} error: errcode={err_code}, errmsg={err_msg}")
                        continue  # Try next endpoint
                
                # Try different response formats
                reading_data = (data.get("readingData") or data.get("readInfo") or 
                              data.get("data") or data.get("bookProgress") or
                              data.get("progress") or data)
                
                if reading_data and isinstance(reading_data, dict):
                    # Check if it has useful fields
                    has_useful_data = any(key in reading_data for key in [
                        "currentPage", "readPage", "totalPage", "pageCount",
                        "readPercentage", "progress", "currentChapter", "chapterIdx"
                    ])
                    if has_useful_data:
                        print(f"[DEBUG] ✅ {endpoint_path} - Found reading data with keys: {list(reading_data.keys())}")
                        return reading_data
                    else:
                        print(f"[DEBUG] {endpoint_path} - Response doesn't contain reading progress fields")
                        continue
                
                # If no nested data but errcode is 0, return the whole response if it looks useful
                if data.get("errcode") == 0 or data.get("errCode") == 0:
                    has_useful_data = any(key in data for key in [
                        "currentPage", "readPage", "totalPage", "pageCount",
                        "readPercentage", "progress", "currentChapter", "chapterIdx"
                    ])
                    if has_useful_data:
                        print(f"[DEBUG] ✅ {endpoint_path} - Returning full response with reading data")
                        return data
                
                print(f"[DEBUG] {endpoint_path} - No useful reading data found")
                continue  # Try next endpoint
                
            except requests.exceptions.HTTPError as e:
                # Skip 404s (endpoint doesn't exist)
                if hasattr(e.response, 'status_code') and e.response.status_code == 404:
                    print(f"[DEBUG] {endpoint_path} - 404 Not Found, trying next endpoint...")
                    continue
                print(f"[DEBUG] {endpoint_path} HTTP error: {e}")
                continue  # Try next endpoint
            except Exception as e:
                print(f"[DEBUG] {endpoint_path} exception: {e}")
                continue  # Try next endpoint
        
        # If all endpoints failed, return None
        print(f"[DEBUG] ❌ All reading data endpoints failed for book {book_id}")
        return None
    
    def get_all_books_with_progress(self) -> List[Dict[str, Any]]:
        """
        Fetch all books with their reading progress.
        Returns list of book dicts with: title, author, current_page, total_page, etc.
        """
        # Get shelf data - returns (full_response, book_progress_list)
        shelf_data, book_progress_list = self.get_shelf()
        notebooks = self.get_notebooks()
        
        # Check for bookList in shelf response (all books, not just with progress)
        all_book_ids = set()
        all_book_progress = {}
        
        # Try to get all books from bookList API endpoint
        try:
            response = self.session.get(
                WEREAD_BOOK_LIST_API,
                params={"synckey": 0}
            )
            response.raise_for_status()
            book_list_data = response.json()
            
            if book_list_data.get("errcode") == 0:
                book_list = book_list_data.get("bookList", [])
                if book_list:
                    print(f"[API] Found {len(book_list)} books in bookList API (all books)")
                    for book_item in book_list:
                        book_info = book_item.get("book", {})
                        book_id = book_info.get("bookId")
                        if book_id:
                            all_book_ids.add(book_id)
                            # Store with book info and progress if available
                            progress = book_item.get("progress", 0)
                            all_book_progress[book_id] = {
                                "book": book_info,
                                "progress": progress,
                                "has_full_info": True
                            }
        except Exception as e:
            print(f"[DEBUG] bookList API not available: {e}")
        
        # Also check bookList in shelf response if available
        if "bookList" in shelf_data:
            book_list = shelf_data.get("bookList", [])
            print(f"[API] Found {len(book_list)} books in shelf bookList")
            for book_item in book_list:
                book_id = None
                if isinstance(book_item, dict):
                    book_id = book_item.get("bookId") or book_item.get("book", {}).get("bookId")
                    if book_id and book_id not in all_book_ids:
                        all_book_ids.add(book_id)
                        # Store the book info
                        if "book" in book_item:
                            all_book_progress[book_id] = {"book": book_item["book"], "progress": book_item.get("progress", 0), "has_full_info": True}
                        else:
                            all_book_progress[book_id] = book_item
        
        # Then add progress data from bookProgress (books with reading progress)
        for book_progress_item in book_progress_list:
            book_id = book_progress_item.get("bookId")
            if book_id:
                all_book_ids.add(book_id)
                # Merge progress data into existing book or create new entry
                if book_id in all_book_progress:
                    all_book_progress[book_id].update(book_progress_item)
                else:
                    all_book_progress[book_id] = book_progress_item
        
        # Add notebooks that aren't already in shelf
        for notebook in notebooks:
            book_info = notebook.get("book", {})
            book_id = book_info.get("bookId")
            if book_id and book_id not in all_book_ids:
                all_book_ids.add(book_id)
                all_book_progress[book_id] = {"book": book_info}
        
        # If we don't have bookList, use bookProgress and create entries for missing books
        # based on bookCount
        if "bookList" not in shelf_data:
            book_count = shelf_data.get("bookCount", 0) or shelf_data.get("pureBookCount", 0)
            if book_count > len(all_book_progress):
                print(f"[API] Total books: {book_count}, but only {len(all_book_progress)} have progress data")
                print(f"[API] Note: Books without progress will be synced with minimal data")
        
        if not all_book_progress:
            print("[API WARNING] No books found. Check your cookies - they may be expired or invalid.")
            print("[API TIP] Make sure you're logged into weread.qq.com and copy fresh cookies.")
            return []
        
        print(f"[API] Processing {len(all_book_progress)} books...")
        
        if not all_book_progress:
            print("[API WARNING] No books found. Check your cookies - they may be expired or invalid.")
            print("[API TIP] Make sure you're logged into weread.qq.com and copy fresh cookies.")
            return []
        
        print(f"[API] Processing {len(all_book_progress)} books...")
        books_data = []
        
        for book_id, book_item in all_book_progress.items():
            try:
                # Try to get detailed book info (but don't fail if it doesn't work)
                detail = None
                reading_data = None
                try:
                    detail = self.get_book_detail(book_id)
                except:
                    pass  # Book detail endpoint might not work for all books
                
                try:
                    reading_data = self.get_reading_data(book_id)
                except:
                    pass  # Reading data endpoint might not work for all books
                
                # Extract progress from book_item (shelf bookProgress format)
                percent = None
                if "progress" in book_item:
                    percent = book_item.get("progress", 0)  # This is already a percentage (0-100)
                
                # Get book info - prioritize book_item, then detail, then fetch
                book_info = None
                if "book" in book_item and book_item.get("has_full_info"):
                    book_info = book_item["book"]
                elif detail:
                    book_info = detail
                elif "book" in book_item:
                    book_info = book_item["book"]
                
                # If we still don't have book info, try fetching it
                if not book_info or not book_info.get("title"):
                    if not detail:
                        detail = self.get_book_detail(book_id)
                    if detail:
                        book_info = detail
                
                # Last resort: create minimal book_info from book_id
                if not book_info:
                    book_info = {"bookId": book_id}
                
                # Extract progress from reading_data if available
                current_page = None
                total_page = None
                
                if reading_data:
                    current_page = reading_data.get("currentPage") or reading_data.get("readPage")
                    total_page = reading_data.get("totalPage") or reading_data.get("pageCount")
                    if not percent:
                        percent = reading_data.get("readPercentage") or reading_data.get("progress")
                
                if detail:
                    total_page = total_page or detail.get("pageCount") or detail.get("totalPage")
                
                # Calculate current page from percent if we have total
                if percent is not None and total_page and not current_page:
                    current_page = int(round((percent / 100.0) * total_page))
                
                # Determine status
                if percent is not None and percent >= 100:
                    status = "Read"
                elif percent is not None and percent > 0:
                    status = "Currently Reading"
                elif current_page and current_page > 0:
                    status = "Currently Reading"
                else:
                    status = "To Be Read"
                
                # Extract dates
                started_at = None
                last_read_at = None
                date_finished = None
                
                if reading_data:
                    if reading_data.get("startTime"):
                        try:
                            started_at = dtparser.parse(str(reading_data["startTime"]))
                        except:
                            pass
                    if reading_data.get("lastReadTime") or reading_data.get("updateTime"):
                        try:
                            last_read_at = dtparser.parse(str(reading_data.get("lastReadTime") or reading_data.get("updateTime")))
                        except:
                            pass
                
                # Also try dates from book_item (shelf format uses updateTime as timestamp)
                if book_item.get("updateTime"):
                    try:
                        # updateTime is Unix timestamp
                        last_read_at = datetime.fromtimestamp(book_item["updateTime"])
                    except:
                        pass
                
                if status == "Read" and last_read_at:
                    date_finished = last_read_at
                
                # For now, we'll use book_id as title if we can't get the actual title
                # The shelf API doesn't include title/author, so we need to fetch it differently
                # or use a different approach
                title = None
                author = None
                
                if detail:
                    title = detail.get("title")
                    author = detail.get("author")
                
                if not title:
                    # Try to get from a different endpoint or use book_id
                    # For now, we'll need to fetch book info from a different source
                    title = f"Book {book_id}"
                
                book_data = {
                    "title": title,
                    "author": author or "",
                    "current_page": int(current_page) if current_page else None,
                    "total_page": int(total_page) if total_page else None,
                    "status": status,
                    "started_at": started_at,
                    "last_read_at": last_read_at,
                    "date_finished": date_finished,
                    "source": "WeRead",
                }
                
                books_data.append(book_data)
                
                # Rate limiting - be nice to the API
                time.sleep(0.2)
            except Exception as e:
                print(f"[ERROR] Failed to process book {book_id}: {e}")
                continue
        
        return books_data
    
    def get_single_book_data(self, book_id: str, book_item: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Get data for a single book - optimized for one-at-a-time processing
        Uses book info from bookList API (which already has title/author) as primary source
        """
        try:
            # Priority 1: Use book info from book_item (from bookList API - already has title/author)
            book_info = None
            progress = 0
            
            if book_item and "book" in book_item:
                book_info = book_item["book"]
                progress = book_item.get("progress", 0)
                # bookList API already provides title, author, pageCount, etc.
            
            # Priority 2: If book_info doesn't have title, try fetching detail
            if not book_info or not book_info.get("title"):
                detail = self.get_book_detail(book_id)
                if detail:
                    # Merge detail into book_info, preserving any existing data
                    if book_info:
                        book_info.update(detail)
                    else:
                        book_info = detail
            
            # Priority 3: Last resort - create minimal book_info
            if not book_info:
                book_info = {"bookId": book_id}
            
            # Get reading data - try multiple endpoints
            reading_data = None
            print(f"[DEBUG] Attempting to fetch reading_data for book {book_id}...")
            reading_data = self.get_reading_data(book_id)
            if reading_data:
                print(f"[DEBUG] ✅ Successfully got reading_data for {book_id} from API")
            else:
                print(f"[DEBUG] ⚠️  No reading_data returned from any API endpoint for {book_id}")
            
            # DEBUG: Print all available data
            print(f"\n{'='*60}")
            print(f"[DEBUG] FULL API RESPONSE DATA for book {book_id}")
            print(f"{'='*60}")
            print(f"\n1. book_info (from book_item or detail):")
            print(json.dumps(book_info, indent=2, ensure_ascii=False, default=str))
            print(f"\n2. book_item (from shelf/bookList with progress data):")
            print(json.dumps(book_item, indent=2, ensure_ascii=False, default=str) if book_item else "None")
            print(f"{'='*60}\n")
            
            # Extract progress from book_item (which contains bookProgress data)
            current_page = None
            total_page = None
            percent = progress  # From book_item (bookList API or bookProgress)
            
            # Get chapter information from book_item (bookProgress data)
            chapter_idx = None
            if book_item:
                chapter_idx = book_item.get("chapterIdx")  # Current chapter index (1-based)
            
            # Get total chapters from book_info
            last_chapter_idx = None
            if book_info:
                last_chapter_idx = book_info.get("lastChapterIdx")  # Total chapters
            
            # Try to get total pages from book_info (most reliable)
            if book_info:
                # Try all possible field names for total pages
                total_page = (book_info.get("pageCount") or book_info.get("totalPage") or 
                             book_info.get("totalPages") or book_info.get("page") or
                             book_info.get("pages") or book_info.get("pageNum") or
                             book_info.get("totalPageCount") or book_info.get("maxPage"))
            
            # Try to get page data from reading_data API
            if reading_data:
                # Extract current page from reading_data
                if not current_page:
                    current_page = (reading_data.get("currentPage") or 
                                  reading_data.get("readPage") or 
                                  reading_data.get("readPageNum") or
                                  reading_data.get("page"))
                
                # Extract total page from reading_data
                if not total_page:
                    total_page = (reading_data.get("totalPage") or 
                                reading_data.get("pageCount") or
                                reading_data.get("totalPages") or
                                reading_data.get("maxPage") or
                                reading_data.get("pageNum"))
                
                # Update percent from reading_data if available
                if not percent or percent == 0:
                    percent = (reading_data.get("readPercentage") or 
                             reading_data.get("progress") or
                             reading_data.get("readPercent"))
                
                print(f"[DEBUG] From reading_data API: current_page={current_page}, total_page={total_page}, percent={percent}")
            
            # Calculate current page from percent if we have total but not current
            if percent is not None and total_page and not current_page:
                current_page = int(round((percent / 100.0) * total_page))
                print(f"[DEBUG] Calculated current_page from percent: {current_page} = {percent}% of {total_page}")
            
            # If we have current_page but not total_page, try to estimate from percent
            if current_page and percent is not None and percent > 0 and not total_page:
                total_page = int(round((current_page / (percent / 100.0))))
                print(f"[DEBUG] Estimated total_page from current_page and percent: {total_page} = {current_page} / ({percent}%)")
            
            print(f"[DEBUG] Book {book_id} - EXTRACTED: total_page={total_page}, current_page={current_page}, percent={percent}, chapterIdx={chapter_idx}, lastChapterIdx={last_chapter_idx}")
            
            # Check for finished flags (highest priority)
            is_finished = False
            if book_info:
                is_finished = (book_info.get("finishReading") == 1 or 
                              book_info.get("finished") == 1 or
                              book_info.get("isFinished") == 1 or
                              book_info.get("readFinish") == 1)
            if book_item and not is_finished:
                is_finished = (book_item.get("finishReading") == 1 or 
                              book_item.get("finished") == 1 or
                              book_item.get("isFinished") == 1)
            if reading_data and not is_finished:
                is_finished = (reading_data.get("finishReading") == 1 or 
                              reading_data.get("finished") == 1 or
                              reading_data.get("isFinished") == 1)
            
            # Determine status - finished flag takes priority
            if is_finished:
                status = "Read"
                print(f"[DEBUG] Book {book_id} - marked as Read (finished flag = 1)")
            elif percent is not None and percent >= 100:
                status = "Read"
            elif percent is not None and percent > 0:
                status = "Currently Reading"
            elif current_page and current_page > 0:
                status = "Currently Reading"
            else:
                status = "To Be Read"
            
            # Extract dates - prioritize first read time as started_at
            started_at = None
            first_read_at = None  # First time reading this book
            last_read_at = None
            date_finished = None
            
            # Collect all possible start times to find the earliest (first read)
            start_times = []
            
            # Debug: print raw date data
            if book_item and book_item.get("updateTime"):
                print(f"[DEBUG] Book {book_id} - updateTime (raw): {book_item.get('updateTime')}")
            
            if reading_data:
                print(f"[DEBUG] Book {book_id} - reading_data keys: {list(reading_data.keys())}")
                if reading_data.get("startTime"):
                    print(f"[DEBUG] Book {book_id} - startTime (raw): {reading_data.get('startTime')}")
                    try:
                        start_time_raw = reading_data["startTime"]
                        # Handle Unix timestamp (seconds)
                        if isinstance(start_time_raw, (int, float)):
                            if start_time_raw > 1e10:  # Milliseconds timestamp
                                start_time = datetime.fromtimestamp(start_time_raw / 1000)
                            else:  # Seconds timestamp
                                start_time = datetime.fromtimestamp(start_time_raw)
                        else:
                            start_time = dtparser.parse(str(start_time_raw))
                        start_times.append(start_time)
                        started_at = start_time
                        print(f"[DEBUG] Book {book_id} - parsed startTime: {start_time}")
                    except Exception as e:
                        print(f"[DEBUG] Book {book_id} - failed to parse startTime: {e}")
                
                if reading_data.get("lastReadTime") or reading_data.get("updateTime"):
                    try:
                        last_read_raw = reading_data.get("lastReadTime") or reading_data.get("updateTime")
                        if isinstance(last_read_raw, (int, float)):
                            if last_read_raw > 1e10:  # Milliseconds
                                last_read_at = datetime.fromtimestamp(last_read_raw / 1000)
                            else:  # Seconds
                                last_read_at = datetime.fromtimestamp(last_read_raw)
                        else:
                            last_read_at = dtparser.parse(str(last_read_raw))
                    except Exception as e:
                        print(f"[DEBUG] Book {book_id} - failed to parse lastReadTime: {e}")
            
            # Also check book_item for updateTime (from bookProgress) - this is Unix timestamp
            if book_item and book_item.get("updateTime"):
                try:
                    update_time_raw = book_item["updateTime"]
                    # updateTime is typically Unix timestamp in seconds
                    if isinstance(update_time_raw, (int, float)):
                        if update_time_raw > 1e10:  # Milliseconds timestamp
                            update_time = datetime.fromtimestamp(update_time_raw / 1000)
                        else:  # Seconds timestamp
                            update_time = datetime.fromtimestamp(update_time_raw)
                        print(f"[DEBUG] Book {book_id} - parsed updateTime: {update_time} (from timestamp {update_time_raw})")
                        if not last_read_at:
                            last_read_at = update_time
                        # Use updateTime as potential first read if we don't have startTime
                        if not start_times:
                            start_times.append(update_time)
                    else:
                        # Try parsing as string
                        update_time = dtparser.parse(str(update_time_raw))
                        if not last_read_at:
                            last_read_at = update_time
                        if not start_times:
                            start_times.append(update_time)
                except Exception as e:
                    print(f"[DEBUG] Book {book_id} - failed to parse updateTime: {e}")
            
            # Use earliest start time as first_read_at and started_at
            if start_times:
                first_read_at = min(start_times)
                started_at = first_read_at
                print(f"[DEBUG] Book {book_id} - final started_at: {started_at}")
            
            if status == "Read" and last_read_at:
                date_finished = last_read_at
            
            # Get title and author
            title = book_info.get("title") or book_info.get("name") or f"Book {book_id}"
            author = book_info.get("author") or book_info.get("authorName") or ""
            
            # Get additional book information - try multiple field names
            cover_image = (book_info.get("cover") or book_info.get("coverUrl") or 
                          book_info.get("bookCover") or book_info.get("coverImg") or
                          book_info.get("intro"))
            
            genre = (book_info.get("category") or book_info.get("categoryName") or 
                    book_info.get("genre") or book_info.get("categoryText") or
                    book_info.get("type"))
            
            rating = (book_info.get("rating") or book_info.get("score") or 
                     book_info.get("star") or book_info.get("bookRating") or
                     book_info.get("myRating"))
            
            # Get year started reading (extract year from started_at date)
            year_started = None
            if started_at:
                try:
                    year_started = started_at.year
                except:
                    pass
            
            # Debug: print if we don't have title
            if not title or title == f"Book {book_id}":
                print(f"[DEBUG] Book {book_id} - book_info keys: {list(book_info.keys())}")
                print(f"[DEBUG] Book {book_id} - book_item keys: {list(book_item.keys()) if book_item else 'None'}")
            
            return {
                "title": title,
                "author": author,
                "current_page": int(current_page) if current_page else None,
                "total_page": int(total_page) if total_page else None,
                "status": status,
                "started_at": started_at,  # First read at (earliest start time)
                "last_read_at": last_read_at,
                "date_finished": date_finished,
                "source": "WeRead",
                "cover_image": cover_image,
                "genre": genre,
                "year_started": year_started,
                "rating": float(rating) if rating else None,
            }
        except Exception as e:
            print(f"[ERROR] Failed to get data for book {book_id}: {e}")
            import traceback
            traceback.print_exc()
            return None


def fetch_from_api(cookies: str) -> List[Dict[str, Any]]:
    """Convenience function to fetch all books from WeRead API"""
    client = WeReadAPI(cookies)
    return client.get_all_books_with_progress()

