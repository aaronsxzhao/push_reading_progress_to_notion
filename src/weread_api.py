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
from datetime import datetime
from typing import Optional, Dict, Any, List
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
        })
        
        # Parse cookies string into dict
        if cookies:
            cookie_dict = {}
            for item in cookies.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    cookie_dict[key.strip()] = value.strip()
            self.session.cookies.update(cookie_dict)
    
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
                print(f"[API ERROR] {data.get('errmsg', 'Unknown error')}")
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
        except Exception as e:
            print(f"[API ERROR] Failed to fetch book detail for {book_id}: {e}")
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
        except Exception as e:
            print(f"[API ERROR] Failed to fetch reading data for {book_id}: {e}")
            return None
    
    def get_all_books_with_progress(self) -> List[Dict[str, Any]]:
        """
        Fetch all books with their reading progress.
        Returns list of book dicts with: title, author, current_page, total_page, etc.
        """
        notebooks = self.get_notebooks()
        books_data = []
        
        for notebook in notebooks:
            book_info = notebook.get("book", {})
            book_id = book_info.get("bookId")
            
            if not book_id:
                continue
            
            # Get detailed info
            detail = self.get_book_detail(book_id)
            reading_data = self.get_reading_data(book_id)
            
            # Extract progress
            current_page = None
            total_page = None
            percent = None
            
            if reading_data:
                # Try different fields for progress
                current_page = reading_data.get("currentPage") or reading_data.get("readPage")
                total_page = reading_data.get("totalPage") or reading_data.get("pageCount")
                percent = reading_data.get("readPercentage") or reading_data.get("progress")
            
            if detail:
                total_page = total_page or detail.get("pageCount") or detail.get("totalPage")
            
            # Determine status
            if percent and percent >= 100:
                status = "Read"
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
            
            if status == "Read" and last_read_at:
                date_finished = last_read_at
            
            book_data = {
                "title": book_info.get("title") or detail.get("title") or "Unknown",
                "author": book_info.get("author") or detail.get("author") or "",
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
            time.sleep(0.5)
        
        return books_data


def fetch_from_api(cookies: str) -> List[Dict[str, Any]]:
    """Convenience function to fetch all books from WeRead API"""
    client = WeReadAPI(cookies)
    return client.get_all_books_with_progress()

