# WeRead → Notion Sync Web Server

This web server provides an HTTP endpoint to trigger book synchronization from WeRead to Notion. You can access it from anywhere, including embedding it in Notion.

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install flask flask-cors
   ```

2. **Start the server:**
   ```bash
   python3 src/sync_web_server.py
   ```

3. **Access the server:**
   - Open http://localhost:8765 in your browser
   - Or use the endpoints programmatically

## Configuration

Add these optional settings to your `.env` file:

```bash
# Server settings
SYNC_SERVER_PORT=8765          # Port to run server on (default: 8765)
SYNC_SERVER_HOST=0.0.0.0      # Host to bind to (default: 0.0.0.0 = all interfaces)

# Optional: API key for security
SYNC_API_KEY=your-secret-key-here
```

## Endpoints

### GET `/`
Home page with instructions and status display.

### GET `/status`
Get current sync status (JSON):
```bash
curl http://localhost:8765/status
```

Response:
```json
{
  "running": false,
  "started_at": null,
  "completed_at": "2025-01-13T12:00:00",
  "progress": {
    "total": 100,
    "processed": 100,
    "synced": 95,
    "errors": 5
  },
  "message": "Sync completed successfully",
  "error": null
}
```

### GET `/sync`
Trigger a sync and show HTML page:
- Opens a page that shows sync progress
- Auto-refreshes to show status

### POST `/sync`
Trigger a sync (JSON response):
```bash
curl -X POST http://localhost:8765/sync
```

If API key is set:
```bash
curl -X POST "http://localhost:8765/sync?key=your-secret-key"
```

### GET `/health`
Health check endpoint:
```bash
curl http://localhost:8765/health
```

## Using in Notion

### Method 1: Web Bookmark/Embed

1. In Notion, create a new page or add a block
2. Type `/web` or `/embed`
3. Paste the URL: `http://your-server:8765/sync`
4. Notion will create a clickable link/embed

### Method 2: Button with Webhook

1. Create a button in Notion
2. Use a webhook service (like Zapier, Make.com, or n8n) to call:
   ```
   POST http://your-server:8765/sync
   ```

### Method 3: Status Widget

Embed the status page to see real-time sync status:
```
http://your-server:8765/status
```

## Making it Accessible from Internet

### Option 1: ngrok (Quick & Easy)

1. Install ngrok: https://ngrok.com/
2. Start your server: `python3 src/sync_web_server.py`
3. In another terminal, run:
   ```bash
   ngrok http 8765
   ```
4. Copy the ngrok URL (e.g., `https://abc123.ngrok.io`)
5. Use this URL in Notion: `https://abc123.ngrok.io/sync`

### Option 2: Deploy to Cloud

Deploy to services like:
- **Heroku**: Free tier available
- **Railway**: Free tier available
- **Render**: Free tier available
- **PythonAnywhere**: Free tier available
- **Fly.io**: Free tier available

Example for Heroku:
```bash
# Create Procfile
echo "web: python3 src/sync_web_server.py" > Procfile

# Deploy
git init
git add .
git commit -m "Add web server"
heroku create your-app-name
git push heroku main
```

### Option 3: Local Network Access

If you're on the same network:
1. Find your local IP: `ifconfig` (Mac/Linux) or `ipconfig` (Windows)
2. Use: `http://YOUR_IP:5000/sync`
3. Make sure firewall allows port 5000

## Security

### API Key Protection

If you expose the server to the internet, set an API key:

1. Add to `.env`:
   ```bash
   SYNC_API_KEY=your-very-secret-key-here
   ```

2. Use it in requests:
   ```bash
   curl -X POST "http://your-server:5000/sync?key=your-very-secret-key-here"
   ```

### Firewall

Only expose the port if necessary. For local use, bind to `127.0.0.1`:
```bash
SYNC_SERVER_HOST=127.0.0.1
```

## Running as a Service

### macOS (launchd)

Create `~/Library/LaunchAgents/com.weread.sync.server.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.weread.sync.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/path/to/push_reading_progress_to_notion/src/sync_web_server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/push_reading_progress_to_notion</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/weread-sync-server.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/weread-sync-server.error.log</string>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.weread.sync.server.plist
```

### Linux (systemd)

Create `/etc/systemd/system/weread-sync-server.service`:
```ini
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
```

Enable and start:
```bash
sudo systemctl enable weread-sync-server
sudo systemctl start weread-sync-server
```

## Troubleshooting

### Port Already in Use
Change the port in `.env`:
```bash
SYNC_SERVER_PORT=8766
```

### Can't Access from Internet
- Check firewall settings
- Use ngrok for quick testing
- Make sure `SYNC_SERVER_HOST=0.0.0.0` (not `127.0.0.1`)

### Sync Not Starting
- Check `/health` endpoint
- Verify all env vars are set (NOTION_TOKEN, NOTION_DATABASE_ID, WEREAD_COOKIES)
- Check server logs

## Example Usage

### Trigger sync from command line:
```bash
curl -X POST http://localhost:8765/sync
```

### Check status:
```bash
curl http://localhost:8765/status | jq
```

### Health check:
```bash
curl http://localhost:8765/health
```
