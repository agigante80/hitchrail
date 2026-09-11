#!/usr/bin/env bash
# check-phases-version: 4
#
# The roadmap-phases guard: four rules that make rolling wave planning mechanical.
#
#   check-phases.sh [--offline] [--roadmap FILE]
#     default     check everything; rules 1, 3 and 4 call the host
#     --offline   check only rule 2, which needs no host
#
# Exit 0 clean, 1 a rule found something, 2 could not run, 3 the roadmap is malformed.
#
# The rules, numbered as the messages number them:
#   1. Every open ticket has a phase. This is what makes the untriaged set a single query instead
#      of a full rescan, and it is what the method pays for by deferring plans.
#   2. Every `open` or `done` phase has a plan file carrying a "Fails if" section. `done` is
#      included so a phase moved straight from `planned` to `done` cannot skip the state where a
#      plan is required.
#   3. Roadmap state and milestone state agree, and at most one phase is `open`.
#   4. A phase marked `done` holds no open tickets. This is also the circuit breaker: closing a
#      phase forces every unfinished ticket somewhere explicit, so the default is to re-shape and
#      never to extend.
#
# SOURCE OF TRUTH. The roadmap owns which phases exist and their state; the host owns which phase
# each ticket is in. Different facts, so neither store duplicates the other and there is nothing to
# drift. The guard is what keeps that true.
#
# A CHECK THAT CANNOT RUN MUST NEVER REPORT CLEAN. An unreachable host exits 2 and says which rules
# did not run, the posture .githooks/pre-push already takes for a missing base ref.
#
# OPT-IN BY THE PRESENCE OF THE ROADMAP. A project with no roadmap.md has nothing to check and exits
# 0 saying so, the same posture check-private-leaks.sh takes for a missing name list. This group is
# optional and must not break a project that declines it.

set -uo pipefail

# The roadmap format lives in roadmap-lib.sh, defined once (#162). Anchored to this script's own
# location, never the working directory: both assets land in the same directory in the source tree
# and in a forge-adapt install, so adjacency holds in both shapes.
_HERE_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_HERE_LIB/roadmap-lib.sh" ]; then
  # shellcheck source=roadmap-lib.sh
  . "$_HERE_LIB/roadmap-lib.sh"
else
  echo "check-phases: roadmap-lib.sh not found next to this script. It defines the roadmap format," >&2
  echo "  so nothing can be checked without it. Install it alongside this asset." >&2
  exit 2
fi

SELF="$(abspath "${BASH_SOURCE[0]}")"

die() { printf 'check-phases: %s\n' "$1" >&2; exit 2; }

ROADMAP=""
OFFLINE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --offline)  OFFLINE=1 ;;
    --roadmap)  shift; [ $# -gt 0 ] || die "--roadmap needs a path"; ROADMAP="$1" ;;
    # Prints the whole comment header rather than a hardcoded line range, which is the bug that
    # made the leak scanners' --help truncate mid-sentence when their headers grew.
    --help|-h)  awk 'NR==1{next} /^# *[a-z0-9-]+-version: [0-9]+$/{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$SELF"; exit 0 ;;
    -*)         die "unknown flag: $1" ;;
    *)          die "unexpected argument: $1" ;;
  esac
  shift
done

# docs/ first, then the root, so a project that keeps it either place works with no flag.
if [ -z "$ROADMAP" ]; then
  for c in docs/roadmap.md roadmap.md; do [ -f "$c" ] && { ROADMAP="$c"; break; }; done
fi
if [ -z "$ROADMAP" ]; then
  echo "check-phases: no roadmap at docs/roadmap.md or roadmap.md, so there is nothing to check." >&2
  echo "  This is not an error: the guard is opt-in by the presence of the file." >&2
  exit 0
fi


PHASES="$(parse_roadmap "$ROADMAP")"
if printf '%s\n' "$PHASES" | grep -q '^MALFORMED'; then
  printf '%s\n' "$PHASES" \
    | awk -F'\t' -v f="$ROADMAP" '/^MALFORMED/ {printf("check-phases: %s: phase \"%s\": %s\n", f, $2, $3)}' >&2
  echo "check-phases: state must be one of: planned, open, done, backlog." >&2
  echo "  NOTHING was checked. A partially parsed roadmap reports phases as compliant that were never read." >&2
  exit 3
fi

violations=0
report() { printf '%s\n' "$1"; violations=$((violations + 1)); }

