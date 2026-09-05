# Hitchrail: versioning

The single semver authority for this project. The release gate enforces *that* a version was
bumped; it deliberately does not decide *which* level. That judgement is yours, and this document
is the rule you apply.

## The canonical source

`pyproject.toml`, key `project.version`. One place, and nothing mirrors it.

`hitchrail.__version__` is read at runtime from `importlib.metadata.version("hitchrail")` rather
than written out a second time. A hand synced mirror is a thing that can disagree with itself,
and the cheapest way to pass a version drift check is to have nothing to check.

This is a deliberate departure from the forge-kit reference, which prefers tag derived versioning
(`setuptools-scm` or `hatch-vcs`) for a project that builds a wheel. Tag derived is cleaner in the
abstract: there is no file to forget to bump. It is wrong here for two reasons, and both are worth
writing down so the next reader does not relitigate it:

- it replaces `uv_build` as the build backend, which the design chose on purpose (the `uv init`
  default, and much faster than hatchling), and
- it adds a build time dependency to a project whose entire discipline is having three
  dependencies and being small enough to audit.

If the build backend ever changes for an unrelated reason, revisit this. Until then, one version,
in `pyproject.toml`.

## The contract

Hitchrail is a published package that people run as a tool: `uvx hitchrail`. So semver here means
the **operator contract**: what somebody upgrading has to do.

**MAJOR** - the upgrade breaks the person running it. They must change something:

- a removed or renamed CLI flag, or a changed default that alters what gets bound
- a removed or renamed HTTP route, or a changed response shape the interface branches on
- a removed or changed error `code` (`ram_soft`, `ram_hard`, `self_protected`, `start_died`,
  `url_pending`, `locked`), because a script can be branching on it
- a changed tmux session prefix, since existing sessions stop being recognised
- dropping a Python version from the supported set
- a security control becoming stricter in a way that refuses a configuration that used to work,
  for example requiring a token where one was previously optional

**MINOR** - a new backward compatible capability. Upgrading is safe with no action:

- a new route, a new flag, a new state surfaced in the interface
- a new error `code` alongside the existing ones
- a new configuration option with a default that preserves the current behaviour

**PATCH** - a bug fix or an internal change with no operator facing behaviour change:

- a fix to state derivation that makes a wrong answer right. This is a patch even though the
  reported state changes, because the previous answer was a defect, not a contract
- a dependency or CVE update
- a tmux footgun workaround
- documentation, tests, tooling

While the version is `0.y.z`, a breaking change may ship as MINOR. That ends at `1.0.0`, and
`1.0.0` should be cut when the HTTP interface is one you are willing to keep.

**That outstanding interface change is now decided, and it still has to LAND before 1.0.**
Phase 12 asked what identifies a project when there is more than one root. Today it is the
folder name, which stops being unique the moment a second root exists, and that name is the
path segment, the tmux session suffix and the interface's row key at once.

#119 decided it on 2026-09-04: **a project is `<root-label>~<folder>`, always, including with
one root.** The reasoning is in the design, section 6.0. What matters here is the level.

**Shipping it is a breaking change to the operator contract, and it ships as MINOR because the
version is `0.y.z`.** Every existing identifier gains a prefix, so every saved `/grant` link
and every `POST /api/sessions/{name}` written against 0.1.0 changes. That is a MAJOR after
1.0 and a MINOR before it, which is the whole reason this was pulled forward: 0.1.0 was
published on 2026-09-04 with no installed base, and the cost of the break rises from that day
onward and never falls.

**1.0 cannot be cut until this has landed**, not merely until it has been decided. A decision
recorded and not implemented leaves the interface exactly as unwilling to keep as it was.

## The machine ships the level; it never picks one

#133 automated the release: a merge to `main` tags, releases and publishes, with no
approval click. **What it did not automate is the number.** `release.yml` reads
`pyproject.toml` and ships what it finds; it has no bump step, and adding one would
contradict the section below rather than extend it.

The upstream component this was adapted from auto-patches every green merge. That suits a
trunk where merges are commits. Here a merge to `main` is a reviewed batch that already
carries a deliberate version, because the release gate refuses one that does not.

## Deciding the level

Conventional Commit prefixes are a **hint, never the authority**. A mistyped prefix mis-bumps
silently, and a squash merge uses the pull request title rather than the commit messages. You
pick; the gate enforces that you picked.

The one place a machine can decide is a dependency bot update: consume an upstream release,
bounded impact, PATCH. That lane is not installed here, because there is no dependency bot on
this repository yet.

## Security releases

A fix to one of the seven controls in `docs/tech-guidelines.md` section 5 is a PATCH by the rule
above, and that is correct: the contract did not change, the implementation was wrong. But it is
not an ordinary patch in any other sense.

- cut it on its own, not batched with unrelated work, so people can read the diff
- say plainly in the release notes what was reachable and by whom, including the parts that are
  inconvenient to admit. A stated limitation is a feature of the documentation
- if the fix requires an operator to change something, that is a MAJOR, and the awkwardness of
  that is not a reason to pretend otherwise

## What the version is not

The `<name>-version` markers on the components under `.claude/` version those governance
components for drift detection. `template-version` in `.github/ISSUE_TEMPLATE/` versions the
issue templates. Neither has anything to do with the version of Hitchrail. Different axes; do not
conflate them.
