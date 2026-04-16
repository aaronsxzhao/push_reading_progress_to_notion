#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serverless function for Vercel — trigger a WeRead -> Notion sync via HTTP.
"""

import os
import sys
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from notion_client import Client
from weread_api import WeReadAPI
from weread_notion_sync import get_db_properties
from weread_notion_sync_api import sync_books_from_api


def _run_sync(query_params: dict) -> tuple[int, dict]:
    NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
    NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
    WEREAD_COOKIES = os.environ.get("WEREAD_COOKIES")

    expected_key = os.environ.get("SYNC_API_KEY", "")
    api_key = query_params.get("key", [None])[0]
    if expected_key and api_key != expected_key:
        return 401, {"error": "Invalid API key"}

    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        return 500, {"error": "Missing NOTION_TOKEN or NOTION_DATABASE_ID"}

    if not WEREAD_COOKIES:
        return 500, {"error": "Missing WEREAD_COOKIES"}

    try:
        limit = None
        sync_limit = os.environ.get("SYNC_LIMIT")
        if sync_limit:
            try:
                limit = int(sync_limit)
                if limit <= 0:
                    limit = None
            except ValueError:
                limit = None

        test_book_title = os.environ.get("WEREAD_TEST_BOOK_TITLE")
        if test_book_title and test_book_title.lower() in (
            "none", "null", "false", "off", "disable", "0",
        ):
            test_book_title = None

        # Proactively renew cookies before syncing
        api = WeReadAPI(WEREAD_COOKIES, auto_refresh=False)
        if api.renew_cookies_silent():
            WEREAD_COOKIES = api.get_cookie_string()

        notion = Client(auth=NOTION_TOKEN)
        db_props = get_db_properties(notion, NOTION_DATABASE_ID)
        sync_books_from_api(
            notion, NOTION_DATABASE_ID, db_props, WEREAD_COOKIES,
            limit=limit, test_book_title=test_book_title,
        )

        return 200, {"status": "success", "message": "Sync completed successfully"}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


class handler(BaseHTTPRequestHandler):
    """Vercel serverless handler."""

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        status, body = _run_sync(query)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        self.do_GET()
