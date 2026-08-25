#!/usr/bin/env bash
# version-lib.sh: the shared release primitive. Compares the working-tree version against
# the latest released git tag and classifies the result. Every release-automation lane
# (gate / auto-on-dependency / auto-on-merge) sources this and acts on the one-word verdict,
# so the version<->tag logic lives in exactly one place.
#
# Verdicts (printed to stdout, one word; human detail goes to stderr):
#   first-release  no release tag exists yet, so any version may ship
#   ahead          working version > latest tag, already bumped deliberately; ship AS-IS, NEVER re-bump
#   equal          working version == latest tag, nobody bumped; the lane decides (block | auto-patch)
#   behind         working version < latest tag, branch is behind a release; REGRESSION, hard stop
#
# Config via env (forge-adapt sets these for the project's canonical version source):
#   VERSION_SOURCE  file|node|python|cargo|git|cmd   (default: file)
#                   git = tag-derived (setuptools-scm/hatch-vcs): the version IS the latest tag,
#                   so there is no file to bump; releasing means pushing the next tag.
#   VERSION_FILE    path to a plain-text version  (default: VERSION)
#   VERSION_CMD     shell command printing the version (used when VERSION_SOURCE=cmd)
#   TAG_GLOB        glob matching release tags     (default: v*)
#   TAG_PREFIX      prefix stripped from a tag     (default: v)
#
# Usage:
#   source version-lib.sh            # then call read_version / latest_tag / classify_version
#   bash   version-lib.sh            # prints the verdict (stdout) + detail (stderr); exit 0, or 2 on error
#
# NOTE: callers must check out full history with tags (actions/checkout: fetch-depth: 0,
# fetch-tags: true) or `latest_tag` sees nothing and every release looks like a first-release.
set -uo pipefail

VERSION_SOURCE="${VERSION_SOURCE:-file}"
VERSION_FILE="${VERSION_FILE:-VERSION}"
TAG_PREFIX="${TAG_PREFIX:-v}"
TAG_GLOB="${TAG_GLOB:-${TAG_PREFIX}*}"   # derive from the prefix so a custom prefix can't desync the glob

# _is_semver: true if $1 is X.Y.Z with an optional -prerelease / +build suffix.
_is_semver() { [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-+].+)?$ ]]; }

# read_version: print the project's current (working-tree) canonical version, prefix-free. Each
# source yields EMPTY when the version is absent/unreadable (never a sentinel like "undefined"), so
# classify_version's emptiness + semver checks fail closed instead of releasing garbage.
read_version() {
  case "$VERSION_SOURCE" in
    file)   [ -f "$VERSION_FILE" ] && tr -d '[:space:]' < "$VERSION_FILE" ;;
    node)   node -p "require('./package.json').version || ''" 2>/dev/null ;;   # '' not "undefined" when missing
    python) python3 -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print(d.get('project',{}).get('version') or d.get('tool',{}).get('poetry',{}).get('version') or '')" 2>/dev/null ;;
    cargo)  awk '/^\[package\]/{p=1;next} /^\[/{p=0} p&&/^[[:space:]]*version[[:space:]]*=/{if(match($0,/"[^"]+"/)){print substr($0,RSTART+1,RLENGTH-2);exit}}' Cargo.toml 2>/dev/null ;;  # scoped to [package]
    git)    git describe --tags --abbrev=0 --match "$TAG_GLOB" 2>/dev/null | sed "s/^${TAG_PREFIX}//" || true ;;  # empty (exit 0) when no tag, so callers under `set -e` don't abort
    cmd)    eval "${VERSION_CMD:?VERSION_CMD must be set when VERSION_SOURCE=cmd}" ;;
    *)      echo "version-lib: unknown VERSION_SOURCE '$VERSION_SOURCE'" >&2; return 2 ;;
  esac
}

