#!/usr/bin/env bash
# Sync docs/wiki/*.md to the GitHub wiki remote (separate git repo).
#
# Usage:
#   ./docs/wiki/sync-wiki.sh
#   ./docs/wiki/sync-wiki.sh git@github.com:Exios66/local-mailroom-sandbox.wiki.git
#
# Enable the Wiki tab and create the first page before the first clone.
set -euo pipefail

WIKI_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$WIKI_DIR/../.." && pwd)"
REPO_URL="${1:-}"

if [[ -z "$REPO_URL" ]]; then
  REPO_URL="$(cd "$REPO_ROOT" && git remote get-url origin 2>/dev/null || true)"
fi
if [[ -z "$REPO_URL" ]]; then
  echo "Usage: $0 <repo-url>" >&2
  exit 1
fi

WIKI_REPO_URL="${REPO_URL%.git}.wiki.git"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Cloning $WIKI_REPO_URL"
git clone "$WIKI_REPO_URL" "$TEMP_DIR" || {
  echo "Create the first wiki page on GitHub, then retry." >&2
  exit 1
}

cp "$WIKI_DIR"/*.md "$TEMP_DIR/"
# GitHub wiki home page is Home.md
cd "$TEMP_DIR"
git add -A
git commit -m "Sync wiki pages from local-mailroom-sandbox docs/wiki" || echo "No changes to commit"
git push origin HEAD

echo "View: ${REPO_URL%.git}/wiki"
