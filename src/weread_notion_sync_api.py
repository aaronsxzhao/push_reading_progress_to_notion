#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WeRead API -> Notion Books & Media auto-sync (Direct API mode)
Fetches data directly from WeRead API without needing Obsidian.

This script:
- Fetches all books from WeRead API using cookies
- Syncs to Notion database
- Can run on a schedule (cron/launchd) or manually

Required env vars:
  NOTION_TOKEN
  NOTION_DATABASE_ID
  WEREAD_COOKIES (your WeRead session cookies)

Optional env vars: same as weread_notion_sync.py
"""

import os
import sys
import time
import hashlib
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Force unbuffered output for real-time logs (important for GitHub Actions)
if os.environ.get("PYTHONUNBUFFERED") != "1":
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except AttributeError:
        # Python < 3.7 doesn't have reconfigure
        pass

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv not installed, skip loading .env
    pass

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from notion_client import Client
from weread_api import WeReadAPI
from weread_gateway import WeReadGateway, create_weread_client
from config import (
    env,
    PROP_TITLE, PROP_AUTHOR, PROP_STATUS, PROP_CURRENT_PAGE, PROP_TOTAL_PAGE,
    PROP_DATE_FINISHED, PROP_SOURCE, PROP_STARTED_AT, PROP_LAST_READ_AT,
    STATUS_TBR, STATUS_READING, STATUS_READ, SOURCE_WEREAD,
)

# Reuse Notion helpers
from weread_notion_sync import (
    get_db_properties, prop_exists, build_props, find_page_by_title, upsert_page, index_weread_pages
)


# Helper functions for creating Notion blocks
def get_heading(level: int, content: str) -> Dict[str, Any]:
    """Create a heading block"""
    if level == 1:
        heading = "heading_1"
    elif level == 2:
        heading = "heading_2"
    else:
        heading = "heading_3"
    return {
        "type": heading,
        heading: {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": content,
                    },
                }
            ],
            "color": "default",
            "is_toggleable": False,
        },
    }


def get_table_of_contents() -> Dict[str, Any]:
    """Create a table of contents block"""
    return {"type": "table_of_contents", "table_of_contents": {"color": "default"}}


def get_quote(content: str) -> Dict[str, Any]:
    """Create a quote block"""
    return {
        "type": "quote",
        "quote": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": content},
                }
            ],
            "color": "default",
        },
    }


def get_callout(content: str, style: Optional[int] = None, color_style: Optional[int] = None, review_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a callout block (for highlights/bookmarks)
    
    Args:
        content: The text content
        style: Highlight style (0=line, 1=background, 2=wavy)
        color_style: Color style (1=red, 2=purple, 3=blue, 4=green, 5=yellow)
        review_id: If present, indicates this is a note/review
    """
    # Set emoji based on style and review_id
    emoji = "〰️"  # Default (wavy line)
    if style == 0:
        emoji = "💡"  # Line
    elif style == 1:
        emoji = "〰️"  # Background
    
    # If reviewId is present, it's a note
    if review_id is not None:
        emoji = "✍️"  # Note
    
    # Set color based on color_style
    color = "default"
    if color_style == 1:
        color = "red"
    elif color_style == 2:
        color = "purple"
    elif color_style == 3:
        color = "blue"
    elif color_style == 4:
        color = "green"
    elif color_style == 5:
        color = "yellow"
    
    return {
        "type": "callout",
        "callout": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": content,
                    },
                }
            ],
            "icon": {"emoji": emoji},
            "color": color,
        },
    }


