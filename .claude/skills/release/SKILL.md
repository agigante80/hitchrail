---
name: release
description: Cut a versioned Hitchrail release - bump project.version in pyproject.toml, verify the five gates are green on 3.11/3.12/3.13, tag vX.Y.Z, publish the wheel to PyPI, and close the tickets the release shipped. Use when asked to "release", "cut a release", "bump the version", "ship vX.Y.Z", or "tag a release".
---

<!-- release-version: 5 -->

# Release

Promote the current code to a versioned release: bump semver, verify the pipeline is green, tag,
publish, and close the tickets the release ships. Honest reporting throughout: **never claim
"released" until the publish pipeline is actually green.**

> This is the *invoked* ship. Its "bumped past the last tag" precondition is also enforced on
> every pull request by the `release-automation` gate. Note the limitation recorded there: this
> project works on `main` directly, so the gate often has no PR to fire on, which makes the
> precondition check below the real enforcement today.

## Version source

**Canonical:** `pyproject.toml`, key `project.version`. Nothing mirrors it.

`hitchrail.__version__` is read at runtime from `importlib.metadata.version("hitchrail")`, so
there is no second copy to keep equal. The version check guard that ships with this skill is
therefore a genuine no-op here, and that is the point: a mirror you do not have cannot drift.

The bump level comes from `docs/versioning.md`, which is the single semver authority. It is an
operator contract, not a public API contract: MAJOR is "the person running `uvx hitchrail` has to
change something".

```bash
# read the current version
python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

# the verdict against the latest release tag
VERSION_SOURCE=python bash scripts/version-lib.sh
```

## Bump modes

| Mode | Effect |
|---|---|
| `patch` / `minor` / `major` | bump `project.version` per `docs/versioning.md` |
| `sync` | nothing to sync. There is one source and no mirrors |

Bumping is a single committed step before the release runs:
`chore(release): bump version to X.Y.Z`. The **level is a human judgement**; do not infer it from
commit prefixes. Conventional Commit subjects are a hint and nothing more.

## Forge operations

GitHub, so `gh` is used directly. There is no `scripts/forge-lib.sh` in this repository and none
is needed.

| Step | Command |
|---|---|
| is CI green? | `gh run list --branch main --limit 1 --json conclusion -q '.[0].conclusion'` |
| does the tag exist? | `git tag -l "v<X.Y.Z>"` and `gh release view "v<X.Y.Z>"` |
| create the release | `gh release create "v<X.Y.Z>" --title "..." --notes "..."` |
| close a shipped ticket | `gh issue comment <N> --body "Released in v<ver>"` then `gh issue close <N>` |

## Release flow

### 1. Preconditions (verify, never force)

- **The version was bumped past the last published tag.** `scripts/version-lib.sh` prints `ahead`
  or `first-release`. `equal` means bump first; `behind` means the branch is stale
- **All five gates are green on all three interpreters.** Not four of five, and not "green on
  3.12 and probably fine on the others". The gates are `pytest`, `ruff check`,
  `ruff format --check`, `mypy` and `lint-imports`, on 3.11, 3.12 and 3.13:

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
gh run list --branch main --limit 1 --json databaseId,conclusion,name
```

- **The behaviour has been watched working in the running application.** This is a standing
  project rule, not a release formality: a phase is not finished because its code exists and the
  suite is green. For a release that means somebody has started, observed, gracefully stopped and
  killed a real Claude session with this build, and has seen a forged `Host` refused on a live
  socket. If nobody has, the release is not ready and saying so is the correct outcome
- **The working tree is clean** and the tag does not already exist

Report exactly which precondition failed and the single next action. Do not force past one.

### 2. Compute the release manifest

The tickets this release ships, read from commit **subjects** in the release range:

```bash
git log "v<last>..HEAD" --pretty=%s | grep -oP '\(#\K\d+' | sort -un
```

Subjects only. Commit bodies reference advisory numbers and cross links that are not tickets to
close.

### 3. Tag

This project works on trunk, so there is no release branch to fast forward. Tag directly on
`main`:

```bash
git tag -a "v<X.Y.Z>" -m "hitchrail v<X.Y.Z>"
git push origin "v<X.Y.Z>"
```

If the tag already exists, stop. Re-tagging a published version is never the answer.

### 4. Verify green, then claim

Pushing the tag fires a fresh CI run, and the publish workflow builds and uploads the wheel.

```bash
gh run list --limit 3 --json databaseId,status,conclusion,name
```

Wait for `success` before reporting the release as shipped. Never report "released" on `pending`
or `failure`.

Then confirm the artifact actually exists and installs, because a green workflow and a working
package are different claims:

```bash
uv run --with "hitchrail==<X.Y.Z>" --no-project -- hitchrail --help
```

That is the shape of the check that matters for a tool whose headline install is
`uvx hitchrail`: a stranger, on a machine that has never seen this repository, running it with
one command.

### 5. Close shipped tickets

For each ticket from step 2:

```bash
gh issue comment <N> --repo agigante80/hitchrail --body "Released in v<X.Y.Z>"
gh issue close <N> --repo agigante80/hitchrail
```

This is the step most easily forgotten by hand.

## Release notes

Written for someone deciding whether to upgrade, not for someone who already read the diff.

- lead with anything an operator has to act on. A MAJOR states what they must change, first line
- **security fixes are named plainly**, including what was reachable and by whom. A stated
  limitation is a feature of the documentation; do not soften it
- state what is still not protected: Hitchrail does not sandbox the sessions it starts, and over
  plain HTTP on a LAN the token crosses the network in cleartext
- no em dashes or en dashes. The repository enforces this with a hook, and release notes written
  outside the editor slip past it

## Reporting

Report: version bumped (old to new), gates green on which interpreters, tickets shipped and
closed, tag created, publish pipeline status, and the install check result. If a precondition
blocked the release, report the blocker and the one next action instead.

## Scope boundary

This versions the *product*. The `<name>-version` markers on the components under `.claude/` and
the `template-version` markers in `.github/ISSUE_TEMPLATE/` version those artefacts for drift
detection. Different axes; do not conflate them.
