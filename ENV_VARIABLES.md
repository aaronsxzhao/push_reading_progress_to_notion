# Environment Variables Reference

This document lists all environment variables used by the sync system, renamed for clarity based on their usage.

## Core Configuration

### Notion Integration
- `NOTION_TOKEN` - Your Notion integration token (required)
- `NOTION_DATABASE_ID` - The ID of your Notion database (required)

### Source Selection
- `SYNC_SOURCE` - Which source to sync from: `weread` or `kindle` (default: `weread`)

## WeRead Configuration

### Authentication
- `WEREAD_COOKIES` - WeRead session cookies (required for WeRead sync)
  - Required cookies: `wr_skey`, `wr_vid`, `wr_rt`
  - Recommended: `wr_name`, `wr_localvid`, `wr_gid`, `wr_uid`

### Processing Options
- `WEREAD_MAX_WORKERS` - Number of parallel workers for WeRead sync (default: 5, max: 20)
- `WEREAD_TEST_BOOK_TITLE` - Filter to sync only books matching this title (for testing)
- `WEREAD_CLEAR_BLOCKS` - Clear existing blocks when creating new pages (default: `true`)
- `WEREAD_STYLES` - Filter highlights by style (comma-separated: 0,1,2)
- `WEREAD_COLORS` - Filter highlights by color (comma-separated: 1,2,3,4,5)

## Kindle Configuration

### Authentication
- `KINDLE_COOKIES` - Kindle session cookies (required for Kindle sync)
  - Required: `ubid-main`, `at-main`, `x-main`, `session-id`
- `KINDLE_DEVICE_TOKEN` - Device token for detailed reading data (optional)
  - Get from Network tab: `getDeviceToken?serialNumber=...&deviceType=...`
- `KINDLE_CLIPPINGS` - Path to My Clippings.txt file (alternative to cookies)

### Processing Options
- `KINDLE_MAX_WORKERS` - Number of parallel workers for Kindle sync (default: 5, max: 20)
- `KINDLE_TEST_BOOK_TITLE` - Filter to sync only books matching this title (for testing)
- `KINDLE_CLEAR_BLOCKS` - Clear existing blocks when creating new pages (default: `true`)

## General Sync Options

### Limits and Testing
- `SYNC_LIMIT` - Limit number of books to sync (for testing, default: all books)
  - Set to `1` to test with a single book
  - When set to 1, automatically uses 1 worker and stops after first book

### Web Server
- `SYNC_SERVER_PORT` - Port for web server (default: 8765)
- `SYNC_SERVER_HOST` - Host for web server (default: 0.0.0.0)
- `SYNC_API_KEY` - Optional API key for web server authentication

### Debug
- `WEREAD_DEBUG` - Enable verbose debug output (set to `1` to enable)
- `PYTHONUNBUFFERED` - Force unbuffered output (automatically set in GitHub Actions)

## Migration Guide

### Old Names → New Names

The following variables have been renamed for clarity:

**WeRead:**
- No changes needed - already descriptive

**Kindle:**
- No changes needed - already descriptive

**General:**
- `SYNC_LIMIT` - Already descriptive, no change needed

## Example .env File

```bash
# Core
NOTION_TOKEN=secret_xxx
NOTION_DATABASE_ID=xxx

# Source
SYNC_SOURCE=kindle

# WeRead (if using WeRead)
WEREAD_COOKIES=wr_skey=xxx; wr_vid=xxx; wr_rt=xxx
WEREAD_MAX_WORKERS=5

# Kindle (if using Kindle)
KINDLE_COOKIES=ubid-main=xxx; at-main=xxx; x-main=xxx; session-id=xxx
KINDLE_DEVICE_TOKEN=your-device-token
KINDLE_MAX_WORKERS=5

# Testing
SYNC_LIMIT=1
KINDLE_TEST_BOOK_TITLE=Your Book Title

# Web Server
SYNC_SERVER_PORT=8765
SYNC_API_KEY=your-api-key

# Debug
WEREAD_DEBUG=1
```
