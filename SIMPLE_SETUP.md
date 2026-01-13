# Simple Setup - Trigger Sync from Anywhere

## What You Need

1. Code pushed to GitHub
2. GitHub secrets configured
3. A way to trigger the sync (3 options below)

---

## Option 1: Use GitHub Actions Website (Easiest!)

**No coding needed - just click buttons on GitHub**

### Steps:

1. **Push your code to GitHub** (if not done):
   ```bash
   git add .
   git commit -m "Add sync workflow"
   git push
   ```

2. **Add secrets to GitHub:**
   - Go to: `https://github.com/yourusername/your-repo/settings/secrets/actions`
   - Click "New repository secret"
   - Add: `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `WEREAD_COOKIES`

3. **Trigger sync from GitHub:**
   - Go to: `https://github.com/yourusername/your-repo/actions`
   - Click "Sync WeRead to Notion" workflow
   - Click "Run workflow" button
   - Click "Run workflow" again
   - ✅ Sync runs in the cloud!

**That's it!** You can do this from any device, anywhere, as long as you can access GitHub.

---

## Option 2: Use the Trigger HTML Page (Simple Web Interface)

### Step 1: Open the HTML file

**On your current laptop:**
1. Open `trigger.html` in your browser (double-click it, or right-click → Open with → Browser)
2. You'll see a page with a button and configuration fields

### Step 2: Configure it

1. **Get a GitHub Personal Access Token:**
   - Go to: https://github.com/settings/tokens
   - Click "Generate new token (classic)"
   - Name it: "Sync Trigger"
   - Check the `repo` checkbox
   - Click "Generate token"
   - **Copy the token** (starts with `ghp_`)

2. **Fill in the form:**
   - **GitHub Token:** Paste your token
   - **GitHub Repo:** Enter `yourusername/your-repo-name`
   - **Workflow File:** Leave as `sync.yml`
   - Click "Save Config"

### Step 3: Use it

1. Click the "🔄 Start Sync" button
2. Sync starts in GitHub Actions
3. A new tab opens showing the progress

### Step 4: Make it accessible from anywhere

**Option A: Host on GitHub Pages (Free, Recommended)**
1. Push `trigger.html` to your repo
2. Go to repo → Settings → Pages
3. Source: Deploy from a branch → main → / (root)
4. Save
5. Your page will be at: `https://yourusername.github.io/your-repo/trigger.html`
6. **Bookmark this URL** - access from any device!

**Option B: Just use GitHub Actions directly**
- Bookmark: `https://github.com/yourusername/your-repo/actions`
- Click "Run workflow" when you want to sync
- No HTML file needed!

---

## Option 3: Deploy to Vercel (Get a Simple URL)

This gives you a URL like `https://your-app.vercel.app/sync` that you can click from anywhere.

### Steps:

1. **Sign up at vercel.com** (free)

2. **Install Vercel CLI:**
   ```bash
   npm install -g vercel
   ```

3. **Deploy:**
   ```bash
   cd /path/to/push_reading_progress_to_notion
   vercel
   ```
   - Follow prompts (press Enter for defaults)
   - It will ask to link to GitHub - say yes

4. **Add environment variables:**
   - Go to Vercel dashboard → Your project → Settings → Environment Variables
   - Add:
     - `NOTION_TOKEN` = your token
     - `NOTION_DATABASE_ID` = your database ID
     - `WEREAD_COOKIES` = your cookies

5. **Get your URL:**
   - Vercel gives you: `https://your-project.vercel.app`
   - Your sync endpoint: `https://your-project.vercel.app/sync`

6. **Use it:**
   - Open that URL in any browser → Sync runs!
   - Or create a link in Notion to that URL

---

## Which Option Should You Choose?

- **Option 1 (GitHub Actions):** Simplest, no setup needed, just use GitHub website
- **Option 2 (HTML Page):** Good if you want a custom button/interface
- **Option 3 (Vercel):** Best if you want a simple URL you can share/bookmark

---

## Quick Start (Recommended)

**Just use GitHub Actions website:**

1. Push code to GitHub
2. Add secrets
3. Bookmark: `https://github.com/yourusername/your-repo/actions`
4. Click "Run workflow" whenever you want to sync
5. Done! ✅

No HTML files, no hosting, no extra setup needed!
