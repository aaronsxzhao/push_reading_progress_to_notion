#!/usr/bin/env bash
set -euo pipefail

# Installs a launchd job that refreshes WeRead cookies every hour
# (8 AM – 10 PM Beijing / 0:00 – 14:00 UTC) using the saved browser profile.
#
# First-time setup:
#   1. Run interactively to log in and save the browser profile:
#        python scripts/fetch_cookies_auto.py
#   2. Then install this launchd job:
#        bash scripts/install_cookie_refresh.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.aaron.weread.cookie.refresh.plist"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
SCRIPT_PATH="$PROJECT_DIR/scripts/fetch_cookies_auto.py"
ENV_FILE="$PROJECT_DIR/.env"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing venv python at: $PYTHON_BIN"
  echo "Create: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -d "$PROJECT_DIR/.browser_state" ]]; then
  echo "No saved browser state. Run interactively first:"
  echo "  python scripts/fetch_cookies_auto.py"
  exit 1
fi

# Load .env for GH_TOKEN / COOKIE_GIST_ID
set -a
source "$ENV_FILE"
set +a

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.aaron.weread.cookie.refresh</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$SCRIPT_PATH</string>
    <string>--headless</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>GH_TOKEN</key><string>${GH_TOKEN:-}</string>
    <key>COOKIE_GIST_ID</key><string>${COOKIE_GIST_ID:-}</string>
  </dict>

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

echo "Installed: com.aaron.weread.cookie.refresh (runs every hour)"
echo "Logs: tail -f /tmp/weread_cookie_refresh.out.log"
