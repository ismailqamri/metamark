#!/usr/bin/env bash
# cleanup_duplicates.sh
# ---------------------
# Finishes the "consolidate safely" cleanup for the Metamark project:
#   * moves deprecated/duplicate backend files into legal_metrology/_archive/
#   * removes the stale "extension - Copy" folder (the live one is "extension")
#
# Uses `git mv` / `git rm` so history is preserved when run inside the repo.
# Falls back to plain filesystem moves/deletes if git isn't available.
#
# Usage:
#   bash cleanup_duplicates.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND="$ROOT/legal_metrology_backend/legal_metrology"
ARCHIVE="$BACKEND/_archive"

USE_GIT=0
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    USE_GIT=1
fi

mkdir -p "$ARCHIVE"

for f in app.py main.py tempCodeRunnerFile.py rag_compliance.py; do
    src="$BACKEND/$f"
    dst="$ARCHIVE/$f"
    if [ -f "$src" ]; then
        echo "Archiving $f ..."
        if [ "$USE_GIT" -eq 1 ]; then
            git mv -f -- "$src" "$dst" 2>/dev/null || mv -f -- "$src" "$dst"
        else
            mv -f -- "$src" "$dst"
        fi
    else
        echo "Skipping $f (not found)"
    fi
done

DUP_EXT="$ROOT/extension - Copy"
if [ -d "$DUP_EXT" ]; then
    echo 'Removing "extension - Copy" ...'
    if [ "$USE_GIT" -eq 1 ]; then
        git rm -r --quiet -- "$DUP_EXT" 2>/dev/null || rm -rf -- "$DUP_EXT"
    else
        rm -rf -- "$DUP_EXT"
    fi
else
    echo 'Skipping "extension - Copy" (not found)'
fi

echo
echo "Done. Review with:  git status"
echo 'Then commit:        git commit -m "chore: archive duplicate/deprecated files"'
