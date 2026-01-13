# WeRead → Notion Auto Sync

Syncs your WeRead (微信读书) reading progress directly to Notion, updating your Books & Media database automatically.

## Two Modes Available

### 🚀 **Direct API Mode** (Recommended - No Obsidian needed!)
Fetches data directly from WeRead's API using your browser cookies. No plugins or extra apps required.

### 📁 **File Watch Mode** (Alternative)
Watches an Obsidian folder for markdown files exported by the WeRead Obsidian plugin.

## Features
- ✅ Direct API access to WeRead (no Obsidian needed)
- ✅ Real-time file watching (if using Obsidian mode)
- ✅ Upserts books into Notion database
- ✅ Updates:
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

### 3) Choose Your Mode

#### Option A: Direct API Mode (Recommended)

1. **Get your WeRead cookies:**
   - Open [weread.qq.com](https://weread.qq.com) in browser and log in
   - Press F12 → Application tab → Cookies → `weread.qq.com`
   - Copy cookie values (especially `wr_skey`, `wr_vid`, `wr_rt`)
   - Format: `wr_skey=xxx; wr_vid=xxx; wr_rt=xxx`
   - See `scripts/get_weread_cookies.md` for detailed instructions

2. **Add to `.env`:**
   ```bash
   WEREAD_COOKIES=wr_skey=your_value; wr_vid=your_value; wr_rt=your_value
   ```

3. **Run the API sync:**
   ```bash
   source .venv/bin/activate
   python3 src/weread_notion_sync_api.py
   ```

#### Option B: File Watch Mode (Obsidian)

1. **Set up Obsidian WeRead plugin** (if not already done)
2. **Add to `.env`:**
   ```bash
   WEREAD_ROOT=/path/to/your/Obsidian/WeRead
   ```

3. **Run the file watcher:**
   ```bash
   source .venv/bin/activate
   python3 src/weread_notion_sync.py
   ```

## macOS auto-run (launchd)

### For Direct API Mode:

Use the provided `scripts/install_launchd_api.sh` to run sync periodically (default: every hour):

```bash
bash scripts/install_launchd_api.sh
```

To change sync interval, set `SYNC_INTERVAL` in `.env` (in seconds, default 3600 = 1 hour).

Logs:

* /tmp/weread_notion_sync_api.out.log
* /tmp/weread_notion_sync_api.err.log

### For File Watch Mode:

Use the provided `scripts/install_launchd.sh` to install a LaunchAgent that watches files continuously:

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
   ```2. **Verify `.env` is not tracked:**
   ```bash
   git status
   # Should NOT show .env in the output
   ```

3. **Double-check what will be committed:**
   ```bash
   git diff --cached  # if staging
   git diff          # if not staging
   ```### What's safe to commit:
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