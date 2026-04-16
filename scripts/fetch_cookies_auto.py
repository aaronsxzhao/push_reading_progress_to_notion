#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automatic WeRead Cookie Fetcher
Opens a browser, navigates to weread.qq.com, waits for login, and extracts cookies.
Similar to obsidian-weread-plugin's approach but automated.

Requirements:
    pip install selenium webdriver-manager
    OR
    pip install playwright
    playwright install chromium
"""

import os
import sys
import time
import re
from pathlib import Path
from typing import Dict, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def update_env_file(cookies_str: str, env_path: Optional[Path] = None) -> bool:
    """
    Update .env file with new cookies.
    If WEREAD_COOKIES exists, replace it. Otherwise, append it.
    """
    if env_path is None:
        env_path = Path(__file__).parent.parent / ".env"
    
    if not env_path.exists():
        print(f"[INFO] Creating .env file at {env_path}")
        env_path.touch()
    
    # Read existing .env content
    content = env_path.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    # Find and replace WEREAD_COOKIES line
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith('WEREAD_COOKIES='):
            # Replace existing
            new_lines.append(f'WEREAD_COOKIES="{cookies_str}"')
            updated = True
        elif line.strip().startswith('#WEREAD_COOKIES='):
            # Uncomment if commented
            new_lines.append(f'WEREAD_COOKIES="{cookies_str}"')
            updated = True
        else:
            new_lines.append(line)
    
    # If not found, append it
    if not updated:
        if content and not content.endswith('\n'):
            new_lines.append('')
        new_lines.append(f'WEREAD_COOKIES="{cookies_str}"')
    
    # Write back
    env_path.write_text('\n'.join(new_lines), encoding='utf-8')
    return True


def format_cookies(cookie_dict: Dict[str, str]) -> str:
    """Format cookie dict into cookie string format"""
    return "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])


def fetch_cookies_selenium() -> Optional[str]:
    """
    Fetch cookies using Selenium (Chrome/Firefox).
    Returns cookie string if successful, None otherwise.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        print("❌ Selenium not installed. Install with: pip install selenium webdriver-manager")
        return None
    
    print("=" * 80)
    print("🌐 Opening browser with Selenium...")
    print("=" * 80)
    
    # Setup Chrome options
    chrome_options = Options()
    # Uncomment to run headless (no browser window)
    # chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    driver = None
    try:
        # Use webdriver-manager to automatically handle ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Navigate to WeRead
        print("\n📖 Navigating to weread.qq.com...")
        driver.get("https://weread.qq.com")
        time.sleep(2)
        
        # Check if already logged in (look for user profile or bookshelf)
        current_url = driver.current_url
        print(f"   Current URL: {current_url}")
        
        # Wait for page to load and check login status
        try:
            # Wait up to 30 seconds for user to log in
            print("\n⏳ Waiting for login...")
            print("   Please log in to your WeRead account in the browser window.")
            print("   The script will detect when you're logged in.")
            print("   (Waiting up to 60 seconds...)")
            
            # Check for login indicators
            logged_in = False
            max_wait = 60  # seconds
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                time.sleep(2)
                
                # Check URL - if redirected to main page or shelf, likely logged in
                current_url = driver.current_url
                if "weread.qq.com" in current_url and "login" not in current_url.lower():
                    # Check for user elements or bookshelf
                    try:
                        # Look for common logged-in indicators
                        page_source = driver.page_source.lower()
                        if any(indicator in page_source for indicator in ["书架", "shelf", "我的", "profile", "用户"]):
                            logged_in = True
                            break
                    except:
                        pass
                
                # Also check cookies - if we have wr_skey, we're likely logged in
                cookies = driver.get_cookies()
                cookie_dict = {c['name']: c['value'] for c in cookies}
                if 'wr_skey' in cookie_dict and cookie_dict['wr_skey']:
                    logged_in = True
                    break
                
                print(f"   Still waiting... ({int(time.time() - start_time)}s / {max_wait}s)")
            
            if not logged_in:
                print("\n⚠️  Timeout waiting for login. Please try again.")
                return None
            
            print("\n✅ Login detected!")
            # Wait longer to ensure all cookies are set (some cookies are set after page load)
            print("   Waiting for all cookies to be set...")
            time.sleep(5)  # Wait longer for all cookies to be set by the server
            
            # Navigate to a page that requires auth to trigger cookie refresh
            try:
                driver.get("https://weread.qq.com/web/shelf/sync?synckey=0&lectureSynckey=0")
                time.sleep(2)
            except:
                pass
            
        except Exception as e:
            print(f"\n⚠️  Error waiting for login: {e}")
            print("   Please make sure you're logged in and try again.")
            return None
        
        # Extract cookies
        print("\n🍪 Extracting cookies...")
        cookies = driver.get_cookies()
        cookie_dict = {}
        
        for cookie in cookies:
            name = cookie.get('name', '')
            value = cookie.get('value', '')
            if name and value:
                cookie_dict[name] = value
        
        # Filter for WeRead cookies (start with 'wr_')
        weread_cookies = {k: v for k, v in cookie_dict.items() if k.startswith('wr_')}
        
        if not weread_cookies:
            print("❌ No WeRead cookies found. Make sure you're logged in.")
            return None
        
        # Check required cookies
        required = ['wr_skey', 'wr_vid', 'wr_rt']
        missing = [c for c in required if c not in weread_cookies]
        
        if missing:
            print(f"⚠️  Missing required cookies: {', '.join(missing)}")
            print("   But continuing with available cookies...")
        
        print(f"\n✅ Found {len(weread_cookies)} WeRead cookies:")
        for name in sorted(weread_cookies.keys()):
            value = weread_cookies[name]
            print(f"   - {name}: {value[:50]}..." if len(value) > 50 else f"   - {name}: {value}")
        
        # Format cookies
        cookies_str = format_cookies(weread_cookies)
        return cookies_str
        
    except Exception as e:
        print(f"\n❌ Error with Selenium: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if driver:
            print("\n🔄 Closing browser...")
            driver.quit()


BROWSER_STATE_DIR = Path(__file__).parent.parent / ".browser_state"


def fetch_cookies_playwright(headless: bool = False) -> Optional[str]:
    """
    Fetch cookies using Playwright with a persistent browser profile.

    On the first run, a browser window opens for QR-code login.  The session
    is saved to .browser_state/ so that subsequent (even headless) runs can
    reuse it without user interaction.

    Args:
        headless: If True, launch without a visible window (only works after
                  the first manual login has been saved).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Install with: pip install playwright && playwright install chromium")
        return None

    state_dir = str(BROWSER_STATE_DIR)
    has_state = BROWSER_STATE_DIR.exists()

    if headless and not has_state:
        print("No saved browser state — headless refresh not possible yet.")
        print("Run once interactively:  python scripts/fetch_cookies_auto.py")
        return None

    label = "headless" if headless else "interactive"
    print(f"Opening Playwright browser ({label})...")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                state_dir,
                headless=headless,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = context.pages[0] if context.pages else context.new_page()

            page.goto("https://weread.qq.com", wait_until="domcontentloaded")
            time.sleep(2)

            # Check if already logged in from saved state
            cookies = context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            logged_in = bool(cookie_dict.get("wr_skey"))

            if not logged_in:
                if headless:
                    print("Saved session expired — need interactive login.")
                    context.close()
                    return None

                print("Waiting for QR-code login (up to 120 s) ...")
                max_wait = 120
                start_time = time.time()
                while time.time() - start_time < max_wait:
                    time.sleep(2)
                    cookies = context.cookies()
                    cookie_dict = {c["name"]: c["value"] for c in cookies}
                    if cookie_dict.get("wr_skey"):
                        logged_in = True
                        break
                    elapsed = int(time.time() - start_time)
                    print(f"  Waiting... ({elapsed}s / {max_wait}s)")

            if not logged_in:
                print("Timeout waiting for login.")
                context.close()
                return None

            print("Login detected — extracting cookies ...")
            time.sleep(3)

            # Hit shelf to trigger any extra Set-Cookie headers
            try:
                page.goto(
                    "https://weread.qq.com/web/shelf/sync?synckey=0&lectureSynckey=0",
                    wait_until="domcontentloaded",
                )
                time.sleep(2)
            except Exception:
                pass

            cookies = context.cookies()
            weread_cookies: Dict[str, str] = {}
            for c in cookies:
                name, value = c.get("name", ""), c.get("value", "")
                if name.startswith("wr_") and value:
                    weread_cookies[name] = value

            if not weread_cookies:
                print("No WeRead cookies found.")
                context.close()
                return None

            required = ["wr_skey", "wr_vid", "wr_rt"]
            missing = [r for r in required if r not in weread_cookies]
            if missing:
                print(f"Missing cookies: {', '.join(missing)} — continuing anyway")

            print(f"Found {len(weread_cookies)} WeRead cookies:")
            for name in sorted(weread_cookies):
                v = weread_cookies[name]
                print(f"  {name}: {v[:50]}..." if len(v) > 50 else f"  {name}: {v}")

            context.close()
            return format_cookies(weread_cookies)

    except Exception as e:
        print(f"Error with Playwright: {e}")
        import traceback
        traceback.print_exc()
        return None


def _push_to_gist(cookies_str: str) -> None:
    """Push cookies to GitHub Gist if configured."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    gh_token = os.environ.get("GH_TOKEN", "")
    gist_id = os.environ.get("COOKIE_GIST_ID", "")
    if not gh_token or not gist_id:
        return
    try:
        import requests as _req
        r = _req.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {gh_token}",
                     "Accept": "application/vnd.github.v3+json"},
            json={"files": {"weread_cookies.txt": {"content": cookies_str}}},
            timeout=10,
        )
        if r.status_code == 200:
            print("Gist updated with fresh cookies")
        else:
            print(f"Gist update failed: {r.status_code}")
    except Exception as e:
        print(f"Gist update error: {e}")


def main():
    """Main function.

    Flags:
        --headless   Reuse saved browser session (no window, no QR scan).
                     Fails if no saved state exists — run interactively first.
    """
    headless = "--headless" in sys.argv

    if headless:
        print("Cookie refresh (headless) ...")
    else:
        print("WeRead Cookie Fetcher")
        print("  1. Open browser  2. Log in  3. Extract cookies  4. Save to .env + Gist")
        print()

    cookies_str = fetch_cookies_playwright(headless=headless)

    if not cookies_str and not headless:
        print("\nTrying Selenium as fallback...")
        cookies_str = fetch_cookies_selenium()

    if not cookies_str:
        print("Failed to fetch cookies")
        if headless:
            print("Hint: run once without --headless to do the initial login")
        return False

    env_path = Path(__file__).parent.parent / ".env"
    if update_env_file(cookies_str, env_path):
        print(f"Cookies saved to {env_path}")
        _push_to_gist(cookies_str)
        return True
    else:
        print(f"Failed to save cookies to {env_path}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
