# Hitchrail: design

Date: 2026-08-25
Status: approved for planning

## 1. What it is

A small web application that lists every folder under a configured root and
starts or stops a headless Claude Code session in any of them with one tap.
It is a standalone open source tool with its own engine. It does not wrap, call
or require `another tool`.

The primary interface is a phone. The desktop layout is the secondary one.

Design canvas (phone, desktop, edge states):
https://claude.ai/code/artifact/e02013e2-d501-405a-a95c-6404ebe492a6

## 2. Why the name

`hitchrail`. A hitching rail is what you tie your mounts to while they wait,
outside whichever building you are working in. That is what this tool holds: a
row of projects, standing ready, none of them costing you anything until you
take one out.

It was chosen against a hard availability bar, because this is a public
repository and a published package and a rename later would be expensive:

- free on PyPI, including the hyphenated variants PyPI normalizes together
- **zero** existing GitHub repositories of that name, anywhere
- `github.com/hitchrail` unclaimed as an account or organisation
- no software trademark found

Nothing else screened this cleanly. `corral`, the first choice, is free on PyPI
but `ponylang/corral` already owns the name on GitHub. `remuda` has the better
metaphor, a remuda being the string of horses a ranch hand picks a mount from
each day, but its GitHub account name is taken and few people can pronounce it.

Deliberately not named with "Claude" in it. That is Anthropic's trademark, and
a third party package leading with it invites a forced rename later. "Claude
Code" belongs in the description and the README, not in the package name.

The CLI reads as `hitchrail serve`.

## 3. Scope

In scope for v1:

- List every direct subfolder of the root. No git filter, no badge, no
  distinction. A folder is a project.
- Refresh the list on demand.
- Create a new empty folder, immediately startable.
- Start a session in a folder.
- Stop a session in three steps: confirm, then a graceful request you can watch,
  then a kill you can reach for at any moment during the wait. See section 4.3.
- Filter by state (all, running, stopped) and search by name.
- Refuse or warn when starting would exhaust memory.
- Live updates over SSE.
- Read the tail of a session's terminal output.

Out of scope for v1, and stated so nobody plans around them:

- Restart. It is stop followed by start, and the UI can compose it later.
- Multiple roots.
- Any authentication beyond a single shared token.
- Streaming logs. A tail on demand is enough.
- User accounts, roles, or multi-tenancy.
- Sending input to a session. Hitchrail starts and stops agents; it is not a
  terminal.
- **Any agent other than Claude Code.** No second agent is planned, none has
  been asked for, and none will be considered until long after v1 ships. This
  is a non goal rather than an omission, and the paragraph below says what is
  being kept open anyway and why.

### 3.1 Multi agent: not built, not closed off

The temptation with a question like "could this run other agents one day" is to
build a plugin system for one plugin. That is refused here. An interface derived
from a single implementation is shaped like that implementation, and the second
implementation is what teaches you the real interface; guessing it from one data
point produces an abstraction that is harder to change than no abstraction.

What IS done, because each item costs nothing today and is expensive to retrofit:

1. **No vendor name appears in the operator or API contract.** Routes, states,
   error codes and the `Session` fields are already neutral. The one exception,
   the `claude_binary` setting, was renamed to `agent_binary` while nothing is
   released. Under `docs/versioning.md` an operator facing rename is a MAJOR,
   so this specific item goes from free to a major version bump the day v1
   ships.
2. **`claude_ipc.py` is the seam.** It already exists, quarantined for a
   different reason (undocumented internals that change without notice), and
   that is structurally the same boundary a second vendor would need. Its
   members are an agent adapter interface in all but name: how to launch, how
   to identify the process, how to ask for a graceful stop, how to find a
   session link.
3. **The engine asks for a stop; it does not know what a stop is.** See section
   4.3. This is the one place the boundary would otherwise leak, and it leaks
   in a costly direction.

What is deliberately NOT done: no plugin discovery, no entry points, no setting
to select an agent, no second adapter written speculatively, and no further
abstraction of tmux, the process table or the memory guard, which are already
agnostic because none of them can tell what is running in a pane.

**The honest caveat.** The blocker on a second agent is unlikely to be code
shape. Hitchrail's model is a long running headless process, in a tmux pane,
that tolerates unattended operation and can be asked to stop politely. Claude
Code fits because `--dangerously-skip-permissions` exists and it is a persistent
terminal program. An agent that is request and response, or that needs
interactive approval, does not fit that model however clean the adapter is. So
the value of this seam is uncertain even though its cost is near zero, and that
asymmetry is the entire argument for doing the cheap version and stopping.

## 4. Architecture

Modules with hard boundaries, in three layers: discovery and engine below,
Claude Code specifics quarantined to one side, HTTP on top. The engine must be
testable without HTTP, and the HTTP layer must be testable without tmux.

```
src/hitchrail/
  discovery.py   root scanning, folder creation, path safety
  engine.py      state derivation, start, stop, log tail
  claude_ipc.py  everything that knows Claude Code internals
  ram.py         memory readings and the guard decision
  server.py      Starlette app, routes, middleware, SSE
  web/           index.html, app.js, app.css (no build step)
  cli.py         argument parsing, config, uvicorn launch
```

`engine.py` must not import `server.py` or Starlette. This is enforced by an
import-linter contract in CI, not by convention.

### 4.1 The state model

State is derived on demand from the operating system. There is no database and
no persisted session registry, so there is nothing to drift out of sync.

