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

**2. Create the `release` environment** in the repository settings.

**It must exist, and it must be named `release`.** PyPI's trusted publisher
above names it, so the OIDC claim has to carry it. Deleting the environment
does not merely remove a gate: it makes every publish fail.

**It carries no required reviewer, and that is a decision rather than an
oversight.** It had one briefly. The reasoning for removing it: `publish.yml`
runs only on a published GitHub release or a manual dispatch, both of which
already need repository permissions, so on a single maintainer repository the
reviewer asks the same person who just clicked "publish release" to click again
one screen later. Anyone able to trigger a publish here can also approve it, so
the gate stopped a threat that does not exist while adding a step to every
release.

**Put it back the moment a second person gets write access.** Then the control
becomes real: a collaborator with write but not admin, or an Action that can
trigger a workflow but not approve a deployment, is exactly what a required
reviewer stops. What survives without it is the part that was always doing the
work: trusted publishing with no stored credential, and every third party action
pinned to a SHA.

**Do not remove a reviewer while a deployment is waiting on it.** GitHub fails
the pending deployment rather than releasing it, and the run reports a failed
`publish` job with zero steps and no log, which reads like a broken pipeline and
is not one. Re-run the workflow.

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
   uv venv /tmp/probe
   uv pip install --python /tmp/probe/bin/python \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ hitchrail
   /tmp/probe/bin/hitchrail --version
   /tmp/probe/bin/python -c "from hitchrail import pages; print(sorted(p.name for p in pages.WEB.iterdir()))"
   ```

   The extra index is needed because the three runtime dependencies live on
   real PyPI, not on TestPyPI.

   **`uv pip install --python`, not `/tmp/probe/bin/pip`.** `uv venv` creates an
   environment with no `pip` in it, so the obvious form of this command fails
   with "No such file or directory" on the one step whose whole job is proving
   an install works. Found by running it: this document had the broken form
   through the first rehearsal.

   The last line is the check worth keeping. `--version` passes on a wheel whose
   `web/` is missing, and the interface 404s only once somebody opens the page.

3. Record the transcript on #116.

## Every release

**A release is a pull request from `develop` to `main`**, since #132. Work lands on
`develop`; opening the PR is what says "this batch is a release", and `version-bumped`
is a required status check on `main`, so the merge is blocked until step 3 is done. The
gate is no longer advisory and no longer dormant.

Steps 1 to 5 happen ON the pull request. Steps 6 onward happen after it merges.

1. **Decide the level** from `docs/versioning.md`. Semver here is an operator
   contract: a change is MAJOR when the person running `uvx hitchrail` must
   change something. While the version is `0.y.z`, a breaking change may ship
   as a MINOR, and both changes carried by the first release are breaking.

2. **Move the `Unreleased` section of `CHANGELOG.md`** under the new version
   heading, written as `## 0.4.0 - 2026-09-05`: the number, a space, a hyphen,
   the date, and **no brackets**. Keep a Changelog puts brackets round the
   number and `release.yml` cannot parse that form, so a bracketed heading
   publishes no notes and stops the release after the merge. That is checked
   locally now, and the check exists because it was not.

   Write anything missing. Entries say what an operator must DO,
   not what changed. A security fix says plainly what was reachable and by
   whom, including the parts that are embarrassing.

3. **Bump `version` in `pyproject.toml`, then run `uv lock`.** `release-gate.yml`
   checks on every pull request that it is ahead of the latest release tag, and since
   #132 it is a REQUIRED check, so forgetting this blocks the merge rather than
   producing a release that quietly reuses a number.

   **`uv lock` is not optional and the gate will not tell you.** `uv.lock` records
   this project's OWN version, CI runs `uv sync --locked`, and a stale lock fails
   every leg of the matrix on the first step with `the lockfile at uv.lock needs to
   be updated`. `version-bumped` passes while that happens, because it reads
   `pyproject.toml` and nothing else. Written down because the failure names the
   lockfile and not the bump that invalidated it: 0.3.0 lost a CI round to it.

4. **Regenerate the screenshots** if the interface changed:

   ```sh
   uv run pytest -m screenshots
   ```

   They are committed rather than attached to a release, because GitHub renders
   the README from the repository. Regenerating at a release rather than on
   every change is what keeps a binary diff out of ordinary pull requests.

5. **Run the gates**, then the tiers the default run leaves out:

   ```sh
   uv run ruff format --check . && uv run ruff check && uv run mypy \
     && uv run lint-imports && uv run pytest
   uv run pytest -m "e2e or live or live_tmux"
   ```

   **`-m` REPLACES the default deselection rather than narrowing it.** `addopts`
   carries `-m "not screenshots"`, so any `-m` of your own drops that and the
   screenshots tier runs with whatever else you asked for, rewriting five PNGs.
   Harmless at a release, since step 4 regenerates them anyway; a surprise binary
   diff at any other time. Name `screenshots` when you want it and check
   `git status` when you did not.

6. **Merge the pull request.** That is the release, and nothing follows it.

   `release.yml` fires on the push, tags `vX.Y.Z`, publishes a GitHub release whose
   notes ARE the changelog section you wrote in step 2, and calls `publish.yml` to
   upload. No approval click and no second test run.

   **The preconditions are met before the merge, on purpose.** CI green on the pull
   request from `develop`, and step 5's full local run including the browser tier.
   The merge is a decision that has already been made; re-answering it after the fact
   would add a step to every release to learn nothing new.

   **It refuses rather than guessing.** No changelog section for the version, a
   version already on PyPI, or an unreadable answer from PyPI each stop the run
   with a message naming the cause. A version number cannot be reused, only
   yanked, so discovering a collision inside twine is too late.

   Re-running it on an already tagged commit does nothing, so a re-run is never
   destructive.

7. **Verify from the index**, not from the build:

   ```sh
   uvx hitchrail@<the new version> --version
   ```

   The phase's own exit criterion is `uvx hitchrail` working on a machine that
   has never seen this repository. Check the thing itself.

## What is deliberately not automated

**The version bump and the changelog**, and #133 deliberately kept them that way while
automating everything after them. forge-kit's Lane C auto-patches every green merge; this
project does not, because both are judgements about what a change costs an operator and a
generated changelog would carry every commit subject.
Those subjects are written for a reviewer and say why a change was not the
obvious alternative, which is the wrong register for somebody deciding whether
to upgrade.
