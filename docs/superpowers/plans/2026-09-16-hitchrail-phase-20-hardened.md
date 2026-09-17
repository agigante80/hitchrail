# Phase 20: The perimeter, hardened

**Objective: the surfaces 0.8.0 shipped, with their own review's findings
closed or declined in writing.**

## Goal

Every ticket the Phase 14 review filed is closed or declined with its reason
on the ticket, and no refusal on the config file, the TLS pair, the network
guard or the pid route can be reached that is not in words.

## What this phase is actually about

The second pass over Phase 14, taken while the reasoning is fresh. Each ticket
here is a finding from the bounded review loops of that phase's own commits,
filed rather than fixed because the loop stops by rule. That makes this a
different shape of phase from the ones before it: there is no design question
left open, every ticket names a file, a line and a scenario that was executed
against the code as it was, and the work is to make each scenario refuse in
words or to write down why it need not.

**Every ticket was checked against the tree on 2026-09-16 before it was given
a task**, body and comments; they were filed that day and the day before, so
none had drifted. Three were closed in the review as already built (#202,
#198, #134) and one declined (#51); they are not here.

## What this phase is NOT about

**New powers.** Nothing here adds a route, a flag or a control. #189 narrows
where an existing control is offered; #267 moves where a file is read.

**The perimeter's shape.** What a request may change is the literal Phase 14
asserted, and no ticket here widens it. #269 is a question about one flag on
the cookie, not about who gets one.

**Absorbing findings.** A phase whose objective is "hardening" absorbs every
review's lows forever, which is how Phase 10 grew from sixteen tickets to
thirty nine. The set is the seventeen tickets in the milestone on the day this
plan was written. A finding from THIS phase's review goes to Backlog or the
next phase, never here.

## The exit criteria, and which task answers each

| Criterion | Tasks |
|---|---|
| 1. The refusals an operator can meet refuse in words | 87 to 91 |
| 2. No file is read at request time that was read at startup | 92 |
| 3. The two Phase 14 modules are proved, not only passed | 93 |
| 4. End is offered to fewer rows the page is wrong about | 94, 95 |
| 5. Every P3 is done or declined with its reason | 96 to 103 |

## Expected work

Four batches, in dependency order. **Round 1 of the review loop runs at the
end of every batch**, with the security lens on every batch, since every file
here is one the rules load for.

### Batch 1: the refusals an operator can meet, tasks 87 to 91

Independent, small, and each is a scenario that was executed against the code.

- [x] **Task 87, #263.** `RootUnavailable` on stop, kill and signal answers
      503 `root_unavailable` in the envelope, as `logs` does since #249. One
      integration test per route with an unreadable root and a stopped name.

- [x] **Task 88, #265.** A ceiling on `stop_timeout` in `Config._check_numbers`,
      3600 seconds, so the flag and the PATCH refuse from the one validator;
      the page's number field carries the same `max`. `--stop-timeout 100000`
      refuses naming the ceiling; the PATCH is `invalid_value` with the state
      file unchanged.

- [x] **Task 89, #268.** `--tls-cert` with a non loopback `http://` extra
      origin refuses at startup naming the origin and the scheme. The test
      that enshrined the admitting behaviour asserts the refusal; an `https://`
      proxy origin with TLS on still starts.

- [x] **Task 90, #264.** `signal_detached` calls `_reject_if_not_a_project`
      unconditionally before the derive, so a detached process whose argv
      names a folder not under this instance's root is 404 with nothing
      opened, and the label check's comment says what it closes.

- [x] **Task 91, #266.** The no-path guard: no converter in any template, every
      `Assign` whose value is `await request.json()` walked, `query_params`
      by subscript matched. Each bypass proved by applying it to a scratch copy
      of `server.py` and showing the guard fails, in the test's own docstring.

### Batch 2: the two that change structure, tasks 92 and 93

- [x] **Task 92, #267.** `Config` no longer opens a file: the certificate pair
      is loaded once in `cli`, into a real `ssl.SSLContext` handed to uvicorn
      through `ssl_context_factory`, with `minimum_version = TLSv1_2` set and
      asserted; `Preferences.apply` validates the timeout through a static
      `Config.check_stop_timeout`. With TLS on and the key file removed after
      start, `PATCH /api/config {"stop_timeout": 45}` answers 200. **The live
      socket test still runs a grant and a Start through the certificate**,
      premortem 1 below.

- [x] **Task 93, #273.** `settings.py` and `gateway.py` in `[tool.mutmut]
      source_paths` and the security rule, `uv run mutmut run` over both, and
      the survivors READ: each real one gets a killing test written from the
      code around it, and the ticket records which survivors were equivalent.

### Batch 3: what the row can see, tasks 94 and 95

- [x] **Task 94, #189.** Mechanism A: walk `ppid` from a detached candidate to
      the first ancestor `is_tmux_argv` recognises and name it on the row, so
      an agent under another socket says "in a tmux session" rather than "no
      session Hitchrail can address", and `signal_detached` refuses it as
      `owned_elsewhere`. **Not a gate**: nothing here authorises a signal, it
      only withholds the control. A live tmux test on a second private socket.

- [x] **Task 95, #175.** The pane map's newline half: a foreign session name
      containing a newline no longer yields a line `could_be_ours` accepts.
      Ask tmux for a delimiter a name cannot contain, or refuse a name holding
      a newline before the split, and a test with the ticket's own input.

### Batch 4: the P3s, one task each, tasks 96 to 101

Task 96 was one line carrying eight tickets, which is not a plan for any of
them. Split on 2026-09-16, after reading each against the tree: three were
done in one commit, one left the phase, and two were narrowed to what this
phase's objective admits.

- [x] **Task 96, #270.** The config file's remaining refusals in words: a label
      holding `=` asked of the allowlist before it is composed, a NUL escape
      and a non UTF-8 file refused with exit 2 naming the file, the config
      DIRECTORY held to the file's own rule, and the state file written
      through a fresh `O_EXCL` name so a symlink at `state.tmp` is not written
      through.

- [x] **Task 97, #271.** The argv suffix match's reason written where the
      refusal that keeps it true lives, a property test over both parsers'
      alphabet, and `check_roots` re-asking a label's shape so a `Root` built
      in code cannot reach the pane map as something `could_be_ours` refuses.

- [x] **Task 98, #260.** The ARP entry matched by the route's interface as
      well as its address, `normalise_mac` matching its own refusal message,
      both tables decoded with replacement, the STALE window documented as a
      limit rather than closed, one operator command in the guide, and
      `expect_gateway_mac` on the config view with a test.

- [x] **Task 99, #272.** The signal route's smaller refusals: EPERM at the
      open as `pidfd_unavailable`, the uid window written down as advisory
      with the kernel's refusal named as the property, `state.signalled`
      pruned on render, one `Machine` behind the gone-versus-reused split, and
      the live test's orphaned `sleep`. Item 4 of that ticket, binding a
      signal to the pid the person saw, is SPLIT OUT to #279: it changes a
      contract, and this phase adds none.

- [x] **Task 100, #258.** An encrypted TLS key refuses at startup in words,
      naming the key, without ever reaching a prompt. The passphrase INPUT
      that ticket also offered is split out to #280, because a new operator
      input is a new flag and this phase adds none.

- [x] **Task 101, #256.** The settings page keeps a refused toggle's reason
      through the repaint, and the empty state stops naming roots it cannot
      show.

- [x] **Task 102, #269.** Decided by the operator on 2026-09-16: `Secure`
      when we terminate TLS, or when every non loopback `--allow-origin` is
      https. The batch's own review added the third clause a day later, the
      bind: a LAN bind beside an https origin set the flag while our derived
      origins still admitted plain http, which is a cookie the browser
      throws away. `Config.cookie_is_secure` carries the rule, its reason
      and the failures it sits between; the cookie test is parametrised over
      six deployments.

- [ ] **Task 103, #237.** MOVED OUT to Backlog, issue #237. It is the mutation
      sweep over the five modules Phase 10 did not reach, about 139 survivors
      to read, and it has nothing to do with this phase's objective. Its own
      body says it was filed to Backlog deliberately, for the reason this plan
      gives in "What this phase is NOT about": a phase that absorbs work like
      this never ends. It reached the milestone in a triage pass that read it
      as one more P3 to decide.

## Done looks like

- [x] Every task above is ticked, or is marked MOVED OUT with the issue that
      carries it.
- [x] Every ticket in the milestone on 2026-09-16 is closed, done or declined
      with the reason on the ticket, or moved out with the issue that carries
      it named in the task above, and #269's decision is written into
      `security.py` whichever way it went.
- [x] `docs/api.md` documents every code this phase added or changed, held to
      the server both ways.
- [x] `Config(...)` opens no file, asserted.
- [x] The roadmap's Phase 20 block says `state: done`, the milestone is closed,
      `scripts/check-phases.sh` is clean, and this plan has no unticked box
      without a marker.

## Fails if

Written as a premortem on 2026-09-16: it is the end of this phase and it
failed badly; what happened? Three answers, each with the evidence that makes
it believable and the rule that stops it.

1. **Moving the certificate load out of `Config` broke TLS on a live socket
   and the hermetic tier could not see it.** The pair used to be loaded in
   `__post_init__`, where every test that builds a `Config` exercised it; in
   the CLI it is exercised only by `main`, and a context handed to uvicorn
   through a factory is a different code path from `ssl_certfile=`. Phase 14's
   premortem 1 is the precedent: only a socket carries a scheme. Rule: task 92
   keeps `test_a_grant_and_a_start_go_through_our_own_tls` on a real socket,
   and adds the assertion that the context uvicorn was given has the floor.

2. **The listing check on the signal route refused a live session it should
   have reached**, the #42 failure reintroduced one route over: a detached
   agent in a folder renamed under it becomes unreachable by the one route
   that could end it. Rule: task 90's test includes the renamed-folder case
   and asserts the row can still be ended through stop or kill where a tmux
   session exists, and that the pid route's refusal names the listing.

3. **The phase absorbed its own review's findings** and never closed, the
   Phase 10 shape. Every batch's review will find lows, because that is what
   a reviewer does. Rule: a finding from this phase's review is filed to
   Backlog or the next phase with `from-review`, never into this milestone,
   and the "What this phase is NOT about" section is the sentence to cite.

## Out of scope

- A finding from this phase's own review: Backlog, or the next phase.
- New routes, flags or controls: none, by the objective.
- `engine.py`'s split (#274): Phase 18.
- The pane map's other delimiters and `is_tmux_argv`'s reach: only what #175
  and #189 name.
