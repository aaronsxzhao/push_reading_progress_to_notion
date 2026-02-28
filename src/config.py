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


# WeRead API endpoints (only the ones that actually exist)
WEREAD_API_BASE = "https://weread.qq.com"
WEREAD_SHELF_API = f"{WEREAD_API_BASE}/web/shelf/sync"
WEREAD_BOOK_INFO_API = f"{WEREAD_API_BASE}/web/book/info"
WEREAD_READ_INFO_API = f"{WEREAD_API_BASE}/web/book/readinfo"
WEREAD_BOOKMARKLIST_API = f"{WEREAD_API_BASE}/web/book/bookmarklist"
WEREAD_REVIEW_LIST_API = f"{WEREAD_API_BASE}/web/review/list"
WEREAD_CHAPTER_INFO_API = f"{WEREAD_API_BASE}/web/book/chapterInfos"

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

# WeRead Chinese category → English genre mapping.
# Each Chinese category maps to a list of English genre tags (multi-select).
# Existing Notion genres are reused exactly as-is.
GENRE_MAP: dict[str, list[str]] = {
    "个人成长-人在职场":   ["Career", "Self-Help"],
    "个人成长-人生哲学":   ["Philosophy", "Self-Help"],
    "个人成长-励志成长":   ["Self-Help"],
    "个人成长-沟通表达":   ["Communication", "Self-Help"],
    "个人成长-认知思维":   ["Psychology", "Self-Help"],
    "人物传记-传记综合":   ["Biography"],
    "人物传记-军政领袖":   ["Biography", "Politics"],
    "人物传记-财经人物":   ["Biography", "Business"],
    "医学健康-健康":      ["Health"],
    "医学健康-医学":      ["Medicine"],
    "历史-历史读物":      ["History"],
    "哲学宗教-哲学读物":   ["Philosophy"],
    "哲学宗教-宗教":      ["Religion"],
    "哲学宗教-西方哲学":   ["Philosophy"],
    "心理-发展心理学":    ["Psychology"],
    "心理-心理学应用":    ["Psychology"],
    "心理-心理学研究":    ["Psychology"],
    "心理-社会心理学":    ["Psychology", "Sociology"],
    "心理-积极心理学":    ["Psychology", "Self-Help"],
    "心理-认知与行为":    ["Psychology"],
    "政治军事-政治":      ["Politics"],
    "文学-世界名著":      ["Literary Classics"],
    "文学-外国文学":      ["Literature"],
    "文学-散文杂著":      ["Essays"],
    "文学-现代诗歌":      ["Poetry"],
    "文学-经典作品":      ["Literary Classics"],
    "社会文化-文化":      ["Culture"],
    "社会文化-社科":      ["Social Science"],
    "科学技术-科学科普":   ["Popular Science"],
    "科学技术-自然科学":   ["Natural Science"],
    "精品小说-年代小说":   ["Historical fiction"],
    "精品小说-影视原著":   ["Fiction"],
    "精品小说-悬疑推理":   ["Thriller / Mystery"],
    "精品小说-治愈小说":   ["Fiction"],
    "精品小说-社会小说":   ["Literary Fiction"],
    "精品小说-科幻小说":   ["Sci-Fi"],
    "精品小说-青春文学":   ["Young Adult"],
    "经济理财-商业":      ["Business"],
    "经济理财-理财":      ["Finance", "Personal Finance"],
    "经济理财-管理":      ["Management"],
    "经济理财-财经":      ["Economics", "Finance"],
    "艺术-设计":         ["Design"],
    "计算机-编程设计":    ["Programming"],
}


def translate_genres(categories: list[dict] | None) -> list[str]:
    """Translate WeRead category dicts into deduplicated English genre tags."""
    if not categories:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for cat in categories:
        title = cat.get("title", "")
        for eng in GENRE_MAP.get(title, []):
            if eng not in seen:
                seen.add(eng)
                result.append(eng)
    return result
