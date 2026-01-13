# Webhook Setup - Trigger Sync Without Persistent Server

This guide shows you how to trigger syncs on-demand via URL/button without keeping a server running.

## Option 1: Use Webhook Services (Recommended)

### Using Zapier / Make.com / n8n

1. **Create a webhook trigger** in your automation service
2. **Set the webhook URL** to call your sync script
3. **Add a button/link** in Notion that triggers the webhook

#### For Zapier/Make.com:
- Create a webhook → HTTP Request action
- Method: POST
- URL: Your webhook endpoint (see options below)

### Using ngrok (Quick & Easy)

1. **Start the webhook server:**
   ```bash
   python3 webhook_server.py
   ```

2. **In another terminal, start ngrok:**
   ```bash
   ngrok http 8765
   ```

3. **Copy the ngrok URL** (e.g., `https://abc123.ngrok.io`)

4. **Use in your automation:**
   - Webhook URL: `https://abc123.ngrok.io/sync`
   - Method: GET or POST

5. **Create a button in Notion** that calls this URL

## Option 2: macOS Shortcuts (No Server Needed!)

### Create a Shortcut

1. Open **Shortcuts** app on macOS
2. Create a new shortcut
3. Add action: **Run Shell Script**
4. Script:
   ```bash
   cd /path/to/push_reading_progress_to_notion
   source .venv/bin/activate
   python3 webhook_sync.py
   ```

5. **Save** the shortcut (e.g., "Sync WeRead Books")

6. **Make it accessible via URL:**
   - Right-click shortcut → **Copy Link**
   - Or use: `shortcuts://run-shortcut?name=Sync%20WeRead%20Books`

7. **In Notion**, create a link to this URL

### Alternative: Use Shortcuts URL Scheme

Create a link in Notion:
```
shortcuts://run-shortcut?name=Sync%20WeRead%20Books
```

## Option 3: Serverless Function (Cloud)

### Deploy to Vercel / Netlify / Railway

1. **Create a serverless function** that calls `webhook_sync.py`
2. **Deploy** to your platform
3. **Get the function URL**
4. **Use in Notion** or automation services

Example for Vercel (`api/sync.py`):
```python
from webhook_sync import run_sync

def handler(request):
    try:
        run_sync()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
```

## Option 4: IFTTT / Apple Shortcuts Webhook

### IFTTT

1. Create an applet: **Button Widget** → **Webhook**
2. URL: Your webhook endpoint
3. Method: POST
4. Add button to your phone/widget

### Apple Shortcuts (iOS)

1. Create shortcut: **Get Contents of URL**
2. URL: Your webhook endpoint
3. Add to home screen or widget

## Option 5: Simple HTTP Trigger Script

Create a simple script that can be called via HTTP:

```bash
#!/bin/bash
# trigger_sync.sh
cd /path/to/push_reading_progress_to_notion
source .venv/bin/activate
python3 webhook_sync.py
```

Then use a service like:
- **cron-job.org** - Schedule HTTP requests
- **Uptime Robot** - Monitor and trigger
- **Zapier** - Trigger on events

## Recommended Setup for Notion

### Method 1: Zapier + ngrok

1. **Start webhook server:**
   ```bash
   python3 webhook_server.py
   ```

2. **Start ngrok:**
   ```bash
   ngrok http 8765
   ```

3. **In Zapier:**
   - Create Zap: **Button Click** → **Webhook by Zapier**
   - URL: `https://your-ngrok-url.ngrok.io/sync`
   - Method: POST

4. **In Notion:**
   - Add Zapier integration
   - Create button that triggers the Zap

### Method 2: macOS Shortcuts (Simplest!)

1. **Create Shortcut** (see Option 2 above)
2. **In Notion**, add a link:
   ```
   shortcuts://run-shortcut?name=Sync%20WeRead%20Books
   ```

3. **Click the link** → Sync runs automatically!

## Security

If exposing to internet, add API key:

1. **Set in `.env`:**
   ```bash
   SYNC_API_KEY=your-secret-key
   ```

2. **Use in webhook URL:**
   ```
   https://your-url/sync?key=your-secret-key
   ```

## Testing

Test your webhook:
```bash
# Direct call
curl -X POST http://localhost:8765/sync

# With API key
curl -X POST "http://localhost:8765/sync?key=your-key"
```

## Troubleshooting

### Webhook not triggering
- Check if server is running (for webhook_server.py)
- Verify URL is correct
- Check firewall/port settings

### Sync not running
- Check `.env` file has all required variables
- Test sync manually: `python3 webhook_sync.py`
- Check logs for errors

### macOS Shortcuts not working
- Make sure Shortcuts app has necessary permissions
- Test shortcut manually first
- Check file paths are correct
