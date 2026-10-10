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

### Added

- The config file can name more than one agent: an `[agents.<id>]` table
  gives a `package` and the `binary` to start, and a root's `agent = "<id>"`
  picks which one its projects run. A root that names none runs the agent
  `--agent-binary` points at, as before, so an existing config needs no
  change. Every named binary is checked at startup, and an unknown package,
  a bad identifier or a root naming an agent that is not configured stops
  the start with the reason. `GET /api/config` shows each root's `agent`
  and the `agents` table.
- A second package, `antigravity`, starts Google's Antigravity CLI (`agy`,
  read against 1.3.3) with its remote control link, which the row's link
  opens. Stop, Kill, Restart and the closing message take the same steps as
  for Claude Code. What Hitchrail has not seen on agy's screen it reports as
  unknown rather than guessing: no agy row says it is waiting on a question,
  so none offers an answer. **agy's trust prompt never shows**: Hitchrail
  starts agy with the project folder added, which agy takes as trusting
  it, so every folder under a root that runs agy is trusted without being
  asked. Claude Code still asks.

### Fixed

- A running project in a folder under one you trusted as a whole (say, a
  projects root you accepted once) no longer warns that it is waiting to be
  trusted. Claude Code inherits a parent folder's trust and starts without
  the prompt; Hitchrail now reads it the same way. Nothing to change.
- A plugin listed three times by `claude plugin list` read "listed 2 times"
  beside its skipped repeats; the grouped count now says rows ("2 rows"), on
  the CLI and on the page. Nothing to change.
- When the plugin list cannot be read again after a plugin update, each
  `updated` row now says "not confirmed", and `hitchrail update-plugins`
  adds a note on stderr, where before nothing said the version check had not
  happened. Nothing to change.

## 0.18.0 - 2026-10-10

### Fixed

- The startup banner no longer offers a link on a host whose plain http origin
  is withheld (for example `localhost.localdomain` beside an https
  `--allow-origin`), since the grant from it is refused. The startup block
  already says what to browse instead. And the grant page, opened on such an
  address, now shows the server's message naming the origin rather than "That
  key was not accepted", so a correct token is not retyped. A wrong or missing
  key still gets the one sentence. Nothing to change.
- The header theme button now follows the device while Theme is System: when
  the phone switches between light and dark, the button's icon and name
  switch with it, where before they went stale until tapped. Nothing to change.
- On a desktop width (900 px and wider) a long project name is no longer
  squeezed onto two lines by the chips and buttons beside it; the chips wrap
  instead. Phone layouts are unchanged. Nothing to change.

### Changed

- With `stop_prompt` set, a row wrapping up now reads "wrapping up" with the
  time left (for example "wrapping up 4:32"), counted down on the page from
  when the row arrived and resumed correctly after a reload, then "sending the
  exit" at zero. Its Stop button reads "Exit now" and opens the wait, where
  Exit now skips the rest of it. Once the exit is sent the chip reads "stopping", as before.
  With no `stop_prompt` nothing changes. Nothing to change on your side.

## 0.17.0 - 2026-10-10

### Changed

