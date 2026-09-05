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

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). While
the version is `0.y.z`, a breaking change may ship as a MINOR.

## Unreleased

Nothing yet.

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
