#!/usr/bin/env bash
set -euo pipefail

# Refresh WeRead cookies (headless) and immediately run the Notion sync
# while the cookies are guaranteed fresh.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
ENV_FILE="$PROJECT_DIR/.env"

# Load env vars
set -a
source "$ENV_FILE"
set +a

echo "=== $(date '+%Y-%m-%d %H:%M:%S') Cookie refresh + sync ==="

# Step 1: Refresh cookies
echo "[1/2] Refreshing cookies..."
"$PYTHON_BIN" "$PROJECT_DIR/scripts/fetch_cookies_auto.py" --headless
if [ $? -ne 0 ]; then
  echo "Cookie refresh failed — skipping sync"
  exit 1
fi

# Reload env to pick up the fresh cookies
set -a
source "$ENV_FILE"
set +a

# Step 2: Run Notion sync with the fresh cookies
echo "[2/3] Syncing to Notion..."
"$PYTHON_BIN" -u "$PROJECT_DIR/src/weread_notion_sync_api.py"

# Step 3: Compute heatmap data and push to Gist
echo "[3/3] Computing heatmap data..."
"$PYTHON_BIN" -u "$PROJECT_DIR/scripts/compute_heatmap.py"
echo "=== Done ==="