Derivation runs in two directions:

1. For each tmux session with the configured prefix, find the Claude process it
   owns.
2. Independently, scan for processes matching `--remote-control` that no tmux
   pane owns.

That second scan is the point. A tool that only asks tmux reports a Claude that
outlived its terminal as `stopped`, which invites starting a second agent in the
same folder. Four states result:

| State | Meaning |
|---|---|
| `running` | tmux session alive, and it owns a live Claude process |
| `stale` | tmux session alive, no Claude process in it |
| `detached` | Claude process alive, no tmux session Hitchrail can address owns it |
| `stopped` | neither |

`detached` is surfaced in the UI with its pid and an explanation. Hitchrail never
silently reconciles it, because the safe action depends on what that agent is
doing, which Hitchrail cannot know.

**That row said "no tmux session owns it" until #85, and the code never derived
that.** Ownership is read from `list-panes -a`, which returns the panes on the
tmux server Hitchrail is talking to, and the sessions without our prefix were
discarded. An agent alive inside another tool's session was therefore owned by a
pane we had seen and thrown away, and eight of them rendered as orphans at once
on the machine this was developed on.

The fix is the definition, not a fifth state. `foreign` was the honest sounding
option and it buys nothing: such an agent behaves exactly like an orphan in
every direction that matters, since a start must refuse for both, a graceful
stop has no pane of ours to type into for both, and a kill has no session of
ours to kill for both. A state that changes no action is a word, and four states
fit on a phone.

What the row gains instead is `foreign_session`, an overlay in the same family
as `stopping` and `awaiting_trust`: the name of the session that owns the agent,
when one can be seen. **Its absence means no owner was seen, never that there is
none.** `list-panes -a` covers one server on one socket, so an agent under a
different socket, under screen, or under a plain terminal arrives with the field
null and is not orphaned at all. Anything rendering it says "no session Hitchrail
can address" rather than "no tmux session", because the second is a claim this
tool cannot make.

### 4.2 tmux behaviours to encode deliberately

These are known, non obvious, and each gets a named regression test. They are
invisible from the outside and will be reintroduced by any refactor that does
not know about them.

1. tmux treats `.` and `:` as window and pane separators in a target spec. A
   session named `dotted.site` can be created but never addressed. Sanitize on
   the way in and keep the display name separate from the tmux name.
2. `has-session -t name` prefix matches. `cc-vessel` resolves `cc-vessel-social`.
   The `=` prefix forces an exact match, and only for a session target.
3. `list-panes` takes a pane target, ignores a leading `=`, and falls back to
   prefix matching. It needs a trailing `:` to be read as a session. Getting
   this wrong makes a stopped project read as running on a sibling's process.
4. Concurrent starts must be mutually excluded, per FOLDER. A web UI makes
   double submission far easier than a CLI does.

   **Amended in Phase 4: refused, not queued, and keyed on the directory.**
   This originally said "serialize behind a lock". Holding the second request
   open ties up a worker thread to say something already known, and by the time
   it fires the user has forgotten the tap, so the second start answers
   `Locked` immediately. And the key is the RESOLVED directory rather than the
   project name: `resolve_child` allows a symlink inside the root, so two names
   can be one folder, and starting both spawned two agents into the same
   checkout with neither visible to the other.
5. Never issue a bare `tmux kill-server`. Never kill a session Hitchrail did not
   create. Every tmux invocation is scoped explicitly.


**A pane does not outlive its process.** When an agent exits, tmux destroys the
pane, the window, the session, and then the server itself, in under fifty
milliseconds. Anything the agent printed on its way out is gone before a poll
can see it, which matters most for a start that died: that output is almost
always the explanation. `remain-on-exit` is set on the session, chained into
the same `new-session` invocation so it wins the race, and cleared as soon as
the start is confirmed. Left on, a normal exit leaves a dead pane and the
session reads as `stale` rather than `stopped`. Set with `-g` it would change
the user's own tmux server, which this project drives by default.

### 4.3 Stopping, and the one piece of state that is not derived

Stopping is a sequence, not a button:

1. **Confirm.** Cheap to reverse, so it is one tap away from nothing happening.
2. **Graceful request.** Hitchrail asks the agent to finish and exit, and the row
   enters `stopping`. Nothing has been killed. The user watches it happen.
3. **Escalation, available throughout.** A kill control is present for the whole
   wait, so a user who does not want to wait never has to. It is styled as the
   secondary, destructive path, never as the way out of a stuck dialog.
4. **Timeout.** After 30 seconds with no reply, Hitchrail stops waiting and says
   so. It does **not** escalate on its own. The session is still running, and
   the choice to kill it stays the user's.

Kill is deliberately unreachable before a graceful attempt has been made. Not
because forcing is wrong, but because on a phone the destructive control would
otherwise sit under the thumb at the same size as the safe one.

**The engine owns the policy; the agent adapter owns the mechanism.** Step 2 is
"ask the agent to finish", and what that ASK physically is belongs entirely to
`claude_ipc.py`. For Claude Code it is a key sequence typed into the pane. For
something else it could be a signal, a subcommand, or an HTTP call. The engine
therefore calls one function, `claude_ipc.request_stop(...)`, and never iterates
a key sequence or reaches for `tmux.send_keys` itself.

