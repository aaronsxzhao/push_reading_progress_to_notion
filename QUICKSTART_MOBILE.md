# One-Click Sync from iPhone / Notion

Sync your WeRead books to Notion with a single tap - no server needed!

## How It Works

```
iPhone/Notion → GitHub Actions → WeRead API → Your Notion Database
     tap           runs for free      fetches        updates
```

No server running. GitHub Actions only runs when you trigger it (free tier: 2000 mins/month).

---

## Setup (One-Time, ~5 minutes)

### Step 1: Push Code to GitHub

```bash
cd /Users/aaronz/Downloads/push_reading_progress_to_notion
git add .
git commit -m "Setup mobile sync"
git push origin main
```

### Step 2: Add Secrets to GitHub

Go to: **Your Repo → Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Name | Value |
|------|-------|
| `NOTION_TOKEN` | Your Notion integration token |
| `NOTION_DATABASE_ID` | Your Notion database ID |
| `WEREAD_COOKIES` | Your WeRead cookies (from .env) |

### Step 3: Create GitHub Personal Access Token

1. Go to: https://github.com/settings/tokens/new
2. Give it a name: `weread-sync`
3. Select scopes: `repo` and `workflow`
4. Generate token and **copy it** (starts with `ghp_`)

### Step 4: Setup Trigger Page

1. Open `trigger.html` in a browser (can be local file or hosted)
2. Enter your GitHub token and repo name (e.g., `yourusername/push_reading_progress_to_notion`)
3. Click "Save"
4. Tap "Sync Now" to test

---

## Use from iPhone

### Option A: Safari Bookmark (Easiest)

1. Open `trigger.html` (host it on GitHub Pages or anywhere)
2. Add to Home Screen:
   - Tap Share → Add to Home Screen
   - Name it "Sync Books"
3. One tap from home screen to sync!

### Option B: iOS Shortcuts (More Control)

1. Open Shortcuts app
2. Create new shortcut
3. Add action: "Get Contents of URL"
4. Configure:
   - URL: `https://api.github.com/repos/YOUR_USERNAME/push_reading_progress_to_notion/actions/workflows/sync.yml/dispatches`
   - Method: POST
   - Headers:
     - `Authorization`: `Bearer YOUR_GITHUB_TOKEN`
     - `Accept`: `application/vnd.github.v3+json`
   - Request Body: JSON → `{"ref": "main"}`
5. Add to Home Screen

---

## Use from Notion

### Option A: Link Block

Add a bookmark or link to your hosted `trigger.html`:
```
https://yourusername.github.io/push_reading_progress_to_notion/trigger.html
```

### Option B: Button (with Make/Zapier)

1. Create a webhook in Make.com or Zapier
2. Configure it to POST to GitHub Actions API
3. Add the webhook URL as a button in Notion

---

## Host trigger.html on GitHub Pages

1. Go to your repo → Settings → Pages
2. Source: Deploy from a branch
3. Branch: main, folder: / (root)
4. Save
5. Your page will be at: `https://yourusername.github.io/push_reading_progress_to_notion/trigger.html`

---

## Troubleshooting

**"Bad credentials" error**
- Make sure your GitHub token has `repo` and `workflow` permissions
- Token must start with `ghp_`

**"Not Found" error**
- Check your repo name is correct (username/repo)
- Make sure the repo is not private, or token has access

**Sync runs but nothing updates**
- Check GitHub Actions logs: Repo → Actions → Latest run
- Verify your secrets are set correctly

---

## Daily Auto-Sync (Optional)

The workflow is already configured to run daily at 2 AM UTC. To disable:

Edit `.github/workflows/sync.yml` and remove or comment out:
```yaml
schedule:
  - cron: '0 2 * * *'
```
