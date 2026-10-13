#!/usr/bin/env bash
# sync-phases-version: 12
#
# Makes the host's milestones match docs/roadmap.md, or reports that they do not.
#
#   sync-phases.sh [--check] [--roadmap FILE]
#     default   create missing milestones and close the ones whose phase is done
#     --check   change nothing; report what is missing or drifted
#   FORGE_DRY_RUN=1  the milestone READ is still real (see the read below); only the writes are held
#                    and printed as `[dry-run]` lines. The summary line then says `would create` or
#                    `would close`, never `created` or `closed`, because nothing was sent (#307).
#                    Only the exact value 1 counts, as in forge-lib.sh; `true` is a real run.
#
# Exit codes are distinguishable, because this runs from automation:
#   0  in sync (or synced successfully)
#   1  --check found drift; nothing is wrong with the tooling
#   2  usage or environment error
#   3  the roadmap is malformed; NOTHING was written
#   4  a write failed part-way; the host may be partially synced
#
# NEVER DELETES. A milestone that is not in the roadmap is reported and left alone: it may be
# holding someone's tickets, and a sync that deletes what it does not recognise is a footgun aimed
# at other people's data. Same rule and same reason as sync-labels.sh.
#
# NEVER REOPENS EITHER. A phase moved back from done to open is reported, not acted on: reopening a
# milestone is rare and is a human decision, and check-phases.sh rule 3 already reports the
# disagreement. Doing it silently would undo a close somebody meant.
#
# ONE MALFORMED BLOCK STOPS THE WHOLE FILE, rather than syncing the phases it could parse. A partial
# sync is exactly the drift this exists to end.

# NO `awk -v` IN THIS FILE (#259). `-v` runs a backslash-escape pass over its value and Apple's awk
# refuses one holding a newline, so the one site that took a value, the MALFORMED diagnostic's
# `--roadmap` path (caller text), reads it through ENVIRON instead. scripts/test-sync-phases.sh
# counts zero `awk ... -v` lines (scripts/awkv-count.sh, continuations joined). No awk takes a file
# operand either (#405): a `name=value` operand is an assignment, so files come in through `<`.
set -uo pipefail

# The roadmap format lives in roadmap-lib.sh, defined once (#162). Anchored to this script's own
# location, never the working directory: both assets land in the same directory in the source tree
# and in a forge-adapt install, so adjacency holds in both shapes.
_HERE_LIB="$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_HERE_LIB/roadmap-lib.sh" ]; then
  # shellcheck source=roadmap-lib.sh
  . "$_HERE_LIB/roadmap-lib.sh"
else
  echo "sync-phases: roadmap-lib.sh not found next to this script. It defines the roadmap format," >&2
  echo "  so nothing can be synced without it. Install it alongside this asset." >&2
  exit 2
fi

SELF="$(abspath "${BASH_SOURCE[0]}")"


die() { printf 'sync-phases: %s\n' "$1" >&2; exit 2; }

MODE=sync
ROADMAP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check)    MODE=check ;;
    --roadmap)  shift; [ $# -gt 0 ] || die "--roadmap needs a path"; ROADMAP="$1" ;;
    --help|-h)  awk 'NR==1{next} /^# *[a-z0-9-]+-version: [0-9]+$/{next} /^#/{sub(/^# ?/,""); print; next} {exit}' < "$SELF"; exit 0 ;;
    -*)         die "unknown flag: $1" ;;
    *)          die "unexpected argument: $1" ;;
  esac
  shift
done

if [ -z "$ROADMAP" ]; then
  for c in docs/roadmap.md roadmap.md; do [ -f "$c" ] && { ROADMAP="$c"; break; }; done
fi
if [ -z "$ROADMAP" ]; then
  echo "sync-phases: no roadmap at docs/roadmap.md or roadmap.md, so there is nothing to sync." >&2
  echo "  This is not an error: the group is opt-in by the presence of the file." >&2
  exit 0
fi

