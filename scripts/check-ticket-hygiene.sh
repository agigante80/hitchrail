#!/usr/bin/env bash
# Report open issues that are missing a milestone or an area label.
#
# ticket-gate enforces both, but only on tickets somebody chose to run it on.
# This is the sweep: it sees everything, including the ticket filed last night
# and not looked at since. Run it before planning a phase.
#
# An empty milestone is NOT an error here. It means nobody has triaged the
# ticket yet, which is a real and temporary state, so it is reported separately
# from a ticket that is missing something it should have. `Backlog` is the
# answer for triaged work with no phase. See docs/guides/ticket-standards.md.
#
# Usage: check-ticket-hygiene.sh [owner/repo]
# Exit:  0 nothing missing (untriaged tickets alone do not fail)
#        1 at least one triaged ticket is missing an area label
#        2 gh is unavailable or the repo cannot be read
set -uo pipefail

REPO="${1:-}"
if [ -z "$REPO" ]; then
  REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null) || {
    echo "check-ticket-hygiene: cannot determine the repository (is gh authenticated?)" >&2
    exit 2
  }
fi

# The area labels, from docs/guides/ticket-standards.md. Kept here rather than
# parsed out of the doc: a check that derives its expectation from the thing it
# is checking cannot fail.
AREAS="config discovery tmux procs claude-ipc ram events engine security server web cli packaging infrastructure documentation"

issues=$(gh issue list --repo "$REPO" --state open --limit 200 \
  --json number,title,milestone,labels 2>/dev/null) || {
  echo "check-ticket-hygiene: cannot read issues from $REPO" >&2
  exit 2
}

AREAS="$AREAS" python3 - "$issues" <<'PY'
import json
import os
import sys

areas = set(os.environ["AREAS"].split())
issues = json.loads(sys.argv[1])

untriaged: list[str] = []
no_area: list[str] = []

for issue in issues:
    number = issue["number"]
    title = issue["title"][:58]
    labels = {label["name"] for label in issue["labels"]}
    milestone = (issue.get("milestone") or {}).get("title")

    if milestone is None:
        untriaged.append(f"  #{number:<4} {title}")
        # Not yet triaged, so a missing area label is not news about it.
        continue
    if not labels & areas:
        no_area.append(f"  #{number:<4} [{milestone}] {title}")

if untriaged:
    print(f"Untriaged, no milestone yet ({len(untriaged)}):")
    print("\n".join(untriaged))
    print("  Give each a phase, or Backlog if it has no phase. Empty means unread.")
    print()

if no_area:
    print(f"Triaged but missing an area label ({len(no_area)}):")
    print("\n".join(no_area))
    print(f"  One of: {', '.join(sorted(areas))}")
    print("  ticket-gate refuses to score these, because the label is what routes the agents.")
    print()

if not untriaged and not no_area:
    print(f"check-ticket-hygiene: all {len(issues)} open issues carry a milestone and an area label.")

sys.exit(1 if no_area else 0)
PY
