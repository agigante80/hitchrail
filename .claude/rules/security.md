---
paths:
  - "src/hitchrail/security.py"
  - "src/hitchrail/hostnames.py"
  - "src/hitchrail/config.py"
  - "src/hitchrail/server.py"
  - "src/hitchrail/tmux.py"
  - "src/hitchrail/discovery.py"
  - "src/hitchrail/projectnames.py"
  - "src/hitchrail/cli.py"
---

# You are editing the part that stands between a web page and a shell

Hitchrail spawns `claude --dangerously-skip-permissions`. Anyone who can drive
this API can run arbitrary code as the user who started it. Treat every rule
below as a refusal with a test that asserts it, not as advice.

## The controls

1. **No shell.** Argument lists only. `shell=True` is forbidden, no exceptions.
2. **Host allowlist always on**, applied to every route including the event
   stream. Without it, any page the user visits in any browser on the network
   can rebind DNS and drive this API through their own browser, and the browser
   treats the response as same origin.
3. **Origin checked on every mutating request.** Browsers attach `Origin` to
   cross site requests and a rebound attacker cannot forge it. `GET` is exempt,
   because `EventSource` cannot set headers.
4. **A token is mandatory for any non loopback bind.** The server refuses to
   start without one. A README warning is not a mitigation. Compare with
   `secrets.compare_digest`, never `==`.
5. **The root is a hard boundary.** Validate names against an allowlist
   pattern, never a denylist, then confirm the resolved path is a direct child
   of the configured root before spawning or creating anything.
6. **Never a bare `tmux kill-server`.** Never kill a session without the
   configured prefix. Scope every tmux invocation explicitly.
7. **Report refusals honestly.** A guard that fails open, or an error rendered
   as a success, is worse than no guard. If the state of a session cannot be
   determined, say so rather than guessing.
8. **A secret in a URL is a secret in the log.** uvicorn writes its access line
   after the application returns, from the same scope dict the application was
   handed, so a token in the request target is logged in cleartext even when the
   response redirects it out of the address bar. `TokenMiddleware` clears
   `scope["query_string"]` once the grant token is spent, and
   `test_the_grant_keeps_the_token_out_of_the_access_log` fails if that stops.
   It covers the query grant, which is the carrier #21 replaced: the token now
   rides in a URL fragment, and a fragment is sent to no server, so there is
   nothing in the request target to log. The scrub stays because the `?token=`
   form still works until it is removed before 1.0.

   Follow any secret that rides in a URL all the way to every place that URL is
   written down, not only the places this process controls. Scrubbing our own
   log was never going to be enough on its own, and knowing that is what made
   the fragment the fix rather than a fourth mitigation.

   The exemption that flow needs is `security.UNAUTHENTICATED`, and it is a set
   of `(scope type, method, path)` triples rather than of paths. A path alone
   exempts every method and both scope types, so a websocket route or a second
   method on the API route would arrive unauthenticated. Adding an entry is a
   change to the security boundary and needs the argument #21 made, not a line
   in a list. `test_the_exemption_is_exactly_three_entries` is what notices.

## Order matters

Host check before token check. A rebound request must not reach anything that
could reveal whether a token is even correct.

## This is not hypothetical

CVE-2026-32632 (GHSA-hhcg-r27j-fhv9) hit Glances, a localhost and LAN
monitoring web UI, for exactly the missing host validation above: no host
check, therefore DNS rebinding, therefore an attacker's page reading the API
through the victim's browser. Fixed in 4.5.2 by adding a host allowlist.

Hitchrail has the same shape and a worse blast radius, because it starts
processes rather than reporting on them.

## If you weaken one of these

Do not. If a change appears to require it, stop and say so in the pull request
rather than working around it quietly.
