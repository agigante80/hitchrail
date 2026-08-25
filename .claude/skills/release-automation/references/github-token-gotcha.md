# The GITHUB_TOKEN trap and the recursion-immunity trade-off

Any lane that *writes* (pushes a tag, pushes a bump commit), namely Lanes B and C, hits one
non-obvious GitHub behaviour. Getting it wrong produces either a release that never publishes, or
an infinite workflow loop. Both are baked into the templates; this explains why.

## 1. A tag pushed with the default `GITHUB_TOKEN` does NOT trigger other workflows

GitHub deliberately does not start a workflow run from an event caused by the repository's default
`GITHUB_TOKEN`, to stop a workflow from recursively triggering itself. The only exceptions are
`workflow_dispatch` and `repository_dispatch`.

Consequence: if Lane B pushes the `vX.Y.Z` tag with the default `GITHUB_TOKEN`, your
`on: push: { tags: ['v*'] }` **publish** workflow will **not** fire. The release is tagged but
never built/published: a silent half-release.

**Fix (what the template does):** mint a **GitHub App installation token** with
`actions/create-github-app-token` and use it for checkout (so the later `git push` and `git tag`
push use it) and for `gh release create`. A tag pushed with an App token *is* a real identity
event, so it triggers the downstream publish workflow.

- Preferred: a GitHub App (least-privilege, short-lived, not tied to a person). Needs `contents:
  write` on the repo; store `RELEASE_APP_ID` + `RELEASE_APP_PRIVATE_KEY` as secrets.
- Fallback: a PAT secret (a personal identity, broader scope); swap the token step for it.
- Token-free alternative: have the release workflow `repository_dispatch` the publish workflow
  instead of relying on the tag push (the one event the default token *can* trigger).

## 2. Adopting an App token forfeits the free recursion immunity, so guard the loop

The flip side: the default token's non-triggering behaviour was *free loop immunity*. A workflow
that pushes its own bump commit with the default token physically cannot re-trigger itself. The
moment you switch to an App token (step 1) to get downstream triggering, that immunity is gone:
the bump commit now fires `on: push`/`workflow_run` again, including this workflow. So you MUST add
an explicit guard. The templates use:

- **Recursion guard**: the first real step inspects the head commit subject and exits early if it
  is our own `chore(release): automated version bump …` commit. This terminates the loop after
  exactly one extra (no-op) CI run.
- **`concurrency` with `cancel-in-progress: false`**: collapses pile-ups from rapid merges
  without ever cancelling a half-finished tag/release.

> **Reserved subject: why it is distinct.** The guard matches the literal commit-subject prefix
> `chore(release): automated version bump` (a quoted `case` pattern, not a regex), which only this
> lane's bot uses. It is deliberately different from the `release` skill's
> *human* `chore(release): bump version to X.Y.Z`, so a real human-cut release is never mistaken
> for the bot's own commit and silently skipped. Don't reuse the `automated version bump` subject
> for manual commits.

## 3. Why `workflow_run` + `head_sha`, not `on: push`

Lanes B/C trigger on `workflow_run` after the CI workflow concludes `success`, and check out
`github.event.workflow_run.head_sha`, i.e. they release *exactly the commit CI validated*, and
only if it was green. Triggering on raw `push` would let a release race ahead of (or instead of) a
passing test run. The cost is one coupling: the `workflows: ["CI"]` filter must match the CI
workflow's `name:` exactly (forge-adapt wires this).

Note: in the `equal` case the lane tags the bump commit it just pushed (the new version lives only
there). That bump commit is a mechanical one-line change on top of a validated tree; its own CI
re-run is redundant but harmless, and the recursion guard turns it into a no-op.

**Push-race handling.** Because checkout is detached at `head_sha`, the branch tip may have advanced
by the time the lane pushes. The template `git fetch origin "$BRANCH" && git rebase FETCH_HEAD`
before pushing, so the push is a fast-forward, never `--force`. A genuine concurrent version bump
surfaces as a rebase conflict (the run fails loudly and is retried on the next trigger) rather than
a silently lost release. The tag/release step is idempotent (skips an existing tag/release), so a
retried or half-finished run converges instead of wedging on `tag already exists`.

## Sources
- GITHUB_TOKEN does not trigger workflows: https://docs.github.com/en/actions/concepts/security/github_token
- create-github-app-token: https://github.com/actions/create-github-app-token
- Skipping/triggering & loops: https://docs.github.com/en/actions/managing-workflow-runs/skipping-workflow-runs