This split is worth stating because the obvious implementation gets it wrong.
Writing `for keys in GRACEFUL_STOP_KEYS: tmux.send_keys(...)` in the engine puts
three Claude Code assumptions into the layer that is supposed to hold none: that
stopping is keystrokes, that it is a sequence of them, and that they travel
through tmux. The engine keeps what is genuinely its own, which is the timeout,
the in flight marker, the escalation policy and the refusal to escalate
automatically. Step 3's kill stays in the engine too: killing the tmux session
is not agent specific, which is exactly why it is the reliable backstop.

This introduces the only state Hitchrail holds that is not derived from the
operating system: the fact that a graceful stop is in flight, and when it
started. It lives in memory in the engine, keyed by session name, and it is
deliberately not persisted. If Hitchrail restarts mid-stop, that knowledge is lost
and the session simply reads as `running` or `stopped` again, which is the
truth. A `stopping` marker that outlived the process would be a lie waiting to
be told.

So the state table in 4.1 gains one transient overlay, not a fifth derived
state: any session may additionally be marked `stopping` while a request is in
flight. Every consumer treats an unknown or expired marker as absent.

**A second overlay, on the same argument, added at #88.** A running session may
additionally be marked `awaiting_trust`: the agent is alive and owns its pane,
and it is sitting on the workspace trust prompt, which only somebody at a
terminal can answer. `running` is true of it and useless, and the flow
guaranteed to produce it is Hitchrail's own New folder button, since every
folder it creates is one the agent has never seen.

Read from the agent's own config, not from the pane. Which folders have been
trusted is recorded per absolute path in an undocumented file that section 4.4
quarantines, so this costs one file read for the whole listing rather than a
`capture-pane` per running row, and it answers the question exactly rather than
by recognising a wording that is the vendor's to change. When that file cannot
be read or has moved, the answer is that we do not know, and no row claims
anything: an empty answer would put the warning on every row at once.

Hitchrail does not answer that prompt. Agreeing to trust a folder on the
operator's behalf, silently, is a different power from anything else here and
would need its own argument in section 5.

**A third overlay, `awaiting_input`, added at #101, and it is the same
argument reached from the other end.** A graceful stop can leave the agent on a
prompt of its own: asked to exit with background work running, Claude Code opens
a confirmation whose entries decide what happens to that work, and waits. The
row then reads `running` while the interface says the session "has not finished"
and offers a kill, which is true and useless.

Found by looking at the pane when a stop's wait expires, and, since #100, also
by a bounded sweep that looks for the same thing without a stop having happened.

**#88 answered one prompt from a file. Every other one needs the screen**, and
#100 is where that is paid for. The refusal in 4.4 stands as written for the
session link: a `capture-pane` per running row on every listing is what turns a
fifty row page into fifty subprocess calls. What changed is where the looking
happens, not whether it is affordable.

It happens on the sweep that already expires stop markers, never on a request.
That bounds the cost by the state of the MACHINE rather than by how often a
browser polls, which matters because the interface polls the listing every
700 ms for a whole stop wait, and because the adapter's own call timeout is ten
seconds: a cap of ten captures on the listing route would be a hundred seconds
of worst case latency on the executor that also serves the operator's stop.

Three bounds, each for a different failure. A cap on how many panes one sweep
reads, since a machine full of stuck agents would otherwise cost a spawn per
stuck row every second. A wall clock budget, since the cap alone bounds count
and not time. And a TTL on what a sweep found, since a claim about a screen that
outlives the thing watching it is a claim nobody has checked since. Rows the cap
does not reach carry no flag, which means NOT CHECKED rather than healthy.

The predicate is "is this an ordinary input box", not "is the box empty". Those
differ on exactly one case, a person's half typed draft, and a draft is not
somebody being needed. The distinguishing byte is the non breaking space the
input box renders after its prompt ornament and a modal does not.

It remains an overlay on one attempt rather than a property of the session: a
fresh stop clears BOTH sources, and the sweep re establishes its own within a
second if it is still true.

Hitchrail does not answer that prompt either, for the same reason and with more
force: those entries decide the fate of work the operator did not ask to end.

### 4.4 Claude Code internals are quarantined

The session link comes from `~/.claude/sessions/<pid>.json`, key
`bridgeSessionId`, whose value is the URL path segment verbatim including its
`session_` prefix. That file is an undocumented internal, it is not written for
every session, and the fallback of scraping the terminal for a `claude.ai/code`
URL can match a URL that merely appeared as text rather than a live bridge.

All of this lives in `claude_ipc.py` behind one documented function with an
explicit instability warning. When it breaks on a Claude Code update, exactly
one module changes, and the UI degrades to a `pending` state rather than
reporting something false.

This module is also the vendor seam described in section 3.1, and the two roles
reinforce each other rather than competing: whatever has to change when Claude
Code changes is the same set of things that would have to change for a
different agent. Keeping it narrow serves both. Nothing outside this module may
name a Claude Code behaviour, a Claude Code file, or a Claude Code key
sequence.

## 5. Security

The threat model is not incidental to this project. Hitchrail spawns
`claude --dangerously-skip-permissions`. Anyone who can drive its API can run
arbitrary code as the user who started it.

The mobile requirement makes network binding the normal case rather than the
exception, so the token path is the main path.

### 5.1 Controls

