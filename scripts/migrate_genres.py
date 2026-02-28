#!/usr/bin/env python3
"""One-time migration: replace Chinese genre tags with English on all Notion pages."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import env, GENRE_MAP, PROP_GENRE
from notion_client import Client


def main():
    notion = Client(auth=env("NOTION_TOKEN"))
    db_id = env("NOTION_DATABASE_ID")

    db = notion.databases.retrieve(database_id=db_id)
    genre_prop = db["properties"].get(PROP_GENRE, {})
    if genre_prop.get("type") != "multi_select":
        print(f"[ERROR] {PROP_GENRE} is not multi_select — cannot migrate.")
        return

    print("Fetching all pages from Notion...")
    pages = []
    cursor = None
    while True:
        kwargs = {"database_id": db_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.databases.query(**kwargs)
        pages.extend(resp["results"])
        print(f"  Fetched {len(pages)} pages so far...")
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    print(f"Total pages: {len(pages)}\n")
    updated = 0
    skipped = 0

    for page in pages:
        props = page.get("properties", {})
        genre_data = props.get(PROP_GENRE, {})
        if genre_data.get("type") != "multi_select":
            continue

        current_tags = genre_data.get("multi_select", [])
        if not current_tags:
            continue

        current_names = [t["name"] for t in current_tags]
        has_chinese = any(name in GENRE_MAP for name in current_names)
        if not has_chinese:
            skipped += 1
            continue

        title = "?"
        for prop_val in props.values():
            if prop_val.get("type") == "title" and prop_val.get("title"):
                title = prop_val["title"][0].get("plain_text", "?")
                break

        seen: set[str] = set()
        new_tags: list[str] = []
        for name in current_names:
            if name in GENRE_MAP:
                for eng in GENRE_MAP[name]:
                    if eng not in seen:
                        seen.add(eng)
                        new_tags.append(eng)
            else:
                if name not in seen:
                    seen.add(name)
                    new_tags.append(name)

        if set(new_tags) == set(current_names):
            skipped += 1
            continue

        print(f"  {title}")
        print(f"    {current_names} → {new_tags}")

        time.sleep(0.3)
        notion.pages.update(
            page_id=page["id"],
            properties={
                PROP_GENRE: {"multi_select": [{"name": g} for g in new_tags]}
            },
        )
        updated += 1

    print(f"\nDone. Updated: {updated}, Skipped (already English): {skipped}")


if __name__ == "__main__":
    main()
