# Automatic Cookie Fetching

This script automatically fetches WeRead cookies by opening a browser, waiting for you to log in, and extracting cookies.

## Quick Start

```bash
# Install dependencies first
pip install selenium webdriver-manager playwright
playwright install chromium

# Run the automatic cookie fetcher
python3 scripts/fetch_cookies_auto.py
```

## How It Works

1. **Opens a browser** (Chrome/Chromium)
2. **Navigates to weread.qq.com**
3. **Waits for you to log in** (up to 60 seconds)
4. **Detects when you're logged in** (checks for `wr_skey` cookie)
5. **Extracts all WeRead cookies** (all cookies starting with `wr_`)
6. **Saves to `.env` file** automatically

## Requirements

### Option 1: Selenium (Default)
```bash
pip install selenium webdriver-manager
```

### Option 2: Playwright (Faster, Recommended)
```bash
pip install playwright
playwright install chromium
```

The script tries Playwright first, then falls back to Selenium.

## Usage

1. **Run the script:**
   ```bash
   python3 scripts/fetch_cookies_auto.py
   ```

2. **A browser window will open** showing weread.qq.com

3. **Log in to your WeRead account** in the browser window

4. **The script will detect when you're logged in** and extract cookies automatically

5. **Cookies are saved to `.env` file** - you're done!

## What Gets Saved

The script extracts all cookies starting with `wr_` and saves them to your `.env` file:

```env
WEREAD_COOKIES="wr_skey=xxx; wr_vid=xxx; wr_rt=xxx; wr_name=xxx; ..."
```

## Troubleshooting

### Browser doesn't open
- Make sure Chrome/Chromium is installed
- For Playwright: Run `playwright install chromium`
- For Selenium: The script will download ChromeDriver automatically

### Script times out
- Make sure you log in within 60 seconds
- Check your internet connection
- Try running the script again

### No cookies found
- Make sure you're actually logged in to WeRead
- Check that the browser shows weread.qq.com (not a login page)
- Try refreshing the page in the browser window

### Cookies saved but still getting errors
- Run `python3 scripts/check_cookies.py` to validate cookies
- Make sure the `.env` file has the correct format
- Check that cookies weren't truncated

## Comparison with Manual Method

| Method | Pros | Cons |
|--------|------|------|
| **Automatic** | ✅ No manual copying<br>✅ Less error-prone<br>✅ Gets all cookies | ❌ Requires browser automation<br>❌ Needs dependencies |
| **Manual** | ✅ No dependencies<br>✅ Works everywhere | ❌ Manual copying<br>❌ Easy to make mistakes |

## Integration with Sync Script

When cookies expire during sync, the error message will suggest using this script:

```
❌ COOKIE EXPIRATION DETECTED
🔧 SOLUTION:
   🚀 AUTOMATIC (Recommended):
      python3 scripts/fetch_cookies_auto.py
```

Just run the auto-fetch script and try syncing again!