1. **Host allowlist, always on**, covering loopback names plus any host the
   operator configures. This is DNS rebinding defence: without it, any site the
   user visits in any browser on the network can rebind a name to Hitchrail's
   address and drive the API, with the browser treating responses as same
   origin.

   **Amended in Phase 2: not `TrustedHostMiddleware`.** This section originally
   specified Starlette's. Checked against the installed 1.6.0 rather than
   recalled, it does `host.split(":")[0]`, which splits on the FIRST colon and
   turns every IPv6 literal into `"["`, so `http://[::1]:8787/` is refused
   whatever the allowlist holds and a phone on an IPv6 network cannot reach
   Hitchrail at all. Its `www_redirect` default also answers an unrecognised
   host with a redirect built from that same untrusted header.
   `security.HostAllowlistMiddleware` is ten lines and does neither.
2. **Origin check on every mutating request.** `fetch` and `EventSource` send
   `Origin` and a rebound attacker cannot forge it. This is the CSRF control for
   a same origin JSON API.
3. **Token required whenever anything outside this machine can reach it.**
   Refuse to start, do not warn. Generated on first run, printed to the
   terminal, compared in constant time with `secrets.compare_digest` on bytes,
   never on `str`, which raises `TypeError` on any non ASCII character and
   turns a wrong token into an unauthenticated 500.

   **Amended by #108: this said "any non loopback bind", and the bind is not
   the question.** A reverse proxy makes a loopback socket reachable from a
   whole network: `tailscale serve`, an nginx and an SSH forward all hand the
   request to 127.0.0.1. Hitchrail saw loopback, concluded local only, and
   served with no authentication at all, which is the configuration this
   project's own `--allow-origin` help text describes as supported.

   The trigger is therefore what the operator declared, not what was bound. A
   non loopback `--allow-host` or `--allow-origin` exists for no purpose except
   making a remote name work, so either one is a statement that something
   beyond this machine will arrive, and it demands a token exactly as a non
   loopback bind does. `config.remote_reach` is the one place that decides, and
   the CLI asks it rather than keeping a second copy.

   **Amended in Phase 2: the token needs three carriers, not one.** This
   section originally said "token" and left the carrier implicit, which hid a
   hole: `EventSource` cannot set request headers, so a token carried only in
   `Authorization` authenticates every route except the live update stream the
   interface is built on. Hitchrail therefore accepts the token as a Bearer
   header, as a `hitchrail_token` cookie, and as a one time `?token=` query
   grant that trades itself for that cookie and redirects.

   **Amended by #109: how the token is SUPPLIED is a control, not a
   convenience.** It may come from `--token`, from `HITCHRAIL_TOKEN` in the
   environment, or be generated, in that precedence. argv is the weakest of the
   three and the only one that was available: `/proc/<pid>/cmdline` is world
   readable where `/proc/<pid>/environ` is owner only, so a flag publishes the
   token to every account on the machine. Set but empty is refused rather than
   read as absent, because an operator who wrote the variable and left it blank
   believes they configured authentication.

   A supplied token is also stable across restarts, which a generated one is
   not, and that is what a long running deployment needs. The banner therefore
   prints a token it generated and not one the operator already holds. That is
   not a fix for the log: the grant links still carry it, so under a service
   the journal holds the secret, and what the banner should do there is an open
   question rather than a solved one.

   The cookie is `SameSite=Lax`, because `Strict` is withheld on cross site top
   level navigation and a valid cookie would answer 401 to somebody tapping a
   link to Hitchrail from another page. It is deliberately not `Secure`,
   because over plain HTTP on a LAN, a supported deployment, a `Secure` cookie
   is never sent and the tool silently stops working.

   The token reaches the browser in a URL FRAGMENT, `/grant#token=<token>`,
   which is never sent to a server. A secret in a query string is written down
   by everything it passes: our access log, a reverse proxy's, the `Referer`
   header and browser history sync, and only the first of those was ever ours
   to fix.

   That needs one unauthenticated door, because nothing but JavaScript in the
   browser can read a fragment. It is `GET /grant`, a self contained page with
   no data on it, and `POST /api/grant`, which checks the token and sets the
   cookie. The alternative was serving the app shell on a 401: one URL to
   paste, and an exemption every future addition to the shell would inherit.
   The link is generated by `banner()`, so its length costs nobody anything,
   and a single purpose page cannot accrete.

   **Amended by #115: there are two carriers, not three.** The query grant was
   kept so an already saved link would not break, and was deleted before the
   first release instead of before 1.0. Nothing had shipped, so no such link
   existed and nothing had generated one since the banner moved to
   `/grant#token=`: the carrier protected compatibility with a version that was
   never published, and deleting it was free only until Phase 8.

   What went with it is the better half of the argument. `_scrub_grant_param`
   existed solely to keep that carrier's token out of uvicorn's access line,
   and it rested on where uvicorn emits that line rather than on anything ASGI
   guarantees. A control whose correctness depends on another project's call
   ordering is one worth not needing.
4. **Root is a hard boundary.** Every path is resolved with `Path.resolve()` and
   confirmed to be a direct child of the configured root before any process is
   spawned or any directory created. Folder names are validated against an
   allowlist pattern, not a denylist.
5. **No shell.** Every subprocess call passes an argument list. No
   `shell=True`, ever.

**4. Response headers, added by #77.** Every response carries
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and a Content
Security Policy, applied by a middleware that sits OUTSIDE the three controls
above so that refusals carry them too.

This is the only one of the four that refuses nothing. It instructs the
browser, and it lives in `headers.py` rather than `security.py` for that
reason: that module answers one question, "may this request proceed", and
mixing a header setter into it would blur what its asserted ordering is about.

