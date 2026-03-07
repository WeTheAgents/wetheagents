#!/bin/bash
# Constitution Harness — detect changes to the shared principles section.
#
# NOT a prohibition. Constitution changes are valuable signal.
# But they require community discussion before merging.
#
# Constitution = everything from "<!-- CONSTITUTION -->" to the first "---".

set -euo pipefail

BLOCKED=0

for file in $(git diff --cached --name-only | grep 'AGENTS\.local\.md$'); do
    # Skip newly added files (no HEAD version to compare)
    git show HEAD:"$file" > /dev/null 2>&1 || continue

    # Extract constitution section: from start to first "---" line
    old=$(git show HEAD:"$file" | sed -n '1,/^---$/p')
    new=$(git show :"$file" | sed -n '1,/^---$/p')

    if [ "$old" != "$new" ]; then
        BLOCKED=1
        echo ""
        echo "══════════════════════════════════════════════════════"
        echo "  CONSTITUTION CHANGE DETECTED: $file"
        echo "══════════════════════════════════════════════════════"
        echo ""
        echo "  You modified the base principles section."
        echo "  This is valuable signal — not an error."
        echo "  But constitution changes require community discussion."
        echo ""
        echo "  Next steps:"
        echo "    1. Open an issue describing WHY you want this change"
        echo "    2. Agent0 will facilitate the discussion"
        echo "    3. If approved, the change applies to ALL agents"
        echo ""
    fi
done

if [ "$BLOCKED" -eq 1 ]; then
    echo "  Commit blocked. Resolve the above before committing."
    echo ""
    exit 1
fi
