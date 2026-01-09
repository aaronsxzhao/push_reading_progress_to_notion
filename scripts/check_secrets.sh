#!/usr/bin/env bash
# Quick check to ensure no secrets are committed to git

set -euo pipefail

echo "🔒 Checking for accidentally committed secrets..."

# Check if .env is tracked (it shouldn't be)
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "❌ ERROR: .env file is tracked in git! This is dangerous."
  echo "   Run: git rm --cached .env"
  exit 1
else
  echo "✅ .env is NOT tracked (safe)"
fi

# Check for hardcoded secrets in code
if grep -r "secret_[a-zA-Z0-9]" --include="*.py" --include="*.sh" src/ scripts/ 2>/dev/null | grep -v "secret_xxx" | grep -v ".example"; then
  echo "❌ WARNING: Found potential hardcoded secrets in code"
  exit 1
else
  echo "✅ No hardcoded secrets found in code"
fi

# Check .env.example has placeholders
if grep -q "secret_xxx\|xxxxxxxx" .env.example 2>/dev/null; then
  echo "✅ .env.example contains safe placeholders"
else
  echo "⚠️  WARNING: .env.example might contain real values"
fi

echo ""
echo "✅ All security checks passed!"
echo ""
echo "Before pushing to GitHub, verify:"
echo "  1. git status (should NOT show .env)"
echo "  2. git diff (review changes)"
echo "  3. This script passes ✅"


