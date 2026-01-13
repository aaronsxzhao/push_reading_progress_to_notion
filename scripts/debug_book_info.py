#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Debug script to output all book information for a specific book
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.weread_api import WeReadAPI, env

def print_section(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    from datetime import datetime
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def print_json(data, title: str = ""):
    if title:
        print(f"\n{title}:")
    try:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=json_serial))
    except Exception as e:
        print(f"Error serializing: {e}")
        print(f"Type: {type(data)}")
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"  {k}: {type(v).__name__}")

def main():
    book_title = "张一鸣管理日志"
    
    print_section(f"Debugging Book: {book_title}")
    
    # Load cookies
    weread_cookies = env("WEREAD_COOKIES")
    if not weread_cookies:
        print("❌ WEREAD_COOKIES not found in environment")
        return
    
    # Initialize API client
    print("\n[1] Initializing WeRead API client...")
    client = WeReadAPI(weread_cookies)
    
    # Get shelf data
    print("\n[2] Fetching shelf data...")
    shelf_data, all_books_list, book_progress_list = client.get_shelf()
    
    # Find the book
    print(f"\n[3] Searching for book: {book_title}")
    target_book_item = None
    target_book_id = None
    
    for book_item in all_books_list:
        book_info = None
        if "bookInfo" in book_item:
            book_info = book_item["bookInfo"]
        elif "book" in book_item:
            book_info = book_item["book"]
        elif "bookId" in book_item:
            book_info = book_item
        
        if book_info:
            title = book_info.get("title") or book_info.get("name", "")
            if book_title in title or title in book_title:
                target_book_item = book_item
                target_book_id = book_info.get("bookId")
                print(f"   ✅ Found book: {title} (ID: {target_book_id})")
                break
    
    if not target_book_id:
        print(f"   ❌ Book '{book_title}' not found in shelf")
        print(f"\n   Available books:")
        for i, book_item in enumerate(all_books_list[:10], 1):
            book_info = None
            if "bookInfo" in book_item:
                book_info = book_item["bookInfo"]
            elif "book" in book_item:
                book_info = book_item["book"]
            elif "bookId" in book_item:
                book_info = book_item
            if book_info:
                title = book_info.get("title") or book_info.get("name", "Unknown")
                print(f"      {i}. {title}")
        return
    
    # Print raw book_item from shelf
    print_section("Raw book_item from shelf API")
    print_json(target_book_item, "book_item")
    
    # Get book detail
    print_section("Book Detail API")
    book_detail = client.get_book_detail(target_book_id)
    print_json(book_detail, "book_detail")
    
    # Get reading data
    print_section("Reading Data API")
    reading_data = client.get_reading_data(target_book_id)
    print_json(reading_data, "reading_data")
    
    # Get read info
    print_section("Read Info API")
    read_info = client.get_read_info(target_book_id)
    print_json(read_info, "read_info")
    
    # Get chapter info
    print_section("Chapter Info API")
    chapter_info = client.get_chapter_info(target_book_id)
    print_json(chapter_info, "chapter_info")
    
    # Get bookmarks
    print_section("Bookmark List API")
    bookmark_list = client.get_bookmark_list(target_book_id)
    print_json(bookmark_list, "bookmark_list")
    
    # Get notes (highlights without thoughts)
    print_section("Note List API")
    note_list = client.get_note_list(target_book_id)
    print_json(note_list, "note_list")
    
    # Get reviews
    print_section("Review List API")
    summary_reviews, regular_reviews, page_notes, chapter_notes = client.get_review_list(target_book_id)
    print_json(summary_reviews, "summary_reviews")
    print_json(regular_reviews, "regular_reviews")
    print_json(page_notes, "page_notes")
    print_json(chapter_notes, "chapter_notes")
    
    # Get processed book data
    print_section("Processed Book Data (get_single_book_data)")
    book_data = client.get_single_book_data(target_book_id, target_book_item)
    print_json(book_data, "final_book_data")
    
    # Print summary
    print_section("Summary")
    if book_data:
        print(f"Title: {book_data.get('title')}")
        print(f"Author: {book_data.get('author')}")
        print(f"Status: {book_data.get('status')}")
        print(f"Current Page: {book_data.get('current_page')}")
        print(f"Total Page: {book_data.get('total_page')}")
        percent = book_data.get('percent')
        print(f"Progress: {percent}%" if percent is not None else "Progress: None%")
        print(f"Started At: {book_data.get('started_at')}")
        print(f"Last Read At: {book_data.get('last_read_at')}")
        print(f"Date Finished: {book_data.get('date_finished')}")
        print(f"Bookmarks: {len(book_data.get('bookmarks', []))}")
        print(f"Notes (纯划线): {len(book_data.get('notes', []))}")
        print(f"Page Notes: {len(book_data.get('page_notes', []))}")
        print(f"Chapter Notes: {len(book_data.get('chapter_notes', []))}")
        print(f"Summary Reviews: {len(book_data.get('summary_reviews', []))}")
    
    print("\n" + "=" * 80)
    print("Debug complete!")
    print("=" * 80)

if __name__ == "__main__":
    main()
