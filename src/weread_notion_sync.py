#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WeRead (Obsidian markdown) -> Notion Books & Media auto-sync
- Watches an Obsidian folder for changes (no daily manual run)
- Upserts books into a Notion database
- Updates reading progress + timestamps + status

Secrets/config are loaded from environment variables (recommend using .env + launchd env).

Required env vars:
  NOTION_TOKEN
  NOTION_DATABASE_ID
  WEREAD_ROOT

Optional env vars (property names):
  NOTION_TITLE_PROP (default: Name)
  PROP_AUTHOR, PROP_STATUS, PROP_CURRENT_PAGE, PROP_TOTAL_PAGE, PROP_DATE_FINISHED
  PROP_SOURCE, PROP_STARTED_AT, PROP_LAST_READ_AT

Optional env vars (status values):
  STATUS_TBR, STATUS_READING, STATUS_READ

Optional env vars:
  SOURCE_WEREAD (default: WeRead)
"""

import os
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import yaml
from notion_client import Client
from dateutil import parser as dtparser
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# -------------------------
# Config helpers
# -------------------------

def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        if default is None:
            return ""
        return default
    return str(v).strip()

NOTION_TOKEN = env("NOTION_TOKEN")
NOTION_DATABASE_ID = env("NOTION_DATABASE_ID")
WEREAD_ROOT = Path(env("WEREAD_ROOT", os.path.expanduser("~/Obsidian/WeRead"))).expanduser()

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

STATUS_TBR = env("STATUS_TBR", "To Be Read")
STATUS_READING = env("STATUS_READING", "Currently Reading")
STATUS_READ = env("STATUS_READ", "Read")

SOURCE_WEREAD = env("SOURCE_WEREAD", "WeRead")

DEBOUNCE_SECONDS = 1.0

CANDIDATE_FILES = ["metadata.md", "highlights.md", "notes.md", "README.md"]

DATE_PATTERNS = [
    r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)\b",
    r"\b(\d{4}\.\d{1,2}\.\d{1,2})\b",
]

PROGRESS_PATTERNS = [
    r"\b(\d{1,5})\s*/\s*(\d{1,5})\b",  # 172/318
    r"(?:当前进度|进度|阅读进度)[:：]?\s*(\d{1,5})\s*/\s*(\d{1,5})",
    r"\b(\d{1,3}(?:\.\d+)?)\s*%\b",   # 54.1%
]

FINISHED_HINT_PATTERNS = [
    r"(?:已读完|读完了|完成阅读|阅读完成|Finished)\b",
]


# -------------------------
# Markdown parsing
# -------------------------

def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="ignore")

def _parse_frontmatter(text: str) -> Dict[str, Any]:
    """
    Extract YAML frontmatter between --- blocks if present.
    """
    if not text.startswith("---"):
        return {}
    try:
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}
        fm = parts[1]
        data = yaml.safe_load(fm) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _extract_title_author(text: str) -> Tuple[Optional[str], Optional[str]]:
    fm = _parse_frontmatter(text)
    title = None
    author = None

    if fm:
        title = fm.get("title") or fm.get("name")
        author = fm.get("author")

    if not title:
        m = re.search(r"(?m)^\s*#\s+(.+?)\s*$", text)
        title = m.group(1).strip() if m else None

    if not author:
        m = re.search(r"(?im)^\s*author\s*[:：]\s*(.+?)\s*$", text)
        author = m.group(1).strip() if m else None

    if not author:
        m = re.search(r"(?im)^\s*作者\s*[:：]\s*(.+?)\s*$", text)
        author = m.group(1).strip() if m else None

    return title, author

def _extract_progress(text: str) -> Tuple[Optional[int], Optional[int], Optional[float]]:
    # fraction current/total
    for pat in PROGRESS_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            if m.lastindex == 2:
                try:
                    c = int(m.group(1))
                    t = int(m.group(2))
                    if 0 <= c <= 200000 and 1 <= t <= 200000:
                        return c, t, None
                except Exception:
                    pass

    # percent only
    m = re.search(PROGRESS_PATTERNS[-1], text)
    if m:
        try:
            p = float(m.group(1))
            if 0.0 <= p <= 100.0:
                return None, None, p
        except Exception:
            pass

    return None, None, None

def _extract_dates(text: str) -> List[datetime]:
    out: List[datetime] = []
    for pat in DATE_PATTERNS:
        for m in re.finditer(pat, text):
            try:
                out.append(dtparser.parse(m.group(1)))
            except Exception:
                pass
    return out

def _looks_finished(text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in FINISHED_HINT_PATTERNS)


# -------------------------
# Notion helpers
# -------------------------

def get_db_properties(notion: Client, database_id: str) -> Dict[str, Any]:
    db = notion.databases.retrieve(database_id=database_id)
    return db["properties"]

def prop_exists(db_props: Dict[str, Any], name: str) -> bool:
    return name in db_props

def build_props(db_props: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    props: Dict[str, Any] = {}

    if fields.get("title"):
        if prop_exists(db_props, PROP_TITLE):
            # Check if it's a title property
            prop_type = db_props[PROP_TITLE].get("type")
            if prop_type == "title":
                props[PROP_TITLE] = {"title": [{"text": {"content": fields["title"]}}]}
            else:
                # Try as rich_text if title type doesn't work
                props[PROP_TITLE] = {"rich_text": [{"text": {"content": fields["title"]}}]}
        else:
            # Property doesn't exist - print helpful error
            available_props = ", ".join(list(db_props.keys())[:10])
            raise ValueError(f"Property '{PROP_TITLE}' not found in database. Available properties: {available_props}... (set NOTION_TITLE_PROP in .env)")

    if fields.get("author") is not None and fields.get("author") != "" and prop_exists(db_props, PROP_AUTHOR):
        props[PROP_AUTHOR] = {"rich_text": [{"text": {"content": fields["author"]}}]}

    if fields.get("status") and prop_exists(db_props, PROP_STATUS):
        status_prop = db_props[PROP_STATUS]
        prop_type = status_prop.get("type")
        
        # Handle both "select" and "status" property types
        if prop_type in ["select", "status"]:
            # Get available options (same structure for both types)
            options_key = "select" if prop_type == "select" else "status"
            options = status_prop.get(options_key, {}).get("options", [])
            option_names = [opt.get("name") for opt in options]
            
            # Check if the status value matches an option
            status_value = fields["status"]
            if status_value not in option_names:
                # Try case-insensitive match
                status_lower = status_value.lower()
                matched = None
                for opt_name in option_names:
                    if opt_name.lower() == status_lower:
                        matched = opt_name
                        break
                
                if matched:
                    # Use the correct property type format
                    if prop_type == "status":
                        props[PROP_STATUS] = {"status": {"name": matched}}
                    else:
                        props[PROP_STATUS] = {"select": {"name": matched}}
                else:
                    print(f"[WARNING] Status '{status_value}' not found in Notion options.")
                    print(f"[WARNING] Available options: {', '.join(option_names)}")
                    print(f"[WARNING] Skipping status update for this book.")
                    # Don't set status if it doesn't match
            else:
                # Use the correct property type format
                if prop_type == "status":
                    props[PROP_STATUS] = {"status": {"name": status_value}}
                else:
                    props[PROP_STATUS] = {"select": {"name": status_value}}

    if fields.get("current_page") is not None and prop_exists(db_props, PROP_CURRENT_PAGE):
        props[PROP_CURRENT_PAGE] = {"number": int(fields["current_page"])}

    if fields.get("total_page") is not None and prop_exists(db_props, PROP_TOTAL_PAGE):
        props[PROP_TOTAL_PAGE] = {"number": int(fields["total_page"])}

    if fields.get("started_at") and prop_exists(db_props, PROP_STARTED_AT):
        # Handle both datetime and date objects - use same format as date_finished
        started_at = fields["started_at"]
        if hasattr(started_at, 'date'):
            date_str = started_at.date().isoformat()
        elif hasattr(started_at, 'isoformat'):
            date_str = started_at.isoformat()
        else:
            date_str = str(started_at)
        props[PROP_STARTED_AT] = {"date": {"start": date_str}}

    if fields.get("last_read_at") and prop_exists(db_props, PROP_LAST_READ_AT):
        # Convert to local timezone if needed, then format as date (same as date_finished)
        last_read_at = fields["last_read_at"]
        if hasattr(last_read_at, 'astimezone'):
            # Convert to local timezone if it has timezone info
            import dateutil.tz
            if last_read_at.tzinfo is not None:
                last_read_at = last_read_at.astimezone(dateutil.tz.tzlocal())
        if hasattr(last_read_at, 'date'):
            date_str = last_read_at.date().isoformat()
        elif hasattr(last_read_at, 'isoformat'):
            date_str = last_read_at.isoformat()
        else:
            date_str = str(last_read_at)
        props[PROP_LAST_READ_AT] = {"date": {"start": date_str}}

    if fields.get("date_finished") and prop_exists(db_props, PROP_DATE_FINISHED):
        # Handle both datetime and date objects
        date_finished = fields["date_finished"]
        if hasattr(date_finished, 'date'):
            date_str = date_finished.date().isoformat()
        elif hasattr(date_finished, 'isoformat'):
            date_str = date_finished.isoformat()
        else:
            date_str = str(date_finished)
        props[PROP_DATE_FINISHED] = {"date": {"start": date_str}}

    if fields.get("source") and prop_exists(db_props, PROP_SOURCE):
        props[PROP_SOURCE] = {"multi_select": [{"name": fields["source"]}]}

    if fields.get("cover_image") and prop_exists(db_props, PROP_COVER_IMAGE):
        # Cover image as URL (files property) or rich_text
        prop_type = db_props[PROP_COVER_IMAGE].get("type")
        if prop_type == "files":
            props[PROP_COVER_IMAGE] = {"files": [{"type": "external", "name": "Cover", "external": {"url": fields["cover_image"]}}]}
        elif prop_type == "url":
            props[PROP_COVER_IMAGE] = {"url": fields["cover_image"]}
        elif prop_type == "rich_text":
            props[PROP_COVER_IMAGE] = {"rich_text": [{"text": {"content": fields["cover_image"]}}]}

    if fields.get("genre") and prop_exists(db_props, PROP_GENRE):
        prop_type = db_props[PROP_GENRE].get("type")
        if prop_type == "select":
            props[PROP_GENRE] = {"select": {"name": fields["genre"]}}
        elif prop_type == "multi_select":
            props[PROP_GENRE] = {"multi_select": [{"name": fields["genre"]}]}
        elif prop_type == "rich_text":
            props[PROP_GENRE] = {"rich_text": [{"text": {"content": fields["genre"]}}]}

    if fields.get("year_started") is not None and prop_exists(db_props, PROP_YEAR_STARTED):
        prop_type = db_props[PROP_YEAR_STARTED].get("type")
        year_value = str(int(fields["year_started"]))  # Convert to string for multi-select
        
        if prop_type == "multi_select":
            # Multi-select expects a list of objects with "name" field
            props[PROP_YEAR_STARTED] = {"multi_select": [{"name": year_value}]}
        elif prop_type == "select":
            # Single select
            props[PROP_YEAR_STARTED] = {"select": {"name": year_value}}
        elif prop_type == "number":
            props[PROP_YEAR_STARTED] = {"number": int(fields["year_started"])}
        elif prop_type == "rich_text":
            props[PROP_YEAR_STARTED] = {"rich_text": [{"text": {"content": year_value}}]}
        else:
            print(f"[WARNING] Property '{PROP_YEAR_STARTED}' is of type '{prop_type}', which is not supported. Skipping.")

    if fields.get("rating") is not None and prop_exists(db_props, PROP_RATING):
        prop_type = db_props[PROP_RATING].get("type")
        if prop_type == "number":
            props[PROP_RATING] = {"number": float(fields["rating"])}
        elif prop_type == "select":
            # Convert rating to select option (e.g., "5", "4.5", etc.)
            rating_str = str(round(float(fields["rating"]) * 2) / 2)  # Round to 0.5
            props[PROP_RATING] = {"select": {"name": rating_str}}
        elif prop_type == "rich_text":
            props[PROP_RATING] = {"rich_text": [{"text": {"content": str(fields["rating"])}}]}

    return props

def build_update_props(db_props: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    """Build properties for update only: status, last_read_at, date_finished, current_page"""
    props: Dict[str, Any] = {}

    if fields.get("status") and prop_exists(db_props, PROP_STATUS):
        status_prop = db_props[PROP_STATUS]
        prop_type = status_prop.get("type")
        
        # Handle both "select" and "status" property types
        if prop_type in ["select", "status"]:
            options_key = "select" if prop_type == "select" else "status"
            options = status_prop.get(options_key, {}).get("options", [])
            option_names = [opt.get("name") for opt in options]
            
            status_value = fields["status"]
            if status_value not in option_names:
                # Try case-insensitive match
                status_lower = status_value.lower()
                matched = None
                for opt_name in option_names:
                    if opt_name.lower() == status_lower:
                        matched = opt_name
                        break
                
                if matched:
                    if prop_type == "status":
                        props[PROP_STATUS] = {"status": {"name": matched}}
                    else:
                        props[PROP_STATUS] = {"select": {"name": matched}}
            else:
                if prop_type == "status":
                    props[PROP_STATUS] = {"status": {"name": status_value}}
                else:
                    props[PROP_STATUS] = {"select": {"name": status_value}}

    if fields.get("current_page") is not None and prop_exists(db_props, PROP_CURRENT_PAGE):
        props[PROP_CURRENT_PAGE] = {"number": int(fields["current_page"])}

    if fields.get("last_read_at") and prop_exists(db_props, PROP_LAST_READ_AT):
        # Convert to local timezone if needed, then format as date (same as date_finished)
        last_read_at = fields["last_read_at"]
        if hasattr(last_read_at, 'astimezone'):
            # Convert to local timezone if it has timezone info
            import dateutil.tz
            if last_read_at.tzinfo is not None:
                last_read_at = last_read_at.astimezone(dateutil.tz.tzlocal())
        if hasattr(last_read_at, 'date'):
            date_str = last_read_at.date().isoformat()
        elif hasattr(last_read_at, 'isoformat'):
            date_str = last_read_at.isoformat()
        else:
            date_str = str(last_read_at)
        props[PROP_LAST_READ_AT] = {"date": {"start": date_str}}

    if fields.get("date_finished") and prop_exists(db_props, PROP_DATE_FINISHED):
        # Handle both datetime and date objects
        date_finished = fields["date_finished"]
        if hasattr(date_finished, 'astimezone'):
            # Convert to local timezone if it has timezone info
            import dateutil.tz
            if date_finished.tzinfo is not None:
                date_finished = date_finished.astimezone(dateutil.tz.tzlocal())
        if hasattr(date_finished, 'date'):
            date_str = date_finished.date().isoformat()
        elif hasattr(date_finished, 'isoformat'):
            date_str = date_finished.isoformat()
        else:
            date_str = str(date_finished)
        props[PROP_DATE_FINISHED] = {"date": {"start": date_str}}

    return props

def append_review(notion: Client, page_id: str, db_props: Dict[str, Any], review_text: str) -> None:
    """Append review text to the Review property"""
    if not review_text or not prop_exists(db_props, PROP_REVIEW):
        return
    
    try:
        # Get current page to read existing review
        page = notion.pages.retrieve(page_id=page_id)
        existing_review = ""
        
        prop_type = db_props[PROP_REVIEW].get("type")
        if prop_type == "rich_text":
            # Get existing rich_text content
            if PROP_REVIEW in page.get("properties", {}):
                rich_text_array = page["properties"][PROP_REVIEW].get("rich_text", [])
                existing_review = "".join([rt.get("plain_text", "") for rt in rich_text_array])
        
        # Append new review (add separator if existing review exists)
        if existing_review:
            new_review = f"{existing_review}\n\n{review_text}"
        else:
            new_review = review_text
        
        # Update the review property
        notion.pages.update(
            page_id=page_id,
            properties={
                PROP_REVIEW: {"rich_text": [{"text": {"content": new_review}}]}
            }
        )
        print(f"[INFO] Appended review to page {page_id}")
    except Exception as e:
        print(f"[WARNING] Failed to append review: {e}")

def find_page_by_title(notion: Client, database_id: str, title: str) -> Optional[Dict[str, Any]]:
    res = notion.databases.query(
        database_id=database_id,
        filter={"property": PROP_TITLE, "title": {"equals": title}},
        page_size=10
    )
    results = res.get("results", [])
    return results[0] if results else None

def find_page_by_title_and_author(notion: Client, database_id: str, db_props: Dict[str, Any], title: str, author: str) -> Optional[Dict[str, Any]]:
    """Find a page by matching both title AND author"""
    if not title:
        return None
    
    # Build filter: title matches AND author matches
    filters = {
        "and": [
            {"property": PROP_TITLE, "title": {"equals": title}}
        ]
    }
    
    # Add author filter if author exists and property exists
    if author and prop_exists(db_props, PROP_AUTHOR):
        author_filter = {"property": PROP_AUTHOR, "rich_text": {"equals": author}}
        filters["and"].append(author_filter)
    
    try:
        res = notion.databases.query(
            database_id=database_id,
            filter=filters,
            page_size=10
        )
        results = res.get("results", [])
        return results[0] if results else None
    except Exception as e:
        print(f"[WARNING] Error finding page by title and author: {e}")
        # Fallback to title-only search
        return find_page_by_title(notion, database_id, title)

def upsert_page(notion: Client, database_id: str, db_props: Dict[str, Any], fields: Dict[str, Any]) -> str:
    title = fields.get("title", "")
    author = fields.get("author", "")
    
    # Check for duplicate by title AND author
    existing = find_page_by_title_and_author(notion, database_id, db_props, title, author)
    
    if existing:
        # Duplicate found - only update: status, last_read_at, date_finished, current_page
        print(f"[INFO] Duplicate found (title: '{title}', author: '{author}') - updating only: status, last_read_at, date_finished, current_page")
        
        # Build update props (only the fields we want to update)
        update_props = build_update_props(db_props, fields)
        
        if update_props:
            notion.pages.update(page_id=existing["id"], properties=update_props)
            print(f"[INFO] Updated page {existing['id']} with: {list(update_props.keys())}")
        
        # Append review if it exists
        if fields.get("review"):
            append_review(notion, existing["id"], db_props, fields["review"])
        
        return existing["id"]
    
    # No duplicate - create new page with all fields
    print(f"[INFO] Creating new page (title: '{title}', author: '{author}')")
    props = build_props(db_props, fields)
    created = notion.pages.create(parent={"database_id": database_id}, properties=props)
    return created["id"]


# -------------------------
# Folder parsing → fields
# -------------------------

def parse_book_folder(book_dir: Path) -> Optional[Dict[str, Any]]:
    if not book_dir.is_dir():
        return None

    md_files: List[Path] = []
    for name in CANDIDATE_FILES:
        p = book_dir / name
        if p.exists():
            md_files.append(p)

    # include any other md files
    for p in book_dir.glob("*.md"):
        if p not in md_files:
            md_files.append(p)

    if not md_files:
        return None

    title = None
    author = None
    current_page = None
    total_page = None
    percent = None
    all_dates: List[datetime] = []
    finished_hint = False

    for p in md_files:
        text = _read_text(p)

        t, a = _extract_title_author(text)
        if t and not title:
            title = t
        if a and not author:
            author = a

        c, tot, pct = _extract_progress(text)
        if c is not None and tot is not None:
            current_page, total_page = c, tot
        if pct is not None and percent is None:
            percent = pct

        all_dates.extend(_extract_dates(text))
        finished_hint = finished_hint or _looks_finished(text)

    if not title:
        title = book_dir.name.strip()
    if not author:
        author = ""

    # If only percent is found but we know total, estimate current
    if percent is not None and total_page and current_page is None:
        current_page = int(round((percent / 100.0) * total_page))

    started_at = min(all_dates) if all_dates else None
    last_read_at = max(all_dates) if all_dates else None

    has_activity = (last_read_at is not None) or (current_page is not None and current_page > 0)
    is_finished = finished_hint or (current_page is not None and total_page is not None and current_page >= total_page)

    if is_finished:
        status = STATUS_READ
    elif has_activity:
        status = STATUS_READING
    else:
        status = STATUS_TBR

    date_finished = (last_read_at or datetime.now()) if status == STATUS_READ else None

    return {
        "title": title,
        "author": author,
        "current_page": current_page,
        "total_page": total_page,
        "status": status,
        "started_at": started_at,
        "last_read_at": last_read_at,
        "date_finished": date_finished,
        "source": SOURCE_WEREAD,
    }


# -------------------------
# Watcher
# -------------------------

class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, sync_one_fn):
        self.sync_one_fn = sync_one_fn
        self._last_run = 0.0

    def on_any_event(self, event):
        if event.is_directory:
            return
        if not str(event.src_path).lower().endswith(".md"):
            return
        now = time.time()
        if now - self._last_run < DEBOUNCE_SECONDS:
            return
        self._last_run = now
        self.sync_one_fn(Path(event.src_path))

def sync_folder(notion: Client, database_id: str, db_props: Dict[str, Any], book_dir: Path):
    fields = parse_book_folder(book_dir)
    if not fields:
        return
    upsert_page(notion, database_id, db_props, fields)
    print(f"[SYNC] {fields['title']} | {fields['status']} | p={fields.get('current_page')}/{fields.get('total_page')}")

def main():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise SystemExit("Missing NOTION_TOKEN or NOTION_DATABASE_ID env vars.")
    if not WEREAD_ROOT.exists():
        raise SystemExit(f"WEREAD_ROOT does not exist: {WEREAD_ROOT}")

    notion = Client(auth=NOTION_TOKEN)
    db_props = get_db_properties(notion, NOTION_DATABASE_ID)

    # initial full sync (all book dirs)
    for d in sorted([x for x in WEREAD_ROOT.iterdir() if x.is_dir()]):
        try:
            sync_folder(notion, NOTION_DATABASE_ID, db_props, d)
        except Exception as e:
            print(f"[ERROR] {d.name}: {e}")

    print(f"[WATCH] Watching: {WEREAD_ROOT}")

    def sync_one(changed_file: Path):
        book_dir = changed_file.parent
        try:
            sync_folder(notion, NOTION_DATABASE_ID, db_props, book_dir)
        except Exception as e:
            print(f"[ERROR] {book_dir.name}: {e}")

    handler = DebouncedHandler(sync_one)
    observer = Observer()
    observer.schedule(handler, str(WEREAD_ROOT), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()

