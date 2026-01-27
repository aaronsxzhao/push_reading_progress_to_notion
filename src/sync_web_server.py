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
from config import env
from weread_api import WeReadAPI
from weread_notion_sync import get_db_properties
from weread_notion_sync_api import sync_books_from_api

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
    return {
        "notion_token": env("NOTION_TOKEN"),
        "notion_database_id": env("NOTION_DATABASE_ID"),
        "weread_cookies": env("WEREAD_COOKIES"),
        "api_key": env("SYNC_API_KEY", ""),  # Optional API key for security
        "sync_limit": env("SYNC_LIMIT"),
        "test_book_title": env("WEREAD_TEST_BOOK_TITLE"),
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
        if not config["weread_cookies"]:
            raise ValueError("Missing WEREAD_COOKIES")
        
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
        
        with sync_lock:
            sync_status["message"] = "Fetching books from WeRead..."
        
        # Run the sync
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


@app.route("/trigger", methods=["GET"])
def trigger():
    """Mobile-friendly trigger page - can be saved to iPhone home screen"""
    global sync_status
    
    # Optional API key check
    config = get_env_config()
    if config["api_key"]:
        provided_key = request.args.get("key")
        if provided_key != config["api_key"]:
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
                <title>Access Denied</title>
                <style>
                    body { font-family: -apple-system, system-ui, sans-serif; display: flex; justify-content: center; 
                           align-items: center; min-height: 100vh; margin: 0; background: #1a1a1a; color: #fff; }
                    .msg { text-align: center; padding: 20px; }
                </style>
            </head>
            <body><div class="msg"><h1>🔒</h1><p>Invalid API Key</p></div></body>
            </html>
            """, 401
    
    with sync_lock:
        is_running = sync_status["running"]
        current_status = sync_status.copy()
    
    # Build status display
    if is_running:
        status_class = "running"
        status_icon = "🔄"
        status_text = current_status.get("message", "Syncing...")
        button_disabled = "disabled"
        button_text = "Syncing..."
    elif current_status.get("error"):
        status_class = "error"
        status_icon = "❌"
        status_text = current_status.get("error", "Error")[:50]
        button_disabled = ""
        button_text = "Retry Sync"
    elif current_status.get("completed_at"):
        status_class = "success"
        status_icon = "✅"
        status_text = "Sync completed"
        button_disabled = ""
        button_text = "Sync Again"
    else:
        status_class = "ready"
        status_icon = "📚"
        status_text = "Ready to sync"
        button_disabled = ""
        button_text = "Sync Now"
    
    # API key param for redirects
    key_param = f"?key={config['api_key']}" if config["api_key"] else ""
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="WeRead Sync">
        <link rel="apple-touch-icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📚</text></svg>">
        <title>WeRead Sync</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 20px;
                color: #fff;
            }}
            .container {{ text-align: center; width: 100%; max-width: 400px; }}
            .icon {{ font-size: 80px; margin-bottom: 20px; }}
            h1 {{ font-size: 24px; margin-bottom: 10px; font-weight: 600; }}
            .status {{
                padding: 15px 25px;
                border-radius: 12px;
                margin: 20px 0;
                font-size: 16px;
            }}
            .status.ready {{ background: rgba(255,255,255,0.1); }}
            .status.running {{ background: rgba(59,130,246,0.3); animation: pulse 1.5s infinite; }}
            .status.success {{ background: rgba(34,197,94,0.3); }}
            .status.error {{ background: rgba(239,68,68,0.3); }}
            @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.7; }} }}
            .btn {{
                display: block;
                width: 100%;
                padding: 20px 40px;
                font-size: 20px;
                font-weight: 600;
                border: none;
                border-radius: 16px;
                cursor: pointer;
                transition: all 0.2s;
                text-decoration: none;
                margin-top: 20px;
            }}
            .btn-primary {{
                background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
                color: white;
                box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4);
            }}
            .btn-primary:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(59, 130, 246, 0.5); }}
            .btn-primary:active {{ transform: translateY(0); }}
            .btn:disabled {{ opacity: 0.6; cursor: not-allowed; transform: none !important; }}
            .spinner {{
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 3px solid rgba(255,255,255,0.3);
                border-radius: 50%;
                border-top-color: #fff;
                animation: spin 1s linear infinite;
                margin-right: 10px;
                vertical-align: middle;
            }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
            .footer {{ margin-top: 40px; font-size: 12px; opacity: 0.5; }}
            .footer a {{ color: inherit; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">📚</div>
            <h1>WeRead → Notion</h1>
            
            <div class="status {status_class}">
                <span>{status_icon}</span> {status_text}
            </div>
            
            <form action="/sync{key_param}" method="GET">
                <button type="submit" class="btn btn-primary" {button_disabled}>
                    {"<span class='spinner'></span>" if is_running else ""}{button_text}
                </button>
            </form>
            
            <p class="footer">
                <a href="/status{key_param}">View Details</a>
            </p>
        </div>
        
        <script>
            // Auto-refresh when sync is running
            {"setInterval(() => location.reload(), 3000);" if is_running else ""}
        </script>
    </body>
    </html>
    """
    return html


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
      - GET  /trigger   : Mobile-friendly sync button (for iPhone)
      - GET  /status    : Get sync status (JSON)
      - GET  /sync      : Trigger sync (HTML page)
      - POST /sync      : Trigger sync (JSON response)
      - GET  /health    : Health check
    
    For iPhone:
      1. Open http://localhost:{port}/trigger in Safari
      2. Tap Share > Add to Home Screen
      3. One-tap sync from your home screen!
    
    For Notion:
      - Add bookmark: http://localhost:{port}/sync
    
    To change port, set SYNC_SERVER_PORT in .env
    
    Press Ctrl+C to stop
    {'='*60}
    """)
    
    app.run(host=host, port=port, debug=False)
