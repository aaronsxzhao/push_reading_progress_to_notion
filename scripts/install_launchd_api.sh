#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.aaron.weread.notion.sync.api.plist"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
SCRIPT_PATH="$PROJECT_DIR/src/weread_notion_sync_api.py"
ENV_FILE="$PROJECT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env at: $ENV_FILE"
  echo "Create it: cp .env.example .env  && edit .env"
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing venv python at: $PYTHON_BIN"
  echo "Create venv: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# Load .env values into shell
set -a
source "$ENV_FILE"
set +a

# Basic checks
: "${NOTION_TOKEN:?NOTION_TOKEN missing}"
: "${NOTION_DATABASE_ID:?NOTION_DATABASE_ID missing}"
: "${WEREAD_COOKIES:?WEREAD_COOKIES missing}"

# Default: run every hour (3600 seconds)
INTERVAL=${SYNC_INTERVAL:-3600}

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.aaron.weread.notion.sync.api</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$SCRIPT_PATH</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>NOTION_TOKEN</key><string>${NOTION_TOKEN}</string>
    <key>NOTION_DATABASE_ID</key><string>${NOTION_DATABASE_ID}</string>
    <key>WEREAD_COOKIES</key><string>${WEREAD_COOKIES}</string>

    <key>NOTION_TITLE_PROP</key><string>${NOTION_TITLE_PROP:-Name}</string>
    <key>PROP_AUTHOR</key><string>${PROP_AUTHOR:-Author}</string>
    <key>PROP_STATUS</key><string>${PROP_STATUS:-Status}</string>
    <key>PROP_CURRENT_PAGE</key><string>${PROP_CURRENT_PAGE:-Current Page}</string>
    <key>PROP_TOTAL_PAGE</key><string>${PROP_TOTAL_PAGE:-Total Page}</string>
    <key>PROP_DATE_FINISHED</key><string>${PROP_DATE_FINISHED:-Date Finished}</string>
    <key>PROP_SOURCE</key><string>${PROP_SOURCE:-Source}</string>
    <key>PROP_STARTED_AT</key><string>${PROP_STARTED_AT:-Started At}</string>
    <key>PROP_LAST_READ_AT</key><string>${PROP_LAST_READ_AT:-Last Read At}</string>

    <key>STATUS_TBR</key><string>${STATUS_TBR:-To Be Read}</string>
    <key>STATUS_READING</key><string>${STATUS_READING:-Currently Reading}</string>
    <key>STATUS_READ</key><string>${STATUS_READ:-Read}</string>

    <key>SOURCE_WEREAD</key><string>${SOURCE_WEREAD:-WeRead}</string>
  </dict>

  <key>StartInterval</key>
  <integer>${INTERVAL}</integer>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/tmp/weread_notion_sync_api.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/weread_notion_sync_api.err.log</string>
</dict>
</plist>
EOF

echo "Wrote LaunchAgent plist: $PLIST_PATH"

# unload/load to apply changes
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed & started: com.aaron.weread.notion.sync.api"
echo "Runs every ${INTERVAL} seconds (${INTERVAL} = $((INTERVAL / 60)) minutes)"
echo "Logs:"
echo "  tail -f /tmp/weread_notion_sync_api.out.log"
echo "  tail -f /tmp/weread_notion_sync_api.err.log"
echo ""
echo "To change interval, set SYNC_INTERVAL in .env (in seconds, default 3600 = 1 hour)"



