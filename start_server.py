#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple script to start the sync web server
Usage: python3 start_server.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import and run the server
from sync_web_server import app, get_env_config
from weread_api import env

if __name__ == "__main__":
    port = int(env("SYNC_SERVER_PORT", "8765"))
    host = env("SYNC_SERVER_HOST", "0.0.0.0")
    
    print(f"""
    {'='*60}
    📚 WeRead → Notion Sync Server
    {'='*60}
    Starting server on http://{host}:{port}
    
    Access it at: http://localhost:{port}
    
    Press Ctrl+C to stop
    {'='*60}
    """)
    
    app.run(host=host, port=port, debug=False)
