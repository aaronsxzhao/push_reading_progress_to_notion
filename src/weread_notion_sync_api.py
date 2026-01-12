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
import json
from typing import Dict, Any, Optional

from notion_client import Client
from weread_api import WeReadAPI, env

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


def add_blocks_to_page(notion: Client, page_id: str, blocks: list, clear_existing: bool = False):
    """
    Add blocks to a Notion page (handles 100 block limit per request)
    
    Args:
        notion: Notion client
        page_id: Page ID to add blocks to
        blocks: List of block objects to add
        clear_existing: If True, clear existing blocks before adding new ones
    """
    if not blocks:
        return
    
    # Clear existing blocks if requested
    if clear_existing:
        clear_page_blocks(notion, page_id)
    
    results = []
    # Notion API limits to 100 blocks per request
    for i in range(0, len(blocks), 100):
        time.sleep(0.3)  # Rate limiting
        chunk = blocks[i:i + 100]
        try:
            response = notion.blocks.children.append(block_id=page_id, children=chunk)
            results.extend(response.get("results", []))
        except Exception as e:
            print(f"[ERROR] Failed to add blocks chunk {i//100 + 1}: {e}")
            # Continue with next chunk even if one fails
            continue
    
    return results


def create_book_content_blocks(book_data: Dict[str, Any], styles: Optional[list] = None, colors: Optional[list] = None) -> list:
    """
    Create Notion blocks for book content (bookmarks, reviews, quotes, callouts)
    
    Args:
        book_data: Book data dictionary with bookmarks, reviews, chapter_info
        styles: Optional list of allowed highlight styles (filter)
        colors: Optional list of allowed highlight colors (filter)
    """
    blocks = []
    chapter_info = book_data.get("chapter_info")
    bookmarks = book_data.get("bookmarks", [])
    summary_reviews = book_data.get("summary_reviews", [])
    
    if not bookmarks and not summary_reviews:
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
    
    # Add summary reviews
    if summary_reviews:
        blocks.append(get_heading(1, "点评"))
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


