# Cloud Deployment Guide - Trigger Sync from Anywhere

Deploy your sync to the cloud so you can trigger it from any device via URL, without needing your laptop running.

## Option 1: GitHub Actions (Free, No Server Needed!)

### Setup

1. **Push code to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/yourusername/weread-notion-sync.git
   git push -u origin main
   ```

2. **Add Secrets to GitHub:**
   - Go to your repo → Settings → Secrets and variables → Actions
   - Add these secrets:
     - `NOTION_TOKEN`
     - `NOTION_DATABASE_ID`
     - `WEREAD_COOKIES`
     - `SYNC_API_KEY` (optional, for security)

3. **Trigger Sync:**
   
   **Method A: Via GitHub UI**
   - Go to Actions tab → "Sync WeRead to Notion" → Run workflow
   
   **Method B: Via API/URL (Best for Notion!)**
   ```bash
   curl -X POST \
     -H "Authorization: token YOUR_GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     https://api.github.com/repos/yourusername/weread-notion-sync/actions/workflows/sync.yml/dispatches
   ```
   
   **Create a GitHub Personal Access Token:**
   - Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Generate token with `repo` scope
   - Use it in the curl command above

4. **Create a URL for Notion:**
   
   Use a service like **Zapier** or **Make.com** to create a webhook that calls the GitHub API, or use this simple HTML page:

   ```html
   <!DOCTYPE html>
   <html>
   <head><title>Trigger Sync</title></head>
   <body>
     <button onclick="triggerSync()">🔄 Sync WeRead Books</button>
     <div id="status"></div>
     <script>
       async function triggerSync() {
         document.getElementById('status').textContent = 'Triggering...';
         const response = await fetch('https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/actions/workflows/sync.yml/dispatches', {
           method: 'POST',
           headers: {
             'Authorization': 'token YOUR_GITHUB_TOKEN',
             'Accept': 'application/vnd.github.v3+json'
           },
           body: JSON.stringify({ref: 'main'})
         });
         if (response.ok) {
           document.getElementById('status').textContent = '✅ Sync triggered!';
         } else {
           document.getElementById('status').textContent = '❌ Error: ' + response.statusText;
         }
       }
     </script>
   </body>
   </html>
   ```

## Option 2: Vercel (Free Tier Available)

### Setup

1. **Install Vercel CLI:**
   ```bash
   npm i -g vercel
   ```

2. **Deploy:**
   ```bash
   vercel
   ```

3. **Add Environment Variables:**
   - Go to Vercel dashboard → Your project → Settings → Environment Variables
   - Add: `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `WEREAD_COOKIES`, `SYNC_API_KEY`

4. **Get Your URL:**
   - After deployment, you'll get: `https://your-project.vercel.app/sync`
   - Use this URL in Notion or anywhere!

5. **Trigger from Notion:**
   - Create a link: `https://your-project.vercel.app/sync`
   - Or use Zapier/Make.com to call it

## Option 3: Railway (Free Trial)

### Setup

1. **Sign up at railway.app**

2. **Create New Project:**
   - New Project → Deploy from GitHub repo
   - Select your repo

3. **Add Environment Variables:**
   - Variables tab → Add:
     - `NOTION_TOKEN`
     - `NOTION_DATABASE_ID`
     - `WEREAD_COOKIES`
     - `PORT=8765`

4. **Get Your URL:**
   - Railway provides: `https://your-app.railway.app/sync`
   - Use this in Notion!

## Option 4: Render (Free Tier)

### Setup

1. **Sign up at render.com**

2. **Create Web Service:**
   - New → Web Service
   - Connect GitHub repo
   - Build command: `pip install -r requirements.txt`
   - Start command: `python3 api/sync.py`

3. **Add Environment Variables:**
   - Environment tab → Add all required vars

4. **Get URL:**
   - Render provides: `https://your-app.onrender.com/sync`

## Option 5: Netlify Functions

### Setup

