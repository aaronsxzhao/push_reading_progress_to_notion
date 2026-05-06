#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Serverless function for Vercel — serves pre-computed heatmap data from
a GitHub Gist (computed and pushed hourly by the local Mac).

Returns JSON: {
  "days": {"2026-01-15": 3600, ...},   // date -> seconds
  "totalSeconds": 726299,
  "totalDays": 115,
  "currentStreak": 3,
  "longestStreak": 12,
  "booksWithTime": 115
}
"""

import os
import json
from http.server import BaseHTTPRequestHandler
from urllib.request import Request, urlopen


def _fetch_heatmap_from_gist() -> dict | None:
    """Fetch pre-computed heatmap JSON from GitHub Gist."""
    gh_token = os.environ.get("GH_TOKEN", "")
    gist_id = os.environ.get("COOKIE_GIST_ID", "")
    if not gh_token or not gist_id:
        return None
    try:
        req = Request(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {gh_token}",
                     "Accept": "application/vnd.github.v3+json"},
        )
        with urlopen(req, timeout=10) as resp:
            gist = json.loads(resp.read())
            content = gist["files"].get("heatmap_data.json", {}).get("content")
            if content:
                return json.loads(content)
    except Exception:
        pass
    return None


class handler(BaseHTTPRequestHandler):
    """Vercel serverless handler."""

    def do_GET(self):
        data = _fetch_heatmap_from_gist()
        if not data:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Heatmap data not available. Waiting for local sync."
            }).encode())
            return

        body = json.dumps(data, ensure_ascii=False)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300, s-maxage=300")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