def sync_books_from_api(notion: Client, database_id: str, db_props: Dict[str, Any], weread_cookies: str, limit: Optional[int] = None):
    """Fetch books from WeRead API and sync to Notion - processes one at a time with progress monitoring"""
    import time
    start_time = time.time()
    
    print("[API] Initializing WeRead API client...")
    
    client = WeReadAPI(weread_cookies)
    
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
            # Debug first book
            if len(books_map) == 1:
                print(f"[DEBUG] First book in map: bookId={book_id}")
                print(f"[DEBUG] First book info keys: {list(book_info.keys())}")
                print(f"[DEBUG] First book title: {book_info.get('title')}, author: {book_info.get('author')}")
    
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
        all_book_items.append({
            "bookId": book_id,
            "book": book_data["book"],
            "progress": progress_data.get("progress", 0),
            "updateTime": progress_data.get("updateTime"),
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
    
    # Apply limit
    if limit is not None and limit > 0:
        all_book_items = all_book_items[:limit]
        print(f"[API] Limiting to first {limit} book(s) for testing")
    
    total_to_process = len(all_book_items)
    print(f"\n{'='*60}")
    print(f"[PROGRESS] Processing {total_to_process} book(s) one at a time...")
    print(f"{'='*60}\n")
    
    synced_count = 0
    error_count = 0
    
    # Process books one at a time with immediate output
    for i, book_item in enumerate(all_book_items, 1):
        book_id = book_item.get("bookId")
        if not book_id:
            continue
        
        book_start_time = time.time()
        
        try:
            print(f"[{i}/{total_to_process}] 📖 Processing book {book_id}...")
            
            # Get book data one at a time (this is where the work happens)
            book_data = client.get_single_book_data(book_id, book_item)
            
            if book_data:
                # Print full data for first book or if limit is 1
                if i == 1 or limit == 1:
                    print("\n" + "=" * 60)
                    print(f"📖 FULL BOOK DATA (Book {i})")
                    print("=" * 60)
                    print(json.dumps(book_data, indent=2, ensure_ascii=False, default=str))
                    print("=" * 60)
                    print()
                
                # Map status values
                status_map = {
                    "Read": STATUS_READ,
                    "Currently Reading": STATUS_READING,
                    "To Be Read": STATUS_TBR,
                }
                book_data["status"] = status_map.get(book_data.get("status"), STATUS_TBR)
                book_data["source"] = SOURCE_WEREAD
                
                # Sync to Notion - get page ID
                page_id = upsert_page(notion, database_id, db_props, book_data)
                
                # Add bookmarks, reviews, quotes, and callouts as blocks
                if page_id and (book_data.get("bookmarks") or book_data.get("summary_reviews")):
                    print(f"[{i}/{total_to_process}] Adding bookmarks and reviews to page...")
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
                        
                        # Check if we should clear existing blocks (default: True to avoid duplicates)
                        clear_existing = env("WEREAD_CLEAR_BLOCKS", "true").lower() == "true"
                        
                        blocks = create_book_content_blocks(book_data, styles=styles, colors=colors)
                        if blocks:
                            add_blocks_to_page(notion, page_id, blocks, clear_existing=clear_existing)
                            print(f"[{i}/{total_to_process}] ✅ Added {len(blocks)} blocks (bookmarks/reviews)")
                    except Exception as e:
                        print(f"[{i}/{total_to_process}] ⚠️  Failed to add blocks: {e}")
                        import traceback
                        traceback.print_exc()
                
                synced_count += 1
                
                book_time = time.time() - book_start_time
                print(f"✅ [{i}/{total_to_process}] {book_data['title']} | {book_data['status']} | p={book_data.get('current_page')}/{book_data.get('total_page')} | ⏱️  {book_time:.1f}s")
            else:
                print(f"⚠️  [{i}/{total_to_process}] Book {book_id}: No data retrieved")
                error_count += 1
            
            # Stop after first book if limit is 1
            if limit == 1:
                print(f"\n[STOPPED] Processed 1 book as requested (limit=1)")
                break
                
        except Exception as e:
            error_count += 1
            book_time = time.time() - book_start_time
            print(f"❌ [{i}/{total_to_process}] Book {book_id}: {e} | ⏱️  {book_time:.1f}s")
            if limit == 1:  # Show full traceback for first book only
                import traceback
                traceback.print_exc()
        
        # Progress update every 10 books or at the end
        if (i % 10 == 0 and limit != 1) or i == total_to_process:
            elapsed = time.time() - start_time
            avg_time = elapsed / i
            remaining = (total_to_process - i) * avg_time if limit is None else 0
            print(f"\n[PROGRESS] {i}/{total_to_process} | ✅ {synced_count} synced | ❌ {error_count} errors | ⏱️  {elapsed:.1f}s elapsed")
            if remaining > 0:
                print(f"          Estimated time remaining: {remaining/60:.1f} minutes\n")
    
    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[COMPLETE] Processed {total_to_process} books | Synced: {synced_count} | Errors: {error_count}")
    print(f"          Total time: {total_time:.1f}s | Avg: {total_time/total_to_process:.1f}s per book")
    print(f"{'='*60}")


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
    
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        raise SystemExit("Missing NOTION_TOKEN or NOTION_DATABASE_ID env vars.")
    if not WEREAD_COOKIES:
        raise SystemExit("Missing WEREAD_COOKIES env var. See README for how to get cookies.")
    
    notion = Client(auth=NOTION_TOKEN)
    db_props = get_db_properties(notion, NOTION_DATABASE_ID)
    
    sync_books_from_api(notion, NOTION_DATABASE_ID, db_props, WEREAD_COOKIES, limit=limit)


if __name__ == "__main__":
    main()