- `hitchrail update-plugins` now says on stderr, after a Ctrl-C or a failure
  partway, that the rows it printed are provisional: `updated` means only that
  the update ran cleanly, not that the version moved. An interrupt also
  says that any update still running is the plugin after the last `...`
  line, since that line appears when an update finishes. A Ctrl-C or a
  failure before any row was printed says neither (#464).
- The journal's redaction of a request's query string now covers a traceback
  as well as the access line. An error logged with an exception whose message
  held the request target used to print a `?token=` query. Each traceback line
  is cut at its first `?`, so a `?` in unrelated exception text loses the rest
  of that line too; the frames stay (#440).
- The startup lines about the saved settings say more. A refused `state.toml`
  now says the next save from the settings page replaces it (or that saving
  is refused too, when the directory is the problem). A `state.toml` that is a
  symlink to nothing is reported instead of read as a first start. A saved
  stop timeout that `--stop-timeout` overrides is reported, as a saved stop
  policy already was, because removing the flag brings the saved value back
  (#434).
- With a `Secure` cookie (a loopback bind and every non loopback
  `--allow-origin` https), a browser on `http://localhost.localdomain:8787` is
  now refused at the grant with the origin check's 403, naming the origin. It
  used to be granted a cookie the browser then dropped, so every call after it
  was a 401. Browsers treat `localhost` and `*.localhost` as secure contexts
  and not `localhost.localdomain`. If you reach Hitchrail that way, browse
  `http://localhost:8787` instead; the startup block says so. The same rule
  now keeps the plain origin of an `--allow-host` ending in `.localhost`,
  which used to be withheld, and withholds `::ffff:127.0.0.1`'s, which a
  browser does not treat as secure either. Who must present a token is
  unchanged (#436).

## 0.16.0 - 2026-10-09

Nothing to do on upgrade, unless something reads the journal for an ended
detached agent: see Changed.

### Added

- Restart. A running row has a Restart button beside Stop, and
  `POST /api/sessions/{name}/restart`: the same graceful stop, confirmed the
  same way, then a new agent in the same folder once the old one has exited, as
  a fresh conversation. If the stop times out, or you Kill it, nothing is
  started. If the start is refused, the row stays stopped and says why. The
  session payload gains `restarting` and `restart_refused` (#472).

### Changed

- Ending a detached agent journals `sent SIGHUP to` where it said `killed`,
  and an agent that survives the signal is reported as still asking rather
  than as gone. The old line claimed a kill for an agent that handled the
  signal and kept running (#425).

### Fixed

- A Stop with `stop_prompt` set waited its full wrap up ceiling, five minutes
  by default, whenever a background subagent was running: its panel below the
  input box hid the box from the screen reading, so the end of the turn was
  never seen. The exit now goes out once the turn ends, and the wrap up prompt
  is no longer typed behind a queued message on that screen (#475).
- A detached agent whose stop timed out was offered Kill, which the server
  could only refuse. It is offered End, the signal route, and the timeout
  stays on screen (#463).
- A failing close of a process handle while ending a detached agent replaced
  the signal's result with an error and could stop the once a second sweep,
  freezing every stop's timeout. It is logged and the sweep carries on (#426).
- A second Stop pressed while a Kill was in flight could start typing the
  exit over the one still being typed. It now sees the stop already under
  way and does nothing (#432).
- A start or stop in one project could throw away another project's "waiting
  on you" flag, and for a row with a session link nothing set it again (#430).
- A stop's words follow the row they are about and how many rows it covers,
  and Stop all over rows that are already exiting keeps its warning (#433).

## 0.15.1 - 2026-10-09

Nothing to do on upgrade.

### Fixed

- Choosing Light on a phone set to dark, or Dark on one set to light, left the
  settings page's unselected radios drawn in the phone's scheme: dark filled
  discs that looked selected. Native controls now follow the choice. Chrome's
  address bar still takes the phone's colour, by decision (#470).

## 0.15.0 - 2026-10-08

Nothing to do on upgrade, unless a script reads the plugin update's record or
the output of `hitchrail update-plugins`: see Changed.

### Changed

- The plugin update says which plugins actually moved. `updated` used to mean
  only that the agent's update exited zero, which it also does for a plugin
  that was already current, so a run could report 16 updated when three
  versions changed. A plugin that was already current is now `current`, and
  one that moved is `updated` with its versions, shown as `0.12.9 to 0.15.0`.
  The record gains `current` in `counts`, and `from_version` and `to_version`
  on each outcome; `hitchrail update-plugins` prints a `current` count between
  `updated` and `failed`. If the second reading of the plugin list fails, the
  result is what it was before (#311).
- Identical skipped rows are one line. A plugin installed locally in six
  projects used to be six rows of the same words, with nothing to tell them
  apart; the page and `hitchrail update-plugins` now show it once, with how
  many times the agent listed it. The record is unchanged: one outcome per
  row the agent listed, and the counts cover them all (#312).
- `hitchrail update-plugins` prints its rows once the run ends, since
  whether a plugin moved is only known after the second reading of the list.
  While it runs, stderr carries a `... <plugin>` line as each update
  finishes, so a run that has stopped moving shows where it got to; stdout
  is the final account and nothing else. A run that fails partway, or that
  you interrupt with Ctrl-C, still prints the rows it got to, and there
  `updated` means only that the update exited cleanly, not that the version
  moved. An interrupt exits 130.
- Settings is the gear in the bar rather than a link after the footer's
  version, which a first visit missed (#320). The bar's button says "New
  project", and the theme toggle beside it is an icon so the bar stays on one
  line on a phone (#322).
- The title in the bar is the way back to the list from settings and the
  log page, with the mark before it (#324, #333).
- Settings offers Light, Dark and System. The header toggle could store a
  choice but never return to following the device (#323). The choice is kept
  by the browser, as the toggle's always was.
- A search that matches nothing offers to create a folder of that name, in
  the same sheet as "New project", unless a tab or a root chip is hiding a
  folder that already has it (#321). The search field has a clear control
  (#451).
- `/favicon.ico` is served without a token, as the mark already was, so the
  401 a browser's unprompted request left in the log is gone. It is the same
  drawing, readable GET and HEAD only (#325).

### Fixed

- The list fits a 360 px phone. The type scale is smaller, a project name
  has its own line in every state rather than being crushed beside a
  stopped row's buttons, the root chips no longer shrink under their labels
  and overlap, and the last row is no longer hidden behind the footer when a
  filter is on (#447, #448, #449, #450).
- A stop whose wait ran out could leave "No answer" open, offering Kill, over
  a row that had already stopped, when the server's own deadline ended it a
  moment after the page's (#457).

## 0.14.0 - 2026-10-08

Nothing to do on upgrade. One behaviour changes: Stop now answers one
confirmation it used to leave for you, described below.

### Changed

- Stop ends a session that has background work running (a Monitor, a
  background shell or agent) in one tap. Claude Code answers `/exit` there
  with a menu, and the stop used to wait out `stop_timeout` and then ask you
  to press a key; it now chooses "Exit and stop tasks" when that is the
  selected option as the menu appears. Any other menu, or this one worded
  or ordered differently, is left for you as before, and "Move to background
  and exit" is never chosen (#453).

### Fixed

- With `stop_policy = "end_anyway"`, the "is waiting for you" dialog could
  open over a session the server had just ended, showing a pane that could
  not be read. It now opens only while the session is still running.

## 0.13.0 - 2026-10-08

One deployment has something to do: a loopback bind behind an https proxy
that is ALSO reached over a plain http forwarder or alias. See Changed. And if
you ever opened a link of the old `/?token=` form, rotate the token: see the
first line under Fixed (#388).

### Changed

- On a loopback bind whose every `--allow-origin` off this machine is https,
  the plain `http://` origin of an `--allow-host` is no longer accepted: its
  grant is refused with `origin not allowed` naming the origin, where before
  it was accepted and then every request was refused, because the session
  cookie there is `Secure` and a browser on plain http drops it. The startup
  log names each origin withheld. If you reach Hitchrail that way on
  purpose, for example through a plain http forwarder onto its port, add
  that origin with `--allow-origin http://box.lan:8787`, which also turns the
  cookie's `Secure` flag off, or reach it through the https origin (#391).

### Fixed

- The journal no longer records a query string from a request line. A link in
  the old `/?token=<token>` form, which no release printed but a checkout
  from before the first one did, wrote the real token into the journal when
  it was opened, although the request was refused, so anyone who can read
  your journal could read it. If you ever opened such a link,
  rotate the token (#388).
- An `--agent-binary` path that is not there says it was looked for
  relative to the current directory when it was relative, which is also
  why a path starting with `~` is not found, since nothing expands it there,
  and no longer mentions PATH (#393).
- The startup line advising a loopback bind for a `Secure` cookie no longer
  appears where the rebind would not set it, such as an https origin on
  `localhost` or one beside a plain http origin (#394).
- `--host ::ffff:127.0.0.1` is refused at startup naming `127.0.0.1`, where
  before it reached the bind and failed with a traceback: an IPv4 mapped
  address cannot be bound on the server's IPv6 only socket (#395).
- With `stop_prompt` set, the wrap up's exit is no longer typed into an agent
  that is still working when its screen also carries an underline colour
  (#405), and a Stop tapped while an exit is being typed is answered without
  typing a second exit over the first (#406).
- An Exit now that is refused, for example over a draft in the box, leaves
  the wrap up running and still ends it in an exit, where before it ended the
  stop with the prompt still queued (#407).
- Under `stop_policy = end_anyway`, a redraw no longer ends a working agent:
  the kill at expiry needs the screen to show a prompt on two looks a second
  apart, and otherwise the expiry is reported as `ask` reports it (#429).
- Under `stop_policy = end_anyway`, the kill at expiry now ends the agent
  whose screen was read, through a process handle, and nothing if the row
  was restarted in between; any refusal is reported as `ask` would report
  it (#418, #412).
- Every kill now writes a line to the journal, and a stop a Kill ended is no
  longer logged as the agent having exited (#387).
- A row killed and started again while a stop was ending no longer shows the
  fresh agent as waiting for you on the old agent's question (#410).
- A stop ends under the `stop_policy` in force when it was requested, as its
  wait dialog says, so choosing `end_anyway` on the settings page during a
  wait no longer turns that wait into a kill, nor `ask` cancel one (#419).
- The journal no longer says a start is running before it is attempted, nor
  that a stop gave up when the agent exited and only its tmux session stayed;
  an unwatched exit's line says how long it took at most, and an unreadable
  machine at expiry no longer drops that the agent was waiting on you (#389,
  #390).
- A stop's wait reopened in another browser or after a reload now warns of
  the kill its stop was confirmed under, even if the settings page has since
  chosen `ask` (#428); counts from the stop rather than from the tap (#411);
  and offers no Exit now while the wrap up prompt is still being typed, when
  it would do nothing (#408).
- Stop on a row already asked to exit, and Stop all over a set holding one,
  no longer promise a wrap up the server will not type: they say the exit is
  asked again (#416). Stop all over one session says "Stop 1 session?"
  (#414).
- A `stop_policy` saved from the settings page that `--stop-policy` or the
  config file overrides is now named in a warning at startup, so removing
  that setting no longer silently brings back an `end_anyway` (#421).
- A state file Hitchrail refuses to read, because its directory is
  writable by a shared group or others or it does not parse, is now named in
  a warning at startup, where before every hidden root and saved stop setting
  was dropped with nothing said; and a choice on the settings page is refused
  rather than saved into a directory the next start will not read (#397).

### Added

- Each row of the listing and the event stream carries `stop_typing`,
  `stop_age_s` and `stop_policy` while it is stopping; a client may ignore
  them. `docs/api.md` says what each holds.

## 0.12.0 - 2026-10-01

Nothing to do on upgrade. Every new setting is off or unchanged by default,
and every API change is an addition a client may ignore.

### Added

**Stop can let the agent wrap up first.** Set `--stop-prompt` (or
`stop_prompt` in the config file) to one line, such as a slash command that
commits and writes notes, and Stop types it to the agent WITHOUT
interrupting the task in flight: it queues behind that task, and Stop asks
the agent to exit once the prompt's turn ends, or once
`--stop-prompt-timeout` (default 300 seconds) runs out. Kill still
interrupts at any moment, and a second Stop skips to the exit. Unset, which
is the default, Stop is exactly what it was. The prompt can never be set
over HTTP, and the startup block names its kind, never its text. The stop
dialog names each phase of the wait. `stopping_phase` in a session row says
which one a stop is in.

**What a stop that runs out of time on a question does can be chosen**:
`--stop-policy` (or `stop_policy` in the config file) is `ask`, the
default, which reports and offers Kill as before, or `end_anyway`, which
ends the session. It applies only to a stop asked to exit, never to a slow
one with a clear input box, and never to the self project. With neither
set, the settings page can choose it, kept in `state.toml`; set by the flag
or the file, the page shows it as not changeable there. The confirmation
and the wait say beforehand when a stop will be ended. `PATCH /api/config`
takes `stop_policy`, and `GET /api/config` reports it as `{value, source,
editable}`, like `stop_timeout`.

**Hitchrail logs what it does.** Starts, stops, each moment of a stop, and
every refusal go to stderr in uvicorn's format, so the journal answers
"what did Stop do". `--log-level` chooses how much, and `--verbose` is
`--log-level debug`. The token and pane content never reach a log line.

**End and Kill on a detached agent are bound to the pid the person
confirmed.** The page sends `{"pid": N}` to the signal route, and a
different agent in the row by then is `not_ours`, not signalled. The body
is optional, so a script without one works as before; a malformed body, or
a key other than `pid`, is `invalid_body`.

### Fixed

- `127.1` and `::ffff:127.0.0.1` count as loopback, as the bind already
  treated them.
- A config file reached through a symlink has the directory it resolves
  into checked for permissions, and the state file is read by the same rule.
- An `--agent-binary` typed with a directory in it is refused as typed,
  rather than with advice to fix `PATH`, which is never searched for it.
- A stop that worked but was not watched is no longer logged as having
  timed out.
- A body or a Claude state file nested deeper than the parser can follow is
  refused as unreadable rather than as a server error.
- The plugin strip: a cut record keeps its tail, a third copy of a listed
  plugin is called "listed more than once", and an abandoned row is marked
  seen.
- Shutting down cancels the sweep even when the shutdown kill fails.

### Changed

The README states tmux 2.1 as the minimum, where exact `=` targets and the
`#{pid}` format arrived. Older versions fail closed, showing every agent as
detached. Only 3.x is tested.

## 0.11.0 - 2026-09-28

Nothing to do on upgrade. Everything below is a fix or an addition.

### Fixed

**The plugin strip on the settings page no longer locks after a restart.**
On 0.10.0, reloading the page while the server restarted could leave
**Update plugins** disabled for good, until the page was closed and opened
again. Each run record now carries the boot it started in and the kernel's
boot clock (`boot` and `since_boot_us` in `docs/api.md`), so the page knows
which server is newer instead of guessing. `epoch` is unchanged.

**Stopping the server ends a plugin update it started.** Before, the update
ran on in the background after Hitchrail exited. The plugins it had not
reached are reported as `abandoned`, a new result that never means
`failed`, and a shutdown before the list was read fails the run with the
new code `shutting_down`. A client with a fixed list of results or codes
should add both.

**A plugin update that times out now kills the agent's own children too**,
not only the agent, and output that is not valid UTF-8 is replaced rather
than failing the run.

**The agent binary checked at startup is the one that runs.** A relative
`--agent-binary` used to be checked from one directory and run from another.

### Added

`hitchrail` names itself and its version before anything else it prints, so
a refusal at startup says what refused. `--help` shows every flag's default.

## 0.10.0 - 2026-09-24

### Added

**`hitchrail update-plugins`**, which refreshes the agent's marketplaces and
updates every plugin installed at `user` scope, one line per plugin, with no
server, and **Update plugins** on the settings page, which runs the same
update from the phone and shows each plugin's result as it finishes. Nothing
to do on upgrade: bare `hitchrail` still starts the server exactly as before. Read the new paragraph in `SECURITY.md` before relying on
it: an install command a marketplace declares is approved without being shown.

## 0.9.0 - 2026-09-17

Phase 20: the perimeter, hardened. Upgrading is safe with no action unless
one of five refusals now names your configuration: a `--stop-timeout` above
3600 seconds; `--tls-cert` beside a plain `http://` `--allow-origin` off
loopback, which never worked (the `Secure` cookie was never sent back on that
origin) and now says so at startup; a config file whose DIRECTORY others can
write to, refused like the file itself; an `--expect-gateway-mac` that is
not one of the four spellings of a MAC (`aa:bb:cc:dd:ee:ff`,
`aa-bb-cc-dd-ee-ff`, `aabb.ccdd.eeff`, `aabbccddeeff`), which the check used
to accept with stray characters around it; or a `--tls-key` with a
passphrase, which used to reach a prompt no unit can answer.

Still not protected, and stated so it is read rather than discovered:
Hitchrail does not sandbox the sessions it starts, and over plain HTTP on a
LAN the token crosses the network in cleartext, which `--tls-cert` or a TLS
terminating proxy ends.

### Fixed

**A settings write no longer re-reads the TLS private key.** Changing the
stop wait from the settings page rebuilt the configuration to validate it,
which loaded the certificate pair again; a key rotated or removed after
start answered "cannot be loaded, so nothing will be served on this port"
while the server was serving the reply. The pair is loaded once, by the
command line, into the context the server serves with, and TLS 1.2 is the
floor, set rather than inherited.

**Five session routes answered a bare 500 when a root was unmounted.**
Stop, kill, answer, the session link and the signal route on a stopped name
now answer 503 `root_unavailable` in the envelope, as the listing and logs
did.

**The signal route could reach past this instance's root.** Two instances as
the same user, both labelled `main`, each with a folder of the same name: one
could end the other's agent, because the pid route matched the process by
its command line and a command line does not say where the process runs.
It reads the process's working directory after taking the handle and refuses
one outside this instance's root. The tmux routes are unchanged, and a
detached agent whose folder was renamed can still be ended.

**The stop wait has a ceiling, 3600 seconds**, on the flag, the settings
page and the state file alike: a wait past an hour is not one anybody is
watching, and the settings page accepted any number. A `state.toml` holding
a larger value from 0.8.0's page falls back to the default rather than being
honoured, and a `--stop-timeout` above the ceiling refuses at startup.

**An agent inside a tmux Hitchrail is not configured for is no longer
offered End.** A tmux server on another socket, or the one your own terminal
runs in, holds the agent, and the pane map cannot see it because Hitchrail
only asks its own server. The row now finds that server in the process tree
and says "in a tmux server Hitchrail is not configured for (pid N)" instead
of "no session Hitchrail can address"; the signal route refuses it as
`owned_elsewhere` with the pid in a `server_pid` field, and the listing
carries it as `foreign_server_pid`. An agent that outlived its pane under
Hitchrail's own server is still detached and can still be ended.

**A refused toggle on the settings page no longer loses its reason.** With
a state directory that cannot be written, the checkbox snapped back and the
strip went blank, so the person saw a control that would not stay set and no
sentence saying why. The refusal's words survive the repaint that follows it.

**The empty list stops claiming every root is hidden when one is merely
empty**, and stops sending somebody to the settings page for a root the
config file disables, where there is no checkbox to find. It names the file
instead. The listing carries `hidden_roots_editable` for that distinction.

**A TLS key with a passphrase refuses instead of asking for one.** It used
to reach OpenSSL's terminal prompt: interactively that was two prompts, one
at the configuration check and one inside the server, and under the systemd
unit, where there is no terminal, the start failed saying nothing useful.
It now stops at startup naming the key and the command that decrypts it.

**A handle the kernel refuses is no longer reported as somebody else's
process.** `pidfd_open` does not refuse on ownership grounds, so an EPERM
there is a seccomp filter or an LSM denying the syscall; the route now says
so (`pidfd_unavailable`) instead of "not ours to signal", which sent an
operator looking at the wrong process. EPERM at the send keeps its
ownership meaning, which is what it means there.

**The page's memory of what it has ended no longer grows for the life of
the tab.** It is pruned to the rows the listing still carries as detached
at that pid, so on a machine with a small pid ceiling a reused pid under
the same name is offered End before Kill, as any row is.

**The session cookie is `Secure` behind a TLS terminating proxy.** It was
`Secure` only when Hitchrail itself held the certificate, so in the proxy
deployment (bound to loopback, `--allow-origin https://box.lan`, no
`--tls-cert`) the browser also offered the cookie to `http://box.lan`, on
any port, because cookies are not port scoped. It is `Secure` now when the
bind is loopback and every non loopback allowed origin is https, which is
exactly that deployment and costs nothing there. Everything else is
unchanged, including a proxy origin beside a LAN bind: something can still
reach that server in the clear, and a `Secure` cookie on a browser doing so
is never sent back. Loopback origins count for neither.

**The config file's remaining refusals are in words.** A label holding
`=` refuses as a label rather than parsing as a different one; a NUL escape
in a path and a file that is not UTF-8 refuse with exit 2 naming the file
rather than a traceback; a config directory writable by others refuses
naming the directory, since a private file in a shared directory is private
until the next rename; and the state file is written through a fresh
temporary name, so a symlink left at `state.tmp` in a writable state
directory is no longer written through.

**The network guard reads the gateway's entry on the route's interface.**
With ethernet and wifi on one LAN the ARP table holds two entries for the
gateway address, and the guard compared whichever the table listed first.
It matches the interface the default route names now, and a table holding
an interface name that is not UTF-8 is read rather than a traceback.

**A foreign session name holding a newline could put somebody else's pane
into your listing.** tmux 3.1 and earlier store a newline in a session name
verbatim, so a session called `innocent<newline>hr-main~vessel` printed a
line the pane map read as ours, with the foreign pane's pid: the project
then derived running or stale from a process that was never its own. Records
are now ended by a character no tmux stores in a name, so the whole name
arrives together and is refused. tmux 3.2 and later escape the newline
themselves; the fix is for the versions that do not. On tmux 3.7a, which
admits a session with no name, such a session's agent is listed as inside
`(unnamed)` rather than as an orphan with End on offer.

## 0.8.0 - 2026-09-16

Phase 14: the perimeter, chosen rather than assumed. Upgrading is safe with
no action: every flag still works and still wins. Two things worth knowing
before you do: `--stop 60` no longer stands in for `--stop-timeout 60`
(flags are exact now), and a config file writable by others, or owned by
somebody else, refuses to start.

Still not protected, and stated so it is read rather than discovered:
Hitchrail does not sandbox the sessions it starts, and over plain HTTP on a
LAN the token crosses the network in cleartext, which `--tls-cert` now ends
from the server itself.

### Added

**A config file.** Roots can live in `~/.config/hitchrail/config.toml`, one
`[[roots]]` table each with `label`, `path` and an optional `enabled`, read
once at startup. Every refusal `--root` makes, the file makes identically,
and a file that does not parse, or has an unknown key, or is writable by
others, refuses to start naming the file and the line. `--config FILE` names
a different file. The unit template's `ExecStart` no longer carries a root.

**Hide a root.** `PATCH /api/config` toggles `enabled` on a root already in
the file, and that is the only setting a request can change: no route accepts
a path, and a test reads the real route table to keep it so. The choice is
kept in Hitchrail's own `state.toml` beside the config file and only ever
narrows what the file allows. A hidden root's projects leave the listing,
which now names them in `hidden_roots`; its sessions keep running and still
answer by name.

**A detached agent can be ended.** `POST /api/sessions/{name}/signal`
sends SIGTERM to the agent a detached row names, through a pidfd acquired
before the row is re-checked, so a pid another process has taken over is
refused rather than signalled; `/signal/force` is SIGKILL, a second explicit
request. Refused before anything is opened: the self project, this server's
own process tree, a row a visible tmux session owns (attach there), another
user's process. A machine without pidfd support is told so; nothing ever
falls back to signalling a bare pid. The row's End control carries the
honest sentence: Hitchrail can see no session that owns this agent, and if
it is open on a screen somewhere, this will end it there too.

**The wrong network, noticed.** `--expect-gateway-mac` names the default
gateway of the network a named bind was meant for; a start whose gateway is
another refuses with exit 2 and the unit stays stopped until somebody looks,
and one whose gateway cannot be identified yet refuses with exit 3, which the
unit retries. Checked once, at start. Read from `/proc`, no subprocess. A
guard against a laptop serving where it was carried by accident, and the code
says it is not one against an attacker on the LAN, who can present any MAC.

**A folder called `my app` is a project.** The name allowlist admits one
space between two words; a leading, trailing or doubled space, and any other
whitespace, are still refused, and the refusal now says to rename the folder
rather than reading as an invitation to put a symlink beside it, which is
the #32 workaround. Root labels stay spaceless. tmux stores such a name
unchanged, checked on a real server.

**HTTPS from the server itself.** `--tls-cert` and `--tls-key`, both or
neither, refused at startup before the bind when one is missing or the pair
cannot be loaded, so the failure is never plain HTTP on the port you believed
was TLS. The origins the server derives, the banner's links and the cookie's
`Secure` flag follow the scheme. `docs/guides/phone-access.md` route 2a says
where a certificate for a private address comes from, and that the CA has to
be trusted on the phone; Tailscale stays first.

**A settings page.** The footer's "settings" link, and `GET /api/config`
behind it: every value with where it came from, the token never. The stop
wait can be set there, persists in `state.toml`, and the page's own wait now
follows the server's: `--stop-timeout 60` used to get a page that gave up at
thirty seconds and said "it has not finished" while the server was still
waiting. A wait given as a flag is pinned and shown as text.

**Flags are exact.** `--stop 60` no longer stands in for `--stop-timeout 60`.
argparse accepted any unambiguous abbreviation; the settings page needs to
know which flags were given, and reads the names. Nothing documented ever
abbreviated one.

**`--session-prefix`, and `session_prefix` in the file.** The setting
existed with its refusals and nothing reached it. Two instances on one tmux
server need two prefixes: with one, each reads the other's agent in a same
named folder as its own and can stop it, and now they cannot.

## 0.7.0 - 2026-09-14

Phase 13: fifty rows on a phone. Upgrading is safe with no action. Four
files are now served without a token, the mark and its manifest; nothing
else about the boundary moves, and the argument is in `security.py`.

### Added

**Filter by root.** A strip of chips, one per root, present only with more
than one root; chips OR together and AND with the state tab and the search;
the selection survives a reload; the fixed footer says "10 of 50 shown"
whenever a filter hides rows, and the empty state names the filter.

**The search suggests.** Typing shows matching folders under the field, each
naming its root, as an ARIA combobox: focus stays in the field, nothing is
chosen by typing, Down, Up, Enter and Escape as the reference pattern says.
Choosing is exact. The search now matches the folder, not the root label.

**The header stays.** New, the tabs, the chips and the search are reachable
at any scroll position; scrolled, the root line goes and the title shrinks.

**Logs at a URL.** `GET /logs/<name>` shows one project's tail in a tab of
its own, bookmarkable, polled rather than streamed, refusing a name exactly
as the API does. The drawer stays and gains "Open in a tab"; on a desktop it
is wide enough for eighty columns.

**Stop all.** One control in the footer, composed from the stop each row has:
one confirmation, the stops requested one at a time, one wait reporting per
row, the bulk kill inside the wait as the escalation and never before a
graceful attempt. A standalone Kill all was decided against.

**The footer says which build this is, since when, and as whom**, and links
to the source. A row's memory figure says what bounds it: "1.4 GB of 4 GB",
or "no limit", read from the process's cgroup ancestry.

**A mark, a favicon, a home screen tile and glyphs.** The badge words carry a
shape beside them, seven Tabler icons vendored under MIT; the application
has a mark of its own, a favicon, a touch icon and a manifest, so a tab and
a home screen tile are no longer nameless.

### Fixed

**The logs routes answered a bare 500 for a stopped name whose root had
been unmounted**; they say `root_unavailable` now, as the listing does.

## 0.6.0 - 2026-09-11

Phase 11: the interface in every state. Upgrading is safe with no action.
Two row controls have new names, `Logs` and `Open session`, and the colours
have moved slightly so that every label passes AA, mostly in dark mode.

### Changed

**Two row controls are renamed.** `Open`, which opened the pane tail and not
the session, is `Logs`, the word the API already uses. `Continue`, the
vendor's word borrowed out of the sentence that explained it, is
`Open session`, and it keeps that label while the session has no link yet:
tapping it then asks for one. The link is marked as leaving the page.

**The palette is retuned so that every text pair passes AA**, computed from
the stylesheet rather than judged. Most of what moved is in dark mode, where
muted text and the warning badges were well under the line; each token moved
by the smallest lightness shift that clears 4.5:1 with its hue held, and the
accent in dark mode now matches light, since it is only ever a surface under
white text. The two tinted badges use their own foreground tokens.

**A row waiting for an answer wears the `waiting` badge**, the same one a
row waiting to be trusted has worn since 0.3. It used to read `running` while
only its meta line said a person was needed.

### Fixed

**Every dialog sat flush against the bottom of the screen**, with the
dangerous action nearest the thumb, since the keyboard fix in 0.4. The
keyboard reservation is the bottom inset now, so with nothing covered the
dialog is centred again.

**The dialog that says an agent is waiting for you shows what it asked**, in
the same pane view the log drawer uses, with the keys to answer it, above
`Leave it` and `Kill it`. It used to send you to "that terminal", which is
the one place the prompt never is. It also goes away when the agent does.

**A modal the agent had already scrolled past no longer counts as a question.**
The badge lingered; since 0.5 the same mistake could send a key into a
working agent. The output below the prompt is the evidence it moved on.

**A "waiting for an answer" claim re-confirmed after it expired is announced
again.** Closing the phone for thirty seconds and reopening it left the row
unflagged while the server knew better.

**An answer the page could not read is no longer reported as "That did not
work".** On a 2xx the action did work; the screen now says the request was
sent and the reply could not be read, and the list catches up.

**A refused stream no longer rebuilds its sign-in dialog on every reopen
attempt**, and it no longer reports "Live, but this machine cannot be read"
at the one moment it is provably not live.

**`/grant/` with a trailing slash reaches the grant page** instead of a raw
JSON 401. Phones and messaging apps add the slash on their own.

## 0.5.1 - 2026-09-06

### Fixed

**A row could go on saying an agent is waiting for you after you stopped or
restarted it.** Not after you answered the prompt from the keypad: answering
leaves the claim to expire on its own, which it does within a second, and that
is unchanged.

Stopping or starting a session clears the standing claim, on the rule that a
fresh attempt starts from nothing. The background sweep decides what is waiting
by reading screens, which it does without holding its lock, so a stop landing
while it looked could have its clear undone by an observation made a moment
BEFORE it. The row then reported a prompt you had already dealt with.

**After a stop** that lasted about a second, until the next sweep. **After a
start** it lasted up to thirty: a session under fifteen seconds old is not
looked at, so the sweep could not correct the stale claim, and a brand new agent
was rendered as waiting for an answer it had never asked for.

**A stop could say "it has not finished" while the server had not yet noticed it
had.** The same sweep expires stop timers, and it did that in sequence behind the
screen reading. A screen read that overruns, which against an unresponsive tmux
can take half a minute, delayed every expiry behind it, and the browser's own
timer is 30 seconds. The two timers are independent by design and either may be
shorter; what this removes is the server's being reliably the longer one under a
condition nobody chose.

**Neither needs anything from you.** Both corrected themselves eventually, the
first within a second or thirty depending on which way it happened, the second
within one sweep. Both are gone.

## 0.5.0 - 2026-09-06

### Added

**You can answer a prompt an agent is stuck on, from the phone.** Before this,
a session sitting on a question showed you the question and offered `Close`.
The only other control was `Kill it`, so the interface offered the destructive
answer and withheld the safe one, in a situation it had created.

The commonest case is the one Claude Code asks on a folder it has not seen:

```
 Quick safety check: Is this a project you created or one you trust?
 > No, exit
   Yes, I trust this folder
```

Open the pane on a row that says it is waiting, and a keypad appears under the
screen: arrows, Enter, Escape and the digits. Read what the agent asked, press
the key its own words name.

**What this is not.** It sends ONE key from that fixed list, and only while the
screen is showing a question. There is no text box anywhere in it, and there is
not going to be one: sending arbitrary input to an agent is a different product
and stays out. Nothing is ever chosen for you, there is no default and no
timeout that presses anything.

**Worth knowing before you use it on a folder you have not reviewed.**
Answering "Yes, I trust this folder" is the one permission Hitchrail's
`--dangerously-skip-permissions` does not already grant: it lets the agent read,
edit and execute in that folder. You can only reach prompts in folders under a
root you configured, so the question is never about somewhere unexpected, but it
is a real grant and you are making it from a phone. Read the pane, not just the
row.

### Fixed

**A misconfigured service restarted forever instead of stopping.** If you run
Hitchrail as a systemd user unit and it refuses to start, because
`HITCHRAIL_TOKEN` is set to an empty value, a root is not a directory, or the
`ExecStart` line has a typo, the unit retried it every five seconds for as long
as the machine was up. Measured: 37 restarts and 38 copies of the same message,
and systemd's own rate limit never fired, because the five second gap keeps the
attempts outside its default window.

The refusal now stays stopped, which is what the template always claimed it
did. **A port already in use still retries**, since that is usually a previous
instance shutting down.

**The message you get when the agent cannot be found no longer assumes you
never installed it.** It said "Install it", which is the wrong first thing to
read when the binary is installed and merely unreachable, which is the case it
fires in most: a unit at boot, with no terminal attached to ask anything of.

**A lingering install was dead after its first reboot.** The unit template set
no PATH. `loginctl enable-linger` starts the user manager at boot before any
login, when its PATH is systemd's fallback, so `~/.local/bin/claude` could not
be resolved: the service refused with "'claude' is not on PATH" and stayed
stopped. Starting it by hand always worked, because that happens after a login
has fixed the PATH, so nothing showed it until a reboot.

**If you copied the template, add this line** under `[Service]`:

```
Environment=PATH=%h/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
```

If your agent needs something outside those directories, add it to that line,
and prefer a stable path to a version pinned one: a pinned one goes stale at the
next upgrade and fails at the next boot rather than at the upgrade.

**If you copied the template before this,** the two lines to add are
`RestartPreventExitStatus=2` under `[Service]`, and `StartLimitIntervalSec=60`
with `StartLimitBurst=5` under `[Unit]`. The second pair bounds anything the
first cannot name, and they belong in `[Unit]`: systemd has ignored them in
`[Service]` since version 230.

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
  hitchrail --root work=~/work --root personal=~/projects
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
  `~/projects/vessel` both derived `hr-vessel`. The second read as `running` on
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