1. **Create `netlify.toml`:**
   ```toml
   [build]
     functions = "api"
   
   [[redirects]]
     from = "/sync"
     to = "/.netlify/functions/sync"
     status = 200
   ```

2. **Create `api/sync.py`** (already created)

3. **Deploy:**
   ```bash
   npm i -g netlify-cli
   netlify deploy --prod
   ```

## Quick Start: GitHub Actions (Recommended)

This is the **easiest and free** option - **NO HTML FILES NEEDED!**

### Super Simple Method (Just Use GitHub Website):

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Add sync workflow"
   git push
   ```

2. **Add Secrets:**
   - Go to: `https://github.com/yourusername/your-repo/settings/secrets/actions`
   - Click "New repository secret"
   - Add: `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `WEREAD_COOKIES`

3. **Trigger Sync:**
   - Go to: `https://github.com/yourusername/your-repo/actions`
   - Click "Sync WeRead to Notion" workflow
   - Click "Run workflow" → "Run workflow"
   - ✅ Done! Sync runs in the cloud!

**Bookmark the Actions page** - you can trigger sync from any device!

### Alternative: Use trigger.html (Optional)

If you want a custom button interface, you can use the `trigger.html` file:
   ```html
   <!DOCTYPE html>
   <html>
   <head>
     <title>Sync WeRead Books</title>
     <meta name="viewport" content="width=device-width, initial-scale=1">
     <style>
       body { font-family: Arial; text-align: center; padding: 50px; }
       button { padding: 20px 40px; font-size: 18px; background: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer; }
       button:hover { background: #45a049; }
       #status { margin-top: 20px; font-size: 16px; }
     </style>
   </head>
   <body>
     <h1>📚 Sync WeRead to Notion</h1>
     <button onclick="triggerSync()">🔄 Start Sync</button>
     <div id="status"></div>
     <script>
       async function triggerSync() {
         const status = document.getElementById('status');
         status.textContent = '⏳ Triggering sync...';
         
         // Replace with your GitHub token and repo
         const GITHUB_TOKEN = 'YOUR_GITHUB_TOKEN';
         const REPO = 'yourusername/weread-notion-sync';
         
         try {
           const response = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/sync.yml/dispatches`, {
             method: 'POST',
             headers: {
               'Authorization': `token ${GITHUB_TOKEN}`,
               'Accept': 'application/vnd.github.v3+json',
               'Content-Type': 'application/json'
             },
             body: JSON.stringify({ref: 'main'})
           });
           
           if (response.ok) {
             status.textContent = '✅ Sync triggered! Check GitHub Actions for progress.';
           } else {
             const error = await response.text();
             status.textContent = '❌ Error: ' + error;
           }
         } catch (e) {
           status.textContent = '❌ Error: ' + e.message;
         }
       }
     </script>
   </body>
   </html>
   ```

4. **Host the HTML file:**
   - Use GitHub Pages (free!)
   - Or deploy to Vercel/Netlify
   - Or use any static hosting

5. **Access from anywhere:**
   - Open the URL on any device
   - Click button → Sync runs in the cloud!

## Security Notes

- **Never commit secrets** to GitHub
- Use GitHub Secrets for sensitive data
- Add API key protection for public endpoints
- Use HTTPS for all webhook URLs

## Testing

Test your deployment:
```bash
# GitHub Actions
curl -X POST \
  -H "Authorization: token YOUR_TOKEN" \
  https://api.github.com/repos/USER/REPO/actions/workflows/sync.yml/dispatches

# Vercel/Netlify/Railway
curl https://your-app.vercel.app/sync
```

## Troubleshooting

### GitHub Actions not running
- Check secrets are set correctly
- Verify workflow file is in `.github/workflows/`
- Check Actions tab for error messages

### Serverless function errors
- Check environment variables are set
- View function logs in dashboard
- Test locally first: `python3 api/sync.py`

### URL not accessible
- Check deployment status
- Verify URL is correct
- Check firewall/security settings
