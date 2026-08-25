# Semver as an operator contract, and where the bump decision lives

The gate enforces *that* a version was bumped. It deliberately does **not** decide *which* level
(patch/minor/major). That is a human judgement about impact a machine cannot reliably infer, and
auto-guessing it is the exact failure this component avoids. So the project needs a written rule
the author applies, and the canonical home for that rule is the project's **`docs/versioning.md`**.
Both the `release` skill and this skill point at `docs/versioning.md` as the single semver
authority, so the rule is stated once and never drifts between them.

## The contract for an application / service (not a library)

Mapping "public API" onto an app is awkward. For a service or Docker app, define semver as the
**operator/deployment contract**: what a person upgrading the deployment has to do:

- **MAJOR**: the upgrade breaks the deployment. A renamed/removed env var, a changed volume or
  on-disk data layout, a dropped platform/arch, an incompatible migration. The operator MUST
  change something to upgrade.
- **MINOR**: a new, backward-compatible, opt-in capability. Upgrading is safe with no action.
- **PATCH**: a bug fix, CVE/dependency update, or internal change with no operator-facing
  behaviour change.

(`0.y.z`: breaking changes may ship as MINOR until a stable `1.0.0`.)

For a library/package, fall back to the standard public-API definition (breaking API → MAJOR,
additive → MINOR, fix → PATCH).

## Deciding the level: guidance, not automation

- Conventional Commits (`feat:`→minor, `fix:`→patch, `BREAKING CHANGE`→major) may be used as a
  **hint**, never the authority: a mistyped or forgotten prefix mis-bumps silently, and a
  squash-merge ignores commit messages and uses the PR title. The human picks; the gate enforces.
- The dependency-update lane (lane B) is the one exception where the level is machine-decidable,
  because the change is "consume an upstream release" with bounded impact → PATCH (majors of a
  dependency fall back to the human gate).

## Notes for forge-adapt

- Generate or update the project's **`docs/versioning.md`** from this contract, tailored to the
  project's real surface (its actual env vars, volumes, supported platforms).
- Phrase MAJOR triggers in the project's own terms during adaptation (e.g. "renames a `FOO_*`
  env var", "changes the `/data` schema") so the rule is concrete, not generic.
- Leave the bump itself to the author; the gate guarantees they did not skip it.
