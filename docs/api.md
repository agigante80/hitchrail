# The HTTP API

What a client can call, and everything it can be told in reply.

**This is the reference an integrator reads.** The design document argues why
the interface is shaped this way; this says what it does. Where they disagree,
this file is checked against the server by
`tests/test_docs_are_true.py` and the design is not.

## Authentication

Two carriers for one token.

| Carrier | How |
|---|---|
| `Authorization` header | `Authorization: Bearer <token>` |
| Cookie | `hitchrail_token=<token>` |

The cookie exists because `EventSource` cannot set request headers, so a token
living only in `Authorization` would authenticate every route except the live
update stream, which is the one the interface depends on. `POST /api/grant`
trades a token for the cookie: `HttpOnly`, `SameSite=Lax`, `Path=/`, and
`Secure` when the server terminates TLS itself (`--tls-cert`), and also when
it does not but the bind is LOOPBACK and every non loopback `--allow-origin`
is `https`, which is the TLS terminating proxy deployment: the browser
reaches the proxy over HTTPS, so the flag costs nothing there and without it
the cookie is offered to `http://` on the same host at any port, since
cookies are not port scoped. Not `Secure` on a plain HTTP deployment, where
the browser would never send it back, and not on a LAN bind even beside an
https origin, because a browser can still reach that server in the clear and
would throw the cookie away. Loopback origins do not count either way.

**A token is demanded whenever anything outside the machine can reach the
server**: a non loopback bind, or a non loopback name passed to `--allow-host`
or `--allow-origin`. On a plain loopback bind with no such name, no token is
configured and none is required.

Three checks run on every request, in this order, and the order is asserted by
a test: **host allowlist, then token, then origin**. Token precedes origin so
an unauthenticated caller cannot enumerate the origin allowlist by watching a
403 become a 401.

The origin check applies to mutating requests only. `GET` is exempt, because
`EventSource` cannot set headers. The origins derived from the server's own
bind carry its own scheme, `https` with `--tls-cert` and `http` without; an
origin a proxy presents is `--allow-origin`, with the proxy's scheme and port.

## What `{name}` is

**A project is `<root-label>~<folder>`**, always, including when only one root
is configured. `--root` takes `label=path` and is repeatable, and the label is
the first half of every identifier below.

```
hitchrail --root work=~/work --root personal=~/projects

POST /api/sessions/work~vessel
POST /api/sessions/personal~vessel
```

Both halves are held to the same allowlist, letters, digits, `.`, `_`, `-`
and, in a folder name, a single space between words (`work~my app`, sent as
`work~my%20app`), so neither can contain `~`. The identifier therefore has exactly one split point
and two project directories can never produce one name. A bare `vessel` is not
an identifier and is refused: with more than one root it would name two things,
and choosing one for the caller at a destructive route is the ambiguity this
replaced.

`~` rather than `/` because a slash does not survive the route table below:
`work%2Fvessel` is a 404, and a converter wide enough to match it would swallow
the `/kill`, `/logs` and `/url` sub-routes. `~` is unreserved in RFC 3986, so it
needs no encoding.