**The concrete exposure was the key, not the data.** `GET /grant` is reachable
without a token by design, and since #21 it is a page containing a password
field. Framing is a GET, so any page that knew an allowlisted hostname could
have iframed it and drawn its own chrome around that field. The app shell was
never at risk: `SameSite=Lax` withholds the cookie from a cross site framed
subresource, so a framed `/` shows a token screen rather than somebody's
projects.

The policy is per route and exact, the way `route_path` is. `/` gets
`default-src 'self'`, which #76 made possible by serving the typefaces from
here instead of fetching them from Google. `/grant` gets `default-src 'none'`
plus a `sha256` hash for each of its inline blocks, computed from the file at
import so it cannot drift, because that page is served straight off disk and a
nonce would mean rewriting the document per request. Everything else gets
`default-src 'none'`.

`'unsafe-inline'` appears nowhere. On the one unauthenticated page holding a
password field it would give away most of what the policy is for.

**What this cost to get right is worth recording.** The first version omitted
`connect-src` from the grant policy. `connect-src` does not usefully fall back,
so with `default-src 'none'` the page's one `fetch` was blocked, the token was
never traded, and the only symptom was the page reporting that the key was not
accepted. Every header assertion passed, because the header was exactly what we
said it would be. The browser tier found it, which is the argument for that
tier existing.

### 5.2 Precedent

This is not hypothetical. CVE-2026-32632 (GHSA-hhcg-r27j-fhv9) hit Glances, a
localhost and LAN system monitoring web UI, for exactly this: no host
validation, therefore DNS rebinding, therefore an attacker's page reading the
API. Fixed in 4.5.2 by adding a host allowlist. Hitchrail has the same shape and a
worse blast radius, because Glances reports state while Hitchrail starts processes.

Sources:
- https://github.com/nicolargo/glances/security/advisories/GHSA-hhcg-r27j-fhv9
- https://www.starlette.io/middleware/

### 5.2b What the API can actually do

