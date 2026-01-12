#!/usr/bin/env python3
"""
Helper script to check what properties exist in your Notion database
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from notion_client import Client
from weread_notion_sync import env, get_db_properties

def main():
    NOTION_TOKEN = env("NOTION_TOKEN")
    NOTION_DATABASE_ID = env("NOTION_DATABASE_ID")
    
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("❌ Missing NOTION_TOKEN or NOTION_DATABASE_ID in .env")
        return
    
    notion = Client(auth=NOTION_TOKEN)
    db_props = get_db_properties(notion, NOTION_DATABASE_ID)
    
    print("=" * 60)
    print("Notion Database Properties")
    print("=" * 60)
    print()
    
    title_props = []
    for prop_name, prop_info in db_props.items():
        prop_type = prop_info.get("type", "unknown")
        print(f"  {prop_name}: {prop_type}")
        if prop_type == "title":
            title_props.append(prop_name)
    
    print()
    print("=" * 60)
    if title_props:
        print(f"✅ Title property found: {title_props[0]}")
        print()
        print(f"Set in your .env file:")
        print(f'NOTION_TITLE_PROP="{title_props[0]}"')
    else:
        print("⚠️  No title property found!")
        print("   Your database needs a title property (the first column)")
    print("=" * 60)

if __name__ == "__main__":
    main()