# --- rule 2 (file only) -----------------------------------------------------
while IFS="$(printf '\t')" read -r name state plan; do
  [ -n "$name" ] || continue
  case "$state" in open|done) ;; *) continue ;; esac
  if [ -z "$plan" ]; then
    report "rule 2: phase \"$name\" is $state and declares no plan. Add a 'plan:' line naming the file."
    continue
  fi
  if [ ! -f "$plan" ]; then
    report "rule 2: phase \"$name\" declares plan $plan, which does not exist."
    continue
  fi
  grep -qiE '^#{1,4}[[:space:]]*Fails if' "$plan" \
    || report "rule 2: phase \"$name\" plan $plan has no \"Fails if\" section. Write it as a premortem: it is the end of this phase and it failed badly, what happened?"
done <<EOF
$PHASES
EOF

if [ "$OFFLINE" = 1 ]; then
  echo "check-phases: --offline, so rules 1, 3 and 4 were NOT checked (they need the host)." >&2
  [ "$violations" -eq 0 ] || exit 1
  exit 0
fi

# --- the host rules ---------------------------------------------------------
HERE="$(cd "$(dirname "$SELF")" && pwd)"
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
  p="$(find "$HOME/.claude/plugins" -name forge-lib.sh 2>/dev/null | head -1)"
  [ -n "$p" ] && { printf '%s' "$p"; return 0; }
  return 1
}
LIB="$(find_forge_lib)" || {
  echo "check-phases: forge-lib.sh not found, so rules 1, 3 and 4 were SKIPPED." >&2
  echo "  They were NOT checked and NOT passed." >&2
  echo "  This group DEPENDS on forge-kit-devops, which ships forge-lib.sh (#161). Install it:" >&2
  echo "      /plugin install forge-kit-devops@forge-kit" >&2
  echo "  or point FORGE_LIB at a copy, or pass --offline to check the file-only rule deliberately." >&2
  exit 2
}
# shellcheck source=forge-lib.sh
. "$LIB"

MS="$(forge_milestone_list 2>/dev/null)" || MS=""
ISS="$(forge_issue_milestone_list 2>/dev/null)" || ISS=""
if [ -z "$MS" ] || [ -z "$ISS" ]; then
  echo "check-phases: the host could not be reached, so rules 1, 3 and 4 were SKIPPED." >&2
  echo "  They were NOT checked and NOT passed. Check the token and the forge configuration." >&2
  exit 2
fi

# Rule 1: every open ticket has a phase.
while read -r n; do
  [ -n "$n" ] || continue
  report "rule 1: issue #$n has no phase. Assign one, or put it in the backlog phase, which is a decision to decide later rather than no decision."
done <<EOF
$(printf '%s' "$ISS" | jq -r '.[] | select(.milestone == null) | .number')
EOF

# Rule 3: roadmap state and milestone state agree, and at most one phase is open.
open_count=0
while IFS="$(printf '\t')" read -r name state plan; do
  [ -n "$name" ] || continue
  [ "$state" = open ] && open_count=$((open_count + 1))
  ms_state="$(printf '%s' "$MS" | jq -r --arg t "$name" '.[] | select(.title == $t) | .state' | head -1)"
  if [ -z "$ms_state" ]; then
    report "rule 3: phase \"$name\" has no milestone on the host. Run sync-phases.sh."
    continue
  fi
  case "$state" in
    done) [ "$ms_state" = closed ] \
            || report "rule 3: phase \"$name\" is done in the roadmap but its milestone is open." ;;
    *)    [ "$ms_state" = open ] \
            || report "rule 3: phase \"$name\" is $state in the roadmap but its milestone is closed." ;;
  esac
done <<EOF
$PHASES
EOF
[ "$open_count" -le 1 ] \
  || report "rule 3: $open_count phases are open. At most one may be, or \"the current phase\" names nothing."

# Rule 4: a done phase holds no open tickets. The circuit breaker.
while IFS="$(printf '\t')" read -r name state plan; do
  [ "$state" = done ] || continue
  n="$(printf '%s' "$ISS" | jq -r --arg t "$name" '[.[] | select(.milestone == $t)] | length')"
  [ "${n:-0}" -eq 0 ] \
    || report "rule 4: phase \"$name\" is done but holds $n open ticket(s). Move them to the next phase, a new phase, or backlog: re-shape, never extend."
done <<EOF
$PHASES
EOF

[ "$violations" -eq 0 ] || exit 1
exit 0
