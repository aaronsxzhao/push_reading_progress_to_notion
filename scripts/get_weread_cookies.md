# How to Get WeRead Cookies

## Method 1: Browser DevTools (Recommended)

### Chrome/Edge:
1. Open [weread.qq.com](https://weread.qq.com) in your browser
2. **Log in** to your WeRead account
3. Press **F12** (or right-click → Inspect) to open DevTools
4. Go to **Application** tab (or **Storage** in Firefox)
5. Click **Cookies** → `https://weread.qq.com`
6. Copy all cookie values. You need these cookies:
   - `wr_skey` (most important)
   - `wr_vid`
   - `wr_rt`
   - `wr_localId`
   - Any other cookies present

7. Format them as a cookie string:
   ```
   wr_skey=your_value_here; wr_vid=your_value_here; wr_rt=your_value_here; wr_localId=your_value_here
   ```

### Firefox:
1. Same steps as above
2. Go to **Storage** → **Cookies** → `https://weread.qq.com`
3. Copy cookie values

## Method 2: Browser Extension

Install a cookie export extension:
- **Chrome**: "Get cookies.txt LOCALLY" or "Cookie-Editor"
- **Firefox**: "Cookie Quick Manager"

Then export cookies for `weread.qq.com` and copy the cookie string.

## Method 3: Copy from Network Request

1. Open DevTools → **Network** tab
2. Refresh weread.qq.com
3. Click on any request to `weread.qq.com`
4. In **Headers**, find **Cookie:** header
5. Copy the entire cookie string

## Security Note

⚠️ **Never commit your cookies to git!** They're like passwords - keep them in `.env` only.

