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
import time
from typing import Dict, Any, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from notion_client import Client
from weread_api import WeReadAPI, env

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv not installed, skip loading .env
    pass

# Import Notion helpers from the main sync script
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Reuse config and Notion helpers
from weread_notion_sync import (
    PROP_TITLE, PROP_AUTHOR, PROP_STATUS, PROP_CURRENT_PAGE, PROP_TOTAL_PAGE,
    PROP_DATE_FINISHED, PROP_SOURCE, PROP_STARTED_AT, PROP_LAST_READ_AT,
    STATUS_TBR, STATUS_READING, STATUS_READ, SOURCE_WEREAD,
    get_db_properties, prop_exists, build_props, find_page_by_title, upsert_page
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
        emoji = "⭐"  # Background
    
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
        
        while has_more:
            response = notion.blocks.children.list(block_id=page_id)
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
    import hashlib
    block_type = block.get("type")
    content = ""
    
    if block_type == "callout":
        rich_text = block.get("callout", {}).get("rich_text", [])
        content = "".join([rt.get("text", {}).get("content", "") if isinstance(rt.get("text"), dict) else rt.get("plain_text", "") for rt in rich_text])
    elif block_type == "quote":
        rich_text = block.get("quote", {}).get("rich_text", [])
        content = "".join([rt.get("text", {}).get("content", "") if isinstance(rt.get("text"), dict) else rt.get("plain_text", "") for rt in rich_text])
    elif block_type in ["heading_1", "heading_2", "heading_3"]:
        heading_key = block_type
        rich_text = block.get(heading_key, {}).get("rich_text", [])
        content = "".join([rt.get("text", {}).get("content", "") if isinstance(rt.get("text"), dict) else rt.get("plain_text", "") for rt in rich_text])
    elif block_type == "table_of_contents":
        # Table of contents is always the same, use type as signature
        return f"table_of_contents_{block_type}"
    
    # Create signature from full content (normalized)
    if content:
        content_normalized = content.strip()
        signature = hashlib.md5(content_normalized.encode('utf-8')).hexdigest()
        return f"{block_type}_{signature}"
    
    # For blocks without content, use type and structure
    return f"{block_type}_empty"


def get_existing_blocks(notion: Client, page_id: str) -> Dict[str, str]:
    """
    Get all existing blocks from a page with their signatures and IDs.
    Returns a dict mapping signature -> block_id for deletion purposes.
    """
    existing_blocks = {}  # signature -> block_id
    
    try:
        has_more = True
        while has_more:
            response = notion.blocks.children.list(block_id=page_id)
            blocks = response.get("results", [])
            
            for block in blocks:
                block_id = block.get("id")
                # Extract content from existing block
                block_type = block.get("type")
                content = ""
                
                if block_type == "callout":
                    rich_text = block.get("callout", {}).get("rich_text", [])
                    content = "".join([rt.get("plain_text", "") for rt in rich_text])
                elif block_type == "quote":
                    rich_text = block.get("quote", {}).get("rich_text", [])
                    content = "".join([rt.get("plain_text", "") for rt in rich_text])
                elif block_type in ["heading_1", "heading_2", "heading_3"]:
                    heading_key = block_type
                    rich_text = block.get(heading_key, {}).get("rich_text", [])
                    content = "".join([rt.get("plain_text", "") for rt in rich_text])
                elif block_type == "table_of_contents":
                    signature = f"table_of_contents_{block_type}"
                    existing_blocks[signature] = block_id
                    continue
                
                # Create signature
                if content:
                    import hashlib
                    content_normalized = content.strip()
                    signature = hashlib.md5(content_normalized.encode('utf-8')).hexdigest()
                    signature = f"{block_type}_{signature}"
                    existing_blocks[signature] = block_id
            
            has_more = response.get("has_more", False)
    except Exception as e:
        print(f"[WARNING] Failed to get existing blocks: {e}")
    
    return existing_blocks


def sync_blocks_to_page(notion: Client, page_id: str, new_blocks: list, clear_existing: bool = False):
    """
    Fully sync blocks to a Notion page - adds new blocks, deletes removed blocks, keeps existing ones.
    This ensures the Notion page exactly matches the WeRead data.
    
    Args:
        notion: Notion client
        page_id: Page ID to sync blocks to
        new_blocks: List of block objects that should exist (from WeRead)
        clear_existing: If True, clear all existing blocks first (for new pages)
    
    Returns:
        Tuple of (added_count, deleted_count, kept_count)
    """
    if clear_existing:
        # For new pages, just clear and add all blocks
        clear_page_blocks(notion, page_id)
        existing_blocks = {}
    else:
        # For existing pages, get current blocks for comparison
        existing_blocks = get_existing_blocks(notion, page_id)
    
    if not new_blocks:
        # If no new blocks, delete all existing ones
        deleted_count = len(existing_blocks)
        for block_id in existing_blocks.values():
            try:
                time.sleep(0.1)  # Rate limiting
                notion.blocks.delete(block_id=block_id)
            except Exception as e:
                print(f"[WARNING] Failed to delete block {block_id}: {e}")
        return 0, deleted_count, 0
    
    # Create signatures for new blocks
    new_signatures = {}  # signature -> block
    for block in new_blocks:
        signature = get_block_signature(block)
        if signature not in new_signatures:
            new_signatures[signature] = block
    
    # Find blocks to delete (exist in Notion but not in new data)
    blocks_to_delete = []
    for signature, block_id in existing_blocks.items():
        if signature not in new_signatures:
            blocks_to_delete.append(block_id)
    
    # Find blocks to add (exist in new data but not in Notion)
    blocks_to_add = []
    for signature, block in new_signatures.items():
        if signature not in existing_blocks:
            blocks_to_add.append(block)
    
    # Count blocks that will be kept
    kept_count = len(existing_blocks) - len(blocks_to_delete)
    
    # Delete blocks that no longer exist
    deleted_count = 0
    for block_id in blocks_to_delete:
        try:
            time.sleep(0.1)  # Rate limiting
            notion.blocks.delete(block_id=block_id)
            deleted_count += 1
        except Exception as e:
            print(f"[WARNING] Failed to delete block {block_id}: {e}")
    
    # Add new blocks
    added_count = 0
    if blocks_to_add:
        # Notion API limits to 100 blocks per request
        for i in range(0, len(blocks_to_add), 100):
            time.sleep(0.3)  # Rate limiting
            chunk = blocks_to_add[i:i + 100]
            try:
                response = notion.blocks.children.append(block_id=page_id, children=chunk)
                added_count += len(response.get("results", []))
            except Exception as e:
                print(f"[ERROR] Failed to add blocks chunk {i//100 + 1}: {e}")
                # Continue with next chunk even if one fails
                continue
    
    return added_count, deleted_count, kept_count


def create_book_content_blocks(book_data: Dict[str, Any], styles: Optional[list] = None, colors: Optional[list] = None) -> list:
    """
    Create Notion blocks for book content (bookmarks, reviews, quotes, callouts)
    
    Args:
        book_data: Book data dictionary with bookmarks, reviews, chapter_info, page_notes, chapter_notes
        styles: Optional list of allowed highlight styles (filter)
        colors: Optional list of allowed highlight colors (filter)
    """
    blocks = []
    chapter_info = book_data.get("chapter_info")
    bookmarks = book_data.get("bookmarks", [])
    summary_reviews = book_data.get("summary_reviews", [])
    page_notes = book_data.get("page_notes", [])
    chapter_notes = book_data.get("chapter_notes", [])
    
    if not bookmarks and not summary_reviews and not page_notes and not chapter_notes:
        return blocks
    
    # Group bookmarks by chapter
    if chapter_info:
        # Add table of contents
        blocks.append(get_table_of_contents())
        
        # Group bookmarks by chapter
        bookmarks_by_chapter = {}
        for bookmark in bookmarks:
            chapter_uid = bookmark.get("chapterUid", 1)
            if chapter_uid not in bookmarks_by_chapter:
                bookmarks_by_chapter[chapter_uid] = []
            bookmarks_by_chapter[chapter_uid].append(bookmark)
        
        # Add chapters and their bookmarks
        for chapter_uid, chapter_bookmarks in sorted(bookmarks_by_chapter.items()):
            if chapter_uid in chapter_info:
                chapter_data = chapter_info[chapter_uid]
                chapter_title = chapter_data.get("title", f"Chapter {chapter_uid}")
                chapter_level = chapter_data.get("level", 2)
                blocks.append(get_heading(chapter_level, chapter_title))
            
            # Add bookmarks for this chapter
            for bookmark in chapter_bookmarks:
                # Apply style/color filters if provided
                if bookmark.get("reviewId") is None:
                    if styles is not None and bookmark.get("style") not in styles:
                        continue
                    if colors is not None and bookmark.get("colorStyle") not in colors:
                        continue
                
                mark_text = bookmark.get("markText", "")
                if not mark_text:
                    continue
                
                # Split long text into chunks (Notion has limits)
                for j in range(0, len(mark_text), 2000):
                    chunk = mark_text[j:j + 2000]
                    blocks.append(get_callout(
                        chunk,
                        bookmark.get("style"),
                        bookmark.get("colorStyle"),
                        bookmark.get("reviewId")
                    ))
                
                # Add abstract/quote if present
                abstract = bookmark.get("abstract")
                if abstract:
                    blocks.append(get_quote(abstract))
    else:
        # No chapter info - add bookmarks in order
        for bookmark in bookmarks:
            # Apply style/color filters if provided
            if bookmark.get("reviewId") is None:
                if styles is not None and bookmark.get("style") not in styles:
                    continue
                if colors is not None and bookmark.get("colorStyle") not in colors:
                    continue
            
            mark_text = bookmark.get("markText", "")
            if not mark_text:
                continue
            
            # Split long text into chunks
            for j in range(0, len(mark_text), 2000):
                chunk = mark_text[j:j + 2000]
                blocks.append(get_callout(
                    chunk,
                    bookmark.get("style"),
                    bookmark.get("colorStyle"),
                    bookmark.get("reviewId")
                ))
    
    # Add page notes (页面笔记)
    if page_notes:
        blocks.append(get_heading(1, "页面笔记"))
        for note in page_notes:
            content = note.get("content", "").strip()
            page = note.get("page", note.get("pageNum", "?"))
            if not content:
                continue
            
            # Create callout with page info
            page_info = f"第 {page} 页: {content}"
            for j in range(0, len(page_info), 2000):
                chunk = page_info[j:j + 2000]
                blocks.append(get_callout(chunk, None, None, None))
    
    # Add chapter notes (章节笔记)
    if chapter_notes:
        blocks.append(get_heading(1, "章节笔记"))
        for note in chapter_notes:
            content = note.get("content", "").strip()
            chapter_uid = note.get("chapterUid", "?")
            if not content:
                continue
            
            # Get chapter title if available
            chapter_title = ""
            if chapter_info and chapter_uid in chapter_info:
                chapter_title = chapter_info[chapter_uid].get("title", f"章节 {chapter_uid}")
            else:
                chapter_title = f"章节 {chapter_uid}"
            
            # Create callout with chapter info
            chapter_info_text = f"{chapter_title}: {content}"
            for j in range(0, len(chapter_info_text), 2000):
                chunk = chapter_info_text[j:j + 2000]
                blocks.append(get_callout(chunk, None, None, None))
    
    # Add summary reviews (书籍书评)
    if summary_reviews:
        blocks.append(get_heading(1, "书籍书评"))
        for review_item in summary_reviews:
            review = review_item.get("review", {})
            content = review.get("content", "")
            if not content:
                continue
            
            # Split long text into chunks
            for j in range(0, len(content), 2000):
                chunk = content[j:j + 2000]
                blocks.append(get_callout(
                    chunk,
                    review_item.get("style"),
                    review_item.get("colorStyle"),
                    review.get("reviewId")
                ))
    
    return blocks


def print_all_notes(book_data: Dict[str, Any], book_title: str):
    """
    Print summary of all types of notes from WeRead (simplified output)
    """
    bookmarks = book_data.get("bookmarks", [])
    page_notes = book_data.get("page_notes", [])
    chapter_notes = book_data.get("chapter_notes", [])
    summary_reviews = book_data.get("summary_reviews", [])
    
    total_notes = len(bookmarks) + len(page_notes) + len(chapter_notes) + len(summary_reviews)
    
    if total_notes > 0:
        print(f"   📝 Notes: {len(bookmarks)} 划线, {len(page_notes)} 页面, {len(chapter_notes)} 章节, {len(summary_reviews)} 书评")


def sync_books_from_api(notion: Client, database_id: str, db_props: Dict[str, Any], weread_cookies: str, limit: Optional[int] = None, test_book_title: Optional[str] = None):
    """Fetch books from WeRead API and sync to Notion - processes one at a time with progress monitoring"""
    import time
    start_time = time.time()
    
    print("[API] Initializing WeRead API client...")
    
    client = WeReadAPI(weread_cookies)
    
    # Validate cookies before proceeding
    print("[API] Validating cookies...")
    if not client.validate_cookies():
        print("\n❌ Cookie validation failed. Please update your cookies in .env file.")
        print("   The sync will continue but may fail with authentication errors.\n")
    
    # Get shelf data first to know total count
    print("[API] Fetching shelf data...")
    shelf_data, all_books_list, book_progress_list = client.get_shelf()
    
    total_books = shelf_data.get("bookCount", 0) or shelf_data.get("pureBookCount", 0) or len(all_books_list)
    print(f"[API] Total books in shelf: {total_books}")
    
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
        print("[ERROR] No books found!")
        return
    
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
            return  # Only return if no books found
    
    # Apply limit
    if limit is not None and limit > 0:
        all_book_items = all_book_items[:limit]
        print(f"[API] Limiting to first {limit} book(s) for testing")
    
    total_to_process = len(all_book_items)
    
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
            # Each thread gets its own session to avoid conflicts
            thread_client = WeReadAPI(weread_cookies)
            
            # Get book data (this is where the work happens)
            book_data = thread_client.get_single_book_data(book_id, book_item)
            
            if book_data:
                # Print notes summary (simplified)
                bookmarks = book_data.get("bookmarks", [])
                notes = book_data.get("notes", [])  # Highlights without thoughts
                page_notes = book_data.get("page_notes", [])
                chapter_notes = book_data.get("chapter_notes", [])
                summary_reviews = book_data.get("summary_reviews", [])
                total_notes = len(bookmarks) + len(notes) + len(page_notes) + len(chapter_notes) + len(summary_reviews)
                
                if total_notes > 0:
                    with print_lock:
                        print(f"   [{i}/{total_to_process}] 📝 Notes: {len(notes)} 纯划线, {len(bookmarks)} 划线(含想法), {len(page_notes)} 页面, {len(chapter_notes)} 章节, {len(summary_reviews)} 书评")
                
                # Map status values
                status_map = {
                    "Read": STATUS_READ,
                    "Currently Reading": STATUS_READING,
                    "To Be Read": STATUS_TBR,
                }
                book_data["status"] = status_map.get(book_data.get("status"), STATUS_TBR)
                book_data["source"] = SOURCE_WEREAD
                
                # Sync to Notion - get page ID and whether it's new
                page_id, is_new = upsert_page(notion, database_id, db_props, book_data)
                
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
                        
                        blocks = create_book_content_blocks(book_data, styles=styles, colors=colors)
                        if blocks or not is_new:  # Sync even if no blocks (to delete removed notes)
                            added_count, deleted_count, kept_count = sync_blocks_to_page(notion, page_id, blocks, clear_existing=clear_existing)
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


def main():
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
    
    # Debug: show if test_book_title is being used
    if test_book_title:
        print(f"\n[DEBUG] ⚠️  Test book title filter is ACTIVE: '{test_book_title}'")
        print(f"[DEBUG] To disable: unset WEREAD_TEST_BOOK_TITLE or comment it out in .env")
        print(f"[DEBUG] Current env value: {repr(test_book_title_raw)}\n")
    else:
        print(f"[DEBUG] Test book title filter is DISABLED (processing all books)")
    
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise SystemExit("Missing NOTION_TOKEN or NOTION_DATABASE_ID env vars.")
    if not WEREAD_COOKIES:
        raise SystemExit("Missing WEREAD_COOKIES env var. See README for how to get cookies.")
    
    notion = Client(auth=NOTION_TOKEN)
    db_props = get_db_properties(notion, NOTION_DATABASE_ID)
    
    sync_books_from_api(notion, NOTION_DATABASE_ID, db_props, WEREAD_COOKIES, limit=limit, test_book_title=test_book_title)


if __name__ == "__main__":
    main()
