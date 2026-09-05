# Changelog

**What you have to DO, not what changed.** The diff already says what changed.
This says whether taking a version costs you anything, which is what
[`docs/versioning.md`](docs/versioning.md) means by calling semver an operator
contract.

Most commits produce no entry here. A change nobody running Hitchrail can
notice does not belong in this file.

Hand written rather than generated. The commit subjects are written for a
reviewer and say why a change was not the obvious alternative, which is the
wrong register for somebody deciding whether to upgrade.

**Security fixes say plainly what was reachable and by whom**, including the
parts that are embarrassing. `docs/versioning.md` requires it.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with
one deliberate departure: **a version heading is `## 0.4.0 - 2026-09-05`,
without the brackets that standard puts round the number.**

That is not cosmetic and it is not free to get wrong. `release.yml` builds the
GitHub release notes by finding `^## <version>`, so a bracketed heading matches
nothing, the notes come back empty and the release refuses after the merge to
`main`. It happened on 0.4.0, and the bracketed form is what a careful author
writes precisely BECAUSE this line names that standard. The departure is
written down here rather than left as a trap, and
`test_every_released_version_has_notes_the_release_job_can_extract` runs the
workflow's own script so it fails locally instead.

While the version is `0.y.z`, a breaking change may ship as a MINOR.

## Unreleased

## 0.4.0 - 2026-09-05

### Fixed

**A session stuck on a prompt looked healthy.** If an agent put up anything that
needed answering, other than the workspace trust prompt, its row said `running`
and nothing else: no link, no explanation, and no way to tell it apart from a
session that was working. From a phone there was nothing to act on. Such a row
now says it is waiting for an answer, the same wording a timed out stop already
produced.

A row where somebody is simply typing is NOT flagged, which the previous check
could not tell apart. It looked for an empty input box; the question is whether
there is an input box at all.

**What this costs:** Hitchrail now reads the screen of running sessions that
have no link yet, on the background timer rather than when you load the page, at
most ten of them a second and never for longer than three seconds at a stretch.
Nothing you tap waits on it. On a machine with nothing stuck it reads nothing,
and with nobody looking at the page it does not even check: a Hitchrail sitting
idle overnight costs exactly what it did before.

**A live agent inside another tool's tmux session was reported as orphaned.**
If anything else on your machine runs agents in its own tmux sessions, those
projects showed as `detached` with the words "no tmux session", while the agent
was sitting in a terminal you had open. On the machine this was found on, eight
rows at once. Nothing was lost by it, but `detached` is the row that invites you
to go and deal with a process by hand, so it pointed people at the wrong action.

Such a row now names the session that holds the agent, and a row where no owner
can be seen says "no session Hitchrail can address" rather than claiming there
is no session at all. Hitchrail reads which sessions exist and still creates,
signals and kills only its own.

**For anyone driving the API:** every session now carries `foreign_session`,
which is the owning session's name or `null`. `null` means no owner was seen,
not that the agent is orphaned: ownership is read from the one tmux server
Hitchrail is configured to talk to.

**Under a systemd unit the startup banner never reached the journal.** Python
block buffers standard output when it is not a terminal, so the banner sat in a
buffer that a running server never flushes, and the whole log was uvicorn's four
lines. What was lost is the only statement of which addresses the server will
answer to, and the warning that fires when a service has no `HITCHRAIL_TOKEN`
and is therefore invalidating the link on your phone at every restart. Nothing
to do: the banner flushes itself now, and `packaging/hitchrail.service` also
sets `PYTHONUNBUFFERED=1` for everything else a service prints.

### Documentation

The README leads with the setup most people want: several roots, running as a
service, reachable from a phone, as one recipe rather than four sections that
each held part of it.

## 0.3.0 - 2026-09-05

**MINOR, and nothing to do on upgrade unless you were reading the token from
inside a session Hitchrail started.**

### Security

**A session Hitchrail starts no longer inherits `HITCHRAIL_TOKEN`.** Before this
version it did, and the agent could print it. That is worth saying plainly: the
token is the only thing between a stranger on your network and a shell on this
machine, "print your environment" is an ordinary thing to ask an agent, the
answer lands in a pane, and the log drawer shows panes. It was also reachable
without anybody asking, since an agent reads repositories that can contain
instructions.

What it never was: an escalation. The agent runs as you with permissions
skipped, so it could already read whatever file you put the token in. What
changes is how easy the token is to stumble into and how likely it is to end up
somewhere you did not intend, such as a transcript.

