#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/dexterai/.openclaw/workspace/ai-tech-lead-digest"
cd "$REPO_DIR"

DATE=${1:-$(date +%F)}
ISSUE_PATH=$(python3 tools/generate_issue.py --date "$DATE")

# Commit + push

git add site/feed.json "site/$ISSUE_PATH" || true
if ! git diff --cached --quiet; then
  git commit -m "digest: $DATE" >/dev/null
  git push >/dev/null
fi

PAGES_URL="https://dexterai-bot.github.io/ai-tech-lead-digest/site/$ISSUE_PATH"

MSG=$(cat <<EOF
AI Tech Lead Digest — $DATE

• Read the full issue: $PAGES_URL
EOF
)

openclaw message send --channel telegram --target -5241424017 --message "$MSG" --json >/dev/null