**This changed after 0.1.0.** Every identifier from that release gains a prefix.
See `CHANGELOG.md`.

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/projects` | every folder under every configured root, with its state |
| `POST` | `/api/projects` | create a folder |
| `POST` | `/api/sessions/{name}` | start a session |
| `DELETE` | `/api/sessions/{name}` | begin a graceful stop, returns immediately |
| `POST` | `/api/sessions/{name}/kill` | kill now, valid at any point |
| `POST` | `/api/sessions/{name}/signal` | SIGTERM to a detached agent nothing addressable owns, through a pidfd |
| `POST` | `/api/sessions/{name}/signal/force` | SIGKILL to the same, a second explicit request |
| `POST` | `/api/sessions/{name}/answer` | send one key to a prompt the agent is blocked on |
| `GET` | `/api/sessions/{name}/logs` | tail of the pane |
| `GET` | `/api/sessions/{name}/url` | the session's link, once it has one |
| `GET` | `/api/events` | SSE stream of state changes |
| `GET` | `/api/config` | the effective configuration, every value with its source, never the token |
| `PATCH` | `/api/config` | hide or show a configured root, or set the stop wait; the two settings a request may change |
| `POST` | `/api/plugins/update` | begin updating the agent's plugins, returns immediately with the run record |
| `GET` | `/api/plugins/update` | the current or last plugin run, `idle` when there has been none |
| `GET` | `/logs/{name}` | a page showing one project's tail, bookmarkable; refuses a name exactly as `/api/sessions/{name}/logs` does |

**Graceful stop and kill are separate routes, not one route with a flag.** A
client that meant to be gentle is never one query parameter away from a kill.
The graceful call returns as soon as the request is sent and reports progress
over the event stream like every other state change.

### The listing payload

`GET /api/projects` answers one object. The fields, checked against the server
in both directions by the suite:

| Field | What it holds |
|---|---|
| `projects` | every project under every root, each in the shape the event stream sends |
| `unsupported` | folders that cannot be projects, each with the rule it broke, capped |
| `unsupported_total` | the true count behind that cap |
| `memory` | the machine's `available_mb` and `total_mb`, null when unreadable |
| `roots` | every root the interface shows as `{label, path}`, one root still a list |
| `hidden_roots` | the labels of configured roots absent from the listing today, disabled in the config file or hidden by a request; an empty page says "hidden" rather than "no projects" |
| `hidden_roots_editable` | of those, the ones a request can bring back: the config file's own `enabled = false` is not one, so an empty page can say where the choice lives |
| `server` | this server, as distinct from this machine |
| `server.version` | the version the installed distribution carries, the string `hitchrail --version` prints; null from a bare checkout |
| `server.user` | the account this server runs as, which is the account every session it starts runs as; the numeric uid when the account has no passwd entry |
| `server.started_at` | when this process started, Unix seconds; format it in the viewer's timezone, never the server's |
| `server.stop_timeout` | seconds the server waits for a graceful stop before reporting it timed out; the browser's own patience is this number, read here rather than assumed |

### The session payload

One project, as `projects` lists it, as `POST` and `DELETE` on
`/api/sessions/{name}` return it, and as the event stream sends it:

| Field | What it holds |
|---|---|
| `name` | the qualified identifier, `<root-label>~<folder>` |
| `state` | one of the four states below |
| `pid` | the agent's process id, null when there is none |
| `ram_mb` | resident memory of the agent and its descendants |
| `ram_limit_mb` | the tightest `memory.max` or `memory.high` on the agent's cgroup ancestry; null when nothing bounds it that Hitchrail can see, which includes an unreadable tree and cgroup v1 |
| `uptime_s` | how long the agent has run |
| `url` | the session link once the agent has published one, else null |
| `stopping` | a graceful stop is in flight |
| `protected` | the self project; refuses every mutating route |
| `awaiting_trust` | the agent is sitting on its trust prompt |
| `awaiting_input` | the agent is sitting on a question only a person can answer |
| `foreign_session` | the tmux session another tool runs the agent under, when one is visible, or `(unnamed)` when that session has no name (tmux 3.7a admits one); null otherwise |
| `foreign_server_pid` | the pid of a tmux server above the agent that Hitchrail is not configured for, found by walking the process tree; null when none is, which still means none was seen |

### `POST /api/sessions/{name}/answer`

Body: `{"key": "Enter"}`. One key, from a fixed set, delivered to a session that
is sitting on a question it cannot answer itself.

```
Up  Down  Enter  Escape  1 2 3 4 5 6 7 8 9
```

**That set is the whole of what this route will send, and it is a literal in
the code rather than a pattern.** There is no free text member. This is not the
"send input to a session" that `docs/roadmap.md` defers: that is an input box
carrying arbitrary text on demand, and it stays deferred. This carries one
keypress in reply to words the operator read on screen.

The key travels in the body and never in the path or query string, so it stays
out of journals, `Referer` headers and any proxy log between a phone and this
process.

The pane is re-read immediately before the key is sent. A screen that no longer
holds a question is `not_asking` (409) and nothing is sent, including when the
pane cannot be read at all. Refusing on "cannot tell" is deliberate: a key not
sent costs another look, and one sent wrongly cannot be recalled.

Refused for the self project (`self_protected`, 423) like every other mutating
route, and `no_agent` (409) for both states that hold no agent to answer:

- **detached**, which has no terminal to answer in at all
- **stale**, which is a tmux session whose agent has gone, so the pane holds a
  shell. Sending a key there types at a shell rather than an agent, and `Up`
  followed by `Enter` would re-run whatever that shell last ran. The pane check
  cannot catch it, because U+276F is the default prompt character of Starship,
  Pure and Powerlevel10k, so a stale pane on a developer's machine looks exactly
  like a prompt awaiting an answer.

### `POST /api/sessions/{name}/signal`, and `/signal/force`

For a `detached` row: an agent alive with no tmux session Hitchrail can
address, which stop and kill cannot reach. `/signal` sends SIGTERM and
`/signal/force` sends SIGKILL; the second is its own route and never what
happens first. 202 with the session body as it was verified a moment before
the signal; the listing shows the row go.

**This is the one destructive route not scoped by the tmux prefix**, so it is
scoped by a check, in one order: a pidfd is acquired, the row is re-derived
and must still be `detached` for that project and that pid with no owner,
and the signal goes through the handle. A pid reused between the listing and
the call is a different process the handle does not refer to (`not_ours`);
one that exited is `gone`; nothing is ever signalled by `os.kill`, and a
machine that cannot open a pidfd is told so (`pidfd_unavailable`, 501).

Refused before any handle is opened: the self project (`self_protected`),
a pid in the process tree this server runs in (also `self_protected`), a row
that is not detached (`not_detached`), a row a tmux Hitchrail can see holds
(`owned_elsewhere`, with the session in a `session` field, or the server's
pid in `server_pid` when it is one on another socket: attach there),
and another user's process (`not_ours`). Refused after the handle, on the
process the handle refers to: a pid that changed identity or left (`not_ours`,
`gone`), and a process whose working directory is not under this
instance's root for that label as configured, at any depth, since an agent
in a worktree runs below its project (`not_ours`: another instance's agent,
or a root that moved since the agent started), because the argv this
route matches on is what a second instance as the same user writes too and
only the directory tells the two apart. A folder deleted under a running
agent still reads as under the root, so that agent can still be ended.

### `GET /api/config`

The effective configuration, for a person on a phone asking "what is this
instance pointed at" without SSH. Every value is `{value, source}` where
`source` is `flag`, `file`, `env` or `default`: `host`, `port`,
`allow_hosts`, `allow_origins`, `self_project`, `agent_binary`,
`session_prefix`, `tls` (the certificate's path, or null),
`expect_gateway_mac` (the flag's value, normalised, or null), the three
memory figures, `config_file` and `state_file`.
`roots` is every configured root as `{label, path, enabled, editable,
source}`, hidden ones included, with `hidden_roots` beside it; `stop_timeout`
is `{value, source, editable}`, its source `state` when the interface set it.
**`token` carries its source and never its value**, and `none` means the
server runs without one, which only a loopback bind allows.

### `POST /api/plugins/update`, and `GET`

Refreshes the agent's marketplaces and updates every plugin installed at
`user` scope, one at a time, the operation `hitchrail update-plugins` runs
(#124, #297). The POST answers 202 at once with the run record; a second POST
while a run is in flight is 409 `update_in_flight` and changes nothing. The
GET answers 200 with the same record at any time, which is how a page that
opens or reconnects in the middle of a run learns where it is: the stream
does not replay.

| Field | What it holds |
|---|---|
| `seq` | a number the server increases on every change to the record, across runs, and never resets while it runs; of two records the larger `seq` is the newer, so a client drops a record older than the one it shows. `0` before any run |
| `state` | `idle` before any run, `running`, `done`, or `failed` when the operation itself could not go on |
| `started_at`, `finished_at` | Unix seconds, null until they happen |
| `outcomes` | one per row of the agent's plugin list so far, in order: `{plugin, scope, result, detail, approved_command}`, `result` one of `updated`, `failed`, `skipped` |
| `counts` | `{updated, failed, skipped}` once `done`; **null otherwise, and always null when `failed`**, so a failure is never rendered as a count |
| `code`, `message` | when `failed`, why, in the codes below; null otherwise |

`updated` means the agent's update exited zero, which it also does for a
plugin that was already current. A plugin at any scope other than `user` is
`skipped` with its scope, since it belongs to a project folder the agent's
list does not name. `detail` and `approved_command` are the agent's own words,
with control characters escaped and cut to 240 characters: render them as
text. `approved_command` is what `-y` approved without showing it, when the
agent reports it; see `SECURITY.md`. Running sessions keep the old versions
until they are restarted.

The codes a `failed` record carries. They are not HTTP statuses: by the time
the operation fails the 202 has been sent.

| Record `code` | When |
|---|---|
| `agent_missing` | the configured agent binary could not be run |
| `marketplace_refresh_failed` | the marketplaces did not refresh, so no plugin was updated |
| `plugins_unreadable` | the installed plugin list was not understood, so nothing was updated, including the rows that parsed |
| `internal_error` | the run stopped on a defect in Hitchrail; the journal has the traceback |

### `PATCH /api/config`

Body: `{"roots": {"work": {"enabled": false}}, "stop_timeout": 45}`, either
half optional. One boolean per configured label, as many labels as the body
names, and a whole number of seconds; the response is the same document
`GET` returns, as it now stands.

**No route accepts a path, and this is the route that would have.** Roots are
read once at startup from `~/.config/hitchrail/config.toml` or `--root`, and
the set of paths Hitchrail can reach is fixed by a person with filesystem
access. This route chooses among them: `enabled` is the whole of what it
edits, the label is validated by membership in the configured set, and
`tests/test_settings_route.py` asserts both against the real route table.

The choice persists in Hitchrail's own `state.toml` beside the config file,
never in the operator's file, and it only ever narrows: a root the config file
sets `enabled = false` on is `editable: false` here, and a request to enable
it is `operator_disabled` (409). Every label in a body is checked before
anything is written, so one unknown label (`unknown_root`, 404) changes
nothing. Any key outside `roots.<label>.enabled` is `not_editable` (400), the
same answer whether the key is a root's `path` or the server's `host`.

Hiding a root removes its projects from the listing and stops nothing: a
session in a hidden root still answers to its name on every session route,
so an agent hidden by mistake can still be stopped. `enabled = false` in the
config file is stronger than hiding: `POST /api/sessions/{name}` in such a
root is `operator_disabled` (409) and spawns nothing, while stop, kill and
logs still resolve the name, so an agent already there can be ended.

`stop_timeout` is the one policy value: a longer wait lets a request do
nothing it could not already do. It passes the refusal `--stop-timeout`
passes (`invalid_value`, 400: a whole number of seconds, 1 to 3600), persists
in `state.toml`, and is read by the engine and reported on the listing's
`server` object from the next request.
A `--stop-timeout` flag pins it: the value shows `source: "flag"`,
`editable: false`, and a request to change it is `operator_pinned` (409)
rather than a write the next restart would ignore.

## Session states

Derived on demand, never stored.

| State | Meaning |
|---|---|
| `running` | tmux session alive, owns a live agent process |
| `stale` | tmux session alive, no agent in it |
| `detached` | agent alive, no tmux session Hitchrail can address owns it |
| `stopped` | neither |

`detached` is surfaced with its pid and never silently reconciled. Hitchrail
cannot end a detached agent: everything it can destroy is addressed by a
session name it created, and a bare pid has no name.

A session carries `foreign_session`: the name of the tmux session that owns the
agent when Hitchrail can see one, and `null` when it cannot. It is sent on every
session, and `null` is sent rather than the field being omitted, so a client can
tell "no owner was seen" from "this server does not send the field".

**`null` does not mean the agent is orphaned.** Ownership is read from one
`list-panes -a` against the tmux server Hitchrail is configured to use, so an
agent under a different socket, under screen, or under a plain terminal has no
owner Hitchrail can see and is reported the same way as a genuine orphan. A
client rendering this must not turn `null` into "no tmux session".

## The error envelope

Every refusal has the same shape.

```json
{ "code": "already_running", "message": "vessel is already running" }
```

**`code` is the contract. `message` is for a person.** Branch on the code; the
wording can change in a patch release.

Some codes carry extra fields alongside those two. Read them by name rather
than by position.

### Every code the server can return

| Code | Status | When |
|---|---|---|
| `host_rejected` | 400 | the `Host` header names something not on the allowlist |
| `invalid_body` | 400 | a body was required and was absent or not JSON |
| `invalid_name` | 400 | the project name is not one this tool will accept |
| `unauthorized` | 401 | no token, or the wrong one |
| `origin_missing` | 403 | a mutating request with no `Origin` |
| `origin_rejected` | 403 | a mutating request whose `Origin` is not allowed |
| `not_found` | 404 | no such route |
| `unknown_project` | 404 | no such folder under the root |
| `unknown_root` | 404 | no configured root carries that label |
| `not_editable` | 400 | the settings body names something a request may not change |
| `operator_disabled` | 409 | the config file disables that root: a request cannot enable it, and nothing is started in it |
| `operator_pinned` | 409 | that setting is given on the command line, and a request cannot override a flag |
| `invalid_value` | 400 | a settings value the command line would refuse too, in the same words |
| `state_unwritable` | 503 | the choice could not be written to `state.toml`, so it was not made |
| `already_exists` | 409 | a folder of that name is already there |
| `already_running` | 409 | that project already has a live session |
| `update_in_flight` | 409 | a plugin update is already running; machine wide, unlike `locked` |
| `locked` | 409 | a start is already in flight for that project |
| `no_agent` | 409 | there is no agent to act on, so the request cannot be honoured |
| `invalid_key` | 400 | the key asked for is not one of the keys Hitchrail will send |
| `not_asking` | 409 | a key was sent but the screen is not showing a question to answer |
| `not_running` | 409 | a stop or kill was asked for something that is not running |
| `not_detached` | 409 | the signal route was asked for a row that is running, stale or stopped |
| `owned_elsewhere` | 409 | a tmux Hitchrail can see holds the agent: `session` names it when the pane map saw it, else `server_pid` names a server on another socket found in the process tree |
| `gone` | 409 | the process left between the listing and the call; nothing was signalled |
| `not_ours` | 409 | the pid is not the agent derivation identified: reused, another user's, or refused by the kernel; nothing was signalled |
| `pidfd_unavailable` | 501 | this machine cannot signal through a race free handle, and Hitchrail will not signal a bare pid; also what an EPERM at the handle is, since `pidfd_open` never refuses on ownership and a denial there is seccomp or an LSM |
| `ram_soft` | 409 | memory is tight; retry with acknowledgement to start anyway |
| `stop_unsafe` | 409 | the pane is not in a state where a stop can be requested safely |
| `url_pending` | 409 | the session has no link yet; ask again |
| `method_not_allowed` | 405 | that route does not accept that method |
| `self_protected` | 423 | the configured self project must never be stopped |
| `start_died` | 502 | the agent was started and exited immediately |
| `machine_unreadable` | 503 | the state of the machine could not be determined |
| `root_unavailable` | 503 | the configured root could not be read |
| `ram_hard` | 507 | below the hard memory floor; Hitchrail will not start into that |

**`machine_unreadable` is the one to handle deliberately.** An unreadable
machine is an error rather than a fifth state, so a client that renders a 503
as "the request failed" will show an empty list where the truth is that the
machine could not be read. Say which it is.

## The event stream

`GET /api/events` is `text/event-stream`. Each unnamed event (`message`)
carries one session as JSON, in the same shape as an entry from
`GET /api/projects`.

A plugin run is announced as a NAMED event, `event: plugins`, whose data is
the whole run record, the shape `GET /api/plugins/update` returns, on start,
after each plugin, and at the end. A client listening only for `message`
never sees one, which is what keeps it from being rendered as a session.

It is exempt from the origin check, deliberately, because `EventSource` cannot
set request headers. It is not exempt from the host allowlist or the token.

A slow client is dropped rather than allowed to hold the server. Reconnect and
refetch the listing; the stream carries what happens from now on and does not
replay history.
