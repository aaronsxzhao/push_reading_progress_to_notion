#!/usr/bin/env python3
"""
Create a private GitHub Gist to store WeRead cookies.
This allows cookies to be automatically updated and synced to GitHub Actions.

Usage:
    python scripts/setup_cookie_gist.py

Requirements:
    - GH_TOKEN environment variable (GitHub token with gist scope)
    - WEREAD_COOKIES in .env file
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system("pip install requests")
    import requests

from dotenv import load_dotenv

def main():
    # Load .env
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
    
    gh_token = os.environ.get("GH_TOKEN")
    cookies = os.environ.get("WEREAD_COOKIES", "")
    
    if not gh_token:
        print("❌ GH_TOKEN not found!")
        print()
        print("1. Create a GitHub token at: https://github.com/settings/tokens/new")
        print("   - Select scopes: 'gist' (required) + 'repo' + 'workflow'")
        print("2. Add to .env file:")
        print('   GH_TOKEN="ghp_xxxxxxxxxxxx"')
        return 1
    
    if not cookies:
        print("❌ WEREAD_COOKIES not found in .env!")
        print("   Run: python scripts/fetch_cookies_auto.py")
        return 1
    
    # Clean cookies string
    if cookies.startswith('"') and cookies.endswith('"'):
        cookies = cookies[1:-1]
    
    print("Creating private GitHub Gist for cookies...")
    
    response = requests.post(
        "https://api.github.com/gists",
        headers={
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github.v3+json"
        },
        json={
            "description": "WeRead Cookies (auto-updated)",
            "public": False,
            "files": {
                "weread_cookies.txt": {
                    "content": cookies
                }
            }
        }
    )
    
    if response.status_code == 201:
        gist = response.json()
        gist_id = gist["id"]
        gist_url = gist["html_url"]
        
        print(f"✅ Gist created successfully!")
        print()
        print(f"   Gist ID: {gist_id}")
        print(f"   URL: {gist_url}")
        print()
        
        # Update .env file
        content = env_path.read_text(encoding='utf-8')
        if 'COOKIE_GIST_ID=' not in content:
            with open(env_path, 'a') as f:
                f.write(f'\n# GitHub Gist for cookie sync\nCOOKIE_GIST_ID="{gist_id}"\n')
            print("✅ Added COOKIE_GIST_ID to .env")
        
        print()
        print("📋 Add these secrets to GitHub (Settings → Secrets → Actions):")
        print()
        print(f"   GH_TOKEN       = {gh_token[:10]}...")
        print(f"   COOKIE_GIST_ID = {gist_id}")
        print()
        print("Now when you run sync locally and cookies refresh,")
        print("they'll automatically sync to the Gist for GitHub Actions to use!")
        
        return 0
    else:
        print(f"❌ Failed to create Gist: {response.status_code}")
        print(response.text)
        return 1


if __name__ == "__main__":
    sys.exit(main())
