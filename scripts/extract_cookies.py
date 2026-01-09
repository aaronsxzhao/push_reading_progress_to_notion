#!/usr/bin/env python3
"""
Helper script to extract WeRead cookies from browser
Run this and follow the instructions to get all cookies easily.
"""

print("=" * 60)
print("WeRead Cookie Extractor")
print("=" * 60)
print()
print("Method 1: Copy from Browser DevTools (Easiest)")
print("-" * 60)
print("1. Open https://weread.qq.com in Chrome/Edge")
print("2. Log in to your account")
print("3. Press F12 to open DevTools")
print("4. Go to 'Application' tab (or 'Storage' in Firefox)")
print("5. Click 'Cookies' → 'https://weread.qq.com'")
print("6. You should see cookies like:")
print("   - wr_skey")
print("   - wr_vid")
print("   - wr_rt")
print("   - wr_localId")
print("   - wr_gid")
print("   - wr_uid")
print()
print("7. Copy each cookie's VALUE (not the name)")
print("8. Format them like this:")
print()
print("   wr_skey=YOUR_VALUE_HERE; wr_vid=YOUR_VALUE_HERE; wr_rt=YOUR_VALUE_HERE; wr_localId=YOUR_VALUE_HERE")
print()
print("=" * 60)
print("Method 2: Copy Cookie Header from Network Tab")
print("-" * 60)
print("1. Open DevTools → Network tab")
print("2. Refresh weread.qq.com")
print("3. Click on any request (like 'shelf' or 'notebooks')")
print("4. In 'Headers' section, find 'Cookie:' header")
print("5. Copy the ENTIRE cookie string")
print("6. Paste it directly into your .env file:")
print()
print("   WEREAD_COOKIES=<paste entire cookie string here>")
print()
print("=" * 60)
print("Method 3: Browser Extension")
print("-" * 60)
print("Install 'Cookie-Editor' extension:")
print("- Chrome: https://chrome.google.com/webstore/detail/cookie-editor")
print("- Firefox: https://addons.mozilla.org/firefox/addon/cookie-editor/")
print()
print("Then:")
print("1. Go to weread.qq.com and log in")
print("2. Click the Cookie-Editor extension icon")
print("3. Find weread.qq.com")
print("4. Export as 'Netscape' format or copy all cookies")
print()
print("=" * 60)
print("IMPORTANT: Required Cookies")
print("-" * 60)
print("You MUST have at least these cookies:")
print("  ✅ wr_skey (MOST IMPORTANT - authentication)")
print("  ✅ wr_vid (session ID)")
print("  ✅ wr_rt (refresh token)")
print()
print("Optional but recommended:")
print("  - wr_localId")
print("  - wr_gid")
print("  - wr_uid")
print()
print("=" * 60)
print("Current .env check:")
print("-" * 60)

import os
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file, 'r') as f:
        for line in f:
            if line.startswith("WEREAD_COOKIES="):
                cookies_str = line.split("=", 1)[1].strip()
                # Remove quotes if present
                if cookies_str.startswith('"') and cookies_str.endswith('"'):
                    cookies_str = cookies_str[1:-1]
                if cookies_str.startswith("'") and cookies_str.endswith("'"):
                    cookies_str = cookies_str[1:-1]
                
                cookies = {}
                for item in cookies_str.split(";"):
                    item = item.strip()
                    if "=" in item:
                        key, value = item.split("=", 1)
                        cookies[key.strip()] = value.strip()
                
                print(f"Found {len(cookies)} cookies:")
                for key, value in cookies.items():
                    print(f"  - {key}: {value[:20]}..." if len(value) > 20 else f"  - {key}: {value}")
                
                required = ["wr_skey", "wr_vid", "wr_rt"]
                missing = [c for c in required if c not in cookies]
                if missing:
                    print(f"\n❌ MISSING required cookies: {', '.join(missing)}")
                    print("   Get fresh cookies from browser!")
                else:
                    print("\n✅ All required cookies present")
                    if len(cookies) < 3:
                        print("⚠️  You have the minimum, but more cookies might help")
else:
    print("No .env file found")

print()
print("=" * 60)

