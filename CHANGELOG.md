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

Nothing has been published yet, so everything below is what the first release
will carry rather than a change from something you are running.

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

### Fixed

- A `detached` agent is no longer offered a control that did nothing. The row
  shows the pid and says what it means. Hitchrail still cannot end a detached
  agent, and that is a stated limit rather than a missing feature.
