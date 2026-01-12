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
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

import requests
from dateutil import parser as dtparser
import dateutil.tz


def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        if default is None:
            return ""
        return default
    return str(v).strip()


# WeRead API endpoints - matching obsidian-weread-plugin (https://github.com/zhaohongxuan/obsidian-weread-plugin)
WEREAD_API_BASE = "https://weread.qq.com"
WEREAD_NOTEBOOKS_API = f"{WEREAD_API_BASE}/api/user/notebook"  # Obsidian plugin uses this
WEREAD_SHELF_API = f"{WEREAD_API_BASE}/web/shelf/sync"
WEREAD_BOOK_INFO_API = f"{WEREAD_API_BASE}/web/book/bookDetail"
WEREAD_BOOK_INFO_API_V2 = f"{WEREAD_API_BASE}/web/book/info"  # Obsidian plugin: /web/book/info
WEREAD_READING_DATA_API = f"{WEREAD_API_BASE}/web/readingData"
WEREAD_BOOK_LIST_API = f"{WEREAD_API_BASE}/web/shelf/bookList"
# Alternative endpoints to try for reading data
WEREAD_READ_INFO_API = f"{WEREAD_API_BASE}/web/book/readinfo"  # Obsidian plugin: readinfo (lowercase)
WEREAD_BOOK_READING_API = f"{WEREAD_API_BASE}/web/book/reading"
WEREAD_USER_READING_API = f"{WEREAD_API_BASE}/web/user/reading"
# Additional endpoints for bookmarks, reviews, and chapters - matching obsidian plugin
WEREAD_BOOKMARKLIST_API = f"{WEREAD_API_BASE}/web/book/bookmarklist"  # Obsidian plugin uses weread.qq.com, not i.weread.qq.com
WEREAD_REVIEW_LIST_API = f"{WEREAD_API_BASE}/web/review/list"  # Obsidian plugin uses weread.qq.com, not i.weread.qq.com
WEREAD_NOTE_LIST_API = f"{WEREAD_API_BASE}/web/book/note"  # Try note endpoint for highlights without thoughts
WEREAD_CHAPTER_INFO_API = f"{WEREAD_API_BASE}/web/book/chapterInfos"  # Obsidian plugin uses weread.qq.com, not i.weread.qq.com
WEREAD_GET_PROGRESS_API = f"{WEREAD_API_BASE}/web/book/getProgress"  # Obsidian plugin: /web/book/getProgress


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
            
            # Validate cookies - based on obsidian-weread-plugin requirements
            # Required cookies for all API endpoints (HighlightResponse, BookReviewResponse, 
            # ChapterResponse, BookReadInfoResponse, BookDetailResponse, BookProgressResponse)
            required_cookies = ["wr_skey", "wr_vid", "wr_rt"]
            missing = [c for c in required_cookies if c not in cookie_dict]
            
            if missing:
                error_msg = f"\n{'='*80}\n"
                error_msg += f"❌ MISSING REQUIRED COOKIES\n"
                error_msg += f"{'='*80}\n"
                error_msg += f"Missing: {', '.join(missing)}\n"
                error_msg += f"\nThese cookies are REQUIRED for all WeRead API endpoints:\n"
                error_msg += f"  - wr_skey: Authentication key (MOST IMPORTANT)\n"
                error_msg += f"  - wr_vid: Session ID\n"
                error_msg += f"  - wr_rt: Refresh token\n"
                error_msg += f"\n🔧 SOLUTION:\n"
                error_msg += f"  1. Open https://weread.qq.com in your browser\n"
                error_msg += f"  2. Log in to your account\n"
                error_msg += f"  3. Press F12 → Application tab → Cookies → weread.qq.com\n"
                error_msg += f"  4. Copy ALL cookie values (especially wr_skey, wr_vid, wr_rt)\n"
                error_msg += f"  5. Update WEREAD_COOKIES in your .env file\n"
                error_msg += f"  6. Format: wr_skey=xxx; wr_vid=xxx; wr_rt=xxx\n"
                error_msg += f"\nSee scripts/get_weread_cookies.md for detailed instructions\n"
                error_msg += f"{'='*80}\n"
                print(error_msg)
                raise ValueError(f"Missing required cookies: {', '.join(missing)}. See error message above for details.")
            
            # Check for wr_skey specifically (most important)
            if "wr_skey" not in cookie_dict or not cookie_dict["wr_skey"]:
                raise ValueError("wr_skey cookie is required but missing or empty. This is the most important cookie for authentication.")
            
            # Optional but recommended cookies (used by obsidian-weread-plugin for validation)
            recommended_cookies = ["wr_name", "wr_localvid", "wr_gid", "wr_uid"]
            missing_recommended = [c for c in recommended_cookies if c not in cookie_dict]
            
            print(f"[API] ✅ All required cookies present: {', '.join(required_cookies)}")
            if missing_recommended:
                print(f"[API] ⚠️  Missing recommended cookies: {', '.join(missing_recommended)}")
                print(f"[API]    These may help with cookie validation and refresh")
            else:
                print(f"[API] ✅ All recommended cookies present")
            
            print(f"[API] Found wr_skey cookie (length: {len(cookie_dict['wr_skey'])})")
            print(f"[API] Loaded {len(cookie_dict)} total cookies: {', '.join(cookie_dict.keys())}")
            
            # Store cookie dict for validation
            self.cookie_dict = cookie_dict
    
    def validate_cookies(self) -> bool:
        """
        Validate cookies by making a test API call.
        Based on obsidian-weread-plugin validation method (see api.ts).
        Returns True if cookies are valid, False otherwise.
        """
        try:
            # First check if we have wr_name cookie (used by obsidian plugin for validation)
            has_wr_name = "wr_name" in self.cookie_dict and self.cookie_dict.get("wr_name")
            
            response = self.session.get(
                WEREAD_SHELF_API,
                params={"synckey": 0, "lectureSynckey": 0},
                timeout=10
            )
            
            # Check for 401 or auth errors
            if response.status_code == 401:
                self._check_auth_error(response, "Cookie Validation (Shelf API)")
                return False
            
            # Check response data for error codes (obsidian plugin checks for -2012: 登录超时)
            try:
                data = response.json()
                if "errCode" in data:
                    err_code = data.get("errCode")
                    err_msg = data.get("errMsg", "Unknown error")
                    
                    # Error code -2012 is "登录超时" (login timeout) - same as obsidian plugin
                    if err_code in [-2010, -2012, -1, 401, 403]:
                        print(f"\n{'='*80}")
                        print(f"❌ COOKIE VALIDATION FAILED")
                        print(f"{'='*80}")
                        print(f"Error Code: {err_code}")
                        print(f"Error Message: {err_msg}")
                        if err_code == -2012:
                            print(f"\n⚠️  This is error -2012 (登录超时 - Login Timeout)")
                            print(f"   Your cookies have expired. Get fresh cookies from browser.")
                        print(f"\n🔧 SOLUTION:")
                        print(f"   1. Open https://weread.qq.com in your browser")
                        print(f"   2. Make sure you're logged in")
                        print(f"   3. Get fresh cookies (see scripts/get_weread_cookies.md)")
                        print(f"   4. Update WEREAD_COOKIES in your .env file")
                        print(f"   5. Required cookies: wr_skey, wr_vid, wr_rt")
                        print(f"   6. Optional but recommended: wr_name, wr_localvid, wr_gid")
                        print(f"{'='*80}\n")
                        return False
            except:
                pass
            
            # Check for set-cookie header (obsidian plugin uses this to refresh cookies)
            set_cookie = response.headers.get('set-cookie') or response.headers.get('Set-Cookie')
            if set_cookie and not has_wr_name:
                print("[API] ⚠️  Received set-cookie header - cookies may need refresh")
            
            if response.status_code == 200:
                print("[API] ✅ Cookie validation successful")
                # Check if we have wr_name (used by obsidian plugin for validation)
                if has_wr_name:
                    print("[API] ✅ wr_name cookie present (good for cookie refresh validation)")
                return True
            else:
                print(f"[API] ⚠️  Cookie validation returned status {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"[API] ⚠️  Cookie validation failed: {e}")
            return False
    
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
            
            # Check for HTTP 401 first
            if response.status_code == 401:
                self._check_auth_error(response, "Shelf API")
                return {}, [], []
            
            response.raise_for_status()
            data = response.json()
            
            # Check for error response FIRST
            if "errCode" in data:
                err_code = data.get("errCode")
                err_msg = data.get("errMsg", "Unknown error")
                print(f"[API ERROR] Shelf API returned error: errCode={err_code}, errMsg={err_msg}")
                print(f"[DEBUG] Full error response:")
                print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
                
                # If it's an auth error, show detailed help
                if err_code in [-2010, -2012, -1, 401, 403]:
                    print(f"\n{'='*80}")
                    print(f"❌ AUTHENTICATION ERROR - Shelf API")
                    print(f"{'='*80}")
                    print(f"Error Code: {err_code}")
                    print(f"Error Message: {err_msg}")
                    print(f"\n🔧 SOLUTION:")
                    print(f"   1. Open https://weread.qq.com in your browser")
                    print(f"   2. Make sure you're logged in")
                    print(f"   3. Get fresh cookies (see scripts/get_weread_cookies.md)")
                    print(f"   4. Update WEREAD_COOKIES in your .env file")
                    print(f"   5. Required cookies: wr_skey, wr_vid, wr_rt")
                    print(f"   6. Optional but recommended: wr_localvid, wr_gid")
                    print(f"\n💡 TIP: Check your .env file - make sure all cookies are present and not truncated")
                    print(f"{'='*80}\n")
                
                return {}, [], []
            
            # Shelf API returns data directly, not wrapped in errcode/errmsg
            # The 'books' field contains ALL books with full info (title, author, etc.)
            all_books = []
            if "books" in data:
                all_books = data.get("books", [])
                print(f"[API] Found {len(all_books)} books in 'books' field")
            
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
    
    def get_notebooks(self) -> List[Dict[str, Any]]:
        """
        Get all notebooks (books with notes/highlights).
        Returns list of book data.
        Matches obsidian-weread-plugin implementation.
        """
        try:
            # Obsidian plugin uses: GET /api/user/notebook (no params)
            response = self.session.get(
                WEREAD_NOTEBOOKS_API
            )
            
            # Check for 401 status first (matching obsidian plugin)
            if response.status_code == 401:
                try:
                    data = response.json()
                    if data.get("errcode") == -2012:
                        # 登录超时 -2012
                        print("[API] Cookie expired (errcode -2012) - need fresh cookies")
                        return []
                    else:
                        print(f"[API ERROR] Notebooks 401 error: {data.get('errcode', 'Unknown')}")
                        return []
                except:
                    print("[API ERROR] Notebooks 401 error - unable to parse response")
                    return []
            
            response.raise_for_status()
            data = response.json()
            
            # Check for errcode == -2012 even if status is not 401 (matching obsidian plugin)
            if data.get("errcode") == -2012 or data.get("errCode") == -2012:
                print("[API] Cookie expired (errcode -2012) - need fresh cookies")
                return []
            
            # Check for set-cookie header (obsidian plugin uses this to refresh cookies)
            resp_cookie = response.headers.get('set-cookie') or response.headers.get('Set-Cookie')
            if resp_cookie:
                # Note: We don't update cookies automatically here, but we could
                pass
            
            # Try different response formats (obsidian plugin uses resp.json.books)
            if data.get("errcode") == 0 or data.get("errCode") == 0:
                books = data.get("books", [])
                if books:
                    return books
            
            # If no errcode or errcode is 0 but no books, check if data itself is a list
            if isinstance(data, list):
                return data
            
            # Check if there's a different structure
            if "books" in data:
                books = data.get("books", [])
                return books
            
            # If we get here, print the error but also return what we can
            errcode = data.get("errcode") or data.get("errCode")
            errmsg = data.get("errmsg") or data.get("errMsg")
            if errcode or errmsg:
                print(f"[API ERROR] Notebooks: {errmsg or 'Unknown error'} (errcode: {errcode})")
            else:
                print(f"[API WARNING] Notebooks: Unexpected response structure. Keys: {list(data.keys())}")
            return []
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                try:
                    data = e.response.json()
                    if data.get("errcode") == -2012:
                        print("[API] Cookie expired (errcode -2012) - need fresh cookies")
                    else:
                        print(f"[API ERROR] Notebooks 401: {data.get('errcode', 'Unknown')}")
                except:
                    print("[API ERROR] Notebooks 401 - unable to parse error response")
                return []
            if e.response.status_code == 404:
                print(f"[API WARNING] Notebooks endpoint not found (404). Trying shelf endpoint...")
                return []
            print(f"[API ERROR] Failed to fetch notebooks: {e}")
            return []
        except Exception as e:
            print(f"[API ERROR] Failed to fetch notebooks: {e}")
            return []
    
    def get_single_notebook_data(self, book_id: str) -> Optional[Dict[str, Any]]:
        """
        Get notebook data for a single book using syncNotebook approach.
        This is different from get_notebooks() - it fetches detailed notebook data for one book.
        Matches obsidian-weread-plugin syncNotebook pattern.
        """
        try:
            # Try different endpoints that might be used by syncNotebook
            endpoints_to_try = [
                (f"{WEREAD_API_BASE}/api/user/notebook/{book_id}", {}),
                (f"{WEREAD_API_BASE}/web/book/notebook", {"bookId": book_id}),
                (f"{WEREAD_API_BASE}/api/book/notebook", {"bookId": book_id}),
                (f"{WEREAD_API_BASE}/web/user/notebook", {"bookId": book_id}),
            ]
            
            for endpoint, params in endpoints_to_try:
                try:
                    response = self.session.get(endpoint, params=params if params else None)
                    
                    # Check for auth errors first
                    if self._check_auth_error(response, f"Single Notebook API ({endpoint})"):
                        continue
                    
                    if response.status_code == 404:
                        continue  # Try next endpoint
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Return the data structure
                    return data
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 404:
                        continue  # Try next endpoint
                    # For other errors, try next endpoint
                    continue
                except Exception as e:
                    # Try next endpoint
                    continue
            
            # If all endpoints failed, return None
            print(f"[API WARNING] Could not find single notebook endpoint for book {book_id}")
            return None
        except Exception as e:
            print(f"[API ERROR] Failed to fetch single notebook for book {book_id}: {e}")
            return None
    
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
                response = self.session.get(url, params=params)
                
                # Skip 404s silently (endpoint doesn't exist)
                if response.status_code == 404:
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                # Check for error response
                if "errCode" in data:
                    err_code = data.get("errCode")
                    if err_code != 0:
                        continue  # Try next endpoint
                
                if "errcode" in data:
                    err_code = data.get("errcode")
                    if err_code != 0:
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
                        return reading_data
                    else:
                        continue
                
                # If no nested data but errcode is 0, return the whole response if it looks useful
                if data.get("errcode") == 0 or data.get("errCode") == 0:
                    has_useful_data = any(key in data for key in [
                        "currentPage", "readPage", "totalPage", "pageCount",
                        "readPercentage", "progress", "currentChapter", "chapterIdx"
                    ])
                    if has_useful_data:
                        return data
                
                continue  # Try next endpoint
                
            except requests.exceptions.HTTPError as e:
                # Skip 404s (endpoint doesn't exist)
                if hasattr(e.response, 'status_code') and e.response.status_code == 404:
                    continue
                continue  # Try next endpoint
            except Exception as e:
                continue  # Try next endpoint
        
        # If all endpoints failed, return None
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
            pass
        
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
                        # Use local timezone for timestamp conversion
                        local_tz = dateutil.tz.tzlocal()
                        last_read_at = datetime.fromtimestamp(book_item["updateTime"], tz=local_tz)
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
            reading_data = self.get_reading_data(book_id)
            
            # Get detailed read info (includes pages, reading time, etc.)
            read_info = self.get_read_info(book_id)
            
            # Get bookmarks/highlights
            bookmark_list = self.get_bookmark_list(book_id)
            
            # Try to get notes (highlights without thoughts) separately
            note_list = self.get_note_list(book_id)
            
            # Get all types of notes and reviews
            summary_reviews, regular_reviews, page_notes, chapter_notes = self.get_review_list(book_id)
            
            # Get chapter info
            chapter_info = self.get_chapter_info(book_id)
            
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
            
            # Try to get page data from read_info API (more reliable for pages)
            if read_info:
                current_page, total_page, percent = self._extract_page_info(read_info, current_page, total_page, percent)
            
            # Try to get page data from reading_data API (fallback)
            if reading_data and (not current_page or not total_page):
                current_page, total_page, percent = self._extract_page_info(reading_data, current_page, total_page, percent)
            
            # Calculate current page from percent if we have total but not current
            if percent is not None and total_page and not current_page:
                current_page = int(round((percent / 100.0) * total_page))
            
            # If we have current_page but not total_page, try to estimate from percent
            if current_page and percent is not None and percent > 0 and not total_page:
                total_page = int(round((current_page / (percent / 100.0))))
            
            
            # Check for finishReading flag - ONLY this flag determines if book is read
            is_finished = False
            if book_info and book_info.get("finishReading") == 1:
                is_finished = True
            elif book_item and book_item.get("finishReading") == 1:
                is_finished = True
            elif book_item and "book" in book_item and book_item["book"].get("finishReading") == 1:
                is_finished = True
            elif reading_data and reading_data.get("finishReading") == 1:
                is_finished = True
            
            # Determine status - ONLY finishReading=1 means "Read"
            # Progress < 5% is considered "To Be Read"
            if is_finished:
                status = "Read"
            elif percent is not None and percent >= 5:
                status = "Currently Reading"
            elif current_page and total_page and (current_page / total_page * 100) >= 5:
                status = "Currently Reading"
            else:
                status = "To Be Read"
            
            # Extract dates from read_info API response
            # Date Started: read_info.readDetail.beginReadingDate
            # Date Finished: read_info.finishedDate
            # Last Read At: read_info.readDetail.lastReadingDate
            started_at = None
            last_read_at = None
            date_finished = None
            
            # Priority 1: Extract dates from read_info.readDetail and read_info.finishedDate
            if read_info:
                read_detail = read_info.get("readDetail")
                if read_detail:
                    if read_detail.get("beginReadingDate"):
                        started_at = self._parse_date_field(read_detail.get("beginReadingDate"))
                    if read_detail.get("lastReadingDate"):
                        last_read_at = self._parse_date_field(read_detail.get("lastReadingDate"))
                if read_info.get("finishedDate"):
                    date_finished = self._parse_date_field(read_info.get("finishedDate"))
            
            # Fallback: Use old logic if dates not found in read_info
            if not started_at or not last_read_at:
                start_times = []
                if reading_data:
                    if not started_at and reading_data.get("startTime"):
                        parsed_start = self._parse_date_field(reading_data.get("startTime"))
                        if parsed_start:
                            start_times.append(parsed_start)
                            started_at = parsed_start
                    if not last_read_at and (reading_data.get("lastReadTime") or reading_data.get("updateTime")):
                        last_read_raw = reading_data.get("lastReadTime") or reading_data.get("updateTime")
                        parsed_last = self._parse_date_field(last_read_raw)
                        if parsed_last:
                            last_read_at = parsed_last
                if book_item and book_item.get("updateTime"):
                    parsed_update = self._parse_date_field(book_item.get("updateTime"))
                    if parsed_update:
                        if not last_read_at:
                            last_read_at = parsed_update
                        if not started_at:
                            start_times.append(parsed_update)
                if not started_at and start_times:
                    started_at = min(start_times)
            
            # If date_finished not found but book is finished, use last_read_at as fallback
            if not date_finished and status == "Read" and last_read_at:
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
            
            # Get year started reading
            year_started = started_at.year if started_at else None
            
            
            # Format reading time from read_info
            reading_time_formatted = None
            if read_info and read_info.get("readingTime"):
                reading_time_seconds = read_info.get("readingTime", 0)
                hours = reading_time_seconds // 3600
                minutes = (reading_time_seconds % 3600) // 60
                if hours > 0:
                    reading_time_formatted = f"{hours}时{minutes}分" if minutes > 0 else f"{hours}时"
                elif minutes > 0:
                    reading_time_formatted = f"{minutes}分"
            
            # Combine bookmarks, notes, and reviews
            all_bookmarks = []
            if bookmark_list:
                all_bookmarks.extend(bookmark_list)
            if note_list:
                # Add notes (highlights without thoughts) to bookmarks
                all_bookmarks.extend(note_list)
            if regular_reviews:
                all_bookmarks.extend(regular_reviews)
            
            # Sort all bookmarks by chapter and position
            if all_bookmarks:
                all_bookmarks = sorted(
                    all_bookmarks,
                    key=lambda x: (
                        x.get("chapterUid", 1),
                        0 if (not x.get("range") or x.get("range", "").split("-")[0] == "") 
                        else int(x.get("range", "0-0").split("-")[0]),
                    ),
                )
            
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
                # New fields for bookmarks, reviews, quotes, and callouts
                "bookmarks": all_bookmarks,  # Combined bookmarks, notes, and regular reviews (划线笔记)
                "notes": note_list or [],  # Highlights without thoughts (纯划线，无想法)
                "summary_reviews": summary_reviews,  # Summary/commentary reviews (书籍书评)
                "page_notes": page_notes,  # Page notes (页面笔记)
                "chapter_notes": chapter_notes,  # Chapter notes (章节笔记)
                "chapter_info": chapter_info,  # Chapter structure
                "read_info": read_info,  # Full reading info including readingTime
                "reading_time": reading_time_formatted,  # Formatted reading time
            }
        except Exception as e:
            print(f"[ERROR] Failed to get data for book {book_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def _parse_date_field(date_value: Any) -> Optional[datetime]:
        """Parse date field from API response - handles timestamps and strings"""
        if date_value is None:
            return None
        try:
            local_tz = dateutil.tz.tzlocal()
            if isinstance(date_value, (int, float)):
                # Handle Unix timestamp (seconds or milliseconds)
                if date_value > 1e10:  # Milliseconds timestamp
                    return datetime.fromtimestamp(date_value / 1000, tz=local_tz)
                else:  # Seconds timestamp
                    return datetime.fromtimestamp(date_value, tz=local_tz)
            else:
                # Try parsing as string
                parsed = dtparser.parse(str(date_value))
                # Ensure local timezone if naive
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=local_tz)
                return parsed
        except Exception:
            return None
    
    @staticmethod
    def _extract_page_info(data: Dict[str, Any], current_page: Optional[int] = None, 
                           total_page: Optional[int] = None, percent: Optional[float] = None) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        """Extract page information from API response data"""
        if not current_page:
            current_page = (data.get("currentPage") or data.get("readPage") or 
                          data.get("readPageNum") or data.get("page"))
        if not total_page:
            total_page = (data.get("totalPage") or data.get("pageCount") or
                         data.get("totalPages") or data.get("maxPage") or data.get("pageNum"))
        if not percent or percent == 0:
            percent = (data.get("readPercentage") or data.get("progress") or
                      data.get("readPercent") or data.get("readingProgress"))
        return current_page, total_page, percent
    
    def _check_auth_error(self, response, api_name: str) -> bool:
        """Check if response indicates authentication error (expired cookies)"""
        try:
            status_code = getattr(response, 'status_code', None)
            if status_code == 401:
                error_text = getattr(response, 'text', '').lower()
                if "login" in error_text or status_code == 401:
                    print(f"\n{'='*80}")
                    print(f"❌ COOKIE EXPIRATION DETECTED - {api_name}")
                    print(f"{'='*80}")
                    print(f"Status Code: {status_code}")
                    error_msg = getattr(response, 'text', 'No error message')[:200]
                    print(f"Error: {error_msg}")
                    print(f"\n🔧 SOLUTION:")
                    print(f"   1. Open https://weread.qq.com in your browser")
                    print(f"   2. Make sure you're logged in")
                    print(f"   3. Get fresh cookies (see scripts/get_weread_cookies.md)")
                    print(f"   4. Update WEREAD_COOKIES in your .env file")
                    print(f"   5. Required cookies: wr_skey, wr_vid, wr_rt")
                    print(f"   6. Optional but recommended: wr_localvid, wr_gid")
                    print(f"\n💡 DEBUGGING:")
                    print(f"   - Check if cookies in .env are complete (not truncated)")
                    print(f"   - Make sure there are no extra quotes or spaces")
                    print(f"   - Format: wr_skey=xxx; wr_vid=xxx; wr_rt=xxx")
                    print(f"{'='*80}\n")
                    return True
        except Exception as e:
            pass
        return False
    
    def get_bookmark_list(self, book_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get bookmarks/highlights for a book"""
        try:
            response = self.session.get(
                WEREAD_BOOKMARKLIST_API,
                params={"bookId": book_id}
            )
            
            # Check for auth errors first
            if self._check_auth_error(response, "Bookmark List API"):
                return None
            
            response.raise_for_status()
            data = response.json()
            
            if "updated" in data:
                # Sort by chapterUid and position
                updated = data.get("updated", [])
                updated = sorted(
                    updated,
                    key=lambda x: (x.get("chapterUid", 1), int(x.get("range", "0-0").split("-")[0]) if x.get("range") else 0),
                )
                return updated
            return None
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 401:
                # Already handled by _check_auth_error
                return None
            print(f"[API ERROR] Failed to fetch bookmarks for book {book_id}: {e}")
            return None
        except Exception as e:
            print(f"[API ERROR] Failed to fetch bookmarks for book {book_id}: {e}")
            return None
    
    def get_note_list(self, book_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get notes (highlights without thoughts) for a book.
        This might be separate from reviews - trying /web/book/note endpoint.
        """
        try:
            # Try different possible endpoints for notes
            endpoints_to_try = [
                (f"{WEREAD_API_BASE}/web/book/note", {"bookId": book_id}),
                (f"{WEREAD_API_BASE}/web/book/notes", {"bookId": book_id}),
                (f"{WEREAD_API_BASE}/api/book/note", {"bookId": book_id}),
            ]
            
            for endpoint, params in endpoints_to_try:
                try:
                    response = self.session.get(endpoint, params=params)
                    
                    # Check for auth errors first
                    if self._check_auth_error(response, f"Note List API ({endpoint})"):
                        continue
                    
                    if response.status_code == 404:
                        continue  # Try next endpoint
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Try different response formats
                    if isinstance(data, list):
                        return data
                    if "notes" in data:
                        return data.get("notes", [])
                    if "data" in data and isinstance(data.get("data"), list):
                        return data.get("data", [])
                    if "bookmarks" in data:
                        return data.get("bookmarks", [])
                    
                    # If we got here, return the data structure as-is
                    return data if isinstance(data, list) else []
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 404:
                        continue  # Try next endpoint
                    # For other errors, try next endpoint
                    continue
                except Exception as e:
                    # Try next endpoint
                    continue
            
            # If all endpoints failed, return None
            print(f"[API WARNING] Could not find note endpoint for book {book_id}")
            return None
        except Exception as e:
            print(f"[API ERROR] Failed to fetch notes for book {book_id}: {e}")
            return None
    
    def get_review_list(self, book_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Get all types of notes and reviews for a book.
        Returns (summary_reviews, regular_reviews, page_notes, chapter_notes)
        
        Note types in WeRead API:
        - Type 1: 划线笔记 (underline/highlight notes) - regular reviews
        - Type 2: 页面笔记 (page notes) - notes on specific pages
        - Type 3: 章节笔记 (chapter notes) - notes on chapters
        - Type 4: 书籍书评 (book reviews) - summary/commentary reviews
        """
        try:
            # Obsidian plugin uses: /web/review/list?bookId=${bookId}&listType=11&mine=1&synckey=0
            # Note: synckey (lowercase 'k') not syncKey
            response = self.session.get(
                WEREAD_REVIEW_LIST_API,
                params={"bookId": book_id, "listType": 11, "mine": 1, "synckey": 0}
            )
            
            # Check for auth errors first
            if self._check_auth_error(response, "Review List API"):
                return [], [], [], []
            
            response.raise_for_status()
            data = response.json()
            
            reviews = data.get("reviews", [])
            
            # Categorize by type
            summary_reviews = []  # Type 4: 书籍书评 (book reviews)
            regular_reviews = []  # Type 1: 划线笔记 (underline/highlight notes)
            page_notes = []       # Type 2: 页面笔记 (page notes)
            chapter_notes = []    # Type 3: 章节笔记 (chapter notes)
            
            for review_item in reviews:
                review = review_item.get("review", {})
                review_type = review.get("type")
                
                if review_type == 4:
                    # 书籍书评 (book reviews)
                    summary_reviews.append(review_item)
                elif review_type == 1:
                    # 划线笔记 (underline/highlight notes)
                    # Transform to match bookmark format
                    transformed = {**review, "markText": review.pop("content", "")}
                    regular_reviews.append(transformed)
                elif review_type == 2:
                    # 页面笔记 (page notes)
                    page_notes.append(review)
                elif review_type == 3:
                    # 章节笔记 (chapter notes)
                    chapter_notes.append(review)
                # Unknown type - skip it
            
            return summary_reviews, regular_reviews, page_notes, chapter_notes
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 401:
                # Already handled by _check_auth_error
                return [], [], [], []
            print(f"[API ERROR] Failed to fetch reviews for book {book_id}: {e}")
            return [], [], [], []
        except Exception as e:
            print(f"[API ERROR] Failed to fetch reviews for book {book_id}: {e}")
            return [], [], [], []
    
    def get_chapter_info(self, book_id: str) -> Optional[Dict[int, Dict[str, Any]]]:
        """Get chapter information for a book"""
        try:
            # Obsidian plugin uses: POST /web/book/chapterInfos with body {bookIds: [bookId]}
            # We'll try the simpler version first, then fallback to extended version if needed
            body = {"bookIds": [book_id]}
            response = self.session.post(WEREAD_CHAPTER_INFO_API, json=body)
            
            # Check for auth errors first
            if self._check_auth_error(response, "Chapter Info API"):
                return None
            
            response.raise_for_status()
            data = response.json()
            
            if (
                data
                and "data" in data
                and len(data["data"]) == 1
                and "updated" in data["data"][0]
            ):
                update = data["data"][0]["updated"]
                return {item["chapterUid"]: item for item in update}
            return None
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 401:
                # Already handled by _check_auth_error
                return None
            print(f"[API ERROR] Failed to fetch chapter info for book {book_id}: {e}")
            return None
        except Exception as e:
            print(f"[API ERROR] Failed to fetch chapter info for book {book_id}: {e}")
            return None
    
    def get_read_info(self, book_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed reading information including progress, pages, and reading time"""
        try:
            response = self.session.get(
                WEREAD_READ_INFO_API,
                params={"bookId": book_id, "readingDetail": 1, "readingBookIndex": 1, "finishedDate": 1}
            )
            response.raise_for_status()
            data = response.json()
            
            if data:
                return data
            return None
        except Exception as e:
            print(f"[API ERROR] Failed to fetch read info for book {book_id}: {e}")
            return None


def fetch_from_api(cookies: str) -> List[Dict[str, Any]]:
    """Convenience function to fetch all books from WeRead API"""
    client = WeReadAPI(cookies)
    return client.get_all_books_with_progress()
