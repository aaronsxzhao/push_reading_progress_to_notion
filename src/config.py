#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centralized configuration for WeRead -> Notion sync.

This module provides:
- Environment variable loading with defaults
- Cookie persistence utilities
- Common configuration constants
"""

import os
from pathlib import Path
from typing import Optional

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    ENV_PATH = Path(__file__).parent.parent / ".env"
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
except ImportError:
    ENV_PATH = Path(__file__).parent.parent / ".env"


def env(name: str, default: Optional[str] = None) -> str:
    """Get environment variable with optional default."""
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        if default is None:
            return ""
        return default
    return str(v).strip()


def update_env_file(key: str, value: str, env_path: Optional[Path] = None) -> bool:
    """
    Update a key in the .env file.
    If key exists, replace it. Otherwise, append it.
    
    Args:
        key: Environment variable name (e.g., 'WEREAD_COOKIES')
        value: Value to set (will be quoted)
        env_path: Path to .env file (defaults to project root)
    
    Returns:
        True if successful
    """
    if env_path is None:
        env_path = ENV_PATH
    
    if not env_path.exists():
        print(f"[CONFIG] Creating .env file at {env_path}")
        env_path.touch()
    
    # Read existing .env content
    content = env_path.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    # Find and replace the key
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f'{key}=') or stripped.startswith(f'#{key}='):
            # Replace existing (or uncomment if commented)
            new_lines.append(f'{key}="{value}"')
            updated = True
        else:
            new_lines.append(line)
    
    # If not found, append it
    if not updated:
        if content and not content.endswith('\n'):
            new_lines.append('')
        new_lines.append(f'{key}="{value}"')
    
    # Write back
    env_path.write_text('\n'.join(new_lines), encoding='utf-8')
    return True


def format_cookies(cookie_dict: dict) -> str:
    """Format cookie dictionary as cookie string."""
    return "; ".join(f"{k}={v}" for k, v in sorted(cookie_dict.items()))


def parse_cookies(cookie_str: str) -> dict:
    """Parse cookie string into dictionary."""
    cookies = {}
    if not cookie_str:
        return cookies
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


# WeRead API endpoints
WEREAD_API_BASE = "https://weread.qq.com"
WEREAD_NOTEBOOKS_API = f"{WEREAD_API_BASE}/api/user/notebook"
WEREAD_SHELF_API = f"{WEREAD_API_BASE}/web/shelf/sync"
WEREAD_BOOK_INFO_API = f"{WEREAD_API_BASE}/web/book/bookDetail"
WEREAD_BOOK_INFO_API_V2 = f"{WEREAD_API_BASE}/web/book/info"
WEREAD_READING_DATA_API = f"{WEREAD_API_BASE}/web/readingData"
WEREAD_BOOK_LIST_API = f"{WEREAD_API_BASE}/web/shelf/bookList"
WEREAD_READ_INFO_API = f"{WEREAD_API_BASE}/web/book/readinfo"
WEREAD_BOOK_READING_API = f"{WEREAD_API_BASE}/web/book/reading"
WEREAD_USER_READING_API = f"{WEREAD_API_BASE}/web/user/reading"
WEREAD_BOOKMARKLIST_API = f"{WEREAD_API_BASE}/web/book/bookmarklist"
WEREAD_REVIEW_LIST_API = f"{WEREAD_API_BASE}/web/review/list"
WEREAD_NOTE_LIST_API = f"{WEREAD_API_BASE}/web/book/note"
WEREAD_CHAPTER_INFO_API = f"{WEREAD_API_BASE}/web/book/chapterInfos"
WEREAD_GET_PROGRESS_API = f"{WEREAD_API_BASE}/web/book/getProgress"

# Notion property names (configurable via env)
PROP_TITLE = env("NOTION_TITLE_PROP", "Name")
PROP_AUTHOR = env("PROP_AUTHOR", "Author")
PROP_STATUS = env("PROP_STATUS", "Status")
PROP_CURRENT_PAGE = env("PROP_CURRENT_PAGE", "Current Page")
PROP_TOTAL_PAGE = env("PROP_TOTAL_PAGE", "Total Page")
PROP_DATE_FINISHED = env("PROP_DATE_FINISHED", "Date Finished")
PROP_SOURCE = env("PROP_SOURCE", "Source")
PROP_STARTED_AT = env("PROP_STARTED_AT", "Date Started")
PROP_LAST_READ_AT = env("PROP_LAST_READ_AT", "Last Read At")
PROP_COVER_IMAGE = env("PROP_COVER_IMAGE", "Cover")
PROP_GENRE = env("PROP_GENRE", "Genre")
PROP_YEAR_STARTED = env("PROP_YEAR_STARTED", "Year Started")
PROP_RATING = env("PROP_RATING", "Rating")
PROP_REVIEW = env("PROP_REVIEW", "Review")

# Status values (configurable via env)
STATUS_TBR = env("STATUS_TBR", "To Be Read")
STATUS_READING = env("STATUS_READING", "Currently Reading")
STATUS_READ = env("STATUS_READ", "Read")

# Source identifier
SOURCE_WEREAD = env("SOURCE_WEREAD", "WeRead")
