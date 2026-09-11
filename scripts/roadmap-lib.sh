#!/usr/bin/env bash
# roadmap-lib-version: 1
#
# The roadmap format, defined ONCE and sourced by both roadmap assets (issue #162).
#
# WHY THIS IS A LIBRARY AND NOT DUPLICATED CODE. parse_roadmap is not two similar behaviours that
# happen to look alike; it is ONE definition of a file format with two consumers. If check-phases.sh
# and sync-phases.sh ever parsed the roadmap differently, the guard would pass a file the sync then
# mis-applies. Divergence is a defect BY DEFINITION rather than a possibility, and that is exactly
# what separates a shared specification from the incidental similarity the Rule of Three warns
# against extracting too early.
#
# It shipped duplicated, guarded by a byte-identity test, on a precedent that did not apply: #112
# and #77 guard copies because extraction is IMPOSSIBLE there (a glob is not a regex; the prose
# sites need an inline fallback). Here it is possible, and sync-labels.sh sourcing forge-lib.sh is
# the pattern already proven in this repo.
#
# Source it, do not execute it. Anchor to ${BASH_SOURCE[0]}, never the working directory.

# --- portability ------------------------------------------------------------
# macOS still ships bash 3.2 and a BSD readlink with no -f, and this is installed into other
# people's repositories. A guard that dies on a contributor's laptop is a guard they remove.
if [ "${BASH_VERSINFO[0]:-0}" -ge 4 ]; then
  set_lower() { LOWER="${1?}"; LOWER="${LOWER,,}"; }
else
  set_lower() { LOWER="$(printf '%s' "${1?}" | tr '[:upper:]' '[:lower:]')"; }
fi
abspath() {
  local d b
  d="$(dirname -- "$1")"; b="$(basename -- "$1")"
  d="$(cd -- "$d" 2>/dev/null && pwd -P)" || { printf '%s' "$1"; return; }
  printf '%s/%s' "$d" "$b"
}

# parse_roadmap <file> -> name<TAB>state<TAB>plan, one row per phase, in roadmap order.
#
# REFUSES the whole file rather than skipping a block. A silently ignored phase is a phase the guard
# reports as compliant, which is the drift it exists to end. A malformed row is emitted with a
# MALFORMED marker so the caller can report every problem at once rather than only the first.
#
# NOTE: this function is duplicated verbatim in sync-phases.sh, because each asset must run
# standalone once forge-adapt copies it into a project's scripts/. scripts/test-sync-phases.sh
# asserts the two copies stay byte-identical, the same answer this repo gave for the component path
# set (#112) and the template-dir order (#77).
parse_roadmap() {
  awk '
    /^## Phase:/ {
      if (seen) emit()
      name = $0; sub(/^## Phase: */, "", name); sub(/[ \t]+$/, "", name)
      seen = 1; state = ""; plan = ""; next
    }
    /^state:/ { state = value(); next }
    /^plan:/  { plan  = value(); next }
    END { if (seen) emit() }
    function value(   v) {
      v = $0; sub(/^[a-z]+:[ \t]*/, "", v); sub(/[ \t]+$/, "", v); return v
    }
    function emit() {
      if (state == "") { printf("MALFORMED\t%s\tno state line\n", name); return }
      if (state != "planned" && state != "open" && state != "done" && state != "backlog") {
        printf("MALFORMED\t%s\tunknown state \"%s\"\n", name, state); return
      }
      printf("%s\t%s\t%s\n", name, state, plan)
    }
  ' "$1"
}