The controls above say who may reach the API. This says what reaching it gets
you, because two of the powers are not obvious from the route table and were
never written down (#91).

**Keystroke injection into a live pane.** `Tmux.send_keys` runs
`tmux send-keys -t <pane>`, which writes to the pty. The agent reads characters
arriving on stdin and nothing in that channel marks them as coming from
anything but the keyboard, so **anything Hitchrail types is attributed by the
agent to its user**.

That is not a defect, it is the reason the graceful stop works here at all. A
peer asking over a message bus announces itself and is increasingly refused by
hardened agents, while a `/exit` we type is simply the user typing `/exit`. #89
is where that distinction reversed the design.

The honest framing is **relay, not impersonation**: a person tapped Stop, and
Hitchrail passed that to the pane the way a keyboard would. It holds exactly as
long as the relayed content is what the person asked for. Today there is one
call site, `claude_ipc.request_stop`, which sends only the stop keys, and
nothing structural keeps it that narrow. A future feature that sent a typed
instruction on the user's behalf would be a different product with a different
risk and would not look different from here.

Stated plainly for an outside reader: **whoever holds the token can cause
characters to be typed into any agent session under the configured root.** That
follows from everything above and is defensible. It should be read rather than
discovered.

**Pid signalling, which does not exist and is the next thing somebody adds.**
A `detached` agent has no tmux session, so nothing Hitchrail can currently do
touches it, and on a phone there is no shell to fall back to. The row names the
pid and explains, and that is where it stops.

Every destructive path here is scoped by construction rather than by a check.
`Tmux.kill_session` can only address `hr-<name>`; what protects the operator's
other sessions is the empty prefix refusal in `Tmux.__init__`, and the obvious
guard inside the kill was removed as a tautology. The property is that
**Hitchrail can only kill things it named.**

A bare pid has no name and no prefix. Signalling one would be the first path
outside that property, and the pid is derived by matching an argv tail out of
`ps`, a match that has been wrong twice (#84, #96). A pid is good enough to
SHOW. Signalling it is a higher bar than showing it, and #107 carries the
argument rather than the code.

### 5.3 Stated limitations

Documented in the README rather than hidden:

- Over plain HTTP on a LAN the token crosses the network in cleartext. On a
  WPA2 or WPA3 network that is a modest risk; the remedy is a reverse proxy
  with TLS, and that is documented.
- Hitchrail does not sandbox the sessions it starts. It is a launcher. The agent
  it launches has whatever access the user has.

## 6. HTTP interface

### 6.0 What `{name}` is, decided by #119

**A project is identified by `<root-label>~<folder>`, always, including when
there is only one root.** Every `{name}` in the table below is that qualified
identifier.

```
hitchrail --root work=~/work --root personal=~/personal

  POST /api/sessions/work~vessel
  POST /api/sessions/personal~vessel
  tmux hr-work~vessel, hr-personal~vessel
```

**Injective by construction, not by convention.** `projectnames.NAME_PATTERN`
is `[A-Za-z0-9][A-Za-z0-9._-]*`, so a folder name cannot contain `~`. A root
label is validated against the same pattern, so it cannot either. The qualified
form therefore has exactly one split point and two distinct project directories
can never produce one identifier. This is the same standard that rejected the
digest suffix in `tmux.sanitize`: injective by construction beat injective by
hash, and it beats injective by careful parsing here.

**`~` rather than `/`, and this is forced rather than chosen.** A slash in the
segment does not work: `work%2Fvessel` returns 404 against the route table
below, verified, and widening the converter to `{name:path}` would swallow the
`/kill`, `/logs` and `/url` sub-routes. `~` is unreserved in RFC 3986, so it
needs no encoding, and tmux reserves only `.` and `:`, which `sanitize` already
escapes.

**Qualified even for one root, and that resolves a conflict #119 left open.**
The ticket asked both that an identifier be stable, never changing because
another root was added, and whether a single root should stay unqualified.
Those cannot both hold: if one root gives `vessel` and adding a second makes it
`work~vessel`, the identifier changed for the reason stability forbids.
Stability wins, because the alternative breaks every saved link on a
configuration edit, which is the failure a phone first tool can least afford.
The cost is a one time migration, and it is taken at 0.1.0, published on
2026-09-04 with no installed base, which is the cheapest this will ever be.

**The three options that lost.**

- **A root segment in the path**, `/api/roots/{root}/sessions/{name}`. Explicit
  and needs no separator, and rejected because it changes the shape of every
  route, the SSE payloads and the client at once, for a distinction the
  qualified name already carries in one segment.
- **Bare names with duplicates refused at startup.** Cheapest, changes nothing
  on the wire, and rejected because `~/work/api` alongside `~/personal/api` is
  an ordinary arrangement rather than a corner case, and the refusal arrives at
  a restart rather than when the colliding folder was created. A feature that
  refuses the common shape of the problem it solves is not the feature.
- **A hash or shortened qualified name.** Rejected in #119 before it was
  proposed, on the `sanitize` precedent.

**What follows from the answer, decided here so it is not re-litigated.**

- **Overlapping roots are refused at startup, naming both.** `--root a=~/dev`
  with `--root b=~/dev/client` makes one directory reachable under two
  identifiers, which breaks injectivity from the filesystem side rather than
  the naming side.
- **`--self-project` takes a qualified identifier.** It names one folder in one
  root, and a bare name would be ambiguous exactly where being wrong is worst.
- **The interface shows the root**, or two identically named rows are
  indistinguishable to the person tapping Stop. The folder is the row's name
  and the label is a badge beside it, so the qualified form is not spelled out
  in the interface even though it is what the API uses.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | the single page |
| GET | `/api/projects` | every folder with its state |
| POST | `/api/projects` | create a folder |
| POST | `/api/sessions/{name}` | start a session |
| DELETE | `/api/sessions/{name}` | begin a graceful stop, returns immediately |
| POST | `/api/sessions/{name}/kill` | kill now, valid at any point |
| GET | `/api/sessions/{name}/logs` | tail of the pane |
| GET | `/api/sessions/{name}/url` | the session's link, once it has one |
| GET | `/api/events` | SSE stream of state changes |

The two stop calls are separate on purpose. The graceful one returns as soon as
the request is sent, marks the session `stopping`, and never blocks the
connection for 30 seconds; progress arrives over SSE like every other state
change. The kill is a distinct ROUTE rather than a flag on the same one, so that
"escalate the stop I already started" and "stop this thing" cannot be confused
at the call site, and so a kill is never a query parameter away from a client
that meant to be gentle. An earlier version of this table said
`DELETE /api/sessions/{name}?kill=1`, which is exactly the flag this paragraph
forbids, and the contradiction was copied into six other documents before
anybody read the two together. See #52.

The rule that settles it, and that the table should be read against: **a
duration is a parameter, an action is a route.** Docker draws the line in the
same place, with `t` as a query parameter on `POST /containers/{id}/stop` and a
separate `POST /containers/{id}/kill`. Here there is not even a duration to
pass, because the wait is `stop_timeout` in the configuration rather than a per
request value, so nothing belongs in the query string at all. Jenkins and
GitHub Actions both give the forced variant its own path for the same reason.

A kill is accepted whether or not a graceful stop preceded it. The requirement
that you try gently first is a property of the interface, not of the API: a CLI
user or a script has a legitimate need to kill outright, and enforcing etiquette
in the transport would only invite working around it.

Errors return a JSON body with a stable machine readable `code` and a human
readable `message`. The complete set, because a short list reads as a complete
one and a client cannot tell the difference:

**The complete error table lives in [`docs/api.md`](../../api.md)**, which is
checked against the server in both directions by `tests/test_docs_are_true.py`.
It was here, and it listed six of the codes the server returns while the
complete set sat in a closed phase's plan (#58). One copy, and it is the one a
person integrating would look in.


Four of these exist because of a decision rather than a condition, and the
decision is the part a client author needs.

`ram_soft` is a confirmation gate: the client resubmits with an explicit
acknowledgement. The server never proceeds on a soft refusal by itself.
`ram_hard` is not overridable, which is why they are different codes rather
than one with a severity.

`unknown_project` and `not_running` are deliberately distinguishable. The root
has never heard of the first; the second is a real project that simply is not
running. Collapsing them tells a person to start something that was never
there, or to check a name that is perfectly correct.

`root_unavailable` and `machine_unreadable` are both 503 meaning ask again, and
neither is the caller's fault. The second is the one worth handling carefully:
section 4.1 makes an unreadable machine an error rather than a fifth state
precisely so it is never derived as `stopped`, and a client that renders its
503 as a failed request shows an empty list where the truth is that the machine
cannot be read.

**One refusal is not in this envelope.** A request body over the limit is
answered `413` with a `text/plain` body, because Starlette installs its body
limit outside the exception handlers and it therefore answers before the
application exists. Documented rather than worked around: a check inside the
route that would have answered in the envelope first could never execute, since
the middleware wins even against a client that lies about `content-length`.

SSE uses `sse-starlette`, not a hand rolled `StreamingResponse`. Ping keepalive,
client disconnect detection and generator shutdown are the parts that are
awkward to get right, and reusing a maintained implementation is preferred to
reinventing one. Note its documented caveat: SSE and `GZipMiddleware` are
incompatible, so gzip is not applied to the event route.

## 7. Interface design

The canvas linked in section 1 is the reference. The decisions it encodes:

- **Row asymmetry carries the mobile case.** A running row is tall because it
  holds three actions. A stopped row is one line with one button, so the
  remaining folders stay scannable with a thumb.
- **Nothing depends on hover.** Touch and pointer get identical affordances.
- **44px minimum hit target** in all mockup content.
- **The controller session is visibly protected.** Where Hitchrail is running in a
  folder that has its own session, that row shows a lock rather than a stop
  control. Refusing after the tap is worse than not offering the tap.
- **Stopping escalates, it does not branch.** The confirm step offers only
  Cancel and Stop. Kill appears once the graceful attempt is under way, phrased
  as impatience rather than as an alternative ("Do not wait, kill it now"), and
  stays available for the whole wait. On a phone the destructive path must never
  sit under the thumb at the same weight as the safe one.
- **The timeout screen states the risk before offering the kill**, because that
  is the moment the user is most likely to reach for it and least likely to have
  thought about uncommitted work.
- **The token screen states the consequence plainly**, in the words a person
  would use, not in security jargon.
- **Dark theme is a first class requirement**, not a later addition.

Palette and type are defined in the canvas: warm neutral ground, a saddle tan
accent, sage for running, brick for destructive, Zilla Slab for display, Karla
for body, IBM Plex Mono for machine values.

## 8. Technology and versions

Verified on 2026-08-25 rather than recalled.

| Component | Version | Why |
|---|---|---|
| Python | 3.11+ | present everywhere current, no ambiguity |
| uv | latest | environment, lock, build, publish, one tool |
| uv_build | >=0.12.5,<0.13 | the `uv init` default, and much faster than hatchling |
| Starlette | 1.6.0 | stable since 1.0.0 in March 2026 |
| uvicorn | 0.52.4 | ASGI server |
| sse-starlette | 3.4.8 | SSE, see section 6 |
| pytest | 9.1.1 | tests |
| pytest-asyncio | 1.4.0 | async tests |
| httpx | 0.28.1 | test client |
| ruff | 0.16.4 | lint and format |
| mypy | 2.3.1 | types, strict |

Starlette 1.0 removed `on_startup`, `on_shutdown`, `add_event_handler()` and the
`@app.route()` and `@app.websocket_route()` decorators. Use the `lifespan`
async context manager and an explicit `routes=` list. Any example written
against 0.4x is wrong, and there is a lot of it in circulation.

`ty`, Astral's type checker, is 0.0.74 and marked beta. Not a day one choice for
a tool that spawns processes as the user. Revisit when it is stable.

Runtime dependency budget is three: `starlette`, `uvicorn`, `sse-starlette`. A
fourth requires a written justification in the pull request. Every dependency is
audit surface for a tool with this blast radius.

The frontend has no build step: vanilla JavaScript and CSS served as static
files. A `node_modules` tree would be larger than the auditable part of the
project.

## 9. Distribution and repository layout

### 9.1 How a user installs it

Python, so the equivalent of `npx` is `uvx`. Three supported routes, in the
order the README should present them:

```sh
uvx hitchrail                      # run it without installing anything
uv tool install hitchrail          # keep it on PATH
pipx install hitchrail             # for people already living in pipx
```

`uvx hitchrail` is the headline. It fetches, resolves and runs in one command,
and leaves nothing behind, which is the right first contact for a tool that
people should be able to try before trusting.

**None of these install the things Hitchrail actually needs**, and that is a
property of being a launcher rather than an oversight. tmux and Claude Code are
runtime prerequisites on `PATH`, and neither is a Python dependency, so every
route above succeeds on a machine that cannot run a single session. The README
states them, and the CLI checks them at startup and refuses with a message
naming what is missing, because the alternative is an obscure failure at the
first tap. Linux only: memory comes from `/proc/meminfo` and the process table
from `ps`.

The package name is confirmed free on PyPI as of 2026-08-25, along with the
hyphenated variants PyPI normalizes to the same project. See section 2 for the
full availability check.

The distribution is a pure Python wheel built by `uv_build`. The frontend has
no build step, so the wheel is source plus three static files, and nothing in
the release pipeline compiles anything.

### 9.2 Repository layout

The root is kept deliberately small. Anything that can live in a subdirectory
does, and every tool that can be configured from `pyproject.toml` is configured
there rather than in its own dotfile.

```
README.md          what it is, how to run it, what it will not protect you from
LICENSE            MIT
pyproject.toml     package metadata AND ruff, mypy, pytest, import-linter config
uv.lock            resolved dependencies, committed
.python-version    the development interpreter
.gitignore
src/hitchrail/        the package (see section 4 for the modules)
tests/             mirrors src/hitchrail/, plus tests/e2e/
docs/              specs, guidelines, and the design canvas sources
.github/workflows/ CI
```

`src/` layout rather than a flat package, so tests run against the installed
distribution and cannot accidentally pass by importing the working tree.

Ruff, mypy and pytest all read `pyproject.toml` natively. Import Linter also
supports it, via a `[tool.importlinter]` section, which is what keeps a fifth
dotfile out of the root.

### 9.3 Running unattended, and what that changes

**Added by #110. This is a deliberate departure from an assumption this
document was written under, recorded here rather than left to drift.**

Everything above describes a session shaped tool: a person starts it, watches
it, and closes the terminal. That assumption is load bearing in a place it does
not announce itself. The window in which the API was reachable was the window in
which somebody was sitting at the machine, and several of the judgements in
section 5 are more comfortable than they look because of it.

A systemd user unit removes that coupling permanently. `packaging/hitchrail.service`
is shipped as a template, and the design accepts the change on these terms:

- **A user unit, never a system unit, and never a `--daemon` flag.** Restart,
  logging, and "is it running" belong to the init system, and reimplementing
  them inside a three dependency budget would be the worst trade available. A
  system unit would want a `User=` and would invite running a tool that is
  functionally a shell as root; a user unit inherits the right identity by
  construction.
- **`Restart=on-failure`, never `always`.** Section 5's refusals are deliberate
  stops. Restarting one forever converts a clear message into a boot loop that
  buries it.
- **The banner degrades when it detects the journal.** Under a unit, stdout is
  journald: persistent, and readable beyond the operator. Section 5.2b's
  reasoning about the grant fragment assumed a terminal a person is watching,
  which is exactly the assumption a service breaks. Detection is systemd's
  documented `JOURNAL_STREAM`, and `cli.py` carries the decision.
- **The exposure is stated as the first thing an operator reads**, in
  `docs/guides/phone-access.md`, not as a footnote under an instruction.

What is NOT accepted: this does not reopen the wildcard bind, and it does not
soften any control in section 5. It changes when the tool is reachable, and
therefore what the documentation has to say first. It does not change what the
tool refuses.

## 10. Testing

Every change ships with the test coverage appropriate to it. Code that
compiles, and a suite that still passes, are not evidence that new behaviour
works: they are evidence that nothing obviously broke. The two are different
claims and only the second one is cheap.

### 10.1 What must be covered

For any behaviour added or modified:

- the primary success path
- the edge cases that behaviour actually has
- the failure and error conditions, including the refusals
- the regression, when the change is a fix

A change is not done when the code is written. It is done when the relevant
suites have been run, the failures the change introduced have been fixed, and
the new behaviour is demonstrably protected by a test that would fail without
it.

### 10.2 Three tiers

**Unit.** Hermetic and fast. `tmux`, the process table, memory readings and the
Claude state directory are all faked behind injectable seams, the same approach
the `another tool` suite uses for its hardware backends. No unit test touches a real
tmux server, a real Claude, the network, or the filesystem outside a temporary
root.

**Integration.** The API driven through `httpx.ASGITransport` against a real
Starlette app with a faked engine. No socket is opened and no server is started.
This is the tier that proves routing, middleware, status codes, error bodies and
the SSE contract.

**End to end.** The real application, launched the way a user launches it,
against a temporary root and a fake `claude` shim, driven through a browser with
Playwright. This tier exists because the things most likely to be wrong here are
precisely the things unit tests cannot see: whether the SSE stream actually
reconnects, whether the stop escalation reaches the kill control in the state
the user is really in, whether 53 rows behave at a phone viewport, and whether
the host allowlist rejects a forged `Host` on a live socket rather than in
theory.

E2E has one hard safety rule, learned the expensive way in the reference
implementation: **the E2E tier drives a private tmux server on its own socket**
(`tmux -S "$SOCK"`, invoked with `env -u TMUX`). A bare `tmux` honours `$TMUX`
over `$TMUX_TMPDIR`, so a suite run from inside a tmux session would otherwise
talk to the developer's real server. It creates only prefixed sessions, kills
only what it created, and never the server.

Playwright is a development dependency. It does not touch the three package
runtime dependency budget.

### 10.3 Non negotiable tests

- Each of the four states in 4.1, including `detached`, which is the one a naive
  implementation gets wrong.
- The `stopping` overlay from 4.3: that it is set, that it expires, that a
  restart clears it, and that a kill during the wait is accepted.
- Each tmux behaviour in 4.2, as a named regression test that fails if the
  workaround is removed.
- Every security control in section 5 asserted as a refusal, not only as a
  success: a bad `Host` is rejected, a mutating request with a missing or
  foreign `Origin` is rejected, a non loopback bind without a token refuses to
  start, a folder name containing a separator or a parent reference is rejected,
  and no code path reaches a shell.

### 10.4 Gates

CI runs lint, format check, types, the import boundary contract, unit,
integration and E2E on Python 3.11, 3.12 and 3.13. All are blocking.

Coverage is measured and reported. It is not turned into a percentage gate:
a number that can be satisfied by exercising lines without asserting on them
rewards the wrong behaviour. The gate is review, and the standard is the list in
10.1.

## 11. Risks

| Risk | Handling |
|---|---|
| `bridgeSessionId` changes or disappears | quarantined in `claude_ipc.py`, degrades to `pending` |
| A user exposes Hitchrail to a hostile network | token forced on non loopback bind, host allowlist always on |
| An unattended service is reachable on a network the operator did not choose | overlay route documented first in `docs/guides/phone-access.md`; the token withheld from the journal; see 9.3 |
| Two starts race on the same folder | start lock, and the API is idempotent per folder |
| A started session dies immediately | reported as `start_died` with the captured output, never as running |
| Memory exhaustion from one tap per session | RAM guard with a hard floor and a soft confirmation gate |
