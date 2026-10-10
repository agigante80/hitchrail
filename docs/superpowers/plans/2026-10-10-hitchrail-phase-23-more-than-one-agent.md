# Phase 23: More than one agent, one package each

**Objective: a second agent starts, stops and is derived exactly as Claude
Code is, through its own quarantined package, chosen on the machine and never
from a page, and the S25 has watched the page that shows it.**

**Written 2026-10-10,** from the roadmap block, #334's decision of 2026-10-07,
and the thirteen tickets in the milestone (one, #291, already closed), each read against the tree at
`6365060` (0.18.0).

## Goal

Design section 3.1 says more than one agent is "not built, not closed off",
and promises that the second implementation is what teaches the real
interface. This phase builds that second implementation, through the seam
`claude_ipc/` already is, and writes down what it taught.

## What this phase is actually about

#334 decided the shape: one package per agent, which agents exist is machine
configuration read once and never written, no command template anywhere, and
no vendor name in the operator or API contract beyond an identifier the
operator chooses. The epic tickets (#290, #292 to #296) predate that decision
and describe a registry of templates edited from a page, so each is rewritten
or closed below before any code.

**Checked against the tree and the machine on 2026-10-10.**

- `claude_ipc/` exports twenty eight names, called from `cli`, `derive`,
  `engine`, `plugin_runs`, `stopmarker` and `sweep`. Those calls ARE the
  interface; nothing is invented that a caller does not already make.
- `derive.find_detached` builds its argv tail from `launch_argv` and matches
  `REMOTE_CONTROL_MARKER`. Claude Code and Antigravity both take a flag spelt
  `--remote-control`, so with two agents the tail must stay unique per agent
  or one agent's orphan reads as the other's.
- Installed here: `agy` 1.2.14, `codex` 0.121.0, `gemini` 0.60.0. Read from
  `--help` only, nothing started. `agy` has a per session `--remote-control`
  and `--dangerously-skip-permissions`, the same lifecycle as Claude Code.
  `codex` 0.121.0 has no `remote-control` subcommand at all: its remote story
  is `app-server` plus `--remote <ADDR>`, so #293's premise
  (`codex remote-control start`) does not describe the installed version.

## Decisions

Taken by the agent on 2026-10-10 under Andrea's "start the following phase
and plan", while Andrea is away; each is written so it can be reversed before
the batch that depends on it starts.

- **The second agent is Antigravity (`agy`).** It is the closest fit: a per
  session remote control flag, a permission skipping flag, an interactive TUI
  in a pane. It teaches the interface without also teaching a daemon. If task
  265 finds it cannot run unattended in a pane, the phase re-shapes to
  `gemini` rather than widening the interface for a daemon.
- **The agent is chosen per root, in the config file** (#292). A root table
  gains `agent = "<id>"`, defaulting to the one agent configured today. The
  start route's contract does not change, no page sends an agent, and a
  project's agent is known from its root, which is what derivation needs to
  ask the right package. A choice at start from an allowlist is a different
  contract change; it goes to Backlog as #292 rewritten, with this as the
  reason.
- **Which agents exist is a config file table, read once.** Each entry names
  an identifier, the package it uses and its binary; `--agent-binary` keeps
  meaning the binary of the default agent, so nothing an operator runs today
  changes. The package name is a closed set in code, never a module path from
  the file: the file selects among packages, it cannot load one.
- **No daemon** (#293). Hitchrail does not own a long lived child that is not
  a session in this phase. #293 closes with the codex evidence above; a codex
  package is a Backlog ticket to be argued when its remote story is stable.
- **Plugin updates stay a capability of an agent, not of every agent.** The
  interface says whether an agent has one; the page and the CLI offer it for
  the agents that do. Only Claude Code does today.
- **#296 closes**: tests ship with each task under the testing rules, and the
  fake agent the e2e tier already uses gets a second shape, task 267.

## Fails if

Agent drafted on 2026-10-10, as in Phase 28. It is the end of the phase and
it failed badly. What happened?

1. **The interface was designed before the second agent was looked at.** A
   Protocol was written from Claude Code alone, then bent to fit `agy`, and
   the bends leaked vendor knowledge out of the packages. So task 265 records
   `agy`'s real shapes on a private tmux server BEFORE task 263 fixes the
   interface, and the interface is the union of what the callers already ask,
   nothing more.
2. **One agent's orphan was derived as the other's.** Both spell the marker
   `--remote-control`, a detached `agy` read as a detached Claude Code in the
   same folder, and its Kill signalled the wrong process. So each package owns
   its own argv tail, `find_detached` asks every configured package, and a
   test puts both agents' orphans in one table.
3. **The quarantine leaked.** A vendor name, a key sequence or a flag reached
   `engine`, `derive`, `cli`, the API or the page. So the grep and AST guards
   that hold `claude_ipc` are generalised to every agent package before the
   second one lands, and seen failing on a planted leak.
4. **The config file became a loader.** An `agent` value was turned into an
   import, or a path, or a template. So the package is chosen from a closed
   mapping in code, and an unknown value is a startup refusal with a test.
5. **Claude Code broke on the way.** Moving `claude_ipc` behind the interface
   changed a stop, a wrap up or a derivation that worked. So task 263 is a
   move with no behaviour change, and the full default suite plus the live
   tiers run green before and after it, compared by count.
6. **`agy` could not be watched for real.** Its account, keyring or first run
   prompt made an unattended start impossible, and the phase closed on a
   fake. So task 265 is the gate: a real `agy` started and stopped politely
   in a throwaway root on a private tmux server, never a real projects root,
   or the phase re-shapes to `gemini` with that recorded.
7. **The S25 watch slipped a fourth time.** So it is the close task, held on
   the S25 in Chrome only, and the phase does not close done without it.
8. **The review loop ran away.** One review per batch, under the bounded
   loop; lows to Backlog.

## Expected work

Tasks continue from Phase 28's 258. Batch 1 needs no decision and can start
at once; batches 3 onward run in order.

### Batch 1: the open `claude_ipc` findings, tasks 259 to 261

- [x] **259, #456.** A trusted ancestor's trust is inherited, read by
  `folder_is_trusted` rather than `trusted_folders`, with the sibling whose
  name a string prefix matches pinned untrusted; tests in
  `test_claude_ipc.py` and `test_engine.py` (b29c214, 21ade62).
- [x] **260, #460.** A skipped group is counted in rows rather than
  listings, so the repeated plugin's updated first row reads; the version
  guard's `new is None` half pinned by asserting the versions (e24d4be).
- [x] **261, #491.** A completed run whose second listing fails marks each
  updated row "not confirmed" in the detail the record already carries, on
  stderr and on the run record, so the return shape did not move at all
  (5f813a6).

### Batch 2: the decision written down, task 262

- [x] **262, #334.** Design section 3.1 says built, with the shape above;
  `docs/versioning.md`'s 1.0 terms name it; every Phase 23 ticket rewritten
  or closed (done at planning, below; 532c6d4).

### Batch 3: the seam, tasks 263 and 264

- [x] **263, #290.** An agent interface (a Protocol) whose members are the
  calls the engine layer makes today, `claude_ipc` behind it unchanged, and
  the quarantine guards generalised to every agent package. No behaviour
  change; suites compared by count before and after (0dc5998).
- [x] **264, #290.** The `[agents]` table and the per root `agent` key,
  refused at startup when unknown; derivation and the engine ask the root's
  agent; `find_detached` asks every configured agent. `docs/api.md` and the
  config view name the agent identifier, never a vendor. Derivation asks
  every configured agent in BOTH directions, the root's first, so a changed
  `agent` key cannot hide one still running.

### Batch 4: the second agent, tasks 265 to 267

- [x] **265.** `agy`'s real shapes recorded on a private tmux server in a
  throwaway root: process argv, the polite stop, the input box, a question,
  trust. The gate for the phase (Fails if 6). Recorded on #294, on 1.2.14
  and 1.3.3; no question could be raised, so that one is unknown.
- [x] **266, #294.** The `agy` package (`agy_ipc/`): start, derive, stop and
  wrap up through the interface; its marker is `--add-dir=<folder>`, since
  `--remote-control` is in both agents' argv. A question is unknown, so its
  answer keys refuse. Every action follows the agent derivation found running,
  not the root's (8ab756a and the owner fix after it). The flag skips agy's
  trust prompt: #504.
- [x] **267.** A fake `agy` beside the fake Claude Code in the e2e and
  live_tmux tiers, so a root of each runs in one test. The live_tmux half is
  `test_live_tmux_agents.py`: start, polite stop, wrap up, stale and
  detached for a root of each on one engine, with agy's stand in refusing
  Claude Code's keys. The e2e half is `tests/e2e/test_agents.py`, with 268.

### Batch 5: what a person sees, tasks 268 and 269

- [x] **268.** The page names a row's agent when more than one is
  configured, and offers plugin updates only for agents that have them. The
  update still runs the default agent's binary alone, so a second Claude Code
  agent's plugins are named as not updated from the page rather than
  updated: #505.
- [x] **269, #295.** README and the operator docs: the `[agents]` table, the
  per root key, and how a new agent package is added. README's "More than
  one agent" and `docs/tech-guidelines.md` section 3.1; every `toml` block in
  the published docs is read by the loader in `test_agent_config.py`.

### Close, task 270

- [ ] **270, MOVED OUT to Phase 16 as #468 and #485.** The S25 watch, Chrome
  only, at 360 CSS px: Phase 24's bar, Phase 26's Restart, Phase 28's countdown
  and this phase's agent name, on a throwaway root. Watched on the Pixel
  instead on 2026-10-10 (#485): the bar on one line, the chips, Restart on
  each agent sending the closing message, then the exit, then one start, and
  the plugin scope. The S25 was not reachable, its fourth slip.

## Out of scope

- A page choosing the agent at start (#292, Backlog).
- Any daemon, and codex (#293 closed; Backlog when argued again).
- Command templates or any agent setting a request can write.
- Recording which agent a session was across a reboot: Phase 16, which this
  phase was placed before so it can.

## Done looks like

- [x] An `agy` root and a Claude Code root on one Hitchrail: each starts,
  stops politely, wraps up and is derived running, stale, detached and
  stopped, on the live_tmux tier (`test_live_tmux_agents.py`) and by hand on
  a throwaway root (the Pixel watch, #485).
- [x] No vendor name outside the agent packages, enforced by guards seen
  failing.
- [x] Nothing an agent runs comes from a page: the start route unchanged.
- [x] #334's acceptance met.
- [ ] The S25 watch held: MOVED OUT to Phase 16, #468 and #485.
- [x] Roadmap says done, milestone closed, `check-phases.sh` passes

## Close, 2026-10-10: re-shaped

Tasks 259 to 269 landed: the Agent protocol, the `[agents]` table and the
per root `agent` key, the `agy_ipc` package, a root of each agent on one
engine over a real tmux, the agent chip and the plugin scope on the page, and
the docs. The S25 watch moved out a fourth time; the Pixel watch stands in
for it and cannot see the S25's 360 px width or its font scale.

What the plan did not expect: the security review of the agy package found
that agy's `--add-dir=` answers agy's trust prompt for every folder (#504).
It needs Andrea's choice among three options and, because agy is in
`## Unreleased`, it holds the next release whichever phase that is. It goes
to Phase 16, the next phase, rather than the Backlog for that reason, and the
S25 tickets go with it. Filed for later: #505 (a second Claude Code agent's
plugins), #506 (the wait dialog's title), #507 (the marker's agent required).

Reviews: round 1 found the high this phase most needed caught: every action
went through the ROOT's agent, so a root switched to agy while Claude Code
ran typed agy's keys into Claude Code's pane; fixed in `f3fb188` and
`cfc0025`. Round 2 reviewed only those fixes and found no defect in them,
one medium (six of the sites they changed had no test that failed on a
revert; pinned in `2228f9f`, each test seen failing on its own site) and two
lows (#507, and a stale comment fixed in `2228f9f`). No high, so the loop
stopped after round 2 by rule. Zero rounds found a defect in a prior fix.
