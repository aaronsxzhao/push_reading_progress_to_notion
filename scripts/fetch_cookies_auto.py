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


def fetch_cookies_playwright() -> Optional[str]:
    """
    Fetch cookies using Playwright (more modern, faster).
    Returns cookie string if successful, None otherwise.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not installed. Install with: pip install playwright && playwright install chromium")
        return None
    
    print("=" * 80)
    print("🌐 Opening browser with Playwright...")
    print("=" * 80)
    
    try:
        with sync_playwright() as p:
            # Launch browser (set headless=False to see the browser)
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Navigate to WeRead
            print("\n📖 Navigating to weread.qq.com...")
            page.goto("https://weread.qq.com", wait_until="domcontentloaded")
            time.sleep(2)
            
            print(f"   Current URL: {page.url}")
            
            # Wait for login
            print("\n⏳ Waiting for login...")
            print("   Please log in to your WeRead account in the browser window.")
            print("   The script will detect when you're logged in.")
            print("   (Waiting up to 60 seconds...)")
            
            logged_in = False
            max_wait = 60
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                time.sleep(2)
                
                # Check cookies
                cookies = context.cookies()
                cookie_dict = {c['name']: c['value'] for c in cookies}
                
                if 'wr_skey' in cookie_dict and cookie_dict['wr_skey']:
                    # Check if we're on a logged-in page
                    current_url = page.url
                    if "weread.qq.com" in current_url and "login" not in current_url.lower():
                        logged_in = True
                        break
                
                print(f"   Still waiting... ({int(time.time() - start_time)}s / {max_wait}s)")
            
            if not logged_in:
                print("\n⚠️  Timeout waiting for login. Please try again.")
                browser.close()
                return None
            
            print("\n✅ Login detected!")
            # Wait longer to ensure all cookies are set (some cookies are set after page load)
            print("   Waiting for all cookies to be set...")
            time.sleep(5)  # Wait longer for all cookies to be set by the server
            
            # Navigate to a page that requires auth to trigger cookie refresh
            try:
                page.goto("https://weread.qq.com/web/shelf/sync?synckey=0&lectureSynckey=0", wait_until="domcontentloaded")
                time.sleep(2)
            except:
                pass
            
            # Extract cookies
            print("\n🍪 Extracting cookies...")
            cookies = context.cookies()
            cookie_dict = {}
            
            for cookie in cookies:
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                if name and value:
                    cookie_dict[name] = value
            
            # Filter for WeRead cookies
            weread_cookies = {k: v for k, v in cookie_dict.items() if k.startswith('wr_')}
            
            if not weread_cookies:
                print("❌ No WeRead cookies found. Make sure you're logged in.")
                browser.close()
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
            
            browser.close()
            return cookies_str
            
    except Exception as e:
        print(f"\n❌ Error with Playwright: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Main function"""
    print("=" * 80)
    print("🍪 WeRead Automatic Cookie Fetcher")
    print("=" * 80)
    print()
    print("This script will:")
    print("  1. Open a browser window")
    print("  2. Navigate to weread.qq.com")
    print("  3. Wait for you to log in")
    print("  4. Extract cookies automatically")
    print("  5. Save them to your .env file")
    print()
    
    # Try Playwright first (more modern), then Selenium
    cookies_str = None
    
    print("Trying Playwright first...")
    cookies_str = fetch_cookies_playwright()
    
    if not cookies_str:
        print("\n" + "=" * 80)
        print("Trying Selenium as fallback...")
        print("=" * 80)
        cookies_str = fetch_cookies_selenium()
    
    if not cookies_str:
        print("\n" + "=" * 80)
        print("❌ Failed to fetch cookies with both methods")
        print("=" * 80)
        print("\n🔧 Manual Alternative:")
        print("   See scripts/get_weread_cookies.md for manual cookie extraction")
        return False
    
    # Save to .env file
    print("\n" + "=" * 80)
    print("💾 Saving cookies to .env file...")
    print("=" * 80)
    
    env_path = Path(__file__).parent.parent / ".env"
    if update_env_file(cookies_str, env_path):
        print(f"\n✅ Cookies saved to {env_path}")
        print("\n📋 Next steps:")
        print("   1. Verify cookies are correct in .env file")
        print("   2. Run: python3 src/weread_notion_sync_api.py")
        print("   3. Or test with: python3 scripts/check_cookies.py")
        return True
    else:
        print(f"\n❌ Failed to save cookies to {env_path}")
        print("\n💡 You can manually add this to your .env file:")
        print(f'   WEREAD_COOKIES="{cookies_str}"')
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
