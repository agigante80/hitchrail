#!/usr/bin/env bash
# roadmap-lib-version: 5
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
#
# v2 (#246) adds the WRITE half. Until it existed the kit could read the roadmap and not
# reshape it, so every phase move was a hand edit and the two consumers that need one
# (a phase review, a roadmap reassessment) would each have had to learn the format again.
# See the block above the primitives for the return codes and the invariant they all verify.
#
# v3 (#246 review round 1) fixed two defects the first cut shipped with, both of which the
# parse-back check was structurally blind to. Arguments were bound unguarded, so under the
# `set -u` both consumers run, a short call aborted the CALLER instead of returning 2. And
# caller text travelled to awk through `-v`, which processes backslash escapes, so a plan
# path or a phase name carrying \t was written with a literal tab; the intent and the write
# were computed through the same mangling, so they agreed and the seam check passed it.
#
# v4 (#246 review round 2) fixed three defects IN v3's fixes. A blank line between phases
# belongs to the position rather than to the block, so a move between a heading-terminated
# position and EOF gained or lost a line; blank lines are not a parsed field, so the seam
# check could not see that either. Arity was inferred from emptiness, which is right for
# five primitives and wrong for the two whose argument may legitimately be empty: a
# two-argument set_prose passed the check and ERASED the phase prose with rc 0, and
# set_plan could not clear a plan that rule 2 does not require. And the bounded symlink
# walk stopped at the tenth hop and wrote there, severing a link mid-chain; it now refuses.

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

# --- the WRITE primitives (#246) ---------------------------------------------------------------
#
# The library was a parser with no writer, so reshaping the roadmap was a hand edit and any
# component that reshaped it would have been the format's SECOND definition of this file, which is
# the drift #162 removed. Seven primitives, because five were not enough for the consumers that
# justify them: /phase review must update a phase's prose when scope changes, and a roadmap
# reassessment must merge and refocus a phase and write the reason into the prose.
#
# THEY RETURN, THEY NEVER EXIT. This library is sourced and its own header says so; a library that
# exits kills its caller's shell. Codes: 0 done, 2 a usage error OR an I/O failure, 3 the file is
# malformed or the parser disagrees with what was written, 5 a POLICY refusal on a well-formed
# file. Not 4: sync-phases.sh and sync-labels.sh already use 4 for "a write failed part-way; the
# host may be partially synced", which is the opposite of "nothing was written", and every consumer
# sources those assets. Usage and I/O share 2 deliberately rather than splitting: both mean the
# call could not be carried out and nothing was written, and a caller has the stderr line to tell
# them apart.
#
# EVERY ARGUMENT IS BOUND WITH ${n-}, which is not a style choice. Both consumers run `set -u`, and
# so does every contract test in this tree, so an unguarded `local st="$3"` on a short call aborts
# the CALLER's shell before the function can return anything at all. The promise three paragraphs
# up is only true if the arity check is reachable, and under `set -u` it is not reachable unless
# the binding is guarded first.
#
# CALLER TEXT REACHES awk THROUGH ENVIRON, NEVER THROUGH -v, and every site does it the same way.
# `awk -v x="$v"` processes backslash escapes in the value, so a plan path containing \t is WRITTEN
# as a literal tab; a phase name is worse, because parse_roadmap emits TSV and a name carrying a
# tab splits into the state column, which every consumer then reads as garbage. The parse-back
# check cannot see it, because the intent and the write were computed through the same mangling and
# therefore agree. Apple's awk additionally refuses a -v value containing a newline outright, which
# is #205's finding. The form used here is a COMMAND-PREFIX assignment, `RM_X="$v" awk ...`, which
# puts the value in that one command's environment and leaves nothing behind in the caller's.
# The rule covers DERIVED text too, not only what a caller typed: a temp path built from the
# roadmap's own directory carries whatever that directory is named, so the three sites that pass a
# filename to awk pass it the same way. What `-v` may still carry is a line number, this library's
# own `state`/`plan` literal, and awk's `OFS`; the suite allow-lists exactly those names.
#
# THE WRITER'S EXTENT IS NARROWER THAN THE PARSER'S, on purpose: a block runs to the next `## `
# line, not the next `## Phase:`, so a trailing `## Notes` section is never absorbed into the prose
# a primitive rewrites. That difference is a seam, and the seam is CHECKED rather than trusted:
# every primitive parses its candidate result before the rename and refuses with 3 if parse_roadmap
# disagrees with what it wrote. An invariant that is verified cannot drift from the parser.
#
# AMBIGUITY REFUSES. Two column-0 `state:` or `plan:` lines in one block, or two phases with one
# name, are files the parser tolerates and a writer cannot act on: it cannot tell which line the
# file means. Refusing is the only honest answer, and it is where the writer is deliberately
# stricter than the parser, which must keep reading an imperfect file.
#
# NAMESPACE. This half reserves `RM_*` in the caller's shell. `RM_START`, `RM_END` and `RM_EXPECT`
# are plain globals, because a shell function returns one integer and these need to return more.
# Nothing here is exported.

