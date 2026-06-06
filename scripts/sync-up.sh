#!/usr/bin/env bash
# sync-up — push your fork's main UP to MASTER (roofing).
#
# Fast-forward ONLY: if master has moved since you last synced, it stops and tells
# you to run sync-down first. It NEVER force-pushes a shared branch.
#
# This is a DIRECT push to master — for the maintainer (or anyone with push rights
# to roofing/main). Teammates normally integrate via a Pull Request instead — see
# scripts/publish.sh.
#
# Usage:
#   bash scripts/sync-up.sh
#   MASTER_REMOTE=roofing bash scripts/sync-up.sh     # if your master remote is named differently
set -euo pipefail

MASTER_REMOTE="${MASTER_REMOTE:-upstream}"
MAIN="${MAIN:-main}"

cur="$(git rev-parse --abbrev-ref HEAD)"
[ "$cur" = "$MAIN" ] || { echo "✗ You're on '$cur', not '$MAIN'. Run: git checkout $MAIN"; exit 1; }
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "✗ Working tree not clean — commit your changes first."; exit 1
fi

echo "→ Fetching $MASTER_REMOTE/$MAIN …"
git fetch "$MASTER_REMOTE" "$MAIN"

# Master moved ahead of you → you must merge it in first (no force-push, ever).
if ! git merge-base --is-ancestor "$MASTER_REMOTE/$MAIN" "$MAIN"; then
  echo ""
  echo "⚠ Master ($MASTER_REMOTE/$MAIN) has commits you don't have."
  echo "  Run:  bash scripts/sync-down.sh   (merge them in), then re-run sync-up."
  exit 1
fi

# Nothing new to push.
if git merge-base --is-ancestor "$MAIN" "$MASTER_REMOTE/$MAIN"; then
  echo "✓ Master already has your $MAIN — nothing to push."; exit 0
fi

echo "→ Pushing $MAIN → $MASTER_REMOTE/$MAIN (fast-forward) …"
git push "$MASTER_REMOTE" "$MAIN:$MAIN"
echo "✓ Pushed to master ($MASTER_REMOTE)."
