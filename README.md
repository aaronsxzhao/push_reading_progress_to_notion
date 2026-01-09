# WeRead → Notion Auto Sync

This runs a background watcher that syncs WeRead (via Obsidian markdown exported by the WeRead plugin)
into a Notion database, updating reading progress and status automatically.

## Features
- Watches WeRead folder in real time (no daily runs)
- Upserts book into Notion database
- Updates:
  - Author
  - Current Page / Total Page
  - Status (To Be Read / Currently Reading / Read)
  - Started At / Last Read At
  - Date Finished
  - Source = WeRead

## Setup

### 1) Install deps
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Create `.env`

```bash
cp .env.example .env
# edit .env
```

### 3) Run once (foreground)

```bash
source .venv/bin/activate
python3 src/weread_notion_sync.py
```

## macOS auto-run (launchd)

Use the provided `scripts/install_launchd.sh` to install a LaunchAgent.

```bash
bash scripts/install_launchd.sh
```

Logs:

* /tmp/weread_notion_sync.out.log
* /tmp/weread_notion_sync.err.log

