# Kindle Book Sync Setup

This guide explains how to sync your Kindle books to Notion using the same flow and logic as WeRead.

## Overview

The Kindle sync supports two data sources:
1. **Kindle Cloud Reader API** (requires cookies from read.amazon.com)
2. **My Clippings.txt file** (exported from your Kindle device)

## Option 1: Using Kindle Cloud Reader API

### Step 1: Get Your Kindle Cookies

1. Open https://read.amazon.com in your browser
2. Log in to your Amazon account
3. Press F12 to open Developer Tools
4. Go to **Application** tab → **Cookies** → **read.amazon.com**
5. Copy the following cookies (based on [kindle-api project](https://github.com/Xetera/kindle-api)):
   - `ubid-main` (required)
   - `at-main` (required)
   - `x-main` (required)
   - `session-id` (required)

### Step 2: Configure Environment Variables

Add to your `.env` file:

```bash
# Set source to Kindle
SYNC_SOURCE=kindle

# Kindle cookies (from read.amazon.com) - based on kindle-api project
# Required: ubid-main, at-main, x-main, session-id
KINDLE_COOKIES=ubid-main=xxx; at-main=xxx; x-main=xxx; session-id=xxx

# Optional: Device token for detailed reading data (from getDeviceToken request)
# Get from Network tab: getDeviceToken?serialNumber=...&deviceType=...
KINDLE_DEVICE_TOKEN=your-device-token-here

# Optional: Test with a specific book
KINDLE_TEST_BOOK_TITLE=Your Book Title

# Optional: Limit number of books to sync (for testing)
SYNC_LIMIT=5

# Optional: Number of parallel workers (default: 5)
KINDLE_MAX_WORKERS=5
```

## Reading Data

The Kindle API can fetch detailed reading data including:
- Reading progress percentage
- Last read date
- Reading time
- Current location/page
- Total locations/pages

**Note:** For the most detailed reading data, you may need to provide a `KINDLE_DEVICE_TOKEN`. Without it, you'll still get basic progress from the library search endpoint.

## Option 2: Using My Clippings.txt File

### Step 1: Export My Clippings.txt

1. Connect your Kindle device to your computer
2. Navigate to the Kindle drive
3. Copy the `My Clippings.txt` file to your project directory

### Step 2: Configure Environment Variables

Add to your `.env` file:

```bash
# Set source to Kindle
SYNC_SOURCE=kindle

# Path to My Clippings.txt file
KINDLE_CLIPPINGS=/path/to/My Clippings.txt

# Optional: Test with a specific book
KINDLE_TEST_BOOK_TITLE=Your Book Title
```

## Running the Sync

### Command Line

```bash
# Sync from Kindle Cloud Reader
python3 src/weread_notion_sync_api.py

# Or sync from My Clippings.txt
# (Make sure KINDLE_CLIPPINGS is set in .env)
python3 src/weread_notion_sync_api.py
```

### Using Web Server

The web server automatically detects the source based on `SYNC_SOURCE`:

```bash
# Start server
python3 src/weread_notion_sync_api.py --server

# Trigger sync via HTTP
curl -X POST http://localhost:8765/sync
```

## Data Mapping

The Kindle sync maps data to Notion properties:

- **Title**: Book title
- **Author**: Book author
- **Status**: "Read", "Currently Reading", or "To Be Read"
- **Current Page**: Calculated from reading progress
- **Total Page**: Estimated from book locations or page count
- **Date Started**: First read date
- **Last Read At**: Most recent reading date
- **Source**: "Kindle"
- **Highlights**: All highlights/bookmarks from the book

## Notes

- Kindle Cloud Reader API may have rate limits
- My Clippings.txt parsing is more reliable but requires manual export
- Progress calculation is estimated (Kindle uses "locations" instead of pages)
- Highlights are synced as Notion callout blocks

## Troubleshooting

### Cookie Expiration

If you see authentication errors:
1. Re-login to read.amazon.com
2. Get fresh cookies
3. Update `KINDLE_COOKIES` in `.env`

### No Books Found

- Check that you're logged in to read.amazon.com
- Verify cookies are correctly formatted (semicolon-separated)
- For My Clippings.txt: ensure the file path is correct and the file is readable

### Missing Highlights

- Kindle Cloud Reader API may not return all highlights
- Try using My Clippings.txt for complete highlight data
- Check that the book has highlights in your Kindle library
