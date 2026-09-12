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
trades a token for the cookie.

**A token is demanded whenever anything outside the machine can reach the
server**: a non loopback bind, or a non loopback name passed to `--allow-host`
or `--allow-origin`. On a plain loopback bind with no such name, no token is
configured and none is required.

Three checks run on every request, in this order, and the order is asserted by
a test: **host allowlist, then token, then origin**. Token precedes origin so
an unauthenticated caller cannot enumerate the origin allowlist by watching a
403 become a 401.

The origin check applies to mutating requests only. `GET` is exempt, because
`EventSource` cannot set headers.

## What `{name}` is

**A project is `<root-label>~<folder>`**, always, including when only one root
is configured. `--root` takes `label=path` and is repeatable, and the label is
the first half of every identifier below.

```
hitchrail --root work=~/work --root personal=~/personal

POST /api/sessions/work~vessel
POST /api/sessions/personal~vessel
```

Both halves are held to the same allowlist, `[A-Za-z0-9][A-Za-z0-9._-]*`, so
neither can contain `~`. The identifier therefore has exactly one split point
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
| `POST` | `/api/sessions/{name}/answer` | send one key to a prompt the agent is blocked on |
| `GET` | `/api/sessions/{name}/logs` | tail of the pane |
| `GET` | `/api/sessions/{name}/url` | the session's link, once it has one |
| `GET` | `/api/events` | SSE stream of state changes |

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
| `roots` | every configured root as `{label, path}`, one root still a list |
| `server` | this server, as distinct from this machine |
| `server.version` | the version the installed distribution carries, the string `hitchrail --version` prints; null from a bare checkout |

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
| `already_exists` | 409 | a folder of that name is already there |
| `already_running` | 409 | that project already has a live session |
| `locked` | 409 | a start is already in flight for that project |
| `no_agent` | 409 | there is no agent to act on, so the request cannot be honoured |
| `invalid_key` | 400 | the key asked for is not one of the keys Hitchrail will send |
| `not_asking` | 409 | a key was sent but the screen is not showing a question to answer |
| `not_running` | 409 | a stop or kill was asked for something that is not running |
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

`GET /api/events` is `text/event-stream`. Each event carries one session as
JSON, in the same shape as an entry from `GET /api/projects`.

It is exempt from the origin check, deliberately, because `EventSource` cannot
set request headers. It is not exempt from the host allowlist or the token.

A slow client is dropped rather than allowed to hold the server. Reconnect and
refetch the listing; the stream carries what happens from now on and does not
replay history.
