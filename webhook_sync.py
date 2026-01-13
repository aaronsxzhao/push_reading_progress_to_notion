#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Webhook endpoint to trigger sync on-demand
Can be called from anywhere (Notion, Zapier, IFTTT, etc.)
No persistent server needed - runs sync and exits
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from notion_client import Client
from weread_api import WeReadAPI, env
from weread_notion_sync import get_db_properties
from weread_notion_sync_api import sync_books_from_api


def run_sync():
    """Run the sync process"""
    NOTION_TOKEN = env("NOTION_TOKEN")
    NOTION_DATABASE_ID = env("NOTION_DATABASE_ID")
    WEREAD_COOKIES = env("WEREAD_COOKIES")
    
    # Optional limit for testing
    sync_limit = env("SYNC_LIMIT")
    limit = None
    if sync_limit:
        try:
            limit = int(sync_limit)
            if limit <= 0:
                limit = None
        except ValueError:
            limit = None
    
    # Optional test book title
    test_book_title = env("WEREAD_TEST_BOOK_TITLE")
    if test_book_title and test_book_title.lower() in ("none", "null", "false", "off", "disable", "0"):
        test_book_title = None
    
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise SystemExit("Missing NOTION_TOKEN or NOTION_DATABASE_ID env vars.")
    if not WEREAD_COOKIES:
        raise SystemExit("Missing WEREAD_COOKIES env var.")
    
    notion = Client(auth=NOTION_TOKEN)
    db_props = get_db_properties(notion, NOTION_DATABASE_ID)
    
    sync_books_from_api(
        notion, 
        NOTION_DATABASE_ID, 
        db_props, 
        WEREAD_COOKIES,
        limit=limit,
        test_book_title=test_book_title
    )


if __name__ == "__main__":
    # Simple webhook handler - can be called via HTTP or directly
    if len(sys.argv) > 1 and sys.argv[1] == "--webhook":
        # Running as webhook - return JSON response
        try:
            run_sync()
            print('{"status": "success", "message": "Sync completed"}')
        except Exception as e:
            print(f'{{"status": "error", "message": "{str(e)}"}}')
            sys.exit(1)
    else:
        # Running directly
        run_sync()
