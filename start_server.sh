#!/bin/bash
# Start WeRead → Notion Sync Web Server

cd "$(dirname "$0")"
source .venv/bin/activate 2>/dev/null || true
python3 src/sync_web_server.py
