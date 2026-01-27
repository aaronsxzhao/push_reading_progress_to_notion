#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serverless function for Vercel/Netlify/Railway
Trigger sync via HTTP request
"""

import os
import sys
import json
from pathlib import Path

# Add src to path for imports
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from notion_client import Client
from weread_api import WeReadAPI
from weread_notion_sync import get_db_properties
from weread_notion_sync_api import sync_books_from_api


def handler(request):
    """Serverless function handler"""
    # Get config from environment variables
    NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
    NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
    WEREAD_COOKIES = os.environ.get("WEREAD_COOKIES")
    
    # Optional API key check
    api_key = request.args.get("key") if hasattr(request, 'args') else None
    expected_key = os.environ.get("SYNC_API_KEY", "")
    
    if expected_key and api_key != expected_key:
        return {
            "statusCode": 401,
            "body": json.dumps({"error": "Invalid API key"})
        }
    
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Missing NOTION_TOKEN or NOTION_DATABASE_ID"})
        }
    
    if not WEREAD_COOKIES:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Missing WEREAD_COOKIES"})
        }
    
    try:
        # Optional limit
        sync_limit = os.environ.get("SYNC_LIMIT")
        limit = None
        if sync_limit:
            try:
                limit = int(sync_limit)
                if limit <= 0:
                    limit = None
            except ValueError:
                limit = None
        
        # Optional test book title
        test_book_title = os.environ.get("WEREAD_TEST_BOOK_TITLE")
        if test_book_title and test_book_title.lower() in ("none", "null", "false", "off", "disable", "0"):
            test_book_title = None
        
        notion = Client(auth=NOTION_TOKEN)
        db_props = get_db_properties(notion, NOTION_DATABASE_ID)
        
        # Run sync (this will print to logs)
        sync_books_from_api(
            notion, 
            NOTION_DATABASE_ID, 
            db_props, 
            WEREAD_COOKIES,
            limit=limit,
            test_book_title=test_book_title
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success",
                "message": "Sync completed successfully"
            })
        }
        
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "status": "error",
                "message": str(e)
            })
        }


# Vercel/Netlify style
def vercel_handler(req):
    return handler(req)


# AWS Lambda style
def lambda_handler(event, context):
    class Request:
        def __init__(self, event):
            self.args = event.get("queryStringParameters") or {}
    return handler(Request(event))


# Railway/Generic HTTP
if __name__ == "__main__":
    from flask import Flask, request as flask_request
    app = Flask(__name__)
    
    @app.route("/sync", methods=["GET", "POST"])
    def sync_endpoint():
        class Request:
            def __init__(self, req):
                self.args = req.args
        result = handler(Request(flask_request))
        if isinstance(result, dict) and "statusCode" in result:
            return result["body"], result["statusCode"]
        return result
    
    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok"}, 200
    
    port = int(os.environ.get("PORT", "8765"))
    app.run(host="0.0.0.0", port=port)
