#!/usr/bin/env bash
# sync-down — pull the latest from MASTER (roofing) into your fork's main.
#
# Works the same for the maintainer and every teammate:
#   origin   = your own fork        (FORK_REMOTE)
#   upstream = roofing-concierge    (MASTER_REMOTE, the shared master)
# Does a real 3-way merge (conflicts are surfaced, never auto-clobbered) and
# NEVER force-pushes.
#
# Usage:
#   bash scripts/sync-down.sh
#   MASTER_REMOTE=roofing bash scripts/sync-down.sh   # if your master remote is named differently
set -euo pipefail

MASTER_REMOTE="${MASTER_REMOTE:-upstream}"
FORK_REMOTE="${FORK_REMOTE:-origin}"
MAIN="${MAIN:-main}"

cur="$(git rev-parse --abbrev-ref HEAD)"
[ "$cur" = "$MAIN" ] || { echo "✗ You're on '$cur', not '$MAIN'. Run: git checkout $MAIN"; exit 1; }
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "✗ Working tree not clean — commit or stash your changes first."; exit 1
fi

echo "→ Fetching $MASTER_REMOTE/$MAIN …"
git fetch "$MASTER_REMOTE" "$MAIN"

echo "→ Merging $MASTER_REMOTE/$MAIN into $MAIN …"
if ! git merge --no-edit "$MASTER_REMOTE/$MAIN"; then
  echo ""
  echo "⚠ Merge conflict. Resolve the listed files, then:"
  echo "    git add -A && git commit && git push $FORK_REMOTE $MAIN"
  exit 1
fi

echo "→ Pushing $MAIN to your fork ($FORK_REMOTE) …"
git push "$FORK_REMOTE" "$MAIN"
echo "✓ $MAIN is up to date with master ($MASTER_REMOTE/$MAIN) and pushed to your fork."
