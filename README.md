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
# edit .env with your real values
```

**⚠️ Security Note:** Your `.env` file contains secrets and is **automatically ignored by git** (see `.gitignore`). Never commit your `.env` file to GitHub. Only `.env.example` (with placeholder values) is safe to commit.

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

## Security: Protecting Your Secrets

**Your `.env` file is automatically ignored by git** and will never be committed. Here's how to verify:

### Before pushing to GitHub:

1. **Run the security check:**
   ```bash
   bash scripts/check_secrets.sh
   ```

2. **Verify `.env` is not tracked:**
   ```bash
   git status
   # Should NOT show .env in the output
   ```

3. **Double-check what will be committed:**
   ```bash
   git diff --cached  # if staging
   git diff          # if not staging
   ```

### What's safe to commit:
- ✅ `.env.example` (template with placeholder values)
- ✅ All code files
- ✅ `requirements.txt`, `README.md`, etc.

### What's NEVER committed:
- ❌ `.env` (your real secrets)
- ❌ Any file with `secret_` tokens
- ❌ LaunchAgent plist files

**If you accidentally commit `.env`:**
```bash
git rm --cached .env
git commit -m "Remove accidentally committed .env"
# Then immediately rotate your Notion token in Notion settings
```

