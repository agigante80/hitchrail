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

## Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/projects` | every folder under the root, with its state |
| `POST` | `/api/projects` | create a folder |
| `POST` | `/api/sessions/{name}` | start a session |
| `DELETE` | `/api/sessions/{name}` | begin a graceful stop, returns immediately |
| `POST` | `/api/sessions/{name}/kill` | kill now, valid at any point |
| `GET` | `/api/sessions/{name}/logs` | tail of the pane |
| `GET` | `/api/sessions/{name}/url` | the session's link, once it has one |
| `GET` | `/api/events` | SSE stream of state changes |

**Graceful stop and kill are separate routes, not one route with a flag.** A
client that meant to be gentle is never one query parameter away from a kill.
The graceful call returns as soon as the request is sent and reports progress
over the event stream like every other state change.

## Session states

Derived on demand, never stored.

| State | Meaning |
|---|---|
| `running` | tmux session alive, owns a live agent process |
| `stale` | tmux session alive, no agent in it |
| `detached` | agent alive, no tmux session owns it |
| `stopped` | neither |

`detached` is surfaced with its pid and never silently reconciled. Hitchrail
cannot end a detached agent: everything it can destroy is addressed by a
session name it created, and a bare pid has no name.

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
