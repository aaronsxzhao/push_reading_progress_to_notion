#!/usr/bin/env python3
"""
Refresh WeRead cookies (headless) and immediately sync to Notion + update heatmap.

Designed to be called by launchd every hour. Avoids macOS Gatekeeper issues
that block bash scripts in the Downloads folder.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
PYTHON_BIN = str(PROJECT_DIR / ".venv" / "bin" / "python3")
ENV_FILE = PROJECT_DIR / ".env"


def load_env():
    """Load .env into os.environ."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            os.environ[key.strip()] = val


def run(label: str, args: list[str]) -> bool:
    print(f"  {label}")
    result = subprocess.run(args, cwd=str(PROJECT_DIR), env=os.environ)
    if result.returncode != 0:
        print(f"  FAILED (exit {result.returncode})")
        return False
    return True


def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== {ts} Cookie refresh + sync ===")

    load_env()

    # Step 1: Refresh cookies (headless)
    ok = run("[1/3] Refreshing cookies...", [
        PYTHON_BIN, str(PROJECT_DIR / "scripts" / "fetch_cookies_auto.py"), "--headless",
    ])
    if not ok:
        print("Cookie refresh failed — skipping sync")
        return 1

    # Reload env with the fresh cookies
    load_env()

    # Step 2: Sync to Notion
    run("[2/3] Syncing to Notion...", [
        PYTHON_BIN, "-u", str(PROJECT_DIR / "src" / "weread_notion_sync_api.py"),
    ])

    # Step 3: Compute heatmap data and push to Gist
    run("[3/3] Computing heatmap data...", [
        PYTHON_BIN, "-u", str(PROJECT_DIR / "scripts" / "compute_heatmap.py"),
    ])

    print("=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
