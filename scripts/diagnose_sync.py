#!/usr/bin/env python3
"""Read-only connectivity/data check. Never writes to Notion or reads backups."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config import env
from weread_gateway import create_weread_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    failed = False
    try:
        from notion_client import Client
        if not env("NOTION_TOKEN") or not env("NOTION_DATABASE_ID"):
            raise RuntimeError("Missing NOTION_TOKEN or NOTION_DATABASE_ID in current .env")
        db = Client(auth=env("NOTION_TOKEN")).databases.retrieve(database_id=env("NOTION_DATABASE_ID"))
        print("Notion OK; properties:", {k: v["type"] for k, v in db["properties"].items()})
    except Exception as exc:
        failed = True
        print("Notion check failed:", type(exc).__name__)
    try:
        api = create_weread_client(env("WEREAD_COOKIES"))
        _, books, _ = api.get_shelf()
        for item in books[:max(0, args.limit)]:
            info = item.get("book", item.get("bookInfo", item))
            data = api.get_single_book_data(str(info["bookId"]), item)
            if not data:
                raise RuntimeError("Missing book data")
            print(json.dumps({k: data.get(k) for k in (
                "title", "percent", "status", "last_read_at", "date_finished", "data_source"
            )}, ensure_ascii=False, default=str))
    except Exception as exc:
        failed = True
        print("WeRead check failed:", type(exc).__name__)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
