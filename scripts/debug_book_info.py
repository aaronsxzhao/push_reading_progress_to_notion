#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Debug script to output all book information for a specific book.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from weread_api import WeReadAPI
from config import env


def json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def print_section(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_json(data, title: str = ""):
    if title:
        print(f"\n{title}:")
    try:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=json_serial))
    except Exception as e:
        print(f"Error serializing: {e}")


def main():
    book_title = sys.argv[1] if len(sys.argv) > 1 else "张一鸣管理日志"

    weread_cookies = env("WEREAD_COOKIES")
    if not weread_cookies:
        print("WEREAD_COOKIES not found in environment")
        return

    client = WeReadAPI(weread_cookies)

    print_section(f"Searching shelf for: {book_title}")
    shelf_data, all_books_list, book_progress_list = client.get_shelf()

    target_book_item = None
    target_book_id = None

    for book_item in all_books_list:
        info = book_item.get("book") or book_item.get("bookInfo") or book_item
        title = info.get("title", "")
        if book_title in title or title in book_title:
            target_book_item = book_item
            target_book_id = info.get("bookId")
            print(f"Found: {title} (ID: {target_book_id})")
            break

    if not target_book_id:
        print(f"Book '{book_title}' not found. Available:")
        for i, item in enumerate(all_books_list[:10], 1):
            info = item.get("book") or item.get("bookInfo") or item
            print(f"  {i}. {info.get('title', '?')}")
        return

    print_section("Shelf entry")
    print_json(target_book_item)

    print_section("GET /web/book/info")
    print_json(client.get_book_info(target_book_id))

    print_section("GET /web/book/readinfo")
    print_json(client.get_read_info(target_book_id))

    print_section("GET /web/book/bookmarklist")
    print_json(client.get_bookmark_list(target_book_id))

    print_section("GET /web/review/list")
    s, r, p, c = client.get_review_list(target_book_id)
    print_json({"summary": s, "regular": r, "page": p, "chapter": c})

    print_section("POST /web/book/chapterInfos")
    print_json(client.get_chapter_info(target_book_id))

    print_section("Processed (get_single_book_data)")
    book_data = client.get_single_book_data(target_book_id, target_book_item)
    print_json(book_data)

    if book_data:
        print_section("Summary")
        pure = sum(1 for b in book_data.get("bookmarks", []) if b.get("reviewId") is None)
        notes = sum(1 for b in book_data.get("bookmarks", []) if b.get("reviewId") is not None)
        print(f"Title:    {book_data['title']}")
        print(f"Author:   {book_data['author']}")
        print(f"Status:   {book_data['status']}")
        print(f"Pages:    {book_data.get('current_page')}/{book_data.get('total_page')}")
        print(f"Progress: {book_data.get('percent')}%")
        print(f"Highlights (划线):  {pure}")
        print(f"Notes (笔记):       {notes}")
        print(f"Page notes:         {len(book_data.get('page_notes', []))}")
        print(f"Chapter notes:      {len(book_data.get('chapter_notes', []))}")
        print(f"Book reviews:       {len(book_data.get('summary_reviews', []))}")


if __name__ == "__main__":
    main()
