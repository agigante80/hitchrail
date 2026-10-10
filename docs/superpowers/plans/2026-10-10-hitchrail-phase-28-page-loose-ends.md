# Phase 28: The page's loose ends

**Objective: every bar behaviour Phase 24 shipped has a test that fails when
it is reverted, the page says what the server actually refused and what a
wrap up is doing, and the S25 has watched it at 360 CSS px.**

**Written 2026-10-10,** from the roadmap block and the nine tickets in the
milestone, each read against the tree at `c4d5a04` (0.17.0).

## Goal

Phase 24 closed as re-shaped because neither phone was reachable, and its
reviews left lows on the page. Phase 26 added Restart, also unwatched on the
S25. Phase 27's watch found that the page misreads one of its refusals. This
phase fixes what the page says, pins what it does, and holds both watches
once, here, before Phase 23 adds the agent choice to the same page.

## What this phase is actually about

Two things a person reads are false. The grant page calls an
`origin_rejected` 403 a wrong key, so a person retypes a correct token, and
the banner offers that refused link (#493). A wrap up reads `stopping` for up
to five minutes, so a working stop looks like a hang (#474). Around them sit
comments that are false on the target browser (#466, #461), a theme toggle
that goes stale under System (#466), and behaviours whose tests stay green
with them reverted (#465, #462, #461).

**Checked against the tree on 2026-10-10.** All seven code tickets still
describe the code. #466 item 3 undercounts: `logs.js` also keeps its own
`THEME_KEY` copy and start up block, so both fold into `theme.js`.

**Decisions:**

- **#467, by Andrea on 2026-10-10: keep it.** The empty search create offer
  stays off while any root has the name. The reason is written beside
  `canCreate`, and its guard gets the test #465's round 2 comment asks for.
- **#493: the banner leaves out a withheld host** rather than printing it
  with advice, since the startup block two lines later already says what to
  browse instead. The grant page shows the server's own message for
  `origin_rejected`; a wrong or missing key keeps the one sentence, so the
  page is still not an oracle about which.
- **#474: the countdown is counted on the client from the moment the row
  arrived**, from `stop_age_s`, as `docs/api.md` prescribes; never from the
  phone's clock against a server timestamp.
- **#462, agent taken: the wide layout keeps the shared line** (it has room)
  but the name no longer shrinks: the chips give way first. A 1280 px case on
  the busy fixture asserts no name is clipped.

## Fails if

Agent drafted at Andrea's request on 2026-10-10. It is the end of the phase
and it failed badly. What happened?

1. **The new tests passed on the browser's defaults.** Like the focus ring
   #465 found, an assertion read something Chromium supplies anyway, so it
   pins nothing. So every test this phase adds for a behaviour is seen
   failing once with that behaviour reverted, bytecode caching off, and the
   revert named in the commit.
2. **The S25 watch was skipped a third time.** Everything else closed and the
   watch moved out again. So the watch is the close task, it is held on the
   S25 in Chrome only, and the phase does not close done without it.
3. **The countdown lied.** It drifted on the client clock, went negative,
   restarted at the full timeout after a reload, or broke the row's one line
   at 360 px. So the arithmetic is a pure function with unit tests, and the
   e2e test reloads mid wrap up at 360 px and at 1280 px.
4. **The grant page became an oracle.** Showing the server's message for one
   code was widened to every refusal, and the page started telling a wrong
   key from a missing one. So the e2e test asserts the bad key sentence is
   unchanged for a wrong key, beside the new one for a withheld origin.
5. **app.css grew past its cap.** Four batches touch it. So each batch
   checks `WEB_CAPS` before committing, and a cap that has to rise says why.
6. **The review loop ran away.** One review per batch, under the bounded
   loop; lows to Backlog.

## Expected work

Tasks continue from Phase 27's 251. The batches run one after another, since
three of them edit `app.css`. Each batch is reviewed once at its end.

### Batch 1: what the page tells the person, tasks 252 and 253

- [x] **Task 252, #493.** `banner` skips a host whose plain origin is
      withheld; the grant page shows the server's message for
      `origin_rejected` and keeps the one sentence for a bad key. A banner
      test with `localhost.localdomain` withheld; an e2e test of the grant
      page on a withheld origin, and of a wrong key beside it.
      Landed: banner filter in `cli.py` (under its cap), `grant()` returns the
      sentence to show, tests in `test_cli.py` and `e2e/test_token.py`.
- [x] **Task 253, #474.** A `closing` row's chip reads "wrapping up" with the
      time left, "sending the exit" at zero, and its Stop says it skips the
      wait; `exiting` keeps `stopping`. A pure time left function with unit
      tests; e2e at 360 and 1280 px, reload included.
      Landed: `wrapup.js` (pure) and `wrapup_tick.js`, the chip in `row.js`,
      "Exit now" in `actions.js`; the table runs in the browser tier because
      this project has no JavaScript runner.

### Batch 2: comments and guards that are true, tasks 254 and 255

- [x] **Task 254, #466.** The cut root line's comment says what Android
      Chrome does (no tooltip; the chips and settings carry it); the header
      toggle follows a `prefers-color-scheme` change under System, with an
      e2e test that emulates the change; `settings.js` and `logs.js` read the
      theme only through `theme.js`.
      Landed: the comment is true, `followSystemTheme` in `theme.js`, both
      pages apply the theme through it, e2e tests in `test_shell.py`.
- [x] **Task 255, #461 and #467.** The `stream.js` comment says why the
      accessor exists without the false claim about live bindings; the asset
      import check reads every import form; `publish.yml` asserts its glob
      found files. #467's decision written beside `canCreate`.
      Landed: `_imported_urls` in `test_api.py` with its own test, the
      `publish.yml` guard, the `stream.js` and `search.js` comments, the
      `canCreate` decision.

### Batch 3: tests that fail when reverted, tasks 256 and 257

- [ ] **Task 256, #465.** All six: the bar's own focus ring, the title link
      from `/`, the footer with no settings link and `data-settings-link`
      exactly once, the theme state across pages both ways, the search clear
      with the counter and a chosen chip on two roots, and `canCreate`'s
      guard. Each seen failing with its behaviour reverted.
- [ ] **Task 257, #462.** The name does not shrink at 900 px and wider; a
      1280 px case in `test_layout.py` on the busy fixture.

### The close, task 258

- [ ] **Task 258, #468 and #485.** On the S25 at 360 CSS px, Chrome only,
      against a private root (never the real one): the bar, the settings
      gear, the themes, the busy list, Restart, a wrap up's countdown, and
      the grant page. Nothing on the phone changed; no screenshot of it in a
      ticket or a commit.

## Done looks like

- [ ] Every task ticked, or marked MOVED OUT or NOT BUILT with an issue number
- [ ] Each bar behaviour in #465 has a test seen failing with it reverted
- [ ] The layout is tested at 1280 px as well as 360 and 320
- [ ] #467 is decided and written beside `canCreate`
- [ ] The page has been watched on the S25 at 360 px
- [ ] Roadmap says done, milestone closed, `check-phases.sh` passes

## Out of scope

**Showing the cut root line's full text on a phone.** The comment becomes
true instead; the chips and settings already carry the text.

**The agent choice at start (#292).** Phase 23.

**The log filter's coverage (#490).** Backlog, by Andrea on 2026-10-10.
