# Environment Variables Cleanup Guide

## Issues Found and Fixed

### 1. ✅ SYNC_LIMIT Issue - FIXED
The `SYNC_LIMIT=1` is now working correctly. When set to 1:
- Uses 1 worker (no parallel processing)
- Stops immediately after processing the first book
- Correctly limits the book list before processing

**If you still see 16 books being processed**, make sure:
- You're running the latest code
- The `.env` file has `SYNC_LIMIT=1` (not commented out)
- You're not running an old cached version

### 2. Unused/Unnecessary Parameters

The following parameters in your `.env` are **not needed** for API sync:

- `WEREAD_ROOT` - Only used for old Obsidian file sync, not API sync
  - **Action**: Remove if you're only using API sync

- `KINDLE_CLEAR_BLOCKS=` (empty) - Should be `true` or removed
  - **Action**: Set to `true` or remove (defaults to `true`)

- `WEREAD_CLEAR_BLOCKS=` (empty) - Should be `true` or removed
  - **Action**: Set to `true` or remove (defaults to `true`)

## Recommended .env Structure

### For Kindle Sync (Your Current Setup)

```bash
# ============================================
# REQUIRED - Core Configuration
# ============================================
NOTION_TOKEN=your_token
NOTION_DATABASE_ID=your_database_id
SYNC_SOURCE=kindle
KINDLE_COOKIES=ubid-main=xxx; at-main=xxx; x-main=xxx; session-id=xxx

# ============================================
# OPTIONAL - Testing
# ============================================
SYNC_LIMIT=1                    # Limit to 1 book for testing
KINDLE_TEST_BOOK_TITLE=         # Filter by book title
KINDLE_MAX_WORKERS=10           # Parallel workers (default: 5)

# ============================================
# OPTIONAL - Advanced
# ============================================
KINDLE_DEVICE_TOKEN=            # For detailed reading data
KINDLE_CLIPPINGS=               # Path to My Clippings.txt
KINDLE_CLEAR_BLOCKS=true        # Clear blocks on new pages

# ============================================
# OPTIONAL - Debug
# ============================================
WEREAD_DEBUG=1                  # Enable verbose output
```

### Parameters You Can Remove

If you're **only using Kindle sync** (not WeRead), you can remove:
- `WEREAD_COOKIES`
- `WEREAD_MAX_WORKERS`
- `WEREAD_TEST_BOOK_TITLE`
- `WEREAD_CLEAR_BLOCKS`
- `WEREAD_STYLES`
- `WEREAD_COLORS`
- `WEREAD_ROOT` (definitely remove - not used in API sync)

### Notion Property Names

These are **optional** - only set if your Notion database uses different property names:
- `NOTION_TITLE_PROP`
- `PROP_*` (all PROP_ variables)
- `STATUS_*` (all STATUS_ variables)

If your Notion database uses the default names, you can remove all of these.

## Clean .env Example (Minimal)

For Kindle sync with testing:

```bash
# Required
NOTION_TOKEN=your_token
NOTION_DATABASE_ID=your_database_id
SYNC_SOURCE=kindle
KINDLE_COOKIES=ubid-main=xxx; at-main=xxx; x-main=xxx; session-id=xxx

# Testing
SYNC_LIMIT=1
WEREAD_DEBUG=1
```

## Verification

To verify your `.env` is correct:

1. Check that `SYNC_LIMIT=1` is set (not commented)
2. Run: `python3 src/weread_notion_sync_api.py`
3. You should see: `[KINDLE API] Limiting to first 1 book(s) for testing (from 16 total)`
4. Only 1 book should be processed

If you still see 16 books, check:
- Is `SYNC_LIMIT` commented out? (lines starting with `#` are ignored)
- Are there multiple `SYNC_LIMIT` entries? (last one wins)
- Did you reload the environment? (restart terminal or run `source .env`)
