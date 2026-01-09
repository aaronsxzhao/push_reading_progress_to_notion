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
    """Fetch books from WeRead API and sync to Notion"""
    print("[API] Fetching books from WeRead API...")
    
    client = WeReadAPI(weread_cookies)
    books = client.get_all_books_with_progress()
    
    print(f"[API] Found {len(books)} books")
    
    # Apply limit if specified
    if limit is not None and limit > 0:
        books = books[:limit]
        print(f"[API] Limiting to first {limit} book(s) for testing")
    
    synced_count = 0
    error_count = 0
    
    for book_data in books:
        try:
            # Map status values
            status_map = {
                "Read": STATUS_READ,
                "Currently Reading": STATUS_READING,
                "To Be Read": STATUS_TBR,
            }
            book_data["status"] = status_map.get(book_data.get("status"), STATUS_TBR)
            book_data["source"] = SOURCE_WEREAD
            
            upsert_page(notion, database_id, db_props, book_data)
            synced_count += 1
            print(f"[SYNC] {book_data['title']} | {book_data['status']} | p={book_data.get('current_page')}/{book_data.get('total_page')}")
        except Exception as e:
            error_count += 1
            print(f"[ERROR] {book_data.get('title', 'Unknown')}: {e}")
    
    print(f"\n[COMPLETE] Synced {synced_count} books, {error_count} errors")


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