HERE="$(CDPATH= cd -- "$(dirname "$SELF")" && pwd)"
# Resolving forge-lib.sh: BESIDE, then by SEARCH, never by $CLAUDE_PLUGIN_ROOT.
#
# In a forge-adapt install both assets land in scripts/ and adjacency works. In the forge-kit source
# tree they belong to DIFFERENT skills and can never be adjacent, so adjacency alone works in one
# shape and degrades in the other. A degraded run here does not error, it just stops checking, which
# is the silent failure .claude/memory/shipped-asset-path-resolution.md was written about.
find_forge_lib() {
  [ -n "${FORGE_LIB:-}" ] && [ -f "$FORGE_LIB" ] && { printf '%s' "$FORGE_LIB"; return 0; }
  [ -f "$HERE/forge-lib.sh" ] && { printf '%s' "$HERE/forge-lib.sh"; return 0; }
  local root p
  root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$root" ]; then
    for p in "$root"/scripts/forge-lib.sh \
             "$root"/plugins/*/skills/forge-host/assets/forge-lib.sh; do
      [ -f "$p" ] && { printf '%s' "$p"; return 0; }
    done
  fi
  # LAST RESORT, and the one place the choice is ambiguous (#189). ~/.claude/plugins holds plugin
  # versions SIDE BY SIDE: the cache keeps every installed semver and the marketplace checkout is
  # one more copy, and `find` lists them in directory order. `head -1` picked an arbitrary one,
  # stale three gate runs out of four on the machine that filed the ticket, and nothing said which.
  # Highest `forge-lib-version` marker wins; the path breaks a tie, which is safe because
  # check-version-bump.sh makes an equal marker imply an equal committed body; a copy with no
  # marker is skipped, since it predates the contract this script sources. The pick is PRINTED so
  # a stale one is visible in the run rather than plausible and silent.
  p="$(find "$HOME/.claude/plugins" -name forge-lib.sh 2>/dev/null | while IFS= read -r f; do
         v="$(grep -m1 -o '^# forge-lib-version: [0-9][0-9]*' "$f" 2>/dev/null | grep -o '[0-9]*$')"
         [ -n "$v" ] && printf '%s\t%s\n' "$v" "$f"
       done | sort -t "$(printf '\t')" -k1,1n -k2,2 | tail -1 | cut -f2-)"
  [ -n "$p" ] && {
    echo "sync-phases: forge-lib.sh from $p ($(grep -m1 -o 'forge-lib-version: [0-9]*' "$p"))" >&2
    printf '%s' "$p"; return 0
  }
  return 1
}
if ! LIB="$(find_forge_lib)"; then
  echo "sync-phases: forge-lib.sh not found, so nothing can be synced." >&2
  echo "  This group DEPENDS on forge-kit-devops, which ships forge-lib.sh (#161). Install it:" >&2
  echo "      /plugin install forge-kit-devops@forge-kit" >&2
  echo "  or point FORGE_LIB at a copy, or pass --offline to check the file-only rule deliberately." >&2
  exit 2
fi
# shellcheck source=forge-lib.sh
. "$LIB"

PHASES="$(parse_roadmap "$ROADMAP")"
if grep -q '^MALFORMED' <<< "$PHASES"; then
  printf '%s\n' "$PHASES" \
    | SP_F="$ROADMAP" awk -F'\t' '/^MALFORMED/ {printf("sync-phases: %s: phase \"%s\": %s\n", ENVIRON["SP_F"], $2, $3)}' >&2
  echo "sync-phases: state must be one of: planned, open, done, backlog." >&2
  echo "  NOTHING was written. A partial sync is the drift this exists to end." >&2
  exit 3
fi

# FORGE_DRY_RUN=0 is scoped to this substitution on purpose (#269). forge_api_paginate short-circuits
# to a literal `[]` under FORGE_DRY_RUN=1, GET included, so without it every phase reads as missing
# and --check reports `would create milestone` for milestones that exist. A read has no side effect,
# and the prefix assignment dies with the substitution's subshell, so there is nothing to restore,
# the caller's flag is untouched, and the writes below still see it and stay held. Do NOT hoist this
# to a top-level `FORGE_DRY_RUN=0`: that would let the writes through. The close under the flag also
# relies on forge_milestone_close deciding the dry run before it resolves the title (forge-lib v28,
# #254); this change must not reach `main` before that one (#254 closed, or its commit an ancestor).
MS="$(FORGE_DRY_RUN=0 forge_milestone_list)" || die "could not list milestones; check the token and the forge configuration"

drift=0
while IFS="$(printf '\t')" read -r name state plan; do
  [ -n "$name" ] || continue
  ms_state="$(printf '%s' "$MS" | jq -r --arg t "$name" '.[] | select(.title == $t) | .state' | head -1)"
  if [ -z "$ms_state" ]; then
    if [ "$MODE" = check ]; then
      echo "would create milestone \"$name\""; drift=$((drift + 1))
    else
      forge_milestone_create "$name" "Phase from $ROADMAP" || exit 4
      # #307: the library held the write under the flag, so say `would`. Same predicate as forge-lib.
      if [ "${FORGE_DRY_RUN:-0}" = 1 ]; then echo "would create milestone \"$name\""
      else echo "created milestone \"$name\""; fi
    fi
    continue
  fi
  if [ "$state" = done ] && [ "$ms_state" = open ]; then
    if [ "$MODE" = check ]; then
      echo "would close milestone \"$name\""; drift=$((drift + 1))
    else
      forge_milestone_close "$name" || exit 4
      if [ "${FORGE_DRY_RUN:-0}" = 1 ]; then echo "would close milestone \"$name\""
      else echo "closed milestone \"$name\""; fi
    fi
    continue
  fi
  if [ "$state" != done ] && [ "$ms_state" = closed ]; then
    # Reported, never acted on. See the header: reopening is a human decision.
    echo "note: phase \"$name\" is $state but its milestone is closed. Reopen it by hand if that is wrong; nothing is reopened automatically."
    [ "$MODE" = check ] && drift=$((drift + 1))
  fi
done <<EOF
$PHASES
EOF

# Undeclared milestones: reported, never deleted.
declared="$(printf '%s\n' "$PHASES" | cut -f1)"
while read -r t; do
  [ -n "$t" ] || continue
  grep -qxF "$t" <<< "$declared" \
    || echo "note: milestone \"$t\" is on the host but not in $ROADMAP. Left alone; nothing is ever deleted."
done <<EOF
$(printf '%s' "$MS" | jq -r '.[] | select(.state == "open") | .title')
EOF

if [ "$MODE" = check ] && [ "$drift" -gt 0 ]; then exit 1; fi
exit 0