# latest_tag: the latest release to compare against. Repo-wide highest by default; for tag-derived
# git mode it is HEAD-relative (nearest ancestor release tag) to MATCH read_version's frame, else a
# higher tag on an unmerged sibling branch makes HEAD look `behind` and the engine wrongly refuses.
# (In git mode there is no file to pre-bump, so the version always equals HEAD's tag → `equal`.)
latest_tag() {
  if [ "$VERSION_SOURCE" = git ]; then
    git describe --tags --abbrev=0 --match "$TAG_GLOB" 2>/dev/null | sed "s/^${TAG_PREFIX}//" || true
  else
    git tag --list "$TAG_GLOB" --sort=-v:refname | head -1 | sed "s/^${TAG_PREFIX}//"
  fi
}

# unreleased_commits: count commits on HEAD since its NEAREST ANCESTOR release tag (all of HEAD if
# none). Uses `git describe` (HEAD-relative), not the repo-wide highest tag, so a release tag sitting
# on an unmerged sibling branch does not skew the count. For tag-derived projects there is no version
# file to compare, so "are there unreleased commits?" is the meaningful signal (release = cut a tag).
unreleased_commits() {
  local t
  t=$(git describe --tags --abbrev=0 --match "$TAG_GLOB" 2>/dev/null)
  if [ -z "$t" ]; then git rev-list --count HEAD; else git rev-list --count "${t}..HEAD"; fi
}

# classify_version: print one verdict word. Optional args: $1=working version, $2=latest tag.
classify_version() {
  local now tag nb tb highest
  now="${1-$(read_version)}"
  tag="${2-$(latest_tag)}"
  if [ -z "$now" ]; then echo "version-lib: could not read the working version (VERSION_SOURCE=$VERSION_SOURCE)" >&2; return 2; fi
  # Reject non-semver values (e.g. node's "undefined", a stray cmd output) instead of letting
  # `sort -V` rank them above real versions and mis-classify as `ahead` → a garbage release.
  _is_semver "$now" || { echo "version-lib: working version '$now' is not semver (VERSION_SOURCE=$VERSION_SOURCE)" >&2; return 2; }
  if [ -z "$tag" ]; then echo "first-release"; return 0; fi
  _is_semver "$tag" || { echo "version-lib: latest tag '$tag' is not semver; check TAG_GLOB ('$TAG_GLOB') / TAG_PREFIX ('$TAG_PREFIX')" >&2; return 2; }
  # Compare the RELEASE CORES (strip any -prerelease/+build): `sort -V` ranks `1.2.0-rc1` ABOVE
  # `1.2.0`, which would wrongly read a prerelease as `ahead` and ship it as production. Comparing
  # cores means a prerelease of an already-released core reads as `equal` (the gate then asks for a
  # real bump). Full prerelease precedence is out of scope; the version source should be a clean core.
  nb="${now%%[-+]*}"; tb="${tag%%[-+]*}"
  if [ "$nb" = "$tb" ]; then echo "equal"; return 0; fi
  highest=$(printf '%s\n%s\n' "$nb" "$tb" | sort -V | tail -1)
  if [ "$highest" = "$nb" ]; then echo "ahead"; else echo "behind"; fi
}

# next_patch: print the next PATCH version (X.Y.Z -> X.Y.(Z+1)), dropping any -prerelease
# suffix. PURE: prints, never writes. The auto-release lanes use this to compute the bump; the
# gate never calls it (the gate only reads). Arg optional: $1=base version (default read_version).
next_patch() {
  local v="${1:-$(read_version)}"
  v="${v%%[-+]*}"                    # release core, drop any -prerelease AND +build metadata
  case "$v" in
    *.*.*.*) echo "next_patch: not 3-part semver: $v" >&2; return 2 ;;   # reject 4+ fields
    *.*.*)   printf '%s.%s.%s' "${v%%.*}" "$(printf '%s' "$v" | cut -d. -f2)" "$(( ${v##*.} + 1 ))" ;;
    *)       echo "next_patch: not semver: $v" >&2; return 2 ;;
  esac
}

# Executed directly (not sourced): emit the verdict on stdout, a human line on stderr.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  _now=$(read_version); _tag=$(latest_tag)
  _verdict=$(classify_version "$_now" "$_tag") || exit $?
  echo "version-lib: working=${_now:-?} latest-tag=${_tag:-none} -> $_verdict" >&2
  echo "$_verdict"
fi
