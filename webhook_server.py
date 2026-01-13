#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimal webhook server - starts only when called, runs sync, then exits
Use with services like Zapier, Make.com, or ngrok
"""

import sys
import subprocess
from pathlib import Path

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("Installing Flask...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/sync", methods=["GET", "POST"])
def webhook_sync():
    """Webhook endpoint - triggers sync and returns immediately"""
    # Optional API key check
    api_key = request.args.get("key") or request.headers.get("X-API-Key")
    expected_key = os.environ.get("SYNC_API_KEY", "")
    
    if expected_key and api_key != expected_key:
        return jsonify({"error": "Invalid API key"}), 401
    
    # Run sync in background (non-blocking)
    script_path = Path(__file__).parent / "webhook_sync.py"
    subprocess.Popen([sys.executable, str(script_path), "--webhook"])
    
    return jsonify({
        "status": "started",
        "message": "Sync triggered successfully"
    }), 202


@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("SYNC_SERVER_PORT", "8765"))
    host = os.environ.get("SYNC_SERVER_HOST", "0.0.0.0")
    
    print(f"""
    {'='*60}
    📚 WeRead → Notion Webhook Server
    {'='*60}
    Starting on http://{host}:{port}
    
    Webhook URL: http://{host}:{port}/sync
    
    This server stays running to receive webhook calls.
    Each call triggers a sync and returns immediately.
    
    Press Ctrl+C to stop
    {'='*60}
    """)
    
    app.run(host=host, port=port, debug=False, threaded=True)
