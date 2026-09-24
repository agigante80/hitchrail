# Phase 21: The agent's tooling, kept current

**Objective: the operator brings the agent's plugins up to date from a phone,
and sees what happened to each one.**

## Goal

One operation refreshes the marketplaces and updates every `user` scope
plugin, reporting each plugin separately. It runs as `hitchrail
update-plugins` with no server, and from a control on the phone with the
results arriving as each plugin finishes.

## What this phase is actually about

Upkeep that has no home. The plugins go stale without anyone noticing, and
the operator tends to notice when they are away from the desk, which is
exactly when Hitchrail is the only way in. The phase was placed first on
2026-09-23 on the operator's call, on cost of delay.

**Both tickets were checked against the tree and the vendor CLI (2.1.280) on
2026-09-23 before they were given a task.** #124 was written on 2026-09-04,
and two of its premises had moved: `-y` now approves a command the marketplace
declares, and `plugin list --json` repeats one id per project for `local`
installs, at different versions, with no project path. #124 was rewritten
and split, and #297 is its second half.

**Two decisions were taken by the operator on 2026-09-23**, so no task below
still has a question in it:

- `-y` is passed. A marketplace's declared install command is approved
  unseen, on the argument that an agent spawned with every permission already
  sets that ceiling. The persistent effect is written into `SECURITY.md`.
- Updating the agent binary itself is not in this phase. "Libraries" in the
  request did not mean it.

One more was taken in the rewrite and is recorded on #124 with its reason:
only `user` scope is updated, and every other row is reported as skipped with
its scope, never dropped.

## What this phase is NOT about

**Project scoped plugins.** Updating them needs the project path, which the
listing does not carry; reading it from elsewhere is more vendor state in the
quarantine, and a separate ticket if anyone asks for it.

**Splitting `claude_ipc.py`.** The plugin knowledge goes into the quarantine
because the quarantine is the rule. The size cap moves with its reason
written beside it, and the package split is Phase 18's argument.

**Absorbing findings.** A finding from this phase's review goes to Backlog or
the next phase with `from-review`, never into this milestone.

## The exit criteria, and which task answers each

| Criterion | Tasks |
|---|---|
| 1. The operation exists, quarantined, with every refusal tested | 104 |
| 2. It runs from the command line with no server | 105 |
| 3. It runs from the phone, with the results arriving over time | 106, 107 |
| 4. It has been watched working on a real machine | 108 |

## Expected work

Two batches, in dependency order. **Round 1 of the review loop runs at the
end of each batch**, with the security lens on both: every file here is one
the security rules load for.

### Batch 1: the operation and the subcommand, #124, tasks 104 and 105

- [x] **Task 104, #124.** `claude_ipc.update_plugins(binary, run, report)`:
      the marketplace refresh, the listing parsed and validated, each `user`
      scope id updated once with `-s user -y --json` and its own timeout,
      every other row a `skipped` outcome with its scope. `agent_missing`,
      `marketplace_refresh_failed` and `plugins_unreadable` as one exception
      type carrying the code. The runner is injected; `tests/test_plugins.py`
      holds every case in the ticket's table, and the quarantine guard reads
      the AST's string constants outside `claude_ipc.py`.

- [x] **Task 105, #124.** `hitchrail update-plugins [--agent-binary X]`,
      dispatched before the server's parser so bare `hitchrail` is unchanged.
      One line per outcome, exit 0, 1 or 2. `tests/test_cli.py` for the
      dispatch and the exit codes; the `cli` tier runs the installed console
      script against a fake agent on PATH. README, SECURITY.md, the design's
      `claude_ipc` section, `docs/tech-guidelines.md` and the changelog.

Round 1 of batch 1's review found two mediums, both fixed in `fdd12e8`, and
seven lows, filed as #298 to #304. Round 2 reviewed only that fix, found no
high and two mediums in it, and the loop stopped there by rule: #305, #306.
One round of two found a defect in the previous round's fix, under the trip
wire.

### Batch 2: on the phone, #297, tasks 106 to 108

The gate on #297 changed the shape before any of it was built: the record
travels as a NAMED `plugins` event, because the list page's `message`
listener renders every frame as a session; and `GET /api/plugins/update`
answers a page that joins or reconnects mid run, because the stream does
not replay. Both are alternative 1 of the gate's three.

- [x] **Task 106, #297.** The engine side: an in memory in flight marker,
      `update_in_flight` when it is set, the operation run on a worker thread,
      each outcome and one summary published on the bus, and the marker
      cleared on every exit path. `POST /api/plugins/update` answers 202 and
      is Origin checked. `docs/api.md` in both directions.

