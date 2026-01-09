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
WEREAD_READING_DATA_API = f"{WEREAD_API_BASE}/web/readingData"


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
    
    def get_shelf(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Get all books from shelf (all books in account).
        Returns tuple of (full_response_data, book_progress_list)
        """
        try:
            response = self.session.get(
                WEREAD_SHELF_API,
                params={"synckey": 0, "lectureSynckey": 0}
            )
            response.raise_for_status()
            data = response.json()
            
            # Debug: show what fields are in the response
            print(f"[DEBUG] Shelf API response keys: {list(data.keys())}")
            if "bookCount" in data:
                print(f"[DEBUG] Total book count: {data.get('bookCount')}")
            if "pureBookCount" in data:
                print(f"[DEBUG] Pure book count: {data.get('pureBookCount')}")
            
            # Shelf API returns data directly, not wrapped in errcode/errmsg
            # Check if we have bookProgress (list of books with progress)
            book_progress = []
            if "bookProgress" in data:
                book_progress = data.get("bookProgress", [])
                print(f"[API] Found {len(book_progress)} books with progress in shelf")
            
            # Also check for bookList (all books, including those without progress)
            book_list = []
            if "bookList" in data:
                book_list = data.get("bookList", [])
                print(f"[API] Found {len(book_list)} books in bookList")
            
            # Check for other possible fields that might contain all books
            for key in ["books", "allBooks", "bookItems", "shelfBooks"]:
                if key in data:
                    items = data.get(key, [])
                    if isinstance(items, list) and len(items) > 0:
                        print(f"[DEBUG] Found {len(items)} items in '{key}' field")
            
            # Return both the full data and the progress list
            return data, book_progress
            
        except requests.exceptions.HTTPError as e:
            print(f"[API ERROR] Shelf HTTP error: {e}")
            if hasattr(e.response, 'text'):
                print(f"[DEBUG] Response text: {e.response.text[:500]}")
            return {}, []
        except Exception as e:
            print(f"[API ERROR] Failed to fetch shelf: {e}")
            import traceback
            traceback.print_exc()
            return {}, []
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
        """Get detailed book information"""
        try:
            response = self.session.get(
                WEREAD_BOOK_INFO_API,
                params={"bookId": book_id}
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("errcode") == 0:
                return data.get("book", {})
            return None
        except requests.exceptions.HTTPError as e:
            # Don't print error for 404s - many books don't have this endpoint available
            if e.response.status_code != 404:
                print(f"[API ERROR] Failed to fetch book detail for {book_id}: {e}")
            return None
        except Exception as e:
            # Silently fail - this endpoint doesn't work for many books
            return None
    
    def get_reading_data(self, book_id: str) -> Optional[Dict[str, Any]]:
        """Get reading progress and statistics"""
        try:
            response = self.session.get(
                WEREAD_READING_DATA_API,
                params={"bookId": book_id}
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("errcode") == 0:
                return data.get("readingData", {})
            return None
        except requests.exceptions.HTTPError as e:
            # Don't print error for 404s - many books don't have this endpoint available
            if e.response.status_code != 404:
                print(f"[API ERROR] Failed to fetch reading data for {book_id}: {e}")
            return None
        except Exception as e:
            # Silently fail - this endpoint doesn't work for many books
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
        
        # First, get all books from bookList if available (this should have all 144)
        if "bookList" in shelf_data:
            book_list = shelf_data.get("bookList", [])
            print(f"[API] Found {len(book_list)} books in bookList (all books)")
            for book_item in book_list:
                book_id = None
                if isinstance(book_item, dict):
                    book_id = book_item.get("bookId") or book_item.get("book", {}).get("bookId")
                    if book_id:
                        all_book_ids.add(book_id)
                        # Store the book info
                        if "book" in book_item:
                            all_book_progress[book_id] = {"book": book_item["book"], "progress": book_item.get("progress", 0)}
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
                
                # Get book info
                if "book" in book_item:
                    book_info = book_item["book"]
                elif detail:
                    book_info = detail
                else:
                    # Fallback: create minimal book_info from book_id
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


def fetch_from_api(cookies: str) -> List[Dict[str, Any]]:
    """Convenience function to fetch all books from WeRead API"""
    client = WeReadAPI(cookies)
    return client.get_all_books_with_progress()