Nothing to configure. The spawn is prefixed with `env -u HITCHRAIL_TOKEN`.

### Fixed

Answers about a shared machine, where another tool's tmux server, a tmux binary
under a different name, or a terminal emitting an unusual escape used to produce
a confident wrong answer:

- a tmux binary named `tmux3.4` or `tmux-next` is recognised as tmux, so it no
  longer appears as a detached agent of yours. `tmuxinator` still does not count
- a terminal that emits a charset escape into an empty input box no longer makes
  every graceful stop refuse on that terminal
- a start that timed out could leave a session behind with `remain-on-exit` set,
  and the row then offered Start on a project that had one. It is cleaned up
- the graceful stop waits on the clock the rest of the engine waits on, so a
  stop is as fast as the agent is rather than as slow as a fixed sleep

## 0.2.1 - 2026-09-05

**PATCH, and it changes no behaviour.** `pyproject.toml` names `README.md` as the
package description, so the README is what PyPI shows on the project page. The
0.2.0 page said **"It is not on PyPI yet"** and "hitchrail is not on PyPI, so none
of these work today", which was written before the first release and was wrong the
moment there was a page to display it on.

### Fixed

- **The README no longer denies its own existence.** The Install section now
  documents the three routes as working, and says why a systemd unit wants
  `uv tool install` rather than `uvx`.
- **The status line no longer names a phase range.** It said "phases 0 to 6" and
  was several out of date; `docs/roadmap.md` is the one place that says what is
  built, and a test already asserts the README has not gone back to claiming
  otherwise.

### Added

- **An options table**, so somebody deciding whether to install this can read the
  flags without installing it first. `hitchrail --help` remains the authority.

## 0.2.0 - 2026-09-05

**MINOR, and it carries a breaking change.** While the version is `0.y.z` a breaking
change may ship as MINOR, per `docs/versioning.md`. It is recorded as breaking anyway,
because the point of this file is what a version costs you: every project identifier
gains a prefix, so every saved link and every API caller written against 0.1.0 changes.

**This is the first release to reach `main` through a pull request.** Work now happens on
`develop`, and the release gate blocks a merge whose version was not bumped. It fired for
the first time on the pull request that introduced it, correctly refusing itself.

### Changed, and it renames every project you have

- **A project is now `<root-label>~<folder>`**, so `--root` takes `label=path`
  and is repeatable. One folder of projects was the only shape Hitchrail
  supported; now several are, and a project has to say which root it is in.

  ```sh
  hitchrail --root work=~/work --root personal=~/personal
  ```

  **What you must do.** Add a label to `--root`: `--root main=~/projects`
  rather than `--root ~/projects`. A bare path is refused at startup rather
  than given a label guessed from the directory name, because a guessed label
  would change if you ever moved the directory and rename every project again.

  **Every link saved on your phone stops working**, and so does anything
  driving the API. `POST /api/sessions/vessel` becomes
  `POST /api/sessions/main~vessel`. Load the `/grant` link the program prints
  on startup and re-save it.

  **A qualified name even with one root**, and that is the point rather than an
  oversight. Had one root stayed bare, adding a second would have renamed
  everything on that day instead of this one, and an identifier that changes
  because of unrelated configuration is not one you can save a link to.

  **What was reachable and by whom:** nothing new, and this is the fix rather
  than the exposure. Before it, two roots were not possible at all, and the
  workaround, running two Hitchrails, was silently destructive: the tmux
  session name came from the folder name alone, so `~/work/vessel` and
  `~/personal/vessel` both derived `hr-vessel`. The second read as `running` on
  the first one's session, and tapping Stop on it stopped the other one's
  agent. The same collision applied to detached agent detection, which matches
  on the agent's own argument.

- **`--self-project` takes a qualified identifier**, for the same reason. It
  names the one project that must never be stopped, and a bare name would be
  ambiguous exactly where being wrong is worst.

- **`GET /api/projects` reports `roots`**, a list of `{label, path}`, in place
  of the single `root` string. It is a list even with one root, so a client
  that special cased "one root" would be wrong the day a second was added.

## 0.1.0 - 2026-09-04

**The first published release.** Everything below is what taking this version
gives you rather than a change from something you were running, because there
was nothing to run it from: `hitchrail` did not exist on PyPI before today.

