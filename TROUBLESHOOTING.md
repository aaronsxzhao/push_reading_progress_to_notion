# Troubleshooting Guide

## Error: "Database does not contain any data sources accessible by this API bot"

This means your Notion integration doesn't have access to your database. Here's how to fix it:

### Step 1: Get Your Integration Name
1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Find your integration (the one you created for this sync)
3. Note the integration name (e.g., "WeRead Sync")

### Step 2: Share Database with Integration
1. Open your **Books & Media** database in Notion
2. Click the **"..."** (three dots) menu in the top right
3. Click **"Add connections"** or **"Connections"**
4. Search for and select your integration name
5. Click **"Confirm"** or **"Add"**

### Step 3: Verify Database ID Format
Your database ID should be:
- **32 characters** (with or without dashes)
- From the database URL: `notion.so/workspace/DATABASE_ID?v=...`
- Example: `1ca1dc1ee8db81caae86c13db917e88e` or `1ca1dc1e-e8db-81ca-ae86-c13db917e88e`

Both formats work, but if you're having issues, try:
- Removing dashes: `1ca1dc1ee8db81caae86c13db917e88e`
- Or keeping dashes: `1ca1dc1e-e8db-81ca-ae86-c13db917e88e`

### Step 4: Test Again
```bash
source .venv/bin/activate
set -a && source .env && set +a
python3 src/weread_notion_sync_api.py
```

## Error: "Missing NOTION_TOKEN or NOTION_DATABASE_ID"

Make sure your `.env` file has:
```bash
NOTION_TOKEN=secret_xxx
NOTION_DATABASE_ID=xxx
```

## Error: "Missing WEREAD_COOKIES"

1. Get cookies from browser (see `scripts/get_weread_cookies.md`)
2. Add to `.env`:
```bash
WEREAD_COOKIES=wr_skey=xxx; wr_vid=xxx; wr_rt=xxx
```

## Error: "WEREAD_ROOT does not exist"

Only needed for file watch mode. Either:
1. Set the correct path in `.env`:
```bash
WEREAD_ROOT=/path/to/your/Obsidian/WeRead
```
2. Or use API mode instead (doesn't need WEREAD_ROOT)

## WeRead API Errors

**"Failed to fetch notebooks" or "API ERROR"**
- Cookies may have expired - get fresh ones from browser
- Make sure you're logged into weread.qq.com
- Check internet connection
- Wait a few minutes and try again (rate limiting)

**"No books found"**
- Make sure you have books in your WeRead account
- Check that cookies include `wr_skey` (most important)


