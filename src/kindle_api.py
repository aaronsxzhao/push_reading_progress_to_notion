#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kindle API client
Fetches reading data from Kindle Cloud Reader or parses My Clippings.txt

Authentication: Uses cookie-based auth (get cookies from browser after logging into read.amazon.com)
"""

import os
import json
import math
import time
import urllib.parse
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

import requests
from dateutil import parser as dtparser
import dateutil.tz

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        if default is None:
            return ""
        return default
    return str(v).strip()


# Kindle API endpoints - based on kindle-api project (https://github.com/Xetera/kindle-api)
KINDLE_API_BASE = "https://read.amazon.com"
KINDLE_SERVICE_BASE = f"{KINDLE_API_BASE}/service/web"
KINDLE_LIBRARY_API = f"{KINDLE_API_BASE}/kindle-library/search"
KINDLE_BOOKS_API = f"{KINDLE_API_BASE}/kindle-library/search"  # Get all books
KINDLE_NOTES_API = f"{KINDLE_API_BASE}/kindle-library/notebook"  # Get notes/highlights
# Service endpoints (from kindle-api project)
KINDLE_BOOK_DETAIL_API = f"{KINDLE_SERVICE_BASE}/bookDetails"  # Get book details with reading data
KINDLE_READING_PROGRESS_API = f"{KINDLE_SERVICE_BASE}/readingProgress"  # Get reading progress
KINDLE_DEVICE_TOKEN_API = f"{KINDLE_SERVICE_BASE}/register/getDeviceToken"  # Get device token


class KindleAPI:
    """Direct API client for Kindle Cloud Reader"""
    
    def __init__(self, cookies: str = None, clippings_file: str = None, device_token: str = None):
        """
        Initialize with Kindle cookies or clippings file path.
        
        Args:
            cookies: Cookie string from browser (for Kindle Cloud Reader API)
            clippings_file: Path to My Clippings.txt file (alternative data source)
            device_token: Device token from getDeviceToken request (optional, for detailed reading data)
        
        To get cookies (based on kindle-api project):
        1. Open read.amazon.com in browser and log in
        2. Press F12 → Application tab → Cookies → read.amazon.com
        3. Copy cookie values: ubid-main, at-main, x-main, session-id
        4. OR use scripts/fetch_kindle_cookies_auto.py for automatic fetching
        
        To get device token:
        1. Open read.amazon.com in browser
        2. Press F12 → Network tab
        3. Look for request: getDeviceToken?serialNumber=...&deviceType=...
        4. Copy the serialNumber/deviceType value (they should be the same)
        """
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://read.amazon.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        
        self.clippings_file = clippings_file
        self.use_clippings = clippings_file and Path(clippings_file).exists()
        self.device_token = device_token
        
        # Parse cookies if provided
        if cookies:
            cookie_dict = {}
            cookies = cookies.strip()
            if cookies.startswith('"') and cookies.endswith('"'):
                cookies = cookies[1:-1]
            if cookies.startswith("'") and cookies.endswith("'"):
                cookies = cookies[1:-1]
            
            for item in cookies.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if '%' in value:
                        try:
                            value = urllib.parse.unquote(value)
                        except:
                            pass
                    cookie_dict[key] = value
            
            self.session.cookies.update(cookie_dict)
            
            # Validate required cookies
            required_cookies = ["session-id", "ubid-main"]
            missing = [c for c in required_cookies if c not in cookie_dict]
            
            if missing:
                print(f"[KINDLE API] ⚠️  Missing recommended cookies: {', '.join(missing)}")
                print(f"[KINDLE API]    Some features may not work without these cookies")
            else:
                print(f"[KINDLE API] ✅ Required cookies present")
            
            print(f"[KINDLE API] Loaded {len(cookie_dict)} cookies")
    
    def validate_cookies(self) -> bool:
        """Validate Kindle cookies by making a test API call"""
        if self.use_clippings:
            return True  # Clippings file doesn't need validation
        
        try:
            # Try to fetch library to validate cookies
            response = self.session.get(f"{KINDLE_API_BASE}/kindle-library")
            if response.status_code == 200:
                return True
            return False
        except Exception as e:
            if os.environ.get("WEREAD_DEBUG") == "1":
                print(f"[KINDLE API] Cookie validation error: {e}")
            return False
    
    def get_shelf(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Get all books from Kindle library
        Returns: (shelf_data, all_books_list, book_progress_list)
        """
        if self.use_clippings:
            return self._get_shelf_from_clippings()
        
        try:
            # Try multiple possible endpoints
            endpoints_to_try = [
                (f"{KINDLE_API_BASE}/kindle-library/search", {"query": "", "limit": 1000}),
                (f"{KINDLE_API_BASE}/kindle-library", {}),
                (f"{KINDLE_API_BASE}/kindle-library/books", {}),
                (f"{KINDLE_API_BASE}/api/kindle-library", {}),
            ]
            
            data = None
            response = None
            
            for endpoint_url, params in endpoints_to_try:
                try:
                    if os.environ.get("WEREAD_DEBUG") == "1":
                        print(f"[KINDLE API DEBUG] Trying endpoint: {endpoint_url}")
                    response = self.session.get(endpoint_url, params=params)
                    
                    if os.environ.get("WEREAD_DEBUG") == "1":
                        print(f"[KINDLE API DEBUG] Status code: {response.status_code}")
                    
                    if self._check_auth_error(response, "Kindle Library API"):
                        continue  # Try next endpoint
                    
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            if os.environ.get("WEREAD_DEBUG") == "1":
                                print(f"[KINDLE API DEBUG] Response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                                print(f"[KINDLE API DEBUG] Response preview: {str(data)[:500]}")
                            
                            # Check if we got books - Kindle API uses itemsList
                            books = (data.get("itemsList", []) or 
                                    data.get("items", []) or 
                                    data.get("books", []) or 
                                    data.get("library", []) or 
                                    [])
                            if books:
                                if os.environ.get("WEREAD_DEBUG") == "1":
                                    print(f"[KINDLE API] ✅ Found {len(books)} books using endpoint: {endpoint_url}")
                                break  # Found books, stop trying other endpoints
                            elif os.environ.get("WEREAD_DEBUG") == "1":
                                print(f"[KINDLE API DEBUG] No books found in response, trying next endpoint...")
                        except Exception as e:
                            if os.environ.get("WEREAD_DEBUG") == "1":
                                print(f"[KINDLE API DEBUG] Failed to parse JSON: {e}")
                                print(f"[KINDLE API DEBUG] Response text (first 500 chars): {response.text[:500]}")
                            continue
                    elif os.environ.get("WEREAD_DEBUG") == "1":
                        print(f"[KINDLE API DEBUG] Status {response.status_code}, trying next endpoint...")
                except Exception as e:
                    if os.environ.get("WEREAD_DEBUG") == "1":
                        print(f"[KINDLE API DEBUG] Error with endpoint {endpoint_url}: {e}")
                    continue
            
            if not data:
                print(f"[KINDLE API ERROR] All endpoints failed. Last response: {response.status_code if response else 'No response'}")
                if response:
                    print(f"[KINDLE API DEBUG] Last response text: {response.text[:1000]}")
                return {}, [], []
            
            # Only raise_for_status if we didn't successfully get data
            if response and response.status_code != 200:
                response.raise_for_status()
            
            # Parse Kindle API response structure - try multiple possible formats
            books = []
            if isinstance(data, dict):
                books = (data.get("itemsList", []) or  # Kindle API uses itemsList
                        data.get("items", []) or 
                        data.get("books", []) or 
                        data.get("library", []) or 
                        data.get("data", {}).get("itemsList", []) or
                        data.get("data", {}).get("items", []) or
                        data.get("data", {}).get("books", []) or
                        [])
            elif isinstance(data, list):
                books = data
            
            print(f"[KINDLE API] Found {len(books)} books in library")
            
            # Debug: print first book structure if available
            if books and os.environ.get("WEREAD_DEBUG") == "1":
                print(f"[KINDLE API DEBUG] First book structure: {json.dumps(books[0], indent=2, default=str)[:1000]}")
            
            # Convert to similar structure as WeRead
            all_books_list = []
            book_progress_list = []
            
            for book in books:
                # Try multiple possible ID fields - Kindle uses "asin"
                book_id = (book.get("asin") or 
                          book.get("id") or 
                          book.get("bookId") or
                          str(book.get("asin", "")) or
                          str(book.get("id", "")))
                
                if not book_id:
                    if os.environ.get("WEREAD_DEBUG") == "1":
                        print(f"[KINDLE API DEBUG] Book missing ID, keys: {list(book.keys()) if isinstance(book, dict) else 'Not a dict'}")
                    continue
                
                # Extract book info - Kindle API structure
                # Authors is a list of strings like ['Chou, Yu-kai:']
                authors = book.get("authors", [])
                author = ""
                if isinstance(authors, list) and len(authors) > 0:
                    author = authors[0].rstrip(":")  # Remove trailing colon
                elif isinstance(authors, str):
                    author = authors
                
                book_info = {
                    "bookId": book_id,
                    "asin": book_id,  # Keep ASIN for reference
                    "title": book.get("title") or book.get("bookTitle") or "",
                    "author": author or book.get("author") or "",
                    "cover": book.get("productUrl") or book.get("coverUrl") or book.get("cover") or "",
                    "publisher": book.get("publisher") or "",
                    "publicationDate": book.get("publicationDate") or "",
                    "resourceType": book.get("resourceType", ""),  # EBOOK, etc.
                    "originType": book.get("originType", ""),  # PURCHASE, etc.
                }
                
                # Extract progress - Kindle uses percentageRead (0-100)
                # Also check for syncDate (from kindle-api project's book.details())
                percentage_read = book.get("percentageRead", 0) or 0
                sync_date = book.get("syncDate") or book.get("lastSyncDate")
                
                progress_data = {
                    "bookId": book_id,
                    "progress": float(percentage_read),  # Convert to float for percentage
                    "currentLocation": book.get("currentLocation") or book.get("lastPageRead") or book.get("lastLocation"),
                    "lastReadDate": book.get("lastReadDate") or book.get("lastAccessDate") or sync_date,
                    "readingTime": book.get("readingTimeMinutes", 0) * 60 if book.get("readingTimeMinutes") else 0,
                    "syncDate": sync_date,  # Track when data was last synced
                    "totalLocations": book.get("totalLocations") or book.get("locations"),
                }
                
                all_books_list.append({"book": book_info})
                if progress_data.get("progress", 0) > 0:
                    book_progress_list.append(progress_data)
            
            shelf_data = {
                "bookCount": len(books),
                "pureBookCount": len(books),
            }
            
            return shelf_data, all_books_list, book_progress_list
            
        except Exception as e:
            print(f"[KINDLE API ERROR] Failed to fetch shelf: {e}")
            if os.environ.get("WEREAD_DEBUG") == "1":
                import traceback
                traceback.print_exc()
            return {}, [], []
    
    def _get_shelf_from_clippings(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Parse My Clippings.txt file to get books"""
        try:
            clippings_path = Path(self.clippings_file)
            if not clippings_path.exists():
                print(f"[KINDLE API ERROR] Clippings file not found: {self.clippings_file}")
                return {}, [], []
            
            books_data = self._parse_clippings_file(clippings_path)
            
            all_books_list = []
            book_progress_list = []
            
            for book_id, book_data in books_data.items():
                all_books_list.append({"book": book_data["info"]})
                if book_data.get("progress", 0) > 0:
                    book_progress_list.append({
                        "bookId": book_id,
                        "progress": book_data.get("progress", 0),
                    })
            
            shelf_data = {
                "bookCount": len(books_data),
                "pureBookCount": len(books_data),
            }
            
            return shelf_data, all_books_list, book_progress_list
            
        except Exception as e:
            print(f"[KINDLE API ERROR] Failed to parse clippings file: {e}")
            return {}, [], []
    
    def _parse_clippings_file(self, file_path: Path) -> Dict[str, Dict[str, Any]]:
        """Parse My Clippings.txt file format"""
        books = {}
        
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            
            # Pattern: Title (Author)
            # - Your Highlight on page X | Location Y | Added on Date
            # Highlight text...
            
            current_book = None
            current_book_id = None
            lines = content.split('\n')
            i = 0
            
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue
                
                # Check if this is a book title line (contains parentheses with author)
                if '(' in line and ')' in line:
                    # Extract title and author
                    match = re.match(r'^(.+?)\s*\((.+?)\)', line)
                    if match:
                        title = match.group(1).strip()
                        author = match.group(2).strip()
                        book_id = f"kindle_{hash(title + author) % 1000000000}"  # Generate ID
                        
                        if book_id not in books:
                            books[book_id] = {
                                "info": {
                                    "bookId": book_id,
                                    "title": title,
                                    "author": author,
                                },
                                "bookmarks": [],
                                "progress": 0,
                            }
                        
                        current_book_id = book_id
                        current_book = books[book_id]
                        i += 1
                        continue
                
                # Check if this is a metadata line (page/location/date)
                if '|' in line and ('page' in line.lower() or 'location' in line.lower()):
                    # Skip metadata line, next line should be the highlight
                    i += 1
                    if i < len(lines):
                        highlight_text = lines[i].strip()
                        if highlight_text and current_book:
                            current_book["bookmarks"].append({
                                "text": highlight_text,
                                "chapterUid": 1,
                                "range": "",
                            })
                    i += 1
                    continue
                
                i += 1
            
            # Calculate progress based on highlights (rough estimate)
            for book_id, book_data in books.items():
                if book_data["bookmarks"]:
                    # Estimate progress: if has highlights, assume some progress
                    book_data["progress"] = min(50, len(book_data["bookmarks"]) * 5)  # Rough estimate
            
            return books
            
        except Exception as e:
            print(f"[KINDLE API ERROR] Failed to parse clippings: {e}")
            return {}
    
    def _check_auth_error(self, response: requests.Response, api_name: str) -> bool:
        """Check if response indicates authentication error"""
        if response.status_code in [401, 403]:
            print(f"\n{'='*80}")
            print(f"❌ AUTHENTICATION ERROR - {api_name}")
            print(f"{'='*80}")
            print(f"Status Code: {response.status_code}")
            print(f"\n🔧 SOLUTION:")
            print(f"   1. Open https://read.amazon.com in your browser")
            print(f"   2. Make sure you're logged in")
            print(f"   3. Get fresh cookies (see scripts/get_kindle_cookies.md)")
            print(f"   4. Update KINDLE_COOKIES in your .env file")
            print(f"   5. Required cookies: session-id, ubid-main")
            print(f"{'='*80}\n")
            return True
        return False
    
    def get_single_book_data(self, book_id: str, book_item: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Get data for a single book - same structure as WeRead API
        """
        try:
            # Extract book info from book_item
            book_info = None
            progress = 0
            
            if book_item:
                if "book" in book_item:
                    book_info = book_item["book"]
                    progress = book_item.get("progress", 0)
                elif "bookInfo" in book_item:
                    book_info = book_item["bookInfo"]
                    progress = book_item.get("progress", 0)
                elif "title" in book_item or "name" in book_item:
                    book_info = book_item
                    progress = book_item.get("progress", 0)
                else:
                    progress = book_item.get("progress", 0)
            
            if not book_info:
                book_info = {"bookId": book_id}
            
            # Get bookmarks/highlights
            bookmarks = []
            if self.use_clippings:
                # Get from parsed clippings data
                clippings_data = self._parse_clippings_file(Path(self.clippings_file))
                if book_id in clippings_data:
                    bookmarks = clippings_data[book_id].get("bookmarks", [])
            else:
                # Get from Kindle API
                bookmarks = self.get_bookmarks(book_id)
            
            # Get detailed reading data
            reading_data = None
            if not self.use_clippings:
                reading_data = self.get_reading_data(book_id)
            
            # Get reading progress - prioritize reading_data, then book_item
            reading_progress = progress
            if reading_data:
                # Try to get progress from reading_data
                reading_progress = (reading_data.get("percentageRead") or 
                                   reading_data.get("progress") or 
                                   reading_data.get("percentComplete") or
                                   reading_progress)
            if book_item and book_item.get("progress"):
                reading_progress = book_item.get("progress")
            
            # Calculate pages (Kindle uses locations, estimate pages)
            total_page = None
            current_page = None
            total_locations = None
            current_location = None
            
            # Try to get location/page info from reading_data first
            if reading_data:
                total_locations = reading_data.get("totalLocations") or reading_data.get("locations")
                current_location = reading_data.get("currentLocation") or reading_data.get("lastLocation")
                if not total_locations:
                    total_locations = book_info.get("totalLocations")
                if not current_location:
                    current_location = book_info.get("currentLocation")
            
            # Fallback to book_info
            if not total_locations:
                total_locations = book_info.get("totalLocations")
            if not current_location:
                current_location = book_info.get("currentLocation")
            
            # Convert locations to pages (rough estimate: 1 location ≈ 0.1 pages, or ~550 words per page)
            if total_locations:
                # Rough estimate: 1 location ≈ 0.1 pages
                total_page = int(total_locations / 10)
            elif book_info.get("pageCount"):
                total_page = book_info.get("pageCount")
            
            # Calculate current page from location or progress
            if current_location and total_locations:
                # Calculate page based on location ratio
                location_ratio = current_location / total_locations if total_locations > 0 else 0
                current_page = int(location_ratio * total_page) if total_page else None
            elif total_page and reading_progress:
                # Calculate page from progress percentage
                current_page = int((reading_progress / 100.0) * total_page)
            
            # Determine status
            is_finished = book_info.get("finished") or book_info.get("completed") or reading_progress >= 100
            if is_finished:
                status = "Read"
            elif reading_progress and reading_progress >= 5:
                status = "Currently Reading"
            else:
                status = "To Be Read"
            
            # Extract dates - prioritize reading_data, then book_item
            started_at = None
            last_read_at = None
            date_finished = None
            
            # Try reading_data first (most detailed)
            if reading_data:
                if reading_data.get("firstReadDate"):
                    started_at = self._parse_date_field(reading_data.get("firstReadDate"))
                elif reading_data.get("startedDate"):
                    started_at = self._parse_date_field(reading_data.get("startedDate"))
                elif reading_data.get("beginReadingDate"):
                    started_at = self._parse_date_field(reading_data.get("beginReadingDate"))
                
                if reading_data.get("lastReadDate"):
                    last_read_at = self._parse_date_field(reading_data.get("lastReadDate"))
                elif reading_data.get("lastAccessDate"):
                    last_read_at = self._parse_date_field(reading_data.get("lastAccessDate"))
                elif reading_data.get("lastReadingDate"):
                    last_read_at = self._parse_date_field(reading_data.get("lastReadingDate"))
                
                if reading_data.get("finishedDate"):
                    date_finished = self._parse_date_field(reading_data.get("finishedDate"))
                elif reading_data.get("completedDate"):
                    date_finished = self._parse_date_field(reading_data.get("completedDate"))
            
            # Fallback to book_item
            if book_item:
                if not last_read_at and book_item.get("lastReadDate"):
                    last_read_at = self._parse_date_field(book_item.get("lastReadDate"))
                if not started_at and book_item.get("firstReadDate"):
                    started_at = self._parse_date_field(book_item.get("firstReadDate"))
                if not date_finished and book_item.get("finishedDate"):
                    date_finished = self._parse_date_field(book_item.get("finishedDate"))
            
            # For "To Be Read" books: if no started_at but we have last_read_at, use last_read_at
            if status == "To Be Read" and not started_at and last_read_at:
                started_at = last_read_at
            
            # Get title and author
            title = book_info.get("title") or book_info.get("name") or f"Book {book_id}"
            author = book_info.get("author") or book_info.get("authorName") or ""
            
            return {
                "title": title,
                "author": author,
                "current_page": int(current_page) if current_page else None,
                "total_page": int(total_page) if total_page else None,
                "percent": float(reading_progress) if reading_progress is not None else None,
                "status": status,
                "started_at": started_at,
                "last_read_at": last_read_at,
                "date_finished": date_finished,
                "source": "Kindle",
                "cover_image": book_info.get("cover") or book_info.get("coverUrl"),
                "genre": book_info.get("genre") or book_info.get("category"),
                "year_started": started_at.year if started_at else None,
                "rating": book_info.get("rating"),
                "bookmarks": bookmarks,
                "notes": [],  # Kindle doesn't separate notes from highlights
                "summary_reviews": [],
                "page_notes": [],
                "chapter_notes": [],
                "chapter_info": {},
            }
            
        except Exception as e:
            print(f"[KINDLE API ERROR] Failed to get data for book {book_id}: {e}")
            if os.environ.get("WEREAD_DEBUG") == "1":
                import traceback
                traceback.print_exc()
            return None
    
    def get_reading_data(self, book_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed reading data for a book - based on kindle-api project's book.fullDetails()
        Tries multiple endpoints to get reading statistics, dates, and progress
        """
        if self.use_clippings:
            # For clippings, we don't have detailed reading data
            return None
        
        # Try multiple possible endpoints for reading data (based on kindle-api project)
        endpoints_to_try = [
            # Service endpoints (from kindle-api project)
            (f"{KINDLE_SERVICE_BASE}/bookDetails", {"asin": book_id}),
            (f"{KINDLE_SERVICE_BASE}/readingProgress", {"asin": book_id}),
            # Alternative endpoints
            (f"{KINDLE_API_BASE}/kindle-library/book", {"asin": book_id}),
            (f"{KINDLE_API_BASE}/kindle-library/reading", {"asin": book_id}),
            (f"{KINDLE_API_BASE}/kindle-library/progress", {"asin": book_id}),
        ]
        
        # Add device token to params if available
        params_with_token = {}
        if self.device_token:
            params_with_token["deviceToken"] = self.device_token
        
        for endpoint_url, params in endpoints_to_try:
            try:
                if os.environ.get("WEREAD_DEBUG") == "1":
                    print(f"[KINDLE API DEBUG] Trying reading data endpoint: {endpoint_url}")
                
                # Merge device token into params if available
                request_params = {**params, **params_with_token}
                response = self.session.get(endpoint_url, params=request_params)
                
                if self._check_auth_error(response, "Kindle Reading Data API"):
                    continue
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        
                        if os.environ.get("WEREAD_DEBUG") == "1":
                            print(f"[KINDLE API DEBUG] Reading data response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                            print(f"[KINDLE API DEBUG] Reading data preview: {str(data)[:500]}")
                        
                        # Try to extract reading data from various possible structures
                        reading_data = (data.get("readingData") or 
                                      data.get("readInfo") or 
                                      data.get("progress") or
                                      data.get("data") or
                                      data)
                        
                        if reading_data and isinstance(reading_data, dict):
                            # Check if we have useful data
                            if any(key in reading_data for key in ["lastReadDate", "firstReadDate", "readingTime", "currentLocation", "totalLocations", "lastAccessDate"]):
                                if os.environ.get("WEREAD_DEBUG") == "1":
                                    print(f"[KINDLE API] ✅ Found reading data using endpoint: {endpoint_url}")
                                return reading_data
                            elif os.environ.get("WEREAD_DEBUG") == "1":
                                print(f"[KINDLE API DEBUG] No useful reading data found, trying next endpoint...")
                    except Exception as e:
                        if os.environ.get("WEREAD_DEBUG") == "1":
                            print(f"[KINDLE API DEBUG] Failed to parse JSON: {e}")
                        continue
                elif os.environ.get("WEREAD_DEBUG") == "1":
                    print(f"[KINDLE API DEBUG] Status {response.status_code}, trying next endpoint...")
            except Exception as e:
                if os.environ.get("WEREAD_DEBUG") == "1":
                    print(f"[KINDLE API DEBUG] Error with endpoint {endpoint_url}: {e}")
                continue
        
        # If all endpoints fail, return None (reading data may not be available)
        if os.environ.get("WEREAD_DEBUG") == "1":
            print(f"[KINDLE API] No reading data found for book {book_id} (this is normal if the book hasn't been read)")
        return None
    
    def get_bookmarks(self, book_id: str) -> List[Dict[str, Any]]:
        """Get bookmarks/highlights for a book"""
        if self.use_clippings:
            clippings_data = self._parse_clippings_file(Path(self.clippings_file))
            if book_id in clippings_data:
                return clippings_data[book_id].get("bookmarks", [])
            return []
        
        # Note: Kindle Cloud Reader API doesn't expose highlights/notes via public API
        # Users need to use My Clippings.txt file for highlights
        # This is a limitation of Amazon's API - they don't provide highlights endpoint
        # We'll return empty list and log a debug message
        if os.environ.get("WEREAD_DEBUG") == "1":
            print(f"[KINDLE API] Note: Kindle Cloud Reader API doesn't provide highlights endpoint")
            print(f"[KINDLE API] To get highlights, use My Clippings.txt file (set KINDLE_CLIPPINGS in .env)")
        
        return []  # Kindle API doesn't expose highlights - use My Clippings.txt instead
    
    @staticmethod
    def _parse_date_field(date_value: Any) -> Optional[datetime]:
        """Parse date field from API response"""
        if date_value is None:
            return None
        try:
            local_tz = dateutil.tz.tzlocal()
            if isinstance(date_value, (int, float)):
                if date_value > 1e10:  # Milliseconds
                    return datetime.fromtimestamp(date_value / 1000, tz=local_tz)
                else:  # Seconds
                    return datetime.fromtimestamp(date_value, tz=local_tz)
            else:
                parsed = dtparser.parse(str(date_value))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=local_tz)
                return parsed
        except Exception:
            return None
