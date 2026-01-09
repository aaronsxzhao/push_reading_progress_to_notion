# Quick Start: Direct API Mode (No Obsidian!)

This mode fetches data directly from WeRead's API - no plugins or extra apps needed.

## Step 1: Get Your WeRead Cookies

1. Open [weread.qq.com](https://weread.qq.com) in Chrome/Edge
2. **Log in** to your account
3. Press **F12** → **Application** tab → **Cookies** → `https://weread.qq.com`
4. Copy these cookie values:
   - `wr_skey` (most important!)
   - `wr_vid`
   - `wr_rt`
   - `wr_localId`
5. Format as: `wr_skey=xxx; wr_vid=xxx; wr_rt=xxx; wr_localId=xxx`

**Detailed instructions:** See `scripts/get_weread_cookies.md`

## Step 2: Setup

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env file
cp .env.example .env
```

## Step 3: Configure `.env`

Edit `.env` and add:

```bash
NOTION_TOKEN=secret_your_notion_token
NOTION_DATABASE_ID=your_database_id
WEREAD_COOKIES=wr_skey=xxx; wr_vid=xxx; wr_rt=xxx
```

## Step 4: Test It

```bash
source .venv/bin/activate
set -a && source .env && set +a
python3 src/weread_notion_sync_api.py
```

You should see:
```
[API] Fetching books from WeRead API...
[API] Found X books
[SYNC] Book Title | Currently Reading | p=123/456
...
```

## Step 5: Auto-Run (Optional)

Run sync every hour automatically:

```bash
bash scripts/install_launchd_api.sh
```

Check logs:
```bash
tail -f /tmp/weread_notion_sync_api.out.log
```

## Troubleshooting

**"Missing WEREAD_COOKIES"**
- Make sure you copied ALL cookies from browser
- Format: `cookie1=value1; cookie2=value2`

**"API ERROR" or no books found**
- Cookies may have expired - get fresh ones from browser
- Make sure you're logged into weread.qq.com in browser
- Check that `wr_skey` cookie is present (most important)

**"Failed to fetch notebooks"**
- Try getting fresh cookies
- Check your internet connection
- WeRead API might be temporarily unavailable