- [x] **Task 107, #297.** The control on the settings page, the outcomes
      rendered as they arrive, the failure codes shown with no count, and the
      restart notice when a session is running. The e2e tier at the phone
      viewport with a fake agent.

Round 1 of batch 2's review found a high (a stale GET answer painting
"running" back over "done"), fixed in `11fb0c4`. Round 2 reviewed only that
commit and found a high in it (`seq` restarting with the server so a page
left open across a restart drops every later record) and a medium (the
note never clears), fixed in `1f6ec49`, plus two lows filed as #316 and
#317. Round 3 reviewed only `1f6ec49` and found two more defects: `isStale`
treats a different epoch as always newer, so a record delayed by an await
can repaint over a newer one once the server restarts under it (#314), and
`settle`/`keepNote` are one flag shared by two independent request flows,
so either one's success can wipe the other's owed refusal (#315). Two
consecutive rounds each found a defect in the immediately preceding round's
fix, tripping the review loop's trip wire; the loop stopped there by rule,
both filed rather than fixed.

- [x] **Task 108.** Watched on a real machine: a run from the phone against
      the real agent binary, its per plugin results on screen, and the
      unreadable listing case watched with a shim. The standing rule in the
      roadmap says a phase is not done before this.

      Done 2026-09-23, with the operator's go-ahead, against the development
      machine's own plugins (Claude Code 2.1.280), from the settings page at
      390x844 in Chromium driven by Playwright, the claude-in-chrome
      extension being disconnected. A server on an empty temporary root and
      port 8799, never the real projects root. The run took 33 seconds:
      marketplaces refreshed in 16, then 23 rows arrived one at a time, and
      the summary read `16 updated, 0 failed, 7 left alone`. The six `local`
      installs of one plugin and the one `synced` row were left alone and
      listed. A listing taken before and after shows three versions actually
      moved (forge-kit-devops 0.12.9 to 0.15.0, governance 0.16.9 to 0.18.0,
      roadmap 0.8.4 to 0.9.2): the other thirteen `updated` were already
      current, which is the limit the record documents and a ticket now asks
      to end. The garbled listing case, a shim printing `{"plugins": ...}`,
      was watched through `update-plugins`: `plugins_unreadable`, exit 2,
      nothing updated.

## Done looks like

- [x] Every task above is ticked, or is marked MOVED OUT or NOT BUILT with
      the issue that carries it.
- [x] #124 and #297 are closed.
- [x] `docs/api.md` documents the route, its code and the event shapes, held
      to the server both ways.
- [x] The roadmap's Phase 21 block says `state: done`, the milestone is
      closed, and `scripts/check-phases.sh` passes for this phase.

## Fails if

Written as a premortem on 2026-09-23: it is the end of this phase and it
failed badly; what happened? Four answers, each with the evidence that makes
it believable and the rule that stops it.

1. **It reported success while updating nothing.** The vendor changed the
   listing's shape, the parser read an empty list, and the phone said "0
   updated" in green on a machine with twenty plugins. This is the failure
   #124 was rewritten around, and it is the easiest one to reintroduce in a
   tidy-up that makes an empty list "fine". Rule: an empty listing is a
   legitimate answer only when the JSON is a list, and a non empty list with
   no recognisable row is `plugins_unreadable`; both have a test, and the
   interface renders no count for a failure code.

2. **It hung the server.** A plugin update waited on a prompt, or the network
   stalled, and the in flight marker stayed set forever, so every later
   request was `update_in_flight` until a restart. Rule: every subprocess call
   has a finite timeout, asserted on the runner; the marker is cleared in a
   `finally`, with a test that raises from inside the operation.

3. **It updated the wrong project.** A `local` install was updated from
   Hitchrail's own working directory, or six installs were collapsed into
   one. Rule: no update call is ever made with a scope other than `user`,
   asserted on the argv of every call in the scope test.

4. **The vendor's words leaked out of the quarantine.** The route handler or
   the engine grew a `"plugin"` literal or an `-s` flag while wiring the
   events, and the next vendor change touches three files. Rule: the AST
   guard in task 104 runs over every module but `claude_ipc.py`, and the
   event payloads carry outcomes, never argv.

## Out of scope

- Project, local, synced and managed scope updates: a separate ticket if
  wanted, Backlog.
- Updating the agent binary itself: not requested.
- Splitting `claude_ipc.py`: Phase 18.
- A finding from this phase's own review: Backlog, or the next phase.
