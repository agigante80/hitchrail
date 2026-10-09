# Phase 27: The perimeter's loose ends

**Objective: the origin is parsed in one place every caller uses, each
security finding has a test that fails with its fix reverted, and
`settings.py` is two files along the seam it already has.**

**Written 2026-10-09,** from the roadmap block and the nine tickets in the
milestone, each read against the tree at `4462fba` (0.16.0). Andrea asked for
it to be planned, started and released overnight, so the decisions below are
agent taken, each low stakes and reversible, and each listed again in the
overnight report.

## Goal

Phase 25's batches 4 to 6 hardened the config, the origin check, the state
file and the log filter, and filed what their reviews found but did not fix.
This phase fixes those findings before Phase 23 adds the operator's agent
choice to the same config. `settings.py` is split first, so the state file's
fixes land in a file with room for them.

## What this phase is actually about

Two security findings, each low. #436: a `localhost.localdomain` origin keeps
plain http under a Secure cookie, so the grant answers 200 and every later
call 401s. #440: the log filter that keeps the token out of the journal never
reads a traceback. Around them sit the conditions that let them happen. The
origin is parsed in five places (#439), and one property depends on the order
of two assignments that nothing pins (#437). The state file loses data
quietly (#434). And `settings.py` holds two files' worth of code (#443).

**Checked against the tree on 2026-10-09.** Seven tickets still describe the
code. #441's premise is false: `sweep()` catches every `Exception` in both
bodies and `asyncio.sleep` raises only `CancelledError`, so the awaited task
cannot end by raising anything the shutdown would need to suppress. #464 is
half done: the changelog and README halves shipped in 5294eb3, and the
CLI's interrupt and failure wording is left. #438's third item (a spec line
that overruns) names no line either batch 5 commit touched, so it is dropped
with that reason. #439 counts three copies of the origin parsing; there are
five (`config.py` 121, 134, 472, 841 and `cli.py` 615).

**Decisions taken overnight (agent, reversible):**

- **#436: narrow, not `LOOPBACK_NAMES`.** `is_loopback_host` also decides
  whether a token is demanded and drives the TLS refusals, so the set stays.
  Only `plain_origins_withheld` asks a new question, "is this origin a secure
  context", answered from the W3C Secure Contexts spec's potentially
  trustworthy origin rule: `127.0.0.0/8`, `::1`, `localhost` and names
  ending in `.localhost`. `localhost.localdomain` is not on that list (the
  spec's algorithm 3.1 step 5, read 2026-10-09), so its plain origin is
  withheld with the named 403.
- **#439 item 2: the startup line stays quiet** when a host also has an https
  origin, today's deliberate choice for the phone access setup. The comment
  names the mixed case (https plus a plain forwarder) and why it is accepted.
- **#440: redact the traceback, keep it.** The filter applies the same query
  redaction to the formatted exception text. Dropping `exc_info` would hide
  the error; leaving it means a URL with a token in an exception message
  reaches the journal. A `?` in unrelated exception text is redacted too,
  and that cost is written beside the filter. The false docstring sentence
  about client addresses goes.
- **#441: not built.** Closed with the reason above. A one line suppress
  would need a test that cannot fail.
- **#464: wording only.** `updated` is called provisional after an interrupt
  or a failure. The progress line arrives when an update finishes, not
  when it starts (the plan first said otherwise), so the plugin in flight is
  named by position, as the one after the last `...` line; no new callback. Flagging a failed second
  listing changes what `update_plugins` returns to `plugin_runs`, and stays on
  the ticket for Phase 23, which re-cuts `claude_ipc`.

## Fails if

Agent drafted, since Andrea is away; for Andrea to confirm or rewrite. It is
the end of the phase and it failed badly. What happened?

1. **The split changed behaviour without a test noticing.** Tests that
   monkeypatch `hitchrail.settings.<name>` went on patching the old module
   after the move, so they passed while testing nothing. So the split starts
   with a commit that adds guards and moves nothing, every patch target is
   grepped and moved with its code, and the move commit changes no test
   assertion.
2. **The origin fix changed who needs a token.** Someone tidied
   `LOOPBACK_NAMES` instead of adding the narrow question, and
   `localhost.localdomain` stopped demanding the token or started refusing
   TLS. So a test pins `is_loopback_host("localhost.localdomain")` as true
   and the token rule for it as unchanged, beside the new withholding test.
3. **The redaction hid the error.** The traceback filter cleared `exc_info`
   or ate the whole message, and the next crash left an empty line in the
   journal. So the test asserts the traceback's frames are still there and
   only the query is gone.
4. **The caps went up again.** `config.py` and `cli.py` both sit exactly at
   their caps. The fixes added lines, and each cap rose a little, a tenth
   time. So #439's deduplication lands before #436 and #438 add anything,
   and a cap that still has to rise says why in its commit.
5. **The review loop ran away.** As in Phases 21 and 26: one review per
   batch, the trip wire obeyed, lows filed into Backlog.
6. **Nothing was watched.** Every test passed and no real server ever
   refused `localhost.localdomain`. So the close watch is a real server on a
   private root and a loopback socket, driven by a real browser and `curl`:
   the 403 for `localhost.localdomain` under a Secure cookie, `localhost`
   still granted, and the journal after a forced exception with a query.

## Expected work

Tasks continue from Phase 26's 241. Batch 0 lands first and alone. Batches 1
and 2 touch different files and may run concurrently. Batch 3 waits for
batch 1, since both edit `cli.py`. Each batch is reviewed once at its end,
under the bounded loop; lows go to Backlog.

### Batch 0: room for the state file, task 242

- [x] **Task 242, #443.** `settings.py` split into the operator's config file
      and Hitchrail's state file plus `Preferences`. A guards first commit,
      then a pure move; the caps, the security rules' paths and the
      architecture list updated.

### Batch 1: one origin parser, tasks 243 to 246

Serial, in this order, one implementer. Security auditor review at the end.

- [x] **Task 243, #439.** One origin parser, used by all five call sites;
      `_origin_parts` normalises; the CLI asks `Config` for its https hosts;
      the mixed case named in the comment.
- [x] **Task 244, #437.** `plain_origins_withheld` takes the hosts it reads,
      so no assignment order matters; a test that fails with the order swapped
      on the old code.
- [x] **Task 245, #436.** The secure context question, withholding
      `localhost.localdomain`'s plain origin under a Secure cookie; the token
      rule for it pinned unchanged.
- [x] **Task 246, #438.** The restore advice says the token then crosses
      plain http; `phone-access.md` explains the startup line. Item 3 dropped
      with its reason on the ticket.

### Batch 2: the state file and the log filter, tasks 247 and 248

- [x] **Task 247, #434.** The refusal warning says the next save replaces
      the file; a dangling symlink is logged; a pinned `stop_timeout` with a
      different saved value is reported at startup, as #421 does for
      `stop_policy`.
- [x] **Task 248, #440.** The filter redacts a traceback's query and keeps
      its frames; the client address docstring sentence corrected.

### Batch 3: the CLI's words and a ticket that is not true, tasks 249 and 250

- [x] **Task 249, #464.** The interrupt and failure paths call `updated`
      provisional; the README line agrees.
- [ ] **Task 250, #441.** NOT BUILT, premise false, closed with the reason in
      this plan (#441).

### The close, task 251

- [ ] **Task 251.** The perimeter watched on a real server, private root,
      loopback socket: `localhost.localdomain` refused with the named 403
      under a Secure cookie, `localhost` granted, a forced exception's
      journal line read with its query redacted and its frames intact.

## Done looks like

- [ ] Every task ticked, or marked MOVED OUT or NOT BUILT with an issue number
- [ ] The origin is parsed by one function; a grep test finds no other
      `urlsplit` of an origin in `src/`
- [ ] #436 and #440 each have a test seen failing with the fix reverted
- [ ] `settings.py` is under 400 lines or under a cap lower than 592, and the
      state half is its own module
- [ ] No cap in `ENGINE_LAYER_CAPS` or `OUTER_LAYER_CAPS` went up this phase
      without a reason in its commit
- [ ] Task 251's watch held
- [ ] Roadmap says done, milestone closed, `check-phases.sh` passes

## Out of scope

**A failed second plugin listing, flagged to the caller (#464's remainder).**
It changes `update_plugins`' return value, which Phase 23 re-cuts.

**`LOOPBACK_NAMES` itself.** Who must present a token is not this phase's
question; only which plain origin can carry a Secure cookie is.

**TLS passphrase (#280).** Backlog, by the 2026-10-09 review.

**The page's lows.** Phase 28.
