# WeRead → Notion Sync

Sync your WeRead (微信读书) reading progress to Notion automatically.

## Features

- Syncs books, reading progress, and highlights to Notion
- Works from Mac, iPhone, or Notion itself
- No server required - uses GitHub Actions (free)
- Auto-refreshes cookies when they expire

## Quick Start

### 1. Install

```bash
git clone https://github.com/YOUR_USERNAME/push_reading_progress_to_notion.git
cd push_reading_progress_to_notion
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure `.env`

Edit `.env` with your values:

```bash
# Required
NOTION_TOKEN=secret_xxxxx          # From notion.so/my-integrations
NOTION_DATABASE_ID=xxxxx           # Your Notion database ID
WEREAD_COOKIES="wr_skey=xxx; wr_vid=xxx; wr_rt=xxx"  # From browser

# Optional - for iPhone/Notion trigger
GH_TOKEN=ghp_xxxxx                 # GitHub token (repo + workflow + gist scopes)
```

**Get WeRead Cookies:**
1. Open [weread.qq.com](https://weread.qq.com) and log in
2. Press F12 → Application → Cookies → weread.qq.com
3. Copy `wr_skey`, `wr_vid`, `wr_rt` values

Or run: `python scripts/fetch_cookies_auto.py`

---

## Usage

### On Mac (Local)

**One-time sync:**
```bash
source venv/bin/activate
python src/weread_notion_sync_api.py
```

**Auto-sync every hour (launchd):**
```bash
bash scripts/install_launchd_api.sh
```

**Web server (local trigger):**
```bash
python src/sync_web_server.py
# Open http://localhost:8765/trigger
```

---

### On iPhone (One-Tap Sync)

Trigger sync from anywhere using GitHub Actions - no server needed.

**Setup (one-time):**

1. **Push to GitHub:**
   ```bash
   git add . && git commit -m "Setup" && git push
   ```

2. **Add secrets** (GitHub → Settings → Secrets → Actions):
   | Secret | Value |
   |--------|-------|
   | `NOTION_TOKEN` | Your Notion token |
   | `NOTION_DATABASE_ID` | Your database ID |
   | `WEREAD_COOKIES` | Your cookies string |

3. **Enable GitHub Pages** (GitHub → Settings → Pages):
   - Source: Deploy from branch
   - Branch: `main` / `docs`

4. **Create GitHub Token:**
   - Go to: https://github.com/settings/tokens/new
   - Scopes: `repo`, `workflow`, `gist`
   - Copy the token

**Use:**

1. Open `https://YOUR_USERNAME.github.io/push_reading_progress_to_notion/`
2. Enter your GitHub token and repo name, tap Save
3. Tap **Sync Now**

**Add to Home Screen:**
1. Open the URL in Safari
2. Tap Share → Add to Home Screen
3. One-tap sync from your home screen!

---

### In Notion

Add a bookmark or link to trigger sync:

**Option 1: Link to trigger page**
```
https://YOUR_USERNAME.github.io/push_reading_progress_to_notion/
```

**Option 2: Direct GitHub Actions link**
```
https://github.com/YOUR_USERNAME/push_reading_progress_to_notion/actions
```
Click "Run workflow" to trigger manually.

---

## Auto-Refresh Cookies

WeRead cookies expire. To auto-sync refreshed cookies to GitHub Actions:

1. **Setup cookie gist:**
   ```bash
   # Add GH_TOKEN to .env first
   python scripts/setup_cookie_gist.py
   ```

2. **Add secrets to GitHub:**
   - `GH_TOKEN` - your GitHub token
   - `COOKIE_GIST_ID` - from the script output

Now when you run locally and cookies refresh, they auto-sync to the cloud.

---

## Project Structure

```
src/
  config.py                 # Shared configuration
  weread_api.py             # WeRead API client
  weread_notion_sync.py     # File watch mode (Obsidian)
  weread_notion_sync_api.py # Direct API mode
  sync_web_server.py        # Local web server

scripts/
  fetch_cookies_auto.py     # Auto-fetch cookies from browser
  setup_cookie_gist.py      # Setup cloud cookie sync
  check_cookies.py          # Validate cookies

docs/
  index.html                # Mobile trigger page (GitHub Pages)

.github/workflows/
  sync.yml                  # GitHub Actions workflow
```

---

## Endpoints (Web Server)

When running `python src/sync_web_server.py`:

| Endpoint | Description |
|----------|-------------|
| `GET /` | Home page |
| `GET /trigger` | Mobile-friendly sync button |
| `GET /sync` | Trigger sync (HTML) |
| `POST /sync` | Trigger sync (JSON) |
| `GET /status` | Sync status |
| `GET /health` | Health check |

---

---

### iOS Shortcuts (Alternative)

Create a shortcut to trigger sync without opening a browser:

1. Open **Shortcuts** app
2. Create new shortcut → Add action: **Get Contents of URL**
3. Configure:
   - URL: `https://api.github.com/repos/YOUR_USERNAME/push_reading_progress_to_notion/actions/workflows/sync.yml/dispatches`
   - Method: POST
   - Headers:
     - `Authorization`: `Bearer YOUR_GITHUB_TOKEN`
     - `Accept`: `application/vnd.github.v3+json`
   - Request Body: JSON → `{"ref": "main"}`
4. Add to Home Screen

---

## Run as Background Service

### macOS (launchd)

Auto-start web server on login:

```bash
# Create plist
cat > ~/Library/LaunchAgents/com.weread.sync.server.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.weread.sync.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>src/sync_web_server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/push_reading_progress_to_notion</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF

# Load it
launchctl load ~/Library/LaunchAgents/com.weread.sync.server.plist
```

### Linux (systemd)

```bash
sudo cat > /etc/systemd/system/weread-sync.service << 'EOF'
[Unit]
Description=WeRead to Notion Sync Server
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/push_reading_progress_to_notion
ExecStart=/usr/bin/python3 src/sync_web_server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable weread-sync
sudo systemctl start weread-sync
```

---

## Security

### API Key Protection

For public endpoints, set an API key in `.env`:

```bash
SYNC_API_KEY=your-secret-key
```

Then use: `http://localhost:8765/sync?key=your-secret-key`

### Firewall

Bind to localhost only (no external access):
```bash
SYNC_SERVER_HOST=127.0.0.1
```

### What's Protected

- `.env` is gitignored - never committed
- Use GitHub Secrets for Actions
- Cookie gist is private

---

## Troubleshooting

**Cookies expired:**
- Run `python scripts/fetch_cookies_auto.py` to refresh
- Or manually copy from browser

**Port already in use:**
```bash
lsof -i:8765 | awk 'NR>1 {print $2}' | xargs kill -9
```

**GitHub Actions fails:**
- Check Actions tab for error logs
- Verify secrets are set correctly

**"Bad credentials" on trigger page:**
- GitHub token needs `repo` and `workflow` scopes
- Token must start with `ghp_`

---

## License

MIT
