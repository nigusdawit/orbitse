#!/usr/bin/env bash
# publish — push your CURRENT feature branch to your fork and hand you the PR link
# into master (roofing). This is the teammate "up": integrate via Pull Request,
# not a direct push to master.
#
# Usage:
#   git checkout -b feature/your-thing   # then edit + commit
#   bash scripts/publish.sh
set -euo pipefail

FORK_REMOTE="${FORK_REMOTE:-origin}"
MASTER_SLUG="${MASTER_SLUG:-Aaltaye/roofing-concierge}"   # owner/repo of master
MAIN="${MAIN:-main}"

BR="$(git rev-parse --abbrev-ref HEAD)"
[ "$BR" != "$MAIN" ] || { echo "✗ You're on '$MAIN'. Make a feature branch first: git checkout -b feature/your-thing"; exit 1; }

echo "→ Pushing '$BR' to your fork ($FORK_REMOTE) …"
git push -u "$FORK_REMOTE" "$BR"

# Derive your GitHub username from the fork's origin URL, for the cross-fork PR link.
owner="$(git remote get-url "$FORK_REMOTE" | sed -E 's#(git@[^:]+:|https?://[^/]+/)([^/]+)/.*#\2#')"

echo ""
echo "✓ Pushed. Open a Pull Request into master:"
if command -v gh >/dev/null 2>&1; then
  gh pr create --repo "$MASTER_SLUG" --base "$MAIN" --head "${owner}:${BR}" --web 2>/dev/null \
    || echo "   https://github.com/$MASTER_SLUG/compare/$MAIN...${owner}:${BR}?expand=1"
else
  echo "   https://github.com/$MASTER_SLUG/compare/$MAIN...${owner}:${BR}?expand=1"
fi