**MINOR, not MAJOR, and the reason is the version number itself.** Two of the
entries below are breaking changes to the operator contract. While the version
is `0.y.z` a breaking change may ship as MINOR, per `docs/versioning.md`, and
there is nothing deployed for them to break. They are recorded as breaking
anyway: the point of this file is what a version costs you, and a reader
arriving at 0.2.0 needs to know these were contract changes rather than
additions.

**Install it with `uvx hitchrail --root ~/projects`**, and read
`## What it costs you to run this` in the README before you do. Hitchrail
spawns `claude --dangerously-skip-permissions`, so anyone who can reach its API
can run code on your machine as you.

### Changed, and it breaks a saved link

- **The `?token=<token>` grant is gone.** A link of that shape is now refused
  like any other request with no token. Use the `/grant#token=<token>` link the
  program prints on startup. Nothing has generated the old form since the
  banner changed, so this only affects a link saved by hand.

- **A token is now required whenever anything outside the machine can reach
  Hitchrail**, not only when it binds off loopback. Passing `--allow-host` or
  `--allow-origin` for a name that is not loopback now demands one, and the
  server refuses to start without it.

  **What was reachable and by whom:** before this, running behind a reverse
  proxy such as `tailscale serve` or an nginx meant Hitchrail saw a loopback
  socket, concluded it was local only, and served **with no authentication at
  all** while the whole network on the other side of the proxy could reach it.
  That configuration is described as supported in the program's own help text.
  If you run it that way, add `--token` or set `HITCHRAIL_TOKEN`.

### Added

- **`HITCHRAIL_TOKEN`** supplies the token from the environment. Precedence is
  `--token`, then the environment, then one generated for you. Prefer it to the
  flag on any machine you share: on Linux `/proc/<pid>/cmdline` is world
  readable and `/proc/<pid>/environ` is not, so `--token` shows your token to
  every other account on the box and `ps` does it for them.

  It is also what makes a long running Hitchrail usable. A generated token
  changes on every start, so a service that restarts invalidates the link saved
  on your phone; one from the environment survives.

  Set but empty is refused rather than treated as absent, because an operator
  who writes the variable and leaves the value off has not configured
  authentication.

- **Security headers on every response**: `X-Content-Type-Options: nosniff`,
  framing refused, and a content security policy per route.

  **What was reachable and by whom:** `GET /grant` is reachable without a token
  by design and is a page containing a password field. Nothing in the response
  said it could not be framed, so any page that guessed an allowlisted hostname
  could have put it in an iframe and drawn its own chrome around that field.
  The application itself was not exposed, because the cookie is `SameSite=Lax`
  and is withheld from a cross site framed subresource.

- **`SECURITY.md`**, with private vulnerability reporting enabled, so a hole has
  somewhere to go that is not a public issue.

- **A systemd user unit template**, `packaging/hitchrail.service`, so Hitchrail
  no longer dies with the terminal. Copy it, edit the paths, and
  `loginctl enable-linger` to survive logout and reboot.

  **What you must do:** put `HITCHRAIL_TOKEN` in the unit's `EnvironmentFile`
  and `chmod 600` it. A generated token changes on every restart, so the link
  saved on your phone dies with each one, and anyone who can read that file can
  run code as you.

  **Read this before enabling it.** An always on service is a standing exposure
  rather than a session shaped one. Until now the window in which the API was
  reachable was the window in which you were sitting at the machine watching
  it. `docs/guides/phone-access.md` is the new document about who else is in
  that window, ordered best first: an overlay network such as `tailscale
  serve`, then a named LAN address, and never the wildcard.

- **The startup banner withholds the token when it is writing to the journal.**
  Under a systemd unit, standard output is journald: persistent, and readable
  by root and by members of the `systemd-journal` group. A token printed to a
  terminal scrolls past while you watch it; the same token in the journal is
  kept.

  **What changes for you:** running under a unit, the banner now prints the
  address without the `#token=` fragment and names `HITCHRAIL_TOKEN` as the
  half you append yourself. Nothing changes in a terminal. If you are running
  as a service with a generated token, it says so, because that is wrong twice
  over: a secret in a permanent log, and a link that dies on every restart.

### Fixed

- A `detached` agent is no longer offered a control that did nothing. The row
  shows the pid and says what it means. Hitchrail still cannot end a detached
  agent, and that is a stated limit rather than a missing feature.
