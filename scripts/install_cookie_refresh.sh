#!/usr/bin/env bash
set -euo pipefail

# Installs a launchd job that refreshes WeRead cookies and syncs to
# Notion every hour while the Mac is awake.
#
# First-time setup:
#   1. Run interactively to log in and save the browser profile:
#        python scripts/fetch_cookies_auto.py
#   2. Then install this launchd job:
#        bash scripts/install_cookie_refresh.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.aaron.weread.cookie.refresh.plist"
SCRIPT_PATH="$PROJECT_DIR/scripts/refresh_and_sync.sh"
ENV_FILE="$PROJECT_DIR/.env"

if [[ ! -d "$PROJECT_DIR/.browser_state" ]]; then
  echo "No saved browser state. Run interactively first:"
  echo "  python scripts/fetch_cookies_auto.py"
  exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Missing: $SCRIPT_PATH"
  exit 1
fi

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.aaron.weread.cookie.refresh</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$SCRIPT_PATH</string>
  </array>

  <key>StartInterval</key>
  <integer>3600</integer>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/tmp/weread_cookie_refresh.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/weread_cookie_refresh.err.log</string>
</dict>
</plist>
EOF

echo "Wrote LaunchAgent: $PLIST_PATH"

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed: com.aaron.weread.cookie.refresh"
echo "  Runs every hour: cookie refresh + Notion sync"
echo "  Logs: tail -f /tmp/weread_cookie_refresh.out.log"
