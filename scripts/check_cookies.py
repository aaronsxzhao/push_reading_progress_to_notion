#!/usr/bin/env python3
"""
Check WeRead cookies status and diagnose issues
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.weread_api import WeReadAPI, env

def check_cookies():
    """Check cookie status and diagnose issues"""
    print("=" * 80)
    print("WeRead Cookie Diagnostic Tool")
    print("=" * 80)
    print()
    
    # Load cookies from env
    cookies_str = env("WEREAD_COOKIES")
    
    if not cookies_str:
        print("❌ ERROR: WEREAD_COOKIES not found in environment")
        print()
        print("🔧 SOLUTION:")
        print("   1. Make sure you have a .env file")
        print("   2. Add: WEREAD_COOKIES=wr_skey=xxx; wr_vid=xxx; wr_rt=xxx")
        print("   3. Run: set -a && source .env && set +a")
        return False
    
    # Parse cookies
    cookie_dict = {}
    cookies = cookies_str.strip()
    if cookies.startswith('"') and cookies.endswith('"'):
        cookies = cookies[1:-1]
    if cookies.startswith("'") and cookies.endswith("'"):
        cookies = cookies[1:-1]
    
    for item in cookies.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            cookie_dict[key] = value
    
    print(f"📋 Found {len(cookie_dict)} cookies in .env")
    print()
    
    # Check required cookies
    required = ["wr_skey", "wr_vid", "wr_rt"]
    missing = [c for c in required if c not in cookie_dict]
    
    if missing:
        print(f"❌ MISSING REQUIRED COOKIES: {', '.join(missing)}")
        print()
        print("🔧 Get fresh cookies:")
        print("   1. Open https://weread.qq.com in browser")
        print("   2. Log in")
        print("   3. Press F12 → Application → Cookies → weread.qq.com")
        print("   4. Copy ALL cookie values")
        print("   5. Update .env file")
        return False
    
    print("✅ All required cookies present:")
    for req in required:
        value = cookie_dict[req]
        print(f"   - {req}: {value[:30]}..." if len(value) > 30 else f"   - {req}: {value}")
    print()
    
    # Check recommended cookies
    recommended = ["wr_name", "wr_localvid", "wr_gid", "wr_uid"]
    missing_rec = [c for c in recommended if c not in cookie_dict]
    if missing_rec:
        print(f"⚠️  Missing recommended cookies: {', '.join(missing_rec)}")
        print("   (These help with cookie validation)")
    else:
        print("✅ All recommended cookies present")
    print()
    
    # Test cookies
    print("🧪 Testing cookies with WeRead API...")
    print()
    
    try:
        client = WeReadAPI(cookies_str)
        is_valid = client.validate_cookies()
        
        if is_valid:
            print()
            print("=" * 80)
            print("✅ COOKIES ARE VALID - Ready to sync!")
            print("=" * 80)
            return True
        else:
            print()
            print("=" * 80)
            print("❌ COOKIES ARE EXPIRED OR INVALID")
            print("=" * 80)
            print()
            print("🔧 ACTION REQUIRED:")
            print("   1. Open https://weread.qq.com in your browser")
            print("   2. Make sure you're logged in")
            print("   3. Press F12 → Application → Cookies → weread.qq.com")
            print("   4. Copy ALL cookie values (especially wr_skey, wr_vid, wr_rt)")
            print("   5. Update WEREAD_COOKIES in your .env file")
            print("   6. Format: wr_skey=xxx; wr_vid=xxx; wr_rt=xxx")
            print()
            print("💡 TIP: Cookies expire after some time. Get fresh ones from browser.")
            return False
            
    except ValueError as e:
        print()
        print("=" * 80)
        print("❌ COOKIE ERROR")
        print("=" * 80)
        print(f"Error: {e}")
        return False
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ UNEXPECTED ERROR")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Load .env if available
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    
    success = check_cookies()
    sys.exit(0 if success else 1)
