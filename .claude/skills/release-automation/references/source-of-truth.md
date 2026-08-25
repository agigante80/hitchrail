# Version source of truth: pick one canonical source, wire `version-lib.sh` to it

Every lane compares "the working-tree version" to "the latest release tag". That comparison is
only as trustworthy as the *single* place the version lives. Mirrored versions (a `VERSION` file
*and* `pyproject.toml` *and* a lockfile, all hand-synced) can disagree with themselves, so the
gate ends up asking an unanswerable question. **Pick one canonical source per project**; the
`release` skill's version-check guard keeps any mirrors equal to it.

## Choose the source, set `version-lib.sh` env accordingly

| Project shape | Canonical source | `version-lib.sh` config |
|---|---|---|
| Docker image / service / app, **not** a published package (e.g. Flask+Docker, the TunnelSentinel case) | a plain-text `VERSION` file, read at runtime and baked into the image | `VERSION_SOURCE=file`, `VERSION_FILE=VERSION` |
| Node / TS package | `package.json` `version` | `VERSION_SOURCE=node` |
| Python **package** (builds a wheel) | tag-derived via `setuptools-scm`/`hatch-vcs`, with *no file at all* | `VERSION_SOURCE=git` (see `references/python-tag-derived.md`) |
| Python app, no wheel | a `VERSION` file or `pyproject.toml` `project.version` | `VERSION_SOURCE=file` or `python` |
| Rust crate | `Cargo.toml` `package.version` | `VERSION_SOURCE=cargo` |
| Anything else | a command that prints the version | `VERSION_SOURCE=cmd`, `VERSION_CMD='…'` |

## The end-state: tag-derived (no file to forget)

The cleanest source is **the git tag itself** (`setuptools-scm`, `hatch-vcs`, or `git describe`).
Then there is no version file to forget to bump, so "forgot to bump" becomes structurally
impossible, and the gate degrades to "main has unreleased commits → cut a tag" (the
`unreleased_commits` helper). Set `VERSION_SOURCE=git`; the full Python setup is in
`references/python-tag-derived.md`. It has one hard requirement that bites in CI:
**the build/checkout must have full history and tags**:

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0, fetch-tags: true }
```

Otherwise the derived version silently becomes `0.0`/garbage. The same `fetch-depth: 0` requirement
applies to `version-lib.sh` in *every* mode, because `latest_tag` needs the tags present.

## Notes for forge-adapt

- Detect the canonical source from the stack (lockfiles, `pyproject.toml`, a `VERSION` file,
  existing tags) and set the lane workflow's `env:` block + the `scripts/version-lib.sh` path.
- Default a Docker/service project to the `VERSION`-file mode: it is the honest, tooling-free
  choice when the artifact is an image, not a wheel.
- Where the stack builds a wheel, prefer the tag-derived mode and add the `fetch-tags` step.
- Keep one canonical source; if the project already has mirrors, wire the `release` skill's
  version-check guard so they cannot drift.