_rm_die() { printf 'roadmap-lib: %s\n' "$1" >&2; return "${2:-2}"; }

# _rm_block <file> <phase> -> "<start> <end>" (1-based, end exclusive), or NONE, or DUPLICATE.
# The extent: the `## Phase: <name>` line to the next `^## ` line or EOF.
#
# It prints ONE word or one pair, never a pair followed by a word: the first shape of this function
# printed the block it had already found and then DUPLICATE, so every `case` arm below read the
# two-line string as neither, and a repeated name fell through to the parse-back check and reported
# itself as a malformed file. Collect first, decide at END.
_rm_block() {
  RM_WANT="$2" awk '
    /^## / {
      name = $0; sub(/^## Phase: */, "", name); sub(/[ \t]+$/, "", name)
      if (instart) { s[++n] = instart; e[n] = NR; instart = 0 }
      if ($0 ~ /^## Phase:/ && name == ENVIRON["RM_WANT"]) instart = NR
      next
    }
    END {
      if (instart) { s[++n] = instart; e[n] = NR + 1 }
      if (n == 0) { print "NONE"; exit }
      if (n > 1)  { print "DUPLICATE"; exit }
      print s[1] " " e[1]
    }
  ' "$1"
}

# _rm_end_point <file> -> the line to insert a phase BEFORE so it lands after the last phase.
#
# NOT end-of-file. `--end` means "last PHASE", and a roadmap may carry a trailing `## Notes`
# section that the whole of this design works to leave alone; appending at EOF would put the new
# phase after it, which reads as a phase inside the notes.
_rm_end_point() {
  awk '
    /^## / {
      if (instart) { endp = NR; instart = 0 }
      if ($0 ~ /^## Phase:/) instart = NR
      next
    }
    END { if (instart) print NR + 1; else if (endp) print endp; else print NR + 1 }
  ' "$1"
}

# _rm_split <file> <start> <end> <body-out> <strip-out>
#
# A BLANK LINE BETWEEN TWO PHASES BELONGS TO THE POSITION, NOT TO THE BLOCK, and getting that
# wrong is what made reorder not byte-reversible. A block terminated by a heading carries a
# trailing blank; the LAST block in a file is terminated by EOF and carries none. Move one to the
# other position and the file gains or loses a line, which the parse-back check cannot see because
# blank lines are not a parsed field. So the body is written canonically, with its trailing blanks
# removed, and the separator is emitted by whoever does the inserting. Symmetrically, removing a
# block that reached EOF also removes the blanks immediately BEFORE it, which were its separator
# and have nothing left to separate.
_rm_split() {
  : > "$4"; : > "$5"
  RM_BO="$4" RM_SO="$5" awk -v s="$2" -v e="$3" '
    BEGIN { bo = ENVIRON["RM_BO"]; so = ENVIRON["RM_SO"] }
    { lines[NR] = $0 }
    END {
      last = e - 1
      while (last >= s && lines[last] ~ /^[ \t]*$/) last--
      for (i = s; i <= last; i++) print lines[i] > bo
      st = s
      if (e > NR) { while (st > 1 && lines[st - 1] ~ /^[ \t]*$/) st-- }
      for (i = 1; i < st; i++)  print lines[i] > so
      for (i = e; i <= NR; i++) print lines[i] > so
      close(bo); close(so)
    }
  ' "$1"
}

# _rm_check <file> -> 0 when parse_roadmap reads it cleanly. MALFORMED only.
# A repeated phase NAME is deliberately not checked here. It is not malformed, the parser reads it
# without complaint, and it is only an ambiguity for the phase being written: a writer asked to
# touch Alpha in a file where Beta appears twice knows exactly which lines it means. _rm_block
# reports the repeat for the NAME it was asked about, and that is a policy refusal, a 5.
_rm_check() {
  local out
  out="$(parse_roadmap "$1")" || return 3
  printf '%s\n' "$out" | grep -q '^MALFORMED' && return 3
  return 0
}

# _rm_prose_ok <text> -> 5 when the text would open a `## ` section.
#
# ONE definition, called by both primitives that accept prose. set_prose had this check and
# insert_at did not, and because parse_roadmap only keys on `^## Phase:` the resulting file parsed
# identically, so the seam check passed it. The section then sat outside the phase's writer-visible
# block and inside what a reader sees as the phase: a later set_prose stranded it, and a later
# remove reported success while leaving the removed phase's text attached to the phase above.
_rm_prose_ok() {
  case "$1" in
    "## "*|*"
## "*) _rm_die "that prose opens a '## ' section, which would silently end the block" 5; return 5 ;;
  esac
  return 0
}

# _rm_tmp <path-in-the-same-directory> -> a temp file name beside it.
# mktemp rather than $$, so an interrupted run cannot leave a predictable name behind twice and
# cannot be raced by a pre-created path of the same name.
_rm_tmp() { mktemp "$(dirname "$1")/.roadmap-lib.XXXXXX" 2>/dev/null; }

# _rm_commit <file> <candidate> -> verify the parse-back, then replace atomically.
# The idiom is scripts/forge-adapt-agent-skills.sh's, which has 45 CI tests behind it: the temp
# sits BESIDE the target (never in TMPDIR, which may be on another filesystem or absent), `cp -p`
# carries the mode across, and the rename is what makes the file either the old one or the new one.
# A symlinked roadmap is written THROUGH, because the link is what a project pointed at on purpose.
# The chain is walked by hand, bounded, because BSD readlink has no -f; past the bound it REFUSES,
# since stopping the walk and writing anyway replaces a link with a regular file and leaves the
# real target holding the old content, with nothing in the return code to say so.
#
# THE CALLER STATES WHAT THE PARSE MUST SAY, in RM_EXPECT, and this function refuses when it says
# anything else. A structural check alone is not enough, and the case that proves it is the seam:
# the parser's extent runs past a trailing `## Notes` section while the writer's stops there, so a
# stray `state:` line down in that section silently OVERRIDES the keyed line a primitive just set.
# The result is well-formed, reads clean, and does not say what was written. Only comparing the
# whole parse against the intended one catches that, which is why the invariant is computed rather
# than asserted.
_rm_commit() {
  local target="$1" cand="$2" real link tmp got n=0
  real="$target"
  while [ -L "$real" ]; do
    [ "$n" -lt 10 ] || { _rm_die "'$target' is a symlink chain deeper than 10; refusing rather than writing to a link"; return 2; }
    link="$(readlink "$real")"
    case "$link" in
      /*) real="$link" ;;
      *)  real="$(cd "$(dirname "$real")" && pwd -P)/$link" ;;
    esac
    n=$((n + 1))
  done
  _rm_check "$cand" || { _rm_die "the parser disagrees with what that edit would write; nothing changed" 3; return 3; }
  got="$(parse_roadmap "$cand")"
  [ "$got" = "${RM_EXPECT-}" ] || {
    _rm_die "the parser reads the result differently from what that edit meant to write; nothing changed" 3; return 3; }
  cmp -s "$real" "$cand" && return 0   # byte-identical candidate: no write, no inode change, no mode risked
  tmp="$(_rm_tmp "$real")"
  [ -n "$tmp" ] || { _rm_die "cannot create a temporary file beside '$real'"; return 2; }
  cp -p "$real" "$tmp" 2>/dev/null || cp "$real" "$tmp" || { rm -f "$tmp"; _rm_die "cannot copy '$real'"; return 2; }
  cat "$cand" > "$tmp" || { rm -f "$tmp"; _rm_die "cannot write the new content"; return 2; }
  mv -f "$tmp" "$real" || { rm -f "$tmp"; _rm_die "cannot replace '$real'"; return 2; }
  return 0
}

# _rm_one_open <file> [exclude] -> the name of the open phase, if any.
_rm_one_open() {
  parse_roadmap "$1" | RM_X="${2-}" awk -F'\t' '$2 == "open" && $1 != ENVIRON["RM_X"] { print $1; exit }'
}

# _rm_keyed <file> <start> <end> <key> -> how many column-0 `<key>:` lines the block carries.
# The key is this library's own literal, `state` or `plan`, never caller text.
_rm_keyed() {
  awk -v s="$2" -v e="$3" -v k="$4" 'NR > s && NR < e && index($0, k ":") == 1 { n++ } END { print n + 0 }' "$1"
}

_rm_prepare() {  # _rm_prepare <file> <phase> -> sets RM_START, RM_END; refuses otherwise
  local blk
  [ -f "$1" ] || { _rm_die "no such roadmap: $1"; return 2; }
  _rm_check "$1" || { _rm_die "the roadmap is malformed; refusing to write to it" 3; return 3; }
  blk="$(_rm_block "$1" "$2")"
  case "$blk" in
    NONE)      _rm_die "no phase named '$2'" 5; return 5 ;;
    DUPLICATE) _rm_die "two phases are named '$2'; a writer cannot tell which the file means" 5; return 5 ;;
  esac
  RM_START="${blk%% *}"; RM_END="${blk##* }"
  return 0
}

# roadmap_set_state <file> <phase> <state>
roadmap_set_state() {
  local f="${1-}" phase="${2-}" st="${3-}" open cand rc
  [ -n "$f" ] && [ -n "$phase" ] && [ -n "$st" ] || { _rm_die "usage: roadmap_set_state <file> <phase> <state>"; return 2; }
  case "$st" in planned|open|done|backlog) ;; *) _rm_die "unknown state '$st'"; return 2 ;; esac
  _rm_prepare "$f" "$phase" || return $?
  [ "$(_rm_keyed "$f" "$RM_START" "$RM_END" state)" = 1 ] || {
    _rm_die "the '$phase' block carries no single column-0 state line; a writer cannot act on it" 5; return 5; }
  if [ "$st" = open ]; then
    open="$(_rm_one_open "$f" "$phase")"
    [ -z "$open" ] || { _rm_die "'$open' is already open; at most one phase is open at a time" 5; return 5; }
  fi
  RM_EXPECT="$(parse_roadmap "$f" | RM_P="$phase" RM_V="$st" awk -F'\t' -v OFS='\t' '$1 == ENVIRON["RM_P"] { $2 = ENVIRON["RM_V"] } { print }')"
  cand="$(_rm_tmp "$f")"; [ -n "$cand" ] || { _rm_die "cannot create a temporary file beside '$f'"; return 2; }
  RM_V="$st" awk -v s="$RM_START" -v e="$RM_END" '
    NR > s && NR < e && index($0, "state:") == 1 { print "state: " ENVIRON["RM_V"]; next } { print }
  ' "$f" > "$cand" || { rm -f "$cand"; _rm_die "cannot build the new content"; return 2; }
  _rm_commit "$f" "$cand"; rc=$?; rm -f "$cand"; return $rc
}

# roadmap_set_plan <file> <phase> <path>
roadmap_set_plan() {
  # Arity is counted, never inferred from emptiness. An EMPTY plan path is a legal value, not a
  # short call: check-phases.sh rule 2 requires a plan only for `open` and `done`, so a phase going
  # back to `backlog` legitimately clears its plan, and a library that cannot express that edit
  # forces the hand edit it exists to replace.
  [ "$#" -ge 3 ] || { _rm_die "usage: roadmap_set_plan <file> <phase> <path>"; return 2; }
  local f="${1-}" phase="${2-}" path="${3-}" cand rc
  [ -n "$f" ] && [ -n "$phase" ] || { _rm_die "usage: roadmap_set_plan <file> <phase> <path>"; return 2; }
  _rm_prepare "$f" "$phase" || return $?
  [ "$(_rm_keyed "$f" "$RM_START" "$RM_END" plan)" = 1 ] || {
    _rm_die "the '$phase' block carries no single column-0 plan line; a writer cannot act on it" 5; return 5; }
  RM_EXPECT="$(parse_roadmap "$f" | RM_P="$phase" RM_V="$path" awk -F'\t' -v OFS='\t' '$1 == ENVIRON["RM_P"] { $3 = ENVIRON["RM_V"] } { print }')"
  cand="$(_rm_tmp "$f")"; [ -n "$cand" ] || { _rm_die "cannot create a temporary file beside '$f'"; return 2; }
  RM_V="$path" awk -v s="$RM_START" -v e="$RM_END" '
    NR > s && NR < e && index($0, "plan:") == 1 {
      v = ENVIRON["RM_V"]; print (v == "" ? "plan:" : "plan: " v); next
    } { print }
  ' "$f" > "$cand" || { rm -f "$cand"; _rm_die "cannot build the new content"; return 2; }
  _rm_commit "$f" "$cand"; rc=$?; rm -f "$cand"; return $rc
}

# roadmap_set_prose <file> <phase> <text>   replace a phase's prose, keeping its keyed lines.
roadmap_set_prose() {
  # Same split as set_plan, and here it is the difference between a refusal and SILENT DATA LOSS:
  # a two-argument call used to pass the emptiness check and erase the phase prose with rc 0.
  [ "$#" -ge 3 ] || { _rm_die "usage: roadmap_set_prose <file> <phase> <text>"; return 2; }
  local f="${1-}" phase="${2-}" prose="${3-}" cand rc
  [ -n "$f" ] && [ -n "$phase" ] || { _rm_die "usage: roadmap_set_prose <file> <phase> <text>"; return 2; }
  _rm_prose_ok "$prose" || return 5
  _rm_prepare "$f" "$phase" || return $?
  RM_EXPECT="$(parse_roadmap "$f")"   # prose is not a parsed field: the rows must come back identical
  cand="$(_rm_tmp "$f")"; [ -n "$cand" ] || { _rm_die "cannot create a temporary file beside '$f'"; return 2; }
  # The hand-written format puts one blank line between the last keyed line and the prose, and
  # one between the prose and the next heading (or none at EOF): the leading "\n" below is what
  # makes an unchanged prose round-trip byte-identical on the FIRST call rather than only the second.
  RM_PROSE="$prose" awk -v s="$RM_START" -v e="$RM_END" '
    NR <= s { print; next }
    NR >= e { if (!done) { printf "\n%s\n\n", ENVIRON["RM_PROSE"]; done = 1 } print; next }
    index($0, "state:") == 1 || index($0, "plan:") == 1 { print; next }
    { next }
    END { if (!done) printf "\n%s\n", ENVIRON["RM_PROSE"] }
  ' "$f" > "$cand" || { rm -f "$cand"; _rm_die "cannot build the new content"; return 2; }
  _rm_commit "$f" "$cand"; rc=$?; rm -f "$cand"; return $rc
}

# roadmap_insert_at <file> --before <phase>|--end <name> <state> <plan> <prose>
roadmap_insert_at() {
  local f="${1-}" where="${2-}" ref name st plan prose cand rc at open row
  case "$where" in
    --before) ref="${3-}"; name="${4-}"; st="${5-}"; plan="${6-}"; prose="${7-}" ;;
    --end)    ref=""; name="${3-}"; st="${4-}"; plan="${5-}"; prose="${6-}" ;;
    *) _rm_die "usage: roadmap_insert_at <file> --before <phase>|--end <name> <state> <plan> <prose>"; return 2 ;;
  esac
  [ -n "$f" ] && [ -n "$name" ] && [ -n "$st" ] || { _rm_die "usage: roadmap_insert_at <file> --before <phase>|--end <name> <state> <plan> <prose>"; return 2; }
  [ "$where" != --before ] || [ -n "$ref" ] || { _rm_die "usage: roadmap_insert_at <file> --before <phase> <name> <state> <plan> <prose>"; return 2; }
  case "$st" in planned|open|done|backlog) ;; *) _rm_die "unknown state '$st'"; return 2 ;; esac
  _rm_prose_ok "$prose" || return 5
  [ -f "$f" ] || { _rm_die "no such roadmap: $f"; return 2; }
  _rm_check "$f" || { _rm_die "the roadmap is malformed; refusing to write to it" 3; return 3; }
  case "$(_rm_block "$f" "$name")" in NONE) ;; *) _rm_die "a phase named '$name' is already in the roadmap" 5; return 5 ;; esac
  if [ "$st" = open ]; then
    open="$(_rm_one_open "$f")"
    [ -z "$open" ] || { _rm_die "'$open' is already open; at most one phase is open at a time" 5; return 5; }
  fi
  if [ -n "$ref" ]; then
    at="$(_rm_block "$f" "$ref")"
    case "$at" in
      NONE) _rm_die "no phase named '$ref' to insert before" 5; return 5 ;;
      DUPLICATE) _rm_die "two phases are named '$ref'" 5; return 5 ;;
    esac
    at="${at%% *}"
  else
    at="$(_rm_end_point "$f")"
  fi
  row="$(printf '%s\t%s\t%s' "$name" "$st" "$plan")"
  if [ -n "$ref" ]; then
    RM_EXPECT="$(parse_roadmap "$f" | RM_R="$ref" RM_ROW="$row" awk -F'\t' '$1 == ENVIRON["RM_R"] { print ENVIRON["RM_ROW"] } { print }')"
  else
    RM_EXPECT="$(parse_roadmap "$f"; printf '%s\n' "$row")"
  fi
  cand="$(_rm_tmp "$f")"; [ -n "$cand" ] || { _rm_die "cannot create a temporary file beside '$f'"; return 2; }
  RM_NAME="$name" RM_STATE="$st" RM_PLAN="$plan" RM_PROSE="$prose" awk -v at="$at" '
    function block() {
      printf "## Phase: %s\nstate: %s\nplan: %s\n\n%s\n",
             ENVIRON["RM_NAME"], ENVIRON["RM_STATE"], ENVIRON["RM_PLAN"], ENVIRON["RM_PROSE"]
    }
    NR == at { block(); print ""; done = 1 }
    { prev = $0; print }
    END { if (!done) { if (prev != "") print ""; block() } }
  ' "$f" > "$cand" || { rm -f "$cand"; _rm_die "cannot build the new content"; return 2; }
  _rm_commit "$f" "$cand"; rc=$?; rm -f "$cand"; return $rc
}

# roadmap_reorder <file> <phase> --before <phase>|--end
#
# The block travels as a FILE, never through a command substitution, which strips every trailing
# newline: reorder is supposed to move bytes, and a version that dropped the blank line before the
# destination heading eroded the file a little on every call, so a reorder and its inverse did not
# restore the original.
roadmap_reorder() {
  local f="${1-}" phase="${2-}" where="${3-}" ref="${4-}" cand rc at row
  [ -n "$f" ] && [ -n "$phase" ] || { _rm_die "usage: roadmap_reorder <file> <phase> --before <phase>|--end"; return 2; }
  case "$where" in
    --before) [ -n "$ref" ] || { _rm_die "usage: roadmap_reorder <file> <phase> --before <phase>"; return 2; } ;;
    --end)    ;;
    *) _rm_die "usage: roadmap_reorder <file> <phase> --before <phase>|--end"; return 2 ;;
  esac
  _rm_prepare "$f" "$phase" || return $?
  # The moved row is lifted FIRST, in the shell. Computing it inside the same one-pass awk read
  # the reference row before the moved one whenever the destination sits earlier in the file, and
  # then printed an empty line in its place.
  row="$(parse_roadmap "$f" | RM_P="$phase" awk -F'\t' '$1 == ENVIRON["RM_P"]')"
  case "$where" in
    --before)
      RM_EXPECT="$(parse_roadmap "$f" | RM_P="$phase" RM_R="$ref" RM_ROW="$row" awk -F'\t' '
        $1 == ENVIRON["RM_P"] { next }
        $1 == ENVIRON["RM_R"] { print ENVIRON["RM_ROW"] }
        { print }' )" ;;
    --end)
      RM_EXPECT="$(parse_roadmap "$f" | RM_P="$phase" awk -F'\t' '$1 != ENVIRON["RM_P"]'; printf '%s\n' "$row")" ;;
  esac
  cand="$(_rm_tmp "$f")"; [ -n "$cand" ] || { _rm_die "cannot create a temporary file beside '$f'"; return 2; }
  _rm_split "$f" "$RM_START" "$RM_END" "$cand.body" "$cand.strip" \
    || { rm -f "$cand" "$cand.body" "$cand.strip"; _rm_die "cannot split '$f' around '$phase'"; return 2; }
  case "$where" in
    --before)
      at="$(_rm_block "$cand.strip" "$ref")"
      case "$at" in
        NONE|DUPLICATE) rm -f "$cand" "$cand.body" "$cand.strip"; _rm_die "no single phase named '$ref' to move before" 5; return 5 ;;
      esac
      at="${at%% *}" ;;
    --end)
      at="$(_rm_end_point "$cand.strip")" ;;
  esac
  RM_BF="$cand.body" awk -v at="$at" '
    BEGIN { bf = ENVIRON["RM_BF"] }
    NR == at { while ((getline l < bf) > 0) print l; print ""; done = 1 }
    { prev = $0; print }
    END { if (!done) { if (prev != "") print ""; while ((getline l < bf) > 0) print l } }
  ' "$cand.strip" > "$cand" || { rm -f "$cand" "$cand.body" "$cand.strip"; _rm_die "cannot build the new content"; return 2; }
  rm -f "$cand.body" "$cand.strip"
  _rm_commit "$f" "$cand"; rc=$?; rm -f "$cand"; return $rc
}

# roadmap_remove <file> <phase> [--milestone-empty]
#
# The emptiness check is the CALLER'S to make and to assert, because this library has no host
# dependency and must not grow one: rule 4 refuses a done phase holding open tickets, and the
# answer lives on the forge. So the caller passes --milestone-empty after asking, and without it
# the primitive refuses rather than assuming.
roadmap_remove() {
  local f="${1-}" phase="${2-}" flag="${3-}" cand rc
  [ -n "$f" ] && [ -n "$phase" ] || { _rm_die "usage: roadmap_remove <file> <phase> --milestone-empty"; return 2; }
  [ "$flag" = --milestone-empty ] || {
    _rm_die "refusing to remove '$phase': pass --milestone-empty once you have confirmed on the host that its milestone holds no open tickets" 5; return 5; }
  _rm_prepare "$f" "$phase" || return $?
  RM_EXPECT="$(parse_roadmap "$f" | RM_P="$phase" awk -F'\t' '$1 != ENVIRON["RM_P"]')"
  cand="$(_rm_tmp "$f")"; [ -n "$cand" ] || { _rm_die "cannot create a temporary file beside '$f'"; return 2; }
  _rm_split "$f" "$RM_START" "$RM_END" "$cand.body" "$cand" \
    || { rm -f "$cand" "$cand.body"; _rm_die "cannot split '$f' around '$phase'"; return 2; }
  rm -f "$cand.body"
  _rm_commit "$f" "$cand"; rc=$?; rm -f "$cand"; return $rc
}

# roadmap_rename <file> <old> <new>
#
# REPORTS the host consequence and performs none, because there is nothing to call: forge-lib.sh
# has no milestone rename at all. And nothing downstream notices: after a roadmap-only rename
# sync-phases.sh creates the new milestone, and all four rules pass while the tickets sit under the
# old title. That silence is the whole reason this report exists.
roadmap_rename() {
  local f="${1-}" old="${2-}" new="${3-}" cand rc
  [ -n "$f" ] && [ -n "$old" ] && [ -n "$new" ] || { _rm_die "usage: roadmap_rename <file> <old> <new>"; return 2; }
  _rm_prepare "$f" "$old" || return $?
  case "$(_rm_block "$f" "$new")" in NONE) ;; *) _rm_die "a phase named '$new' is already in the roadmap" 5; return 5 ;; esac
  RM_EXPECT="$(parse_roadmap "$f" | RM_O="$old" RM_N="$new" awk -F'\t' -v OFS='\t' '$1 == ENVIRON["RM_O"] { $1 = ENVIRON["RM_N"] } { print }')"
  cand="$(_rm_tmp "$f")"; [ -n "$cand" ] || { _rm_die "cannot create a temporary file beside '$f'"; return 2; }
  RM_N="$new" awk -v s="$RM_START" 'NR == s { print "## Phase: " ENVIRON["RM_N"]; next } { print }' "$f" > "$cand" \
    || { rm -f "$cand"; _rm_die "cannot build the new content"; return 2; }
  _rm_commit "$f" "$cand"; rc=$?; rm -f "$cand"
  [ "$rc" = 0 ] && printf 'roadmap-lib: renamed in the roadmap only. forge-lib.sh has no milestone rename, so the host still carries the milestone titled "%s" with its tickets; create "%s" and move them, or the phase reads empty while all four rules pass.\n' "$old" "$new" >&2
  return $rc
}
