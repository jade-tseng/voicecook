#!/bin/bash
# Install pre-commit hook for secret detection
# This script copies the pre-commit hook to .git/hooks/

set -e

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK_SOURCE="$PROJECT_ROOT/hook/pre-commit"
HOOK_TARGET="$PROJECT_ROOT/.git/hooks/pre-commit"

# Check if we're in a git repository
if [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo "❌ Error: Not a git repository"
    exit 1
fi

# Check if hook source exists
if [ ! -f "$HOOK_SOURCE" ]; then
    echo "❌ Error: Hook source not found at $HOOK_SOURCE"
    exit 1
fi

# Create .git/hooks directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/.git/hooks"

# Copy the hook
cp "$HOOK_SOURCE" "$HOOK_TARGET"
chmod +x "$HOOK_TARGET"

echo "✅ Pre-commit hook installed successfully!"
echo "📝 Hook location: $HOOK_TARGET"
echo ""
echo "The hook will now scan for secrets (API keys, tokens, etc.) before each commit."
echo ""
echo "To test the hook, try staging a file with a test API key and commit it."
echo "The hook will block commits containing secrets."