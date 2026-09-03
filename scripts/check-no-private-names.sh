#!/usr/bin/env bash
# Refuse to commit anything that names this machine, its owner, or a project
# that is not this one.
#
# The repository is public. It carried 52 real folder names in the design
# canvas for weeks, several of them personal, because a demo list was built
# from a real machine's projects and nobody looked again. This is the guard
# that was missing.
#
# Scans STAGED content only, so it costs nothing until you commit and it
# cannot be fooled by an unstaged working tree.
#
# Usage: check-no-private-names.sh [--all]
#        --all scans every tracked file rather than the staged diff.
# Exit:  0 clean, 1 something private is staged, 2 could not run.
set -uo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "check-no-private-names: not in a git repository" >&2; exit 2; }

# The list lives OUTSIDE the repository, in the unpublished .claude/ directory,
# because a public file enumerating the private names is its own leak: it would
# tell a reader exactly what to search the history for.
DENY_FILE="${HITCHRAIL_PRIVATE_NAMES:-.claude/private-names.txt}"

if [ ! -f "$DENY_FILE" ]; then
  echo "check-no-private-names: no $DENY_FILE, so nothing to check against." >&2
  echo "  This guard is only as good as that list. Create it, one pattern per" >&2
  echo "  line, '#' for comments. It is deliberately not tracked." >&2
  exit 0
fi

if [ "${1:-}" = "--all" ]; then
  FILES=$(git ls-files)
else
  FILES=$(git diff --cached --name-only --diff-filter=ACMR)
fi
[ -z "$FILES" ] && exit 0

found=0
while IFS= read -r pattern; do
  case "$pattern" in ''|'#'*) continue ;; esac
  while IFS= read -r file; do
    [ -f "$file" ] || continue
    # The STAGED blob, not the file on disk: they differ whenever something is
    # half added, and the staged one is what a commit would publish.
    if [ "${1:-}" = "--all" ]; then
      content=$(cat "$file" 2>/dev/null)
    else
      content=$(git show ":$file" 2>/dev/null)
    fi
    if printf '%s' "$content" | grep -qiF -- "$pattern"; then
      echo "  $file carries '$pattern'"
      found=1
    fi
  done <<< "$FILES"
done < "$DENY_FILE"

if [ "$found" -eq 1 ]; then
  cat >&2 <<'MSG'

check-no-private-names: refusing to commit.

This repository is public. The names above are on the private list, which means
they identify the machine, its owner, or somebody else's project.

Use a neutral placeholder. If a name genuinely belongs here, take it off the
list in .claude/private-names.txt and say why in the commit message.
MSG
  exit 1
fi
exit 0
