#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/dexterai/.openclaw/workspace/ai-tech-lead-digest"
cd "$REPO_DIR"

DATE=${1:-$(date +%F)}
ISSUE_PATH=$(python3 tools/generate_issue.py --date "$DATE")

# Commit + push

git add docs/feed.json "docs/$ISSUE_PATH" || true
if ! git diff --cached --quiet; then
  git commit -m "digest: $DATE" >/dev/null
  git push >/dev/null
fi

PAGES_URL="https://dexterai-bot.github.io/ai-tech-lead-digest/$ISSUE_PATH"
ARCHIVE_URL="https://dexterai-bot.github.io/ai-tech-lead-digest/"

MSG=$(cat <<EOF
AI Tech Lead Digest — $DATE

• Full issue: $PAGES_URL
• Archive: $ARCHIVE_URL
EOF
)

openclaw message send --channel telegram --target -5241424017 --message "$MSG" --json >/dev/null
