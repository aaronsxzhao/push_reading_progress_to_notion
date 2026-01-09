#!/usr/bin/env python3
"""
Check what status options are available in your Notion database
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
    
    status_prop_name = env("PROP_STATUS", "Status")
    
    if status_prop_name not in db_props:
        print(f"❌ Status property '{status_prop_name}' not found in database")
        print(f"Available properties: {', '.join(list(db_props.keys())[:10])}")
        return
    
    status_prop = db_props[status_prop_name]
    prop_type = status_prop.get("type")
    
    if prop_type not in ["select", "status"]:
        print(f"⚠️  Property '{status_prop_name}' is not a select/status type (it's {prop_type})")
        return
    
    # Get options based on property type
    options_key = "select" if prop_type == "select" else "status"
    options = status_prop.get(options_key, {}).get("options", [])
    
    print("=" * 60)
    print("Notion Status Options")
    print("=" * 60)
    print()
    
    if not options:
        print("⚠️  No options found in Status property")
    else:
        print(f"Found {len(options)} status options:")
        for i, opt in enumerate(options, 1):
            name = opt.get("name", "Unknown")
            color = opt.get("color", "default")
            print(f"  {i}. {name} (color: {color})")
    
    print()
    print("=" * 60)
    print("Current .env settings:")
    print("=" * 60)
    print(f'STATUS_TBR="{env("STATUS_TBR", "To Be Read")}"')
    print(f'STATUS_READING="{env("STATUS_READING", "Currently Reading")}"')
    print(f'STATUS_READ="{env("STATUS_READ", "Read")}"')
    print()
    
    # Check if they match
    option_names = [opt.get("name") for opt in options]
    tbr = env("STATUS_TBR", "To Be Read")
    reading = env("STATUS_READING", "Currently Reading")
    read = env("STATUS_READ", "Read")
    
    print("Matching check:")
    if tbr in option_names:
        print(f"  ✅ '{tbr}' found in Notion")
    else:
        print(f"  ❌ '{tbr}' NOT found in Notion")
    
    if reading in option_names:
        print(f"  ✅ '{reading}' found in Notion")
    else:
        print(f"  ❌ '{reading}' NOT found in Notion")
    
    if read in option_names:
        print(f"  ✅ '{read}' found in Notion")
    else:
        print(f"  ❌ '{read}' NOT found in Notion")
    
    print()
    print("=" * 60)
    if all(x in option_names for x in [tbr, reading, read]):
        print("✅ All status values match!")
    else:
        print("⚠️  Update your .env file to match the exact option names above")
    print("=" * 60)

if __name__ == "__main__":
    main()