def clear_page_blocks(notion: Client, page_id: str):
    """Clear all blocks from a Notion page (except the page itself)"""
    try:
        # Get all blocks
        has_more = True
        block_ids = []
        
        cursor = None
        seen_cursors = set()
        while has_more:
            kwargs = {"block_id": page_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = notion.blocks.children.list(**kwargs)
            if response.get("has_more"):
                cursor = response.get("next_cursor")
                if not cursor or cursor in seen_cursors:
                    raise RuntimeError("Notion block pagination did not advance")
                seen_cursors.add(cursor)
            blocks = response.get("results", [])
            block_ids.extend([b["id"] for b in blocks])
            has_more = response.get("has_more", False)
        
        # Delete all blocks
        for block_id in block_ids:
            try:
                time.sleep(0.1)  # Rate limiting
                notion.blocks.delete(block_id=block_id)
            except Exception as e:
                print(f"[WARNING] Failed to delete block {block_id}: {e}")
        
        if block_ids:
            print(f"[INFO] Cleared {len(block_ids)} existing blocks from page")
    except Exception as e:
        print(f"[WARNING] Failed to clear blocks: {e}")


def get_block_signature(block: Dict[str, Any]) -> str:
    """
    Create a signature (hash) for a block based on its content.
    Returns a unique identifier for the block's content.
    """
    block_type = block.get("type", "unknown")
    
    # Handle special block types
    if block_type == "table_of_contents":
        return f"table_of_contents_{block_type}"
    
    # Extract content from different block types
    content = ""
    if block_type == "callout":
        rich_text = block.get("callout", {}).get("rich_text", [])
        content = _extract_text_from_rich_text(rich_text)
    elif block_type == "quote":
        rich_text = block.get("quote", {}).get("rich_text", [])
        content = _extract_text_from_rich_text(rich_text)
    elif block_type in ["heading_1", "heading_2", "heading_3"]:
        rich_text = block.get(block_type, {}).get("rich_text", [])
        content = _extract_text_from_rich_text(rich_text)
    
    # Create signature from content
    if content:
        content_normalized = content.strip()
        signature = hashlib.md5(content_normalized.encode('utf-8')).hexdigest()
        return f"{block_type}_{signature}"
    
    return f"{block_type}_empty"


def _extract_text_from_rich_text(rich_text: list) -> str:
    """Helper to extract text content from rich_text array"""
    if not rich_text:
        return ""
    
    texts = []
    for rt in rich_text:
        if isinstance(rt, dict):
            text_obj = rt.get("text", {})
            if isinstance(text_obj, dict):
                texts.append(text_obj.get("content", ""))
            else:
                texts.append(rt.get("plain_text", ""))
    return "".join(texts)


def get_existing_blocks(notion: Client, page_id: str) -> Dict[str, str]:
    """
    Get all existing blocks from a page with their signatures and IDs.
    Returns a dict mapping signature -> block_id for deletion purposes.
    """
    existing_blocks = {}  # signature -> block_id
    
    try:
        has_more = True
        cursor = None
        seen_cursors = set()
        while has_more:
            kwargs = {"block_id": page_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = notion.blocks.children.list(**kwargs)
            if response.get("has_more"):
                cursor = response.get("next_cursor")
                if not cursor or cursor in seen_cursors:
                    raise RuntimeError("Notion block pagination did not advance")
                seen_cursors.add(cursor)
            blocks = response.get("results", [])
            
            for block in blocks:
                block_id = block.get("id")
                # Extract content from existing block
                block_type = block.get("type", "unknown")
                
                if block_type == "table_of_contents":
                    signature = f"table_of_contents_{block_type}"
                    existing_blocks[signature] = block_id
                    continue
                
                # Extract text content
                content = ""
                if block_type == "callout":
                    rich_text = block.get("callout", {}).get("rich_text", [])
                    content = "".join([rt.get("plain_text", "") for rt in rich_text])
                elif block_type == "quote":
                    rich_text = block.get("quote", {}).get("rich_text", [])
                    content = "".join([rt.get("plain_text", "") for rt in rich_text])
                elif block_type in ["heading_1", "heading_2", "heading_3"]:
                    rich_text = block.get(block_type, {}).get("rich_text", [])
                    content = "".join([rt.get("plain_text", "") for rt in rich_text])
                
                # Create signature
                if content:
                    content_normalized = content.strip()
                    signature = hashlib.md5(content_normalized.encode('utf-8')).hexdigest()
                    signature = f"{block_type}_{signature}"
                    existing_blocks[signature] = block_id
            
            has_more = response.get("has_more", False)
    except Exception as e:
        raise RuntimeError("Failed to read existing Notion blocks") from e
    
    return existing_blocks


def add_children(notion: Client, page_id: str, children: list) -> list:
    """Append blocks to a page in chunks of 100 (Notion API limit). Returns result blocks."""
    results = []
    for i in range(0, len(children), 100):
        time.sleep(0.3)
        try:
            resp = notion.blocks.children.append(
                block_id=page_id, children=children[i:i + 100],
            )
            results.extend(resp.get("results", []))
        except Exception as e:
            raise RuntimeError("Failed to append Notion blocks") from e
    return results


def add_grandchildren(notion: Client, results: list, grandchild: Dict[int, Dict[str, Any]]):
    """Nest quote blocks inside callout blocks (the abstract under a note)."""
    for idx, quote_block in grandchild.items():
        if idx < len(results):
            block_id = results[idx].get("id")
            if block_id:
                time.sleep(0.3)
                try:
                    notion.blocks.children.append(block_id=block_id, children=[quote_block])
                except Exception as e:
                    print(f"[WARNING] Failed to add grandchild to block {block_id}: {e}")


def sync_blocks_to_page(
    notion: Client,
    page_id: str,
    new_blocks: list,
    grandchild: Optional[Dict[int, Dict[str, Any]]] = None,
    clear_existing: bool = False,
) -> Tuple[int, int, int]:
    """Append new notes by signature, preserving existing and user-written content.

    clear_existing remains in the signature for callers but never erases pages.
    Quotes are attached atomically as children of newly created callouts.
    """
    import copy
    existing = get_existing_blocks(notion, page_id)
    pending = {}
    existing_quotes = {}
    repaired_quotes = 0
    to_add = []
    for index, block in enumerate(new_blocks):
        signature = get_block_signature(block)
        quotes = []
        if grandchild and index in grandchild and block.get("type") == "callout":
            content = _extract_text_from_rich_text(grandchild[index]["quote"]["rich_text"])
            quotes = [get_quote(content[i:i + 2000]) for i in range(0, len(content), 2000)]
        if signature in existing:
            if quotes:
                parent_id = existing[signature]
                if parent_id not in existing_quotes:
                    existing_quotes[parent_id] = set(get_existing_blocks(notion, parent_id))
                missing = []
                for quote in quotes:
                    quote_signature = get_block_signature(quote)
                    if quote_signature not in existing_quotes[parent_id]:
                        missing.append(quote)
                        existing_quotes[parent_id].add(quote_signature)
                repaired_quotes += len(add_children(notion, parent_id, missing))
            continue
        if signature in pending:
            if quotes:
                nested = pending[signature]["callout"].setdefault("children", [])
                seen_quotes = {get_block_signature(quote) for quote in nested}
                for quote in quotes:
                    if get_block_signature(quote) not in seen_quotes:
                        nested.append(quote)
                        seen_quotes.add(get_block_signature(quote))
            continue
        block = copy.deepcopy(block)
        if quotes:
            block["callout"]["children"] = quotes
        pending[signature] = block
        to_add.append(block)
    results = add_children(notion, page_id, to_add)
    return len(results) + repaired_quotes, 0, len(existing)


def create_book_content_blocks(
    book_data: Dict[str, Any],
    styles: Optional[list] = None,
    colors: Optional[list] = None,
) -> Tuple[list, Dict[int, Dict[str, Any]]]:
    """
    Build Notion blocks for a book's highlights, notes, and reviews.

    Returns (children, grandchild) where:
      - children: flat list of blocks to append to the page
      - grandchild: {block_index: quote_block} — blocks to nest inside
        the callout at that index (the highlighted passage under a note)

    This matches the weread2notion two-pass pattern: first append children,
    then use the returned block IDs to append grandchildren.
    """
    children: list = []
    grandchild: Dict[int, Dict[str, Any]] = {}

    chapter_info = book_data.get("chapter_info")
    bookmarks = book_data.get("bookmarks", [])
    summary_reviews = book_data.get("summary_reviews", [])
    page_notes = book_data.get("page_notes", [])
    chapter_notes = book_data.get("chapter_notes", [])

    if not bookmarks and not summary_reviews and not page_notes and not chapter_notes:
        return children, grandchild

    def _add_bookmark(bookmark):
        """Add a single bookmark/note as callout, track abstract for nesting."""
        if bookmark.get("reviewId") is None:
            if styles is not None and bookmark.get("style") not in styles:
                return
            if colors is not None and bookmark.get("colorStyle") not in colors:
                return

        mark_text = bookmark.get("markText", "")
        if not mark_text:
            return

        for j in range(0, len(mark_text), 2000):
            children.append(get_callout(
                mark_text[j:j + 2000],
                bookmark.get("style"),
                bookmark.get("colorStyle"),
                bookmark.get("reviewId"),
            ))

        abstract = bookmark.get("abstract")
        if abstract:
            grandchild[len(children) - 1] = get_quote(abstract)

    if chapter_info:
        children.append(get_table_of_contents())

        by_chapter: Dict[int, list] = {}
        for bm in bookmarks:
            uid = bm.get("chapterUid") or 0
            by_chapter.setdefault(uid, []).append(bm)

        for uid in sorted(by_chapter, key=str):
            if uid in chapter_info:
                ch = chapter_info[uid]
                children.append(get_heading(ch.get("level", 2), ch.get("title", "")))
            for bm in by_chapter[uid]:
                _add_bookmark(bm)
    else:
        for bm in bookmarks:
            _add_bookmark(bm)

    if page_notes:
        children.append(get_heading(1, "页面笔记"))
        for note in page_notes:
            content = note.get("content", "").strip()
            if content:
                children.append(get_callout(content, None, None, None))

    if chapter_notes:
        children.append(get_heading(1, "章节笔记"))
        for note in chapter_notes:
            content = note.get("content", "").strip()
            uid = note.get("chapterUid")
            if not content:
                continue
            title = ""
            if chapter_info and uid in chapter_info:
                title = chapter_info[uid].get("title", f"章节 {uid}")
            else:
                title = f"章节 {uid}"
            children.append(get_callout(f"{title}: {content}", None, None, None))

    if summary_reviews:
        children.append(get_heading(1, "点评"))
        for item in summary_reviews:
            review = item.get("review", {})
            content = review.get("content", "")
            if not content:
                continue
            for j in range(0, len(content), 2000):
                children.append(get_callout(
                    content[j:j + 2000],
                    item.get("style"),
                    item.get("colorStyle"),
                    review.get("reviewId"),
                ))

    return children, grandchild


def print_all_notes(book_data: Dict[str, Any], book_title: str):
    """Print summary of all types of notes from WeRead"""
    bookmarks = book_data.get("bookmarks", [])
    page_notes = book_data.get("page_notes", [])
    chapter_notes = book_data.get("chapter_notes", [])
    summary_reviews = book_data.get("summary_reviews", [])
    
    total_notes = len(bookmarks) + len(page_notes) + len(chapter_notes) + len(summary_reviews)
    
    if total_notes > 0:
        pure_highlights = sum(1 for b in bookmarks if b.get("reviewId") is None)
        with_comments = sum(1 for b in bookmarks if b.get("reviewId") is not None)
        print(f"   📝 {pure_highlights} 划线, {with_comments} 笔记, {len(page_notes)} 页面, {len(chapter_notes)} 章节, {len(summary_reviews)} 书评")


def sync_books_from_api(notion: Client, database_id: str, db_props: Dict[str, Any], weread_cookies: str, limit: Optional[int] = None, test_book_title: Optional[str] = None):
    """Fetch books from WeRead API and sync to Notion - processes one at a time with progress monitoring"""
    import time
    start_time = time.time()
    
    print("[API] Initializing WeRead API client...")
    
    auto_refresh = (not env("GITHUB_ACTIONS") and
                    env("WEREAD_AUTO_REFRESH_COOKIES", "0").lower() in ("1", "true", "yes"))
    client = create_weread_client(weread_cookies, auto_refresh=auto_refresh)
    if isinstance(client, WeReadAPI) and not client.validate_cookies():
        # Validation may renew cookies; check the fresh session once more.
        if not client.validate_cookies():
            raise RuntimeError("WeRead authentication failed; configure WEREAD_API_KEY or refresh cookies")

    # Get shelf data first to know total count
    print("[API] Fetching shelf data...")
    shelf_data, all_books_list, book_progress_list = (
        client.get_sync_books() if isinstance(client, WeReadGateway) else client.get_shelf()
    )
    
    # Get the current (possibly refreshed) cookies for thread clients
    current_cookies = client.get_cookie_string() if isinstance(client, WeReadAPI) else ""
    
    total_books = len(all_books_list)
    print(f"[API] Total books selected from source: {total_books}")
    
    # Build a map of book_id -> book info from the 'books' field (has full info)
    books_map = {}
    for book_item in all_books_list:
        # The 'books' field structure varies - try different possible structures
        book_info = None
        book_id = None
        
        # Try different possible structures
        if "bookInfo" in book_item:
            book_info = book_item["bookInfo"]
            book_id = book_info.get("bookId")
        elif "book" in book_item:
            book_info = book_item["book"]
            book_id = book_info.get("bookId")
        elif "bookId" in book_item:
            book_id = book_item["bookId"]
            book_info = book_item
        
        if book_id and book_info:
            books_map[book_id] = {
                "book": book_info,
                "has_full_info": True
            }
    
    # Build a map of book_id -> progress from bookProgress
    progress_map = {}
    for progress_item in book_progress_list:
        book_id = progress_item.get("bookId")
        if book_id:
            progress_map[book_id] = progress_item
    
    # Combine: use books_map as base, add progress data
    all_book_items = []
    for book_id, book_data in books_map.items():
        progress_data = progress_map.get(book_id, {})
        # Include ALL progress data (chapterIdx, chapterUid, etc.) not just progress percentage
        # Also include readUpdateTime from the book item if available, or use updateTime from progress
        book_item_data = book_data["book"]
        read_update_time = None
        if isinstance(book_item_data, dict):
            read_update_time = book_item_data.get("readUpdateTime")
        if not read_update_time:
            read_update_time = progress_data.get("updateTime")
        
        all_book_items.append({
            "bookId": book_id,
            "book": book_item_data,
            "progress": progress_data.get("progress", 0),
            "updateTime": progress_data.get("updateTime"),
            "readUpdateTime": read_update_time,  # Latest read time from book_item or progress
            "chapterIdx": progress_data.get("chapterIdx"),  # Current chapter index
            "chapterUid": progress_data.get("chapterUid"),
            "chapterOffset": progress_data.get("chapterOffset"),
            "readingTime": progress_data.get("readingTime"),  # Reading time in seconds
            "has_full_info": True
        })
    
    # Add any books from progress_map that aren't in books_map (shouldn't happen, but just in case)
    for book_id, progress_data in progress_map.items():
        if book_id not in books_map:
            all_book_items.append({
                "bookId": book_id,
                "progress": progress_data.get("progress", 0),
                "updateTime": progress_data.get("updateTime"),
                "readUpdateTime": progress_data.get("updateTime"),  # Use updateTime as readUpdateTime
                "chapterIdx": progress_data.get("chapterIdx"),
                "chapterUid": progress_data.get("chapterUid"),
                "chapterOffset": progress_data.get("chapterOffset"),
                "readingTime": progress_data.get("readingTime"),
                "has_full_info": False
            })
    
    print(f"[API] Combined {len(all_book_items)} books with full info and progress data")
    
    if not all_book_items:
        raise RuntimeError("No book entries returned; sync aborted without writing to Notion")
    
    # Filter by test book title if specified (for troubleshooting)
    if test_book_title:
        original_count = len(all_book_items)
        filtered_items = []
        for book_item in all_book_items:
            book_info = book_item.get("book", {})
            title = book_info.get("title") or book_info.get("name") or ""
            # Case-insensitive partial match
            if test_book_title.lower() in title.lower():
                filtered_items.append(book_item)
                print(f"[TEST] Found matching book: '{title}' (bookId: {book_item.get('bookId')})")
        
        if filtered_items:
            all_book_items = filtered_items
            print(f"[TEST] Filtered to {len(all_book_items)} book(s) matching title '{test_book_title}' (from {original_count} total)")
        else:
            print(f"[TEST] ⚠️  No books found matching title '{test_book_title}'")
            print(f"[TEST] Available book titles (first 10):")
            for i, book_item in enumerate(all_book_items[:10], 1):
                book_info = book_item.get("book", {})
                title = book_info.get("title") or book_info.get("name") or f"Book {book_item.get('bookId')}"
                print(f"[TEST]   {i}. {title}")
            raise RuntimeError("No books matched WEREAD_TEST_BOOK_TITLE; nothing synced")
    
    # Apply limit
    if limit is not None and limit > 0:
        all_book_items = all_book_items[:limit]
        print(f"[API] Limiting to first {limit} book(s) for testing")
    
    total_to_process = len(all_book_items)
    # Read once before workers start; legacy titles can share a WeRead book ID.
    existing_by_book_id = index_weread_pages(notion, database_id, db_props)
    
    # Get max workers from env or use default (5 parallel workers)
    max_workers = int(env("WEREAD_MAX_WORKERS", "5"))
    if max_workers < 1:
        max_workers = 1
    if max_workers > 20:
        max_workers = 20  # Cap at 20 to avoid overwhelming the API
    
    print(f"\n{'='*60}")
    print(f"[PROGRESS] Processing {total_to_process} book(s) with {max_workers} parallel workers...")
    print(f"{'='*60}\n")
    
    synced_count = 0
    error_count = 0
    cookie_error_count = 0  # Track cookie-related errors
    processed_count = 0
    
    # Thread-safe printing lock
    print_lock = Lock()
    
    def process_single_book(book_item_with_index):
        """Process a single book - designed for parallel execution"""
        i, book_item = book_item_with_index
        book_id = book_item.get("bookId")
        if not book_id:
            return None
        
        book_start_time = time.time()
        result = {
            "index": i,
            "book_id": book_id,
            "success": False,
            "error": None,
            "book_data": None,
            "time": 0
        }
        
        try:
            with print_lock:
                print(f"[{i}/{total_to_process}] 📖 Processing book {book_id}...")
            
            # Create a new client instance for this thread (thread-safe)
            # Use current_cookies which may have been refreshed by main client
            # Disable auto_refresh in threads - main client handles refresh
            thread_client = create_weread_client(current_cookies, auto_refresh=False)
            
            # Get book data (this is where the work happens)
            book_data = thread_client.get_single_book_data(book_id, book_item)
            
            if book_data:
                bookmarks = book_data.get("bookmarks", [])
                page_notes = book_data.get("page_notes", [])
                chapter_notes = book_data.get("chapter_notes", [])
                summary_reviews = book_data.get("summary_reviews", [])
                total_notes = len(bookmarks) + len(page_notes) + len(chapter_notes) + len(summary_reviews)
                
                if total_notes > 0:
                    # Count pure highlights vs highlights with user comments
                    pure_highlights = sum(1 for b in bookmarks if b.get("reviewId") is None)
                    with_comments = sum(1 for b in bookmarks if b.get("reviewId") is not None)
                    with print_lock:
                        print(f"   [{i}/{total_to_process}] 📝 {pure_highlights} 划线, {with_comments} 笔记, {len(page_notes)} 页面, {len(chapter_notes)} 章节, {len(summary_reviews)} 书评")
                
                # Map status values
                status_map = {
                    "Read": STATUS_READ,
                    "Currently Reading": STATUS_READING,
                    "To Be Read": STATUS_TBR,
                }
                book_data["status"] = status_map.get(book_data.get("status"), STATUS_TBR)
                book_data["source"] = SOURCE_WEREAD
                
                # Sync to Notion - get page ID and whether it's new
                page_id, is_new = upsert_page(notion, database_id, db_props, book_data,
                                             matching_pages=existing_by_book_id.get(str(book_id), []))
                
                # Add bookmarks, reviews, quotes, and callouts as blocks
                if page_id and (book_data.get("bookmarks") or book_data.get("summary_reviews") or 
                               book_data.get("page_notes") or book_data.get("chapter_notes")):
                    with print_lock:
                        if is_new:
                            print(f"[{i}/{total_to_process}] Adding bookmarks, notes, and reviews to new page...")
                        else:
                            print(f"[{i}/{total_to_process}] Syncing blocks to existing page...")
                    
                    try:
                        # Get optional style/color filters from env vars
                        styles = None
                        colors = None
                        styles_str = env("WEREAD_STYLES")
                        colors_str = env("WEREAD_COLORS")
                        if styles_str:
                            try:
                                styles = [int(s.strip()) for s in styles_str.split(",")]
                            except:
                                pass
                        if colors_str:
                            try:
                                colors = [int(c.strip()) for c in colors_str.split(",")]
                            except:
                                pass
                        
                        # For new pages, respect WEREAD_CLEAR_BLOCKS setting
                        # For existing pages, fully sync (add new, delete removed, keep existing)
                        if is_new:
                            clear_existing = env("WEREAD_CLEAR_BLOCKS", "true").lower() == "true"
                        else:
                            clear_existing = False  # For existing pages, use full sync (not clear)
                        
                        blocks, grandchild = create_book_content_blocks(book_data, styles=styles, colors=colors)
                        if blocks or not is_new:
                            added_count, deleted_count, kept_count = sync_blocks_to_page(
                                notion, page_id, blocks,
                                grandchild=grandchild,
                                clear_existing=clear_existing,
                            )
                            with print_lock:
                                if is_new:
                                    print(f"[{i}/{total_to_process}] ✅ Added {added_count} blocks (bookmarks/reviews)")
                                else:
                                    if added_count > 0 or deleted_count > 0:
                                        print(f"[{i}/{total_to_process}] ✅ Synced blocks: +{added_count} added, -{deleted_count} deleted, {kept_count} kept")
                                    else:
                                        print(f"[{i}/{total_to_process}] ℹ️  All {kept_count} blocks up to date, no changes needed")
                    except Exception as e:
                        with print_lock:
                            print(f"[{i}/{total_to_process}] ⚠️  Failed to add blocks: {e}")
                        if limit == 1:  # Show full traceback for first book only
                            import traceback
                            traceback.print_exc()
                        raise
                
                result["success"] = True
                result["book_data"] = book_data
                result["page_id"] = page_id
            else:
                with print_lock:
                    print(f"⚠️  [{i}/{total_to_process}] Book {book_id}: No data retrieved")
                result["error"] = "No data retrieved"
            
        except Exception as e:
            error_msg = str(e)
            result["error"] = error_msg
            # Check if it's a cookie/auth error
            if "401" in error_msg or "LOGIN" in error_msg.upper() or "expired" in error_msg.lower():
                result["cookie_error"] = True
            if limit == 1:  # Show full traceback for first book only
                import traceback
                traceback.print_exc()
        
        result["time"] = time.time() - book_start_time
        return result
    
    # Process books in parallel
    book_items_with_index = [(i+1, item) for i, item in enumerate(all_book_items)]
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_book = {executor.submit(process_single_book, item): item for item in book_items_with_index}
        
        # Process results as they complete
        for future in as_completed(future_to_book):
            result = future.result()
            if result is None:
                continue
            
            processed_count += 1
            i = result["index"]
            book_id = result["book_id"]
            
            if result["success"]:
                synced_count += 1
                book_data = result["book_data"]
                book_time = result["time"]
                with print_lock:
                    print(f"✅ [{i}/{total_to_process}] {book_data['title']} | {book_data['status']} | p={book_data.get('current_page')}/{book_data.get('total_page')} | ⏱️  {book_time:.1f}s")
            else:
                error_count += 1
                if result.get("cookie_error"):
                    cookie_error_count += 1
                book_time = result["time"]
                with print_lock:
                    print(f"❌ [{i}/{total_to_process}] Book {book_id}: {result['error']} | ⏱️  {book_time:.1f}s")
            
            # Progress update every 10 books or at the end
            if (processed_count % 10 == 0 and limit != 1) or processed_count == total_to_process:
                elapsed = time.time() - start_time
                rate = processed_count / elapsed if elapsed > 0 else 0
                remaining = total_to_process - processed_count
                eta = remaining / rate if rate > 0 else 0
                with print_lock:
                    print(f"\n[PROGRESS] {processed_count}/{total_to_process} books processed | "
                          f"✅ {synced_count} synced | ❌ {error_count} errors | "
                          f"⏱️  {elapsed:.1f}s elapsed | 📊 {rate:.1f} books/s | "
                          f"⏳ ~{eta:.0f}s remaining\n")
            
            # Stop after first book if limit is 1
            if limit == 1 and processed_count >= 1:
                # Cancel remaining tasks
                for future in future_to_book:
                    future.cancel()
                break
    
    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[COMPLETE] Processed {total_to_process} books | Synced: {synced_count} | Errors: {error_count}")
    if cookie_error_count > 0:
        print(f"          ⚠️  Cookie/Auth Errors: {cookie_error_count}")
    if total_to_process > 0:
        print(f"          Total time: {total_time:.1f}s | Avg: {total_time/total_to_process:.1f}s per book")
    else:
        print(f"          Total time: {total_time:.1f}s")
    print(f"{'='*60}")
    
    # Show cookie error summary if any occurred
    if cookie_error_count > 0:
        print(f"\n{'='*80}")
        print(f"⚠️  COOKIE EXPIRATION DETECTED")
        print(f"{'='*80}")
        print(f"   {cookie_error_count} API call(s) failed due to authentication errors (401/LOGIN ERR)")
        print(f"\n   🔧 ACTION REQUIRED:")
        print(f"      1. Open https://weread.qq.com in your browser")
        print(f"      2. Make sure you're logged in")
        print(f"      3. Get fresh cookies (see scripts/get_weread_cookies.md)")
        print(f"      4. Update WEREAD_COOKIES in your .env file")
        print(f"      5. Required cookies: wr_skey, wr_vid, wr_rt")
        print(f"      6. Optional but recommended: wr_localvid, wr_gid")
        print(f"\n   💡 TIP: Check your .env file - make sure cookies are complete and not truncated")
        print(f"{'='*80}\n")

    if error_count:
        raise RuntimeError(f"Sync incomplete: {synced_count} synced, {error_count} failed")
    return {"synced": synced_count, "errors": error_count}


def main():
    # Check if user wants to start web server
    if len(sys.argv) > 1 and sys.argv[1] in ("--server", "-s", "server"):
        print("Starting web server...")
        try:
            from sync_web_server import app
            port = int(env("SYNC_SERVER_PORT", "8765"))
            host = env("SYNC_SERVER_HOST", "0.0.0.0")
            print(f"Server starting on http://{host}:{port}")
            app.run(host=host, port=port, debug=False)
        except ImportError as e:
            print(f"❌ Failed to import web server: {e}")
            print("   Make sure Flask is installed: pip install flask flask-cors")
            sys.exit(1)
        return
    
    NOTION_TOKEN = env("NOTION_TOKEN")
    NOTION_DATABASE_ID = env("NOTION_DATABASE_ID")
    WEREAD_COOKIES = env("WEREAD_COOKIES")
    
    # Optional limit for testing (set SYNC_LIMIT in .env, default: None = all books)
    sync_limit = env("SYNC_LIMIT")
    limit = None
    if sync_limit:
        try:
            limit = int(sync_limit)
            if limit <= 0:
                limit = None
        except ValueError:
            limit = None
    
    # Optional test book title for troubleshooting (set WEREAD_TEST_BOOK_TITLE in .env)
    # Example: WEREAD_TEST_BOOK_TITLE=被讨厌的勇气
    # To disable: comment out the line in .env, unset the variable, or set it to empty
    test_book_title_raw = os.environ.get("WEREAD_TEST_BOOK_TITLE")
    test_book_title = None
    
    # Check if it's set and not empty
    if test_book_title_raw:
        test_book_title = str(test_book_title_raw).strip()
        # Treat empty string, "none", "null", "false" as disabled
        if not test_book_title or test_book_title.lower() in ("none", "null", "false", "off", "disable", "0"):
            test_book_title = None
        else:
            # If it's set, check if it's commented in .env file
            env_file = Path(__file__).parent.parent / ".env"
            if env_file.exists():
                with open(env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        # Check if line is commented out
                        if stripped.startswith('#') and 'WEREAD_TEST_BOOK_TITLE' in stripped:
                            print(f"\n[WARNING] WEREAD_TEST_BOOK_TITLE is set in environment but commented in .env")
                            print(f"[WARNING] Unsetting it to disable the filter...")
                            os.environ.pop("WEREAD_TEST_BOOK_TITLE", None)
                            test_book_title = None
                            break
    
    # Show test book title status only if set (to avoid clutter)
    if test_book_title:
        print(f"\n[INFO] ⚠️  Test book title filter ACTIVE: '{test_book_title}'")
        print(f"[INFO] To disable: unset WEREAD_TEST_BOOK_TITLE or comment it out in .env\n")
    
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise SystemExit("Missing NOTION_TOKEN or NOTION_DATABASE_ID env vars.")
    if not WEREAD_COOKIES and not env("WEREAD_API_KEY"):
        raise SystemExit("Missing WEREAD_API_KEY (recommended) or WEREAD_COOKIES")
    
    notion = Client(auth=NOTION_TOKEN)
    db_props = get_db_properties(notion, NOTION_DATABASE_ID)
    db_props = ensure_sync_properties(notion, NOTION_DATABASE_ID, db_props)
    
    sync_books_from_api(notion, NOTION_DATABASE_ID, db_props, WEREAD_COOKIES, limit=limit, test_book_title=test_book_title)


def ensure_sync_properties(notion, database_id, db_props):
    required = {"Start Date Source": "rich_text", "Current Chapter": "rich_text", "Total Words": "number"}
    additions = {}
    for name, kind in required.items():
        if name not in db_props:
            additions[name] = {kind: {}}
        elif db_props[name].get("type") != kind:
            raise ValueError(f"Notion property {name!r} must have type {kind}; existing property left unchanged")
    if additions:
        notion.databases.update(database_id=database_id, properties=additions)
        return get_db_properties(notion, database_id)
    return db_props


if __name__ == "__main__":
    main()
