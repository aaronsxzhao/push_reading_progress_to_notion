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
PROP_STARTED_AT = env("PROP_STARTED_AT", "Started At")
PROP_LAST_READ_AT = env("PROP_LAST_READ_AT", "Last Read At")

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
        if status_prop.get("type") == "select":
            # Get available options
            options = status_prop.get("select", {}).get("options", [])
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
                    props[PROP_STATUS] = {"select": {"name": matched}}
                else:
                    print(f"[WARNING] Status '{status_value}' not found in Notion options.")
                    print(f"[WARNING] Available options: {', '.join(option_names)}")
                    print(f"[WARNING] Skipping status update for this book.")
                    # Don't set status if it doesn't match
            else:
                props[PROP_STATUS] = {"select": {"name": status_value}}

    if fields.get("current_page") is not None and prop_exists(db_props, PROP_CURRENT_PAGE):
        props[PROP_CURRENT_PAGE] = {"number": int(fields["current_page"])}

    if fields.get("total_page") is not None and prop_exists(db_props, PROP_TOTAL_PAGE):
        props[PROP_TOTAL_PAGE] = {"number": int(fields["total_page"])}

    if fields.get("started_at") and prop_exists(db_props, PROP_STARTED_AT):
        props[PROP_STARTED_AT] = {"date": {"start": fields["started_at"].isoformat()}}

    if fields.get("last_read_at") and prop_exists(db_props, PROP_LAST_READ_AT):
        props[PROP_LAST_READ_AT] = {"date": {"start": fields["last_read_at"].isoformat()}}

    if fields.get("date_finished") and prop_exists(db_props, PROP_DATE_FINISHED):
        props[PROP_DATE_FINISHED] = {"date": {"start": fields["date_finished"].date().isoformat()}}

    if fields.get("source") and prop_exists(db_props, PROP_SOURCE):
        props[PROP_SOURCE] = {"multi_select": [{"name": fields["source"]}]}

    return props

def find_page_by_title(notion: Client, database_id: str, title: str) -> Optional[Dict[str, Any]]:
    res = notion.databases.query(
        database_id=database_id,
        filter={"property": PROP_TITLE, "title": {"equals": title}},
        page_size=10
    )
    results = res.get("results", [])
    return results[0] if results else None

def upsert_page(notion: Client, database_id: str, db_props: Dict[str, Any], fields: Dict[str, Any]) -> str:
    title = fields["title"]
    existing = find_page_by_title(notion, database_id, title)
    props = build_props(db_props, fields)

    if existing:
        notion.pages.update(page_id=existing["id"], properties=props)
        return existing["id"]

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

