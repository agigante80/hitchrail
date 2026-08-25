---
paths:
  - "src/hitchrail/security.py"
  - "src/hitchrail/server.py"
  - "src/hitchrail/tmux.py"
  - "src/hitchrail/discovery.py"
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
