# Releasing

The steps under "Once, before the first release" can only be done by the project
owner in a browser. Everything after that is automatic: the build, the wheel
checks and the upload all run in CI with no credential stored anywhere.

**No count here.** This line said "two of these steps" and a third was added
below it in the same edit, which is how a number in prose goes wrong. The
browser only steps are the ones in that section, and the section is the list.

## Once, before the first release

**0. A PyPI account, with 2FA and a verified email.** Everything below lives
inside an account, so there is nothing to configure before one exists. PyPI
requires two factor authentication on every account and a verified email
address before you may register a project or upload a file. **TestPyPI is a
separate site with its own registration and its own 2FA**, so the rehearsal
below needs a second account rather than the same one.

The PyPI username does not appear anywhere in the configuration. Trusted
publishing authenticates the GitHub identity, so the account you log in with
and the `Owner` field below are unrelated and do not have to match.

**1. Configure the trusted publisher on PyPI.** Owner only, and there is no API
for it.

**It is a PENDING publisher, and it is not where you would look for it.**
`hitchrail` has never been published, so there is no project on PyPI and
therefore no project settings page. The form for a name that does not exist yet
is in the ACCOUNT sidebar, under `Publishing`. It asks for the project name as
well, which the project scoped form does not. After the first publish the same
settings move under the project, which is why every walkthrough written by
somebody who has already shipped describes the other page.

| Field | Value |
|---|---|
| Project name | `hitchrail` (pending publisher form only) |
| Owner | `agigante80` (the GitHub owner, not the PyPI username) |
| Repository | `hitchrail` |
| Workflow | `publish.yml` |
| Environment | `release` |

The workflow filename and the environment name are part of the trust, so
renaming either breaks publishing until PyPI is updated to match.

**Fill in the environment.** PyPI treats it as optional. It is not optional
here: leaving it blank produces a trust that does not require the `release`
environment, and the required reviewer on that environment is the only thing
making a publish need a human click.

**A pending publisher does not reserve the name.** It takes effect when it is
first used to publish, and until then `hitchrail` remains claimable by anybody.
The name was free on PyPI on 2026-08-25 and again on 2026-09-04, under
`hitchrail`, `hitch-rail` and `hitch_rail`. That is a fact with an expiry date,
which is an argument for doing the rehearsal sooner rather than tidily.

Do the same on TestPyPI, for the rehearsal below.

**2. Create the `release` environment** in the repository settings, with
yourself as a required reviewer. That is what makes a publish need a human
click rather than only a workflow run. Without it the workflow still works and
nothing gates it.

**Why no API token.** A token is long lived, so whoever steals it can publish
until somebody notices and revokes it. Trusted publishing exchanges a GitHub
OIDC identity for one that expires within fifteen minutes, and PyPI signs
Sigstore attestations for the artefacts as a side effect. `#4` pinned every
action in anticipation of this pipeline holding a credential; it holds none,
and `tests/test_workflows_are_pinned.py` fails if one is added.

## The rehearsal, once

**A version number on PyPI cannot be reused**, only yanked. So the first real
upload must not be the first time the artefact has been installed from an
index.

1. Run the `publish` workflow by hand, with `index: testpypi`.
2. Install from TestPyPI into a clean machine or container and run it:

   ```sh
   uv venv /tmp/probe && /tmp/probe/bin/pip install \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ hitchrail
   /tmp/probe/bin/hitchrail --version
   ```

   The extra index is needed because the three runtime dependencies live on
   real PyPI, not on TestPyPI.

3. Record the transcript on #116.

## Every release

1. **Decide the level** from `docs/versioning.md`. Semver here is an operator
   contract: a change is MAJOR when the person running `uvx hitchrail` must
   change something. While the version is `0.y.z`, a breaking change may ship
   as a MINOR, and both changes carried by the first release are breaking.

2. **Move the `Unreleased` section of `CHANGELOG.md`** under the new version
   heading, and write anything missing. Entries say what an operator must DO,
   not what changed. A security fix says plainly what was reachable and by
   whom, including the parts that are embarrassing.

3. **Bump `version` in `pyproject.toml`.** `release-gate.yml` checks on every
   pull request that it is ahead of the latest release tag.

4. **Regenerate the screenshots** if the interface changed:

   ```sh
   uv run pytest -m screenshots
   ```

   They are committed rather than attached to a release, because GitHub renders
   the README from the repository. Regenerating at a release rather than on
   every change is what keeps a binary diff out of ordinary pull requests.

5. **Run the gates**, and the browser tier, which is not in the default run:

   ```sh
   uv run ruff format --check . && uv run ruff check && uv run mypy \
     && uv run lint-imports && uv run pytest
   ```

6. **Tag and publish a GitHub release.** A tag alone publishes nothing: the
   workflow triggers on a published release, because a tag is a bookmark and
   publishing is a decision.

7. **Approve the `release` environment** when GitHub asks. That is the human
   click.

8. **Verify from the index**, not from the build:

   ```sh
   uvx hitchrail@<the new version> --version
   ```

   The phase's own exit criterion is `uvx hitchrail` working on a machine that
   has never seen this repository. Check the thing itself.

## What is deliberately not automated

**The version bump and the changelog.** Both are judgements about what a change
costs an operator, and a generated changelog would carry every commit subject.
Those subjects are written for a reviewer and say why a change was not the
obvious alternative, which is the wrong register for somebody deciding whether
to upgrade.
