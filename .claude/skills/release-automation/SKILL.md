---
name: release-automation
description: Enforce Hitchrail releases in CI so a merge to main cannot silently ship without a version bump. Installs the Lane A release gate on pyproject.toml project.version, backed by scripts/version-lib.sh. The enforced sibling of the invoked `release` skill. Use when asked to "enforce version bumps", "block merge without a release", or "stop forgetting to tag releases".
---

<!-- release-automation-version: 8 -->

# Release automation

Make the missing release impossible. The `release` skill is the invoked ship someone runs; this
is the CI layer that runs without being invoked, so a merge to `main` with no version bump is
blocked rather than silently shipped.

> **Composition, not duplication.** The semver rules and the version source live in
> `docs/versioning.md` and the `release` skill. This skill enforces them; it does not restate
> them. See `references/semver-operator-contract.md` and `references/source-of-truth.md`.

## The limitation, stated up front

This project's git convention is to **work on `main` directly**. Lane A triggers on
`pull_request`, so a trunk commit never opens one and the gate never fires for it.

That is not a reason to skip installing it: the moment any work arrives as a pull request, the
gate governs it, and the cost of having it sit there is zero. It **is** a reason not to read the
green checks list as "the version was gated". Until work moves to pull requests, the real
enforcement is the `release` skill's precondition check at the moment somebody cuts a release.

If you want enforcement on trunk commits too, that is a deliberate change to the branching model,
not a workflow tweak. Say so in a ticket rather than bolting a push trigger onto this gate, which
would fail every ordinary commit, since `equal` is the normal verdict for one.

## The one mechanism: version vs latest tag

Every lane shares a single primitive, `scripts/version-lib.sh`, which compares the working tree
version against the latest **released tag** (not the previous commit; the tag is the only truth
for "what is released") and prints one verdict:

| Verdict | Meaning | What a lane does with it |
|---|---|---|
| `first-release` | no release tag yet | allow |
| `ahead` | version > latest tag, bumped deliberately | ship as-is, never re-bump |
| `equal` | version == latest tag, nobody bumped | the lane's policy decides |
| `behind` | version < latest tag, branch is stale | hard stop, this is a regression |

The `ahead` and `behind` handling is the load bearing part: it stops a naive "always patch"
double-bumping a deliberate `1.5.0` into `1.5.1`, and refuses to publish a regression.

## Version source for this project

`VERSION_SOURCE=python`, which reads `pyproject.toml` `project.version`. Nothing mirrors it, so
there is nothing to cross-check and the `release` skill's version guard is a genuine no-op.

`references/source-of-truth.md` recommends tag derived versioning (`setuptools-scm` /
`hatch-vcs`) for a project that builds a wheel, on the grounds that there is then no file to
forget to bump. **We deliberately do not**, for two reasons recorded in `docs/versioning.md`:
it would replace `uv_build` as the build backend, which the design chose on purpose, and it adds
a build time dependency to a project whose whole discipline is having three. Revisit only if the
build backend changes for an unrelated reason.

`fetch-depth: 0` and `fetch-tags: true` are mandatory in the gate's checkout. Without them
`latest_tag` sees nothing and every release looks like a `first-release`.

## Lanes

| Lane | Trigger | Policy on `equal` | Installed here? |
|---|---|---|---|
| **A (Gate)** | PR to `main` | block the merge | **yes** |
| **B (Auto-release on dependency)** | bot PR, CI green | auto-patch + tag + release | no |
| **C (Auto-release on merge)** | every merge, CI green | auto-patch + tag + release | no |

**Lane B is not installed** because there is no dependency bot on this repository. If Dependabot
or Renovate is added later, Lane B becomes the lane that ships an upstream security fix without a
human in the loop, and it earns its machinery: an App token, a recursion guard, and concurrency
control. Read `references/github-token-gotcha.md` before adding it. It also needs a `DEP_PATHS`
scope, which for this project is `pyproject.toml` and `uv.lock` only.

**Lane C is not installed and should not be.** It auto-releases every green merge, which suits a
continuous deployment trunk. Hitchrail publishes deliberate, batched releases to PyPI, where a
version number is a promise to strangers who install it with `uvx`. Auto-patching every merge
would turn that promise into noise. Lane C also supersedes Lane B; never install both.

## What is installed

- `scripts/version-lib.sh` - the verdict primitive, copied verbatim. Stack agnostic, do not edit
  it to adapt; adapt the workflow `env:` block instead
- `.github/workflows/release-gate.yml` - Lane A, wired to `VERSION_SOURCE=python` and `main`
- `docs/versioning.md` - the semver authority, in this project's own terms

**Make `version-bumped` a required status check** on `main` in the repository settings. Until it
is, the gate advises and cannot block, and an advisory gate is a gate that gets clicked past.

## Interaction with the rest of the kit

- **`/ci-health`** discovers all workflows and auto-fixes safe CI failures, but a red release gate
  is an intentional governance signal, not a breakage. The adapted `/ci-health` command treats it
  as investigate-only, the same carve-out it uses for E2E, `lint-imports` and the template
  lockstep guard. Never let it "fix" the gate by auto-bumping the version
- **`dep-auditor`** finds dependency problems and files tickets. Without Lane B, a human ships the
  update through the ordinary release
- **Component markers** (`<name>-version`) and `template-version` markers version the governance
  artefacts; this skill versions the product. Do not conflate them

## Adapting further

- The production branch is `main`
- The version source `env:` is `VERSION_SOURCE: python`; there is no `VERSION_FILE`
- The script path is `scripts/version-lib.sh`
- The bump level stays with the author. The gate guarantees they did not skip it
- Release notes and comments follow the project's writing rules, including no em or en dashes
