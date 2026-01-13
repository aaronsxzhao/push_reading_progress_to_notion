#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Web server to trigger WeRead -> Notion sync via HTTP endpoint
Can be embedded in Notion or accessed from anywhere via URL
"""

import os
import sys
import json
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from flask import Flask, request, jsonify, Response
    from flask_cors import CORS
except ImportError:
    print("❌ Flask not installed. Installing...")
    os.system("pip install flask flask-cors")
    from flask import Flask, request, jsonify, Response
    from flask_cors import CORS

from notion_client import Client
from weread_api import WeReadAPI, env
from weread_notion_sync import get_db_properties
from weread_notion_sync_api import sync_books_from_api, sync_kindle_books_from_api

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests (for Notion embeds)

# Global state for sync status
sync_status = {
    "running": False,
    "started_at": None,
    "completed_at": None,
    "progress": {
        "total": 0,
        "processed": 0,
        "synced": 0,
        "errors": 0
    },
    "message": "Ready",
    "error": None
}

sync_lock = threading.Lock()


def get_env_config():
    """Load configuration from environment"""
    sync_source = env("SYNC_SOURCE", "weread").lower()
    return {
        "notion_token": env("NOTION_TOKEN"),
        "notion_database_id": env("NOTION_DATABASE_ID"),
        "sync_source": sync_source,
        "weread_cookies": env("WEREAD_COOKIES"),
        "kindle_cookies": env("KINDLE_COOKIES"),
        "kindle_clippings": env("KINDLE_CLIPPINGS"),
        "kindle_device_token": env("KINDLE_DEVICE_TOKEN"),
        "api_key": env("SYNC_API_KEY", ""),  # Optional API key for security
        "sync_limit": env("SYNC_LIMIT"),
        "test_book_title": env("WEREAD_TEST_BOOK_TITLE") or env("KINDLE_TEST_BOOK_TITLE"),
    }


def run_sync_in_thread():
    """Run sync in a separate thread"""
    global sync_status
    
    with sync_lock:
        if sync_status["running"]:
            return {"error": "Sync already running"}
        sync_status["running"] = True
        sync_status["started_at"] = datetime.now().isoformat()
        sync_status["completed_at"] = None
        sync_status["error"] = None
        sync_status["message"] = "Starting sync..."
        sync_status["progress"] = {"total": 0, "processed": 0, "synced": 0, "errors": 0}
    
    try:
        config = get_env_config()
        
        if not config["notion_token"] or not config["notion_database_id"]:
            raise ValueError("Missing NOTION_TOKEN or NOTION_DATABASE_ID")
        
        notion = Client(auth=config["notion_token"])
        db_props = get_db_properties(notion, config["notion_database_id"])
        
        limit = None
        if config["sync_limit"]:
            try:
                limit = int(config["sync_limit"])
                if limit <= 0:
                    limit = None
            except ValueError:
                limit = None
        
        test_book_title = config["test_book_title"]
        if test_book_title and test_book_title.lower() in ("none", "null", "false", "off", "disable", "0"):
            test_book_title = None
        
        # Determine which source to sync
        sync_source = config.get("sync_source", "weread").lower()
        
        if sync_source == "kindle":
            if not config["kindle_cookies"] and not config["kindle_clippings"]:
                raise ValueError("Missing KINDLE_COOKIES or KINDLE_CLIPPINGS")
            
            with sync_lock:
                sync_status["message"] = "Fetching books from Kindle..."
            
            # Run Kindle sync
            sync_kindle_books_from_api(
                notion,
                config["notion_database_id"],
                db_props,
                kindle_cookies=config["kindle_cookies"],
                kindle_clippings=config["kindle_clippings"],
                kindle_device_token=config["kindle_device_token"],
                limit=limit,
                test_book_title=test_book_title
            )
        else:
            # Default to WeRead
            if not config["weread_cookies"]:
                raise ValueError("Missing WEREAD_COOKIES")
            
            with sync_lock:
                sync_status["message"] = "Fetching books from WeRead..."
            
            # Run WeRead sync
            sync_books_from_api(
                notion, 
                config["notion_database_id"], 
                db_props, 
                config["weread_cookies"],
                limit=limit,
                test_book_title=test_book_title
            )
        
        with sync_lock:
            sync_status["running"] = False
            sync_status["completed_at"] = datetime.now().isoformat()
            sync_status["message"] = "Sync completed successfully"
            
    except Exception as e:
        with sync_lock:
            sync_status["running"] = False
            sync_status["completed_at"] = datetime.now().isoformat()
            sync_status["error"] = str(e)
            sync_status["message"] = f"Sync failed: {str(e)}"
        import traceback
        traceback.print_exc()


@app.route("/", methods=["GET"])
def index():
    """Home page with instructions"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WeRead → Notion Sync Server</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
            h1 { color: #333; }
            .endpoint { background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0; }
            .code { background: #2d2d2d; color: #f8f8f2; padding: 10px; border-radius: 3px; font-family: monospace; }
            .button { display: inline-block; padding: 10px 20px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px; margin: 10px 0; }
            .button:hover { background: #45a049; }
            .status { padding: 10px; border-radius: 5px; margin: 10px 0; }
            .status.running { background: #fff3cd; }
            .status.success { background: #d4edda; }
            .status.error { background: #f8d7da; }
        </style>
    </head>
    <body>
        <h1>📚 WeRead → Notion Sync Server</h1>
        <p>This server provides an HTTP endpoint to trigger book synchronization from WeRead to Notion.</p>
        
        <h2>Endpoints</h2>
        <div class="endpoint">
            <h3>GET /status</h3>
            <p>Get current sync status</p>
            <div class="code">curl {request.host_url}status</div>
        </div>
        
        <div class="endpoint">
            <h3>POST /sync</h3>
            <p>Trigger a sync (starts in background)</p>
            <div class="code">curl -X POST {request.host_url}sync</div>
        </div>
        
        <div class="endpoint">
            <h3>GET /sync</h3>
            <p>Trigger a sync and wait for completion (returns JSON)</p>
            <div class="code">curl {request.host_url}sync</div>
        </div>
        
        <h2>For Notion</h2>
        <p>You can embed this in Notion by creating a web bookmark or using the URL:</p>
        <div class="code">{request.host_url}sync</div>
        
        <p>Or create a button that calls the endpoint via a webhook/integration.</p>
        
        <h2>Current Status</h2>
        <div id="status" class="status">Loading...</div>
        <a href="/sync" class="button">🔄 Trigger Sync Now</a>
        
        <script>
            function updateStatus() {{
                fetch('/status')
                    .then(r => r.json())
                    .then(data => {{
                        const statusDiv = document.getElementById('status');
                        let className = 'status';
                        let text = '';
                        
                        if (data.running) {{
                            className += ' running';
                            text = `🔄 Running: ${{data.message}}`;
                        }} else if (data.error) {{
                            className += ' error';
                            text = `❌ Error: ${{data.error}}`;
                        }} else if (data.completed_at) {{
                            className += ' success';
                            text = `✅ Completed: ${{data.message}}`;
                        }} else {{
                            text = `⏸️ Ready: ${{data.message}}`;
                        }}
                        
                        statusDiv.className = className;
                        statusDiv.textContent = text;
                    }})
                    .catch(e => {{
                        document.getElementById('status').textContent = 'Error loading status';
                    }});
            }}
            
            updateStatus();
            setInterval(updateStatus, 2000); // Update every 2 seconds
        </script>
    </body>
    </html>
    """
    return html.format(request=request)


@app.route("/status", methods=["GET"])
def status():
    """Get current sync status"""
    with sync_lock:
        return jsonify(sync_status)


@app.route("/sync", methods=["GET", "POST"])
def sync():
    """Trigger sync - GET returns HTML, POST returns JSON"""
    global sync_status
    
    # Optional API key check
    config = get_env_config()
    if config["api_key"]:
        provided_key = request.args.get("key") or request.headers.get("X-API-Key")
        if provided_key != config["api_key"]:
            return jsonify({"error": "Invalid API key"}), 401
    
    # Check if already running
    with sync_lock:
        if sync_status["running"]:
            if request.method == "GET":
                return f"""
                <html><body>
                    <h1>Sync Already Running</h1>
                    <p>Sync is currently in progress. Please wait.</p>
                    <p><a href="/status">Check Status</a></p>
                    <script>setTimeout(() => window.location.href = '/status', 2000);</script>
                </body></html>
                """, 200
            else:
                return jsonify({"error": "Sync already running", "status": sync_status}), 409
    
    # Start sync in background thread
    thread = threading.Thread(target=run_sync_in_thread, daemon=True)
    thread.start()
    
    if request.method == "GET":
        # Return HTML page that auto-refreshes
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Sync Started</title>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="2;url=/status">
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 100px auto; text-align: center; }}
                .spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }}
                @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            </style>
        </head>
        <body>
            <h1>🔄 Sync Started</h1>
            <div class="spinner"></div>
            <p>Redirecting to status page...</p>
            <p><a href="/status">View Status</a></p>
        </body>
        </html>
        """, 200
    else:
        # Return JSON
        return jsonify({
            "message": "Sync started",
            "status": sync_status
        }), 202


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    config = get_env_config()
    checks = {
        "notion_token": bool(config["notion_token"]),
        "notion_database_id": bool(config["notion_database_id"]),
        "weread_cookies": bool(config["weread_cookies"]),
    }
    all_ok = all(checks.values())
    
    return jsonify({
        "status": "healthy" if all_ok else "unhealthy",
        "checks": checks,
        "sync_running": sync_status["running"]
    }), 200 if all_ok else 503


if __name__ == "__main__":
    # Get port from env or use default (using 8765 to avoid conflicts with common ports)
    port = int(env("SYNC_SERVER_PORT", "8765"))
    host = env("SYNC_SERVER_HOST", "0.0.0.0")
    
    print(f"""
    {'='*60}
    📚 WeRead → Notion Sync Server
    {'='*60}
    Starting server on http://{host}:{port}
    
    Endpoints:
      - GET  /          : Home page with instructions
      - GET  /status    : Get sync status (JSON)
      - GET  /sync      : Trigger sync (HTML page)
      - POST /sync      : Trigger sync (JSON response)
      - GET  /health    : Health check
    
    For Notion:
      - Embed URL: http://localhost:{port}/sync
      - Or use: http://localhost:{port}/status (for status updates)
    
    To change port, set SYNC_SERVER_PORT in .env file
    
    Press Ctrl+C to stop
    {'='*60}
    """)
    
    app.run(host=host, port=port, debug=False)
