#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WeRead API -> Notion Books & Media auto-sync (Direct API mode)
Fetches data directly from WeRead API without needing Obsidian.

This script:
- Fetches all books from WeRead API using cookies
- Syncs to Notion database
- Can run on a schedule (cron/launchd) or manually

Required env vars:
  NOTION_TOKEN
  NOTION_DATABASE_ID
  WEREAD_COOKIES (your WeRead session cookies)

Optional env vars: same as weread_notion_sync.py
"""

import os
import time
import json
from typing import Dict, Any, Optional

from notion_client import Client
from weread_api import WeReadAPI, env

# Import Notion helpers from the main sync script
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Reuse config and Notion helpers
from weread_notion_sync import (
    PROP_TITLE, PROP_AUTHOR, PROP_STATUS, PROP_CURRENT_PAGE, PROP_TOTAL_PAGE,
    PROP_DATE_FINISHED, PROP_SOURCE, PROP_STARTED_AT, PROP_LAST_READ_AT,
    STATUS_TBR, STATUS_READING, STATUS_READ, SOURCE_WEREAD,
    get_db_properties, prop_exists, build_props, find_page_by_title, upsert_page
)


def sync_books_from_api(notion: Client, database_id: str, db_props: Dict[str, Any], weread_cookies: str, limit: Optional[int] = None):
    """Fetch books from WeRead API and sync to Notion - processes one at a time with progress monitoring"""
    import time
    start_time = time.time()
    
    print("[API] Initializing WeRead API client...")
    
    client = WeReadAPI(weread_cookies)
    
    # Get shelf data first to know total count
    print("[API] Fetching shelf data...")
    shelf_data, all_books_list, book_progress_list = client.get_shelf()
    
    total_books = shelf_data.get("bookCount", 0) or shelf_data.get("pureBookCount", 0) or len(all_books_list)
    print(f"[API] Total books in shelf: {total_books}")
    
    # Build a map of book_id -> book info from the 'books' field (has full info)
    books_map = {}
    for book_item in all_books_list:
        # The 'books' field structure varies - try different possible structures
        book_info = None
        book_id = None
        
        # Try different possible structures
        if "bookInfo" in book_item:
            book_info = book_item["bookInfo"]
            book_id = book_info.get("bookId")
        elif "book" in book_item:
            book_info = book_item["book"]
            book_id = book_info.get("bookId")
        elif "bookId" in book_item:
            book_id = book_item["bookId"]
            book_info = book_item
        
        if book_id and book_info:
            books_map[book_id] = {
                "book": book_info,
                "has_full_info": True
            }
            # Debug first book
            if len(books_map) == 1:
                print(f"[DEBUG] First book in map: bookId={book_id}")
                print(f"[DEBUG] First book info keys: {list(book_info.keys())}")
                print(f"[DEBUG] First book title: {book_info.get('title')}, author: {book_info.get('author')}")
    
    # Build a map of book_id -> progress from bookProgress
    progress_map = {}
    for progress_item in book_progress_list:
        book_id = progress_item.get("bookId")
        if book_id:
            progress_map[book_id] = progress_item
    
    # Combine: use books_map as base, add progress data
    all_book_items = []
    for book_id, book_data in books_map.items():
        progress_data = progress_map.get(book_id, {})
        # Include ALL progress data (chapterIdx, chapterUid, etc.) not just progress percentage
        all_book_items.append({
            "bookId": book_id,
            "book": book_data["book"],
            "progress": progress_data.get("progress", 0),
            "updateTime": progress_data.get("updateTime"),
            "chapterIdx": progress_data.get("chapterIdx"),  # Current chapter index
            "chapterUid": progress_data.get("chapterUid"),
            "chapterOffset": progress_data.get("chapterOffset"),
            "readingTime": progress_data.get("readingTime"),  # Reading time in seconds
            "has_full_info": True
        })
    
    # Add any books from progress_map that aren't in books_map (shouldn't happen, but just in case)
    for book_id, progress_data in progress_map.items():
        if book_id not in books_map:
            all_book_items.append({
                "bookId": book_id,
                "progress": progress_data.get("progress", 0),
                "updateTime": progress_data.get("updateTime"),
                "chapterIdx": progress_data.get("chapterIdx"),
                "chapterUid": progress_data.get("chapterUid"),
                "chapterOffset": progress_data.get("chapterOffset"),
                "readingTime": progress_data.get("readingTime"),
                "has_full_info": False
            })
    
    print(f"[API] Combined {len(all_book_items)} books with full info and progress data")
    
    if not all_book_items:
        print("[ERROR] No books found!")
        return
    
    # Apply limit
    if limit is not None and limit > 0:
        all_book_items = all_book_items[:limit]
        print(f"[API] Limiting to first {limit} book(s) for testing")
    
    total_to_process = len(all_book_items)
    print(f"\n{'='*60}")
    print(f"[PROGRESS] Processing {total_to_process} book(s) one at a time...")
    print(f"{'='*60}\n")
    
    synced_count = 0
    error_count = 0
    
    # Process books one at a time with immediate output
    for i, book_item in enumerate(all_book_items, 1):
        book_id = book_item.get("bookId")
        if not book_id:
            continue
        
        book_start_time = time.time()
        
        try:
            print(f"[{i}/{total_to_process}] 📖 Processing book {book_id}...")
            
            # Get book data one at a time (this is where the work happens)
            book_data = client.get_single_book_data(book_id, book_item)
            
            if book_data:
                # Print full data for first book or if limit is 1
                if i == 1 or limit == 1:
                    print("\n" + "=" * 60)
                    print(f"📖 FULL BOOK DATA (Book {i})")
                    print("=" * 60)
                    print(json.dumps(book_data, indent=2, ensure_ascii=False, default=str))
                    print("=" * 60)
                    print()
                
                # Map status values
                status_map = {
                    "Read": STATUS_READ,
                    "Currently Reading": STATUS_READING,
                    "To Be Read": STATUS_TBR,
                }
                book_data["status"] = status_map.get(book_data.get("status"), STATUS_TBR)
                book_data["source"] = SOURCE_WEREAD
                
                # Sync to Notion
                upsert_page(notion, database_id, db_props, book_data)
                synced_count += 1
                
                book_time = time.time() - book_start_time
                print(f"✅ [{i}/{total_to_process}] {book_data['title']} | {book_data['status']} | p={book_data.get('current_page')}/{book_data.get('total_page')} | ⏱️  {book_time:.1f}s")
            else:
                print(f"⚠️  [{i}/{total_to_process}] Book {book_id}: No data retrieved")
                error_count += 1
            
            # Stop after first book if limit is 1
            if limit == 1:
                print(f"\n[STOPPED] Processed 1 book as requested (limit=1)")
                break
                
        except Exception as e:
            error_count += 1
            book_time = time.time() - book_start_time
            print(f"❌ [{i}/{total_to_process}] Book {book_id}: {e} | ⏱️  {book_time:.1f}s")
            if limit == 1:  # Show full traceback for first book only
                import traceback
                traceback.print_exc()
        
        # Progress update every 10 books or at the end
        if (i % 10 == 0 and limit != 1) or i == total_to_process:
            elapsed = time.time() - start_time
            avg_time = elapsed / i
            remaining = (total_to_process - i) * avg_time if limit is None else 0
            print(f"\n[PROGRESS] {i}/{total_to_process} | ✅ {synced_count} synced | ❌ {error_count} errors | ⏱️  {elapsed:.1f}s elapsed")
            if remaining > 0:
                print(f"          Estimated time remaining: {remaining/60:.1f} minutes\n")
    
    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[COMPLETE] Processed {total_to_process} books | Synced: {synced_count} | Errors: {error_count}")
    print(f"          Total time: {total_time:.1f}s | Avg: {total_time/total_to_process:.1f}s per book")
    print(f"{'='*60}")


def main():
    NOTION_TOKEN = env("NOTION_TOKEN")
    NOTION_DATABASE_ID = env("NOTION_DATABASE_ID")
    WEREAD_COOKIES = env("WEREAD_COOKIES")
    
    # Optional limit for testing (set SYNC_LIMIT in .env, default: None = all books)
    sync_limit = env("SYNC_LIMIT")
    limit = None
    if sync_limit:
        try:
            limit = int(sync_limit)
            if limit <= 0:
                limit = None
        except ValueError:
            limit = None
    
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise SystemExit("Missing NOTION_TOKEN or NOTION_DATABASE_ID env vars.")
    if not WEREAD_COOKIES:
        raise SystemExit("Missing WEREAD_COOKIES env var. See README for how to get cookies.")
    
    notion = Client(auth=NOTION_TOKEN)
    db_props = get_db_properties(notion, NOTION_DATABASE_ID)
    
    sync_books_from_api(notion, NOTION_DATABASE_ID, db_props, WEREAD_COOKIES, limit=limit)


if __name__ == "__main__":
    main()

