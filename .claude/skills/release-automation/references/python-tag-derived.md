# Python tag-derived versioning (setuptools-scm / hatch-vcs)

The cleanest version source is **the git tag itself**: there is no `VERSION` file and no version
in `pyproject.toml` to forget to bump. "Forgot to bump" becomes structurally impossible because
there is nothing to bump; the only act is pushing a tag. This is the preferred path for a Python
project that **builds a wheel/sdist**. (For a Python *app* shipped as a Docker image, the
`VERSION`-file path in `source-of-truth.md` is simpler, and tag-derived only pays off when you build a
distributable.)

## pyproject.toml

setuptools-scm:

```toml
[build-system]
requires = ["setuptools>=64", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "yourpkg"
dynamic = ["version"]          # version is NOT written here; it comes from the tag

[tool.setuptools_scm]          # presence enables it; section can be empty
```

hatch-vcs:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "yourpkg"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
```

At build time the version is derived from `git describe`: an exact tag `v1.4.0` → `1.4.0`; commits
after it → a dev version like `1.4.1.dev3+g<sha>`.

## The hard CI requirement (the #1 footgun)

The build needs **full history and tags present**, or the derived version silently degrades to
`0.0`/garbage:

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0, fetch-tags: true }
```

This applies to the build, the publish job, and `version-lib.sh` in every mode.

## How the release-automation lanes apply

Set `VERSION_SOURCE=git`. `read_version` then returns the latest tag's version (via
`git describe --tags --abbrev=0 --match "$TAG_GLOB"`).

- **The Lane A gate is moot.** There is no file a PR can bump, because the version always equals the
  latest tag, so "was the version bumped?" is unanswerable. Don't install the file-bump gate for a
  tag-derived project. The meaningful signal instead is `unreleased_commits` (commits since the
  last tag); use it for an *advisory* "main has unreleased work, cut a release" reminder, not a
  hard merge block.
- **Lane C is the natural fit.** `assets/lane-c-auto-release-on-merge.yml` with `VERSION_SOURCE=git`
  treats every green merge as a release and pushes the next patch **tag**, with no commit and no file
  write. setuptools-scm/hatch-vcs then derive the wheel version from that tag. Minor/major releases
  are still done by pushing that tag by hand (`git tag v1.5.0 && git push --tags`); the lane resumes
  auto-patching from there.
- **Bootstrap.** With no tags yet there is no version to derive, so Lane C emits a one-line notice
  and does nothing until you push an initial tag (e.g. `v0.1.0`). After that the automation runs.

## Publishing

Publish on the pushed tag via **PyPI Trusted Publishing** (OIDC, no long-lived token):

```yaml
permissions: { id-token: write }
# ... build sdist+wheel (with fetch-depth: 0), then:
- uses: pypa/gh-action-pypi-publish@release/v1
```

Build the artifact **once**, test that exact artifact, then publish it. Don't rebuild after
testing. Attest provenance (`actions/attest-build-provenance`) on the same artifact when you want
SLSA build-level assurances.

## Trade-offs to accept

- The version only exists *after* a build (or `git describe`); there's no static file to read; CI
  steps that need the version derive it (`python -m setuptools_scm`, or `version-lib.sh` git mode).
- `fetch-depth: 0 + fetch-tags: true` is mandatory everywhere; a shallow clone breaks versioning
  silently.
- A dirty/dev tree yields a `.devN+g<sha>` version: fine for CI builds, surprising if unexpected.
