#!/usr/bin/env bash
# Report phases whose roadmap status disagrees with their GitHub milestone.
#
# `docs/roadmap.md` is the one place that says what is built, and for two
# phases it said the opposite: Phase 8 was closed on GitHub with twelve issues
# and marked nothing at all here, and Phase 12 went on saying "runs next" for
# two days after it shipped. Nobody noticed, because nothing asked.
#
# **This cannot be a pytest gate and that is deliberate.** The answer lives on
# GitHub, so the check needs the network and an authenticated `gh`. A gate that
# needs both fails on a fork, in an offline checkout, and in any CI leg without
# a token, which turns a governance check into a broken build. It is a script
# the release skill runs and a person runs before planning a phase, which is
# the same argument `check-ticket-hygiene.sh` makes and the same one behind the
# skip in `test_every_mutated_module_loads_the_security_rules_when_it_is_edited`.
#
# What it checks, in both directions:
#   - a closed milestone whose phase is not marked done here
#   - a phase marked done here whose milestone still has open issues
#   - a phase marked in progress whose milestone is closed, and vice versa
#
# Usage: check-roadmap-matches-milestones.sh [owner/repo]
# Exit:  0 every phase agrees with its milestone
#        1 at least one disagrees
#        2 gh is unavailable or the repo cannot be read
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROADMAP="$ROOT/docs/roadmap.md"

REPO="${1:-}"
if [ -z "$REPO" ]; then
  REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null) || {
    echo "check-roadmap-matches-milestones: cannot determine the repository" >&2
    exit 2
  }
fi

MILESTONES=$(gh api "repos/$REPO/milestones?state=all&per_page=100" \
  --jq '.[] | "\(.title)\t\(.state)\t\(.open_issues)"' 2>/dev/null) || {
  echo "check-roadmap-matches-milestones: cannot read milestones from $REPO" >&2
  exit 2
}

MILESTONES="$MILESTONES" ROADMAP="$ROADMAP" python3 - <<'PY'
import os
import re
import sys

milestones = {}
for line in os.environ["MILESTONES"].splitlines():
    if not line.strip():
        continue
    title, state, open_issues = line.split("\t")
    match = re.match(r"(Phase \d+)", title)
    if match:
        milestones[match.group(1)] = (state, int(open_issues))

# Phase 0 predates the milestones entirely: the design was approved before there
# was a repository to track it in. Named rather than skipped by a rule, so a
# phase that loses its milestone by accident still fails below.
NO_MILESTONE = {"Phase 0"}

road = open(os.environ["ROADMAP"]).read()
sections = list(re.finditer(r"^## (Phase \d+)[^\n]*$(.*?)(?=^## |\Z)", road, re.M | re.S))
if not sections:
    sys.exit("check-roadmap-matches-milestones: no phase sections found in the roadmap")

problems = []
for match in sections:
    name, body, heading = match.group(1), match.group(2), match.group(0).split("\n")[0]
    if "**Status: done" in body or "(done)" in heading:
        status = "done"
    elif "**Status: in progress" in body:
        status = "in progress"
    else:
        status = "planned"

    if name in NO_MILESTONE:
        if name in milestones:
            problems.append(f"{name} has a milestone now; remove it from NO_MILESTONE")
        continue

    if name not in milestones:
        problems.append(f"{name} is in the roadmap and has no milestone")
        continue

    state, open_issues = milestones[name]
    if state == "closed" and status != "done":
        problems.append(
            f"{name} is CLOSED on GitHub and the roadmap says {status!r}. "
            "Add the status line with the closing date and the issues."
        )
    elif state == "open" and status == "done":
        problems.append(
            f"{name} is marked done in the roadmap and its milestone is open "
            f"with {open_issues} issues. Close the milestone or unmark the phase."
        )
    elif state == "closed" and open_issues:
        problems.append(f"{name}: milestone closed with {open_issues} still open")

if problems:
    print("check-roadmap-matches-milestones: the roadmap and GitHub disagree:")
    for problem in problems:
        print(f"  {problem}")
    sys.exit(1)

print(f"check-roadmap-matches-milestones: all {len(sections)} phases agree with their milestones.")
PY
