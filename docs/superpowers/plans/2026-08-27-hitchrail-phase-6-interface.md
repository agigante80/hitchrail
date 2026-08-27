# Phase 6: The interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The browser interface the design canvas draws, served from the API
built in Phase 5, and the browser tier that proves it does what the canvas says.

**Architecture:** One page, no build step. `server.py` gains a route that serves
`web/index.html` and its two assets. The page talks to the API that already
exists and renders from the SSE stream that already works. Nothing in `src/`
outside `server.py` and `web/` changes, and the engine does not learn that a
browser exists.

**Tech Stack:** Plain HTML, CSS and ES modules, no framework and no bundler.
Playwright for the browser tier, a development dependency only. The three
runtime dependencies do not change.

**Spec:** `docs/superpowers/specs/2026-08-25-hitchrail-design.md`, sections 6
and 7. The canvas sources in `docs/design/` are the reference for anything the
spec describes in words: `Main.dc.html` is the phone, `States.dc.html` is the
six edge states, `Desktop.dc.html` is the wide layout.

---

## Global Constraints

Copied from the spec and `.claude/CLAUDE.md` rather than summarised, because a
task's requirements implicitly include this section.

- **No build step.** `web/` holds `index.html`, `app.js` and `app.css`, served
  as they are. A bundler, a transpiler or a `node_modules` in this repository
  is a change to the distribution story in section 9.1, not a convenience.
- **Three runtime dependencies:** `starlette`, `uvicorn`, `sse-starlette`. A
  fourth needs a written justification. Playwright is a DEV dependency and does
  not touch that budget.
- **Nothing depends on hover.** Touch and pointer get identical affordances.
- **44px minimum hit target** on every control.
- **Dark theme is a first class requirement**, not a later addition.
- **No em dashes or en dashes** anywhere, including the interface copy.
- The engine layer must not import `server`, `cli`, `starlette`, `uvicorn` or
  `sse_starlette`. `uv run lint-imports` enforces it and `web/` is not Python.
- Tests are hermetic outside the `live`, `live_tmux` and new `e2e` tiers.

## Phase 6 file structure

| File | Responsibility |
|---|---|
| `src/hitchrail/web/index.html` | the single page: markup and nothing else |
| `src/hitchrail/web/app.css` | the palette, the type, the two themes, the layout |
| `src/hitchrail/web/app.js` | fetching, rendering, the flows, the stream |
| `src/hitchrail/server.py` | gains the static routes; everything else unchanged |
| `tests/e2e/conftest.py` | the server, the private tmux, the fake agent shim |
| `tests/e2e/test_*.py` | the browser tier, one file per flow |

`web/` sits INSIDE the package rather than beside it, because `uvx hitchrail`
installs a distribution and a directory outside the package is not in it. That
is the same reason `src/` layout was chosen in section 9.2.

## What the design already decided

Extracted from the canvas so no task has to re-derive it, and so a reviewer can
check the page against a table rather than against an artboard.

### Palette, taken from the artboard sources

| Token | Light | Role |
|---|---|---|
| `--ground` | `#F3ECE1` | page background |
| `--surface` | `#FFFDFA` | card and row |
| `--surface-alt` | `#FBF7F1` | inset, drawer |
| `--line` | `#E8DFD1` | borders and rules |
| `--ink` | `#2E251C` | primary text |
| `--ink-soft` | `#4A3E31` | secondary text |
| `--muted` | `#6B5A48` | labels |
| `--muted-2` | `#806E5A` | machine values |
| `--muted-3` | `#A2917D` | disabled |
| `--accent` | `#A8642E` | saddle tan, primary action |
| `--accent-hover` | `#8C5124` | pressed |
| `--accent-light` | `#D08A4A` | accent on dark |
| `--running` | `#5C7F4F` | sage, a live session |
| `--running-dark` | `#45663A` | sage pressed |
| `--danger` | `#9A3B2B` | brick, destructive |
| `--danger-tint` | `#E3C6C0` | destructive background |
| `--warn` | `#B07D2A` | memory pressure |
| `--warn-tint` | `#FBF0DC` | memory background |
| `--ground-dark` | `#362D24` | the dark theme ground |

Dark theme is a token swap on `:root`, driven by `prefers-color-scheme` AND an
explicit toggle, never by a second stylesheet.

### Type

`Zilla Slab` for display, `Karla` for body, `IBM Plex Mono` for machine values:
pids, memory figures, uptimes and log output. Loaded from Google Fonts with a
real fallback stack on every face, because a machine on a LAN with no route to
the internet must still render.

### The six states the canvas says decide the design

From `States.dc.html`, in its own words, because these are the requirements:

1. **Memory, soft threshold.** "Tight on memory". Names the project, states
   what would be left, and offers `Cancel` and `Start anyway`.
2. **Memory, hard floor.** "Not enough memory". States what is free, says
   Hitchrail will not start into that, and points at the largest session with a
   `Stop it` control rather than leaving the person to work it out.
3. **Detached.** "pid 24188 - no tmux session". Offers `Leave it alone` and
   `Kill pid 24188`. The pid is in the button, because the thing being killed is
   a pid rather than a session.
4. **Link pending, and a dead start.** A running row can say "waiting for its
   link"; a start that exited says "died" with "Started, then exited after 3
   seconds" and a `Read what it printed` control.
5. **Reached over the network.** The token screen: a masked field, `Unlock`, and
   the sentence "Anyone with this key can run code on that machine as you."
6. **After dark.** The whole page in dark theme with a running count.

### The phone flows, from `Main.dc.html`

**The filter is a tab strip with counts**, in both artboards, and it was nearly
missed because it appears as `{{ tab.label }}` rather than as literal text:

```js
mkTab('all', 'All', all.length)
mkTab('running', 'Running', runNames.length)
mkTab('stopped', 'Stopped', all.length - runNames.length)
```

Three tabs, each carrying its own count, and `Stopped` is defined as everything
that is not running rather than as the `stopped` STATE. That matters: a `stale`
or `detached` row is not running, so it belongs under `Stopped` even though its
`data-state` says otherwise. Filtering on the state string would hide exactly
the two rows a person most needs to find.

**The controller row's badge reads `controller`**, from
`badge: live && live.controller ? 'controller' : 'running'`. An earlier draft
of this plan said "a lock", which is the affordance, not the label.

Header (`hitchrail`, the root path, `New`), search with an empty state
("Nothing matches" / "No folder here is called that."), rows with `Open` and
`Start`, the stop sequence (`Stop {name}?` with `Cancel` and `Stop`, then
`Stopping {name}` with `Do not wait, kill it now` and `Hide, keep stopping`,
then `No answer from {name}` with `Leave it` and `Kill it`), the log drawer
("last 40 lines of the pane"), and the new folder sheet.

**The stop sequence escalates, it does not branch.** The confirm step offers
only Cancel and Stop. Kill appears once the graceful attempt is under way,
phrased as impatience rather than as an alternative, and stays available for
the whole wait. On a phone the destructive path must never sit under the thumb
at the same weight as the safe one.

## Phase 6 tickets, in dependency order

| Ticket | Task | Note |
|---|---|---|
| #38 | 18, the browser tier | FIRST, with the page skeleton, so every task after it adds tests to a harness that exists rather than one arriving at the end |
| #53 | 18, the page and the palette | the shell, the tokens, both themes, the static routes |
| #54 | 19, the list | rows, the four states, search, the protected lock |
| #55 | 20, stopping | confirm, escalation, the timeout, kill |
| #56 | 21, starting | the two memory refusals, the new folder sheet, the memory footer |
| #57 | 22, live updates | SSE, and reconnection after a backgrounded tab |
| #21 | 23, the fragment grant | needs the page, because only JavaScript can read a fragment |

---
### Task 18: The page, the palette, and the browser tier that will prove it

**Files:**
- Create: `src/hitchrail/web/index.html`, `src/hitchrail/web/app.css`, `src/hitchrail/web/app.js`
- Modify: `src/hitchrail/server.py` (the static routes)
- Create: `tests/e2e/conftest.py`, `tests/e2e/test_shell.py`
- Modify: `pyproject.toml` (the `e2e` marker, the Playwright dev dependency, package data)

**Interfaces:**
- Consumes: `create_app(engine, config, bus)` (Task 15), the `/api/*` routes.
- Produces: `GET /` serving the page and `GET /app.css`, `GET /app.js`; an
  `e2e` pytest marker; `tests/e2e/conftest.py` exposing Playwright's `page` and
  the `server` fixture below.

**The `server` fixture, in full**, because every task after this one selects on
it and a fixture invented per task is four incompatible harnesses:

| Member | Contract |
|---|---|
| `server.base` | `str`, `http://127.0.0.1:<port>`, no trailing slash |
| `server.root` | `pathlib.Path`, the temporary project root |
| `server.seed(**kw)` | set up state BEFORE the page loads. `running`, `stale`, `detached`, `stopped`, `unsupported` take lists of names; `self_project` a name; `available_mb` an int the fake meminfo reports; `stop_timeout` seconds; `ignores_graceful_stop` and `agent_exits_immediately` change how the shim behaves |
| `server.kill(name)` | stop a session from OUTSIDE the browser, which is what makes the stream tests about the stream |
| `server.is_running(name)` | `bool`, asked of the machine rather than the page |
| `server.start_with_token(token)` | restart the server with a token configured |
| `server.access_log` | `list[str]`, the `uvicorn.access` lines captured so far |
| `server.stop_serving()` | kill the server while the page is open, for the dropped stream test |

**And the DOM contract**, for the same reason. These attributes are the seam
between the page and its tests, so they are declared once here rather than
discovered by grepping:

| Attribute | On | Values |
|---|---|---|
| `data-project` | the row | the project name, exactly as the API returns it |
| `data-state` | the row | `running`, `stale`, `detached`, `stopped` |
| `data-stopping` | the row | `true` while a graceful stop is in flight |
| `data-protected` | the row | `true` for the controller session |
| `data-stream` | the shell | `open`, `down` |
| `data-theme` | `:root` | `light`, `dark`, absent when following the system |
| `data-mem-pct` | the footer | the percentage of memory in use, as an integer |

**Why the harness lands with the skeleton.** #37 marked the integration tier
before it tripled, and the same argument applies harder here: a browser tier
added after five flows exist is five flows of retrofitting, and the tier that
proves the interface should exist before the interface does.

- [ ] **Step 1: Add the marker, the dev dependency and the package data**

The marker joins the three that exist, and `tests/test_tiers.py` already
asserts the tiers partition, so `e2e` must be added to its `TIERS` set in the
same commit or that test fails.

```toml
markers = [
  "integration: drives the real Starlette app through httpx.ASGITransport, no socket",
  "live: binds a real loopback socket on an ephemeral port",
  "live_tmux: drives a real tmux server on a private socket",
  "e2e: drives a real browser against a real server; needs `playwright install chromium`",
]
```

`web/` must ship in the wheel. Without this `uvx hitchrail` installs a package
whose page is missing, and the failure is a 404 on the one route a person opens
first.

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/hitchrail"]
artifacts = ["src/hitchrail/web/*"]
```

- [ ] **Step 2: Write the failing shell test**

```python
# tests/e2e/test_shell.py
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_the_page_loads_and_names_the_root(page: Page, server) -> None:
    page.goto(server.base)
    expect(page.get_by_role("heading", name="hitchrail")).to_be_visible()
    expect(page.get_by_text(str(server.root))).to_be_visible()


def test_the_assets_are_served_and_are_not_a_404_page(page: Page, server) -> None:
    """A 404 body still renders as a page, so `to_be_visible` alone would pass
    against a missing stylesheet. Assert the response, not the appearance."""
    css = page.request.get(f"{server.base}/app.css")
    js = page.request.get(f"{server.base}/app.js")
    assert css.status == 200 and "text/css" in css.headers["content-type"]
    assert js.status == 200 and "javascript" in js.headers["content-type"]


def test_nothing_on_the_page_is_smaller_than_the_touch_target(page: Page, server) -> None:
    """44px, from section 7. Measured rather than eyeballed, because this is
    the requirement a stylesheet change breaks silently."""
    page.goto(server.base)
    page.set_viewport_size({"width": 390, "height": 844})
    small = page.evaluate("""() =>
        [...document.querySelectorAll('button, a, [role=button]')]
            .map(el => ({ t: el.textContent.trim().slice(0, 24), h: el.getBoundingClientRect().height }))
            .filter(x => x.h > 0 && x.h < 44)
    """)
    assert small == [], f"controls under the 44px minimum: {small}"


def test_the_dark_theme_is_a_token_swap_not_a_second_stylesheet(page: Page, server) -> None:
    """Dark is first class, so it must be one stylesheet and a media query."""
    page.emulate_media(color_scheme="dark")
    page.goto(server.base)
    ground = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert ground == "rgb(54, 45, 36)", f"dark ground is {ground}"
    # One stylesheet, not two. A second sheet loaded for dark is the thing
    # section 7 rules out by calling dark first class, and it decays the moment
    # somebody edits only one of them.
    sheets = page.evaluate("() => document.styleSheets.length")
    assert sheets == 1, f"{sheets} stylesheets; dark must be a token swap"


def test_the_toggle_wins_over_the_system_preference(page: Page, server) -> None:
    """Both directions. A page that follows `prefers-color-scheme` and ignores
    an explicit choice is a page that fights the person using it."""
    page.emulate_media(color_scheme="light")
    page.goto(server.base)
    page.get_by_role("button", name="Dark").click()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(54, 45, 36)"
    page.emulate_media(color_scheme="dark")
    page.get_by_role("button", name="Light").click()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(243, 236, 225)"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest -m e2e -v`
Expected: FAIL, every test, on a 404 for `/`.

- [ ] **Step 4: Write the harness**

```python
# tests/e2e/conftest.py
"""The browser tier: a real server, a private tmux, and a fake agent.

A fake `claude` shim rather than the real one, for the reason the live_tmux
tier uses a private socket: a test that starts a real agent is a test that
costs money, needs credentials, and cannot run in CI. The shim is a shell
script that prints a line and sleeps, which is enough to be `running`, enough
to have a pane to capture, and enough to be stopped.
"""
```

The shim writes a marker line so the log drawer has something to show, then
waits. It must respond to the graceful stop the way the real agent does, which
means exiting on `/exit` arriving on stdin.

- [ ] **Step 5: Write the page, the palette and the routes**

`index.html` carries markup and no inline style or script. `app.css` defines
the tokens from the table above on `:root`, redefines them under
`@media (prefers-color-scheme: dark)` and under `[data-theme="dark"]`, so the
toggle wins in both directions. The routes are two `FileResponse` handlers and
one for the page, with the same middleware as everything else: the page is
behind the token like every other route, which is what makes the token screen
in Task 23 reachable at all.

- [ ] **Step 6: Run to verify passing, then the gates**

Run: `uv run pytest -m e2e -v` then the five gates.

- [ ] **Step 7: Commit**

```bash
git add src/hitchrail/web tests/e2e pyproject.toml src/hitchrail/server.py
git commit -m "feat(web): the page, the palette, and the browser tier (#53, #38)"
```

---
### Task 19: The list, the four states, search, and the protected lock

**Files:**
- Modify: `src/hitchrail/web/app.js`, `app.css`, `index.html`
- Create: `tests/e2e/test_list.py`

**Interfaces:**
- Consumes: `GET /api/projects` returning `{projects, unsupported, unsupported_total, memory}`.
- Produces: the rendered list; a `data-state` attribute per row, which every
  later task and every test selects on.

**Row asymmetry is the whole mobile argument**, per the canvas annotation. A
running row is tall because it holds three actions. A stopped row is one line
with one button, so the other forty five stay scannable with a thumb. A design
that makes both rows the same height has lost the argument, so the test
measures both.

- [ ] **Step 1: Write the failing tests**

```python
# tests/e2e/test_list.py
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_every_derived_state_renders_as_itself(page: Page, server) -> None:
    """All four from section 4.1. `detached` is the one a naive tool gets
    wrong, so it is drawn with its pid and never silently reconciled."""
    server.seed(running=["vessel"], stale=["koala"], detached=["forge-kit"])
    page.goto(server.base)
    expect(page.locator('[data-project="vessel"]')).to_have_attribute("data-state", "running")
    expect(page.locator('[data-project="koala"]')).to_have_attribute("data-state", "stale")
    expect(page.locator('[data-project="forge-kit"]')).to_have_attribute("data-state", "detached")
    expect(page.locator('[data-project="forge-kit"]')).to_contain_text("no tmux session")


def test_a_running_row_is_taller_than_a_stopped_one(page: Page, server) -> None:
    """The canvas annotation, asserted. Three actions against one button."""
    server.seed(running=["vessel"], stopped=["long-hyphenated-name"])
    page.goto(server.base)
    tall = page.locator('[data-project="vessel"]').bounding_box()["height"]
    short = page.locator('[data-project="long-hyphenated-name"]').bounding_box()["height"]
    assert tall > short, f"running {tall} is not taller than stopped {short}"


def test_the_controller_session_shows_a_lock_and_no_stop(page: Page, server) -> None:
    """Section 7: refusing after the tap is worse than not offering the tap.
    The API answers 423, and an interface that lets you reach a 423 has already
    failed the person holding the phone."""
    server.seed(running=["hitchrail"], self_project="hitchrail")
    page.goto(server.base)
    row = page.locator('[data-project="hitchrail"]')
    expect(row).to_have_attribute("data-protected", "true")
    expect(row.get_by_role("button", name="Stop")).to_have_count(0)


def test_search_filters_and_says_so_when_nothing_matches(page: Page, server) -> None:
    server.seed(stopped=["vessel", "koala", "media-sync"])
    page.goto(server.base)
    page.get_by_role("searchbox").fill("mus")
    expect(page.locator("[data-project]")).to_have_count(1)
    page.get_by_role("searchbox").fill("zzz")
    expect(page.get_by_text("Nothing matches")).to_be_visible()
    expect(page.get_by_text("No folder here is called that.")).to_be_visible()


def test_the_tabs_filter_and_carry_their_own_counts(page: Page, server) -> None:
    """Three tabs from the canvas: All, Running, Stopped, each with a count."""
    server.seed(running=["vessel"], stopped=["koala", "media-sync"])
    page.goto(server.base)
    expect(page.get_by_role("tab", name="All")).to_contain_text("3")
    expect(page.get_by_role("tab", name="Running")).to_contain_text("1")
    expect(page.get_by_role("tab", name="Stopped")).to_contain_text("2")
    page.get_by_role("tab", name="Running").click()
    expect(page.locator("[data-project]")).to_have_count(1)


def test_stopped_means_not_running_rather_than_the_stopped_state(page: Page, server) -> None:
    """`Stopped` is `all.length - runNames.length` in the canvas, not a state
    match. A stale or detached row is not running, so it belongs here: those
    are the two rows a person most needs to find, and a state string filter
    would hide both."""
    server.seed(running=["vessel"], stale=["koala"], detached=["forge-kit"])
    page.goto(server.base)
    page.get_by_role("tab", name="Stopped").click()
    expect(page.locator('[data-project="koala"]')).to_be_visible()
    expect(page.locator('[data-project="forge-kit"]')).to_be_visible()
    expect(page.locator('[data-project="vessel"]')).to_have_count(0)


def test_a_folder_that_cannot_be_a_project_is_accounted_for(page: Page, server) -> None:
    """#7: dropping them silently made a folder called `my app` look like one
    Hitchrail could not see. The count is the true one, not the shown one."""
    server.seed(stopped=["vessel"], unsupported=["my app"])
    page.goto(server.base)
    expect(page.get_by_text("my app")).to_be_visible()
    expect(page.locator('[data-project="my app"]')).to_have_count(0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -m e2e tests/e2e/test_list.py -v`
Expected: FAIL, nothing renders a row yet.

- [ ] **Step 3: Implement the list**

Render from `GET /api/projects`. One function per row state rather than one
function with four branches, because the row shapes genuinely differ and a
single template with conditionals is where the asymmetry gets lost.

- [ ] **Step 4: Run to verify passing, then the gates**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): the list, its four states, search, and the protected lock (#54)"
```

---

### Task 20: Stopping, which escalates rather than branching

**Files:**
- Modify: `src/hitchrail/web/app.js`, `app.css`
- Create: `tests/e2e/test_stopping.py`

**Interfaces:**
- Consumes: `DELETE /api/sessions/{name}` (202), `POST /api/sessions/{name}/kill` (200).
- Produces: the confirm, in flight and timeout steps.

**This is the task the design argues hardest about**, and the one the browser
tier exists for. The sequence is over time: confirm, then a wait during which
kill is reachable, then a timeout that reports and does not escalate on its
own. No status code shows that.

- [ ] **Step 1: Write the failing tests**

```python
# tests/e2e/test_stopping.py
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_the_confirm_step_offers_only_cancel_and_stop(page: Page, server) -> None:
    """It escalates, it does not branch. A kill control at the confirm step
    puts the destructive path under the thumb at the same weight as the safe
    one, which section 7 forbids in those words."""
    server.seed(running=["vessel"])
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Stop").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Stop vessel?")
    expect(dialog.get_by_role("button", name="Cancel")).to_be_visible()
    expect(dialog.get_by_role("button", name="Stop", exact=True)).to_be_visible()
    assert dialog.get_by_role("button", name="kill").count() == 0


def test_kill_appears_once_the_wait_is_under_way_and_stays(page: Page, server) -> None:
    """Available for the WHOLE wait, phrased as impatience rather than as an
    alternative. Asserted twice with time in between, because a control that
    appears and then vanishes passes a single check."""
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Stop").click()
    page.get_by_role("button", name="Stop", exact=True).click()
    expect(page.get_by_text("Stopping vessel")).to_be_visible()
    kill = page.get_by_role("button", name="Do not wait, kill it now")
    expect(kill).to_be_visible()
    page.wait_for_timeout(3000)
    expect(kill).to_be_visible()


def test_the_wait_can_be_dismissed_without_cancelling_the_stop(page: Page, server) -> None:
    """`Hide, keep stopping`. A phone user has other rows to look at, and a
    modal that owns the screen for thirty seconds is a modal they will kill
    the app to escape."""
    server.seed(running=["vessel"], ignores_graceful_stop=True)
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Stop").click()
    page.get_by_role("button", name="Stop", exact=True).click()
    page.get_by_role("button", name="Hide, keep stopping").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator('[data-project="vessel"]')).to_have_attribute("data-stopping", "true")


def test_the_timeout_states_the_risk_before_offering_the_kill(page: Page, server) -> None:
    """Section 7: this is the moment the user is most likely to reach for the
    kill and least likely to have thought about uncommitted work."""
    server.seed(running=["vessel"], ignores_graceful_stop=True, stop_timeout=2)
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Stop").click()
    page.get_by_role("button", name="Stop", exact=True).click()
    expect(page.get_by_text("No answer from vessel")).to_be_visible(timeout=10_000)
    dialog = page.get_by_role("dialog")
    risk = dialog.inner_text().lower()
    assert "unsaved" in risk or "uncommitted" in risk or "lose" in risk, risk
    expect(dialog.get_by_role("button", name="Leave it")).to_be_visible()
    expect(dialog.get_by_role("button", name="Kill it")).to_be_visible()


def test_the_timeout_does_not_kill_by_itself(page: Page, server) -> None:
    """The engine reports and does not escalate; the interface must not do the
    escalating on its behalf. An automatic kill is a destructive action taken
    while the person was not looking."""
    server.seed(running=["vessel"], ignores_graceful_stop=True, stop_timeout=2)
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Stop").click()
    page.get_by_role("button", name="Stop", exact=True).click()
    expect(page.get_by_text("No answer from vessel")).to_be_visible(timeout=10_000)
    page.wait_for_timeout(3000)
    assert server.is_running("vessel"), "the interface killed a session nobody told it to"
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement the sequence**
- [ ] **Step 4: Run to verify passing, then the gates**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): stopping escalates rather than branching (#55)"
```

---
### Task 21: Starting, the two memory refusals, the log drawer and the new folder sheet

**Files:**
- Modify: `src/hitchrail/web/app.js`, `app.css`, `index.html`
- Create: `tests/e2e/test_starting.py`

**Interfaces:**
- Consumes: `POST /api/sessions/{name}` and `?acknowledged=1`, `GET /api/sessions/{name}/logs`, `POST /api/projects`, the `memory` block of the listing.
- Produces: the start flow, both refusal sheets, the drawer, the sheet, the footer.

**The two memory refusals are different sheets, not one with a variable.** The
soft one asks and can be overridden. The hard one refuses and offers a way out
by naming the largest session. Rendering them from one template with a boolean
is how `Start anyway` ends up on a screen that cannot start anything.

- [ ] **Step 1: Write the failing tests**

```python
# tests/e2e/test_starting.py
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_a_start_shows_the_session_without_a_reload(page: Page, server) -> None:
    server.seed(stopped=["long-hyphenated-name"])
    page.goto(server.base)
    page.locator('[data-project="long-hyphenated-name"]').get_by_role("button", name="Start").click()
    expect(page.locator('[data-project="long-hyphenated-name"]')).to_have_attribute(
        "data-state", "running", timeout=15_000
    )


def test_the_soft_floor_asks_and_can_be_overridden(page: Page, server) -> None:
    """`ram_soft` is a 409 carrying available_mb and needed_mb, and the sheet
    states what would be LEFT rather than what is needed, because that is the
    number the decision turns on."""
    server.seed(stopped=["vessel"], available_mb=3600)
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Start").click()
    sheet = page.get_by_role("dialog")
    expect(sheet).to_contain_text("Tight on memory")
    expect(sheet.get_by_role("button", name="Cancel")).to_be_visible()
    sheet.get_by_role("button", name="Start anyway").click()
    expect(page.locator('[data-project="vessel"]')).to_have_attribute(
        "data-state", "running", timeout=15_000
    )


def test_the_hard_floor_refuses_and_offers_a_way_out(page: Page, server) -> None:
    """No `Start anyway` anywhere on this sheet: 507 is not overridable, and a
    control that cannot work is worse than no control."""
    server.seed(running=["media-sync"], stopped=["vessel"], available_mb=1200)
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Start").click()
    sheet = page.get_by_role("dialog")
    expect(sheet).to_contain_text("Not enough memory")
    assert sheet.get_by_role("button", name="Start anyway").count() == 0
    expect(sheet.get_by_role("button", name="Stop it")).to_be_visible()
    expect(sheet).to_contain_text("media-sync")


def test_a_start_that_dies_says_so_and_offers_the_output(page: Page, server) -> None:
    """`start_died` is a 502 carrying the pane. "Started, then exited after 3
    seconds" is a sentence a person can act on; "failed to start" is not."""
    server.seed(stopped=["koala"], agent_exits_immediately=True)
    page.goto(server.base)
    page.locator('[data-project="koala"]').get_by_role("button", name="Start").click()
    expect(page.get_by_text("died")).to_be_visible(timeout=15_000)
    page.get_by_role("button", name="Read what it printed").click()
    expect(page.get_by_role("dialog")).to_contain_text("hitchrail-shim")


def test_the_log_drawer_shows_the_pane_tail(page: Page, server) -> None:
    server.seed(running=["vessel"])
    page.goto(server.base)
    page.locator('[data-project="vessel"]').get_by_role("button", name="Open").click()
    drawer = page.get_by_role("dialog")
    expect(drawer).to_contain_text("last 40 lines of the pane")
    expect(drawer.locator("pre")).to_contain_text("hitchrail-shim")


def test_the_new_folder_sheet_creates_and_refuses(page: Page, server) -> None:
    page.goto(server.base)
    page.get_by_role("button", name="New").click()
    page.get_by_role("textbox").fill("new-thing")
    page.get_by_role("button", name="Create").click()
    expect(page.locator('[data-project="new-thing"]')).to_be_visible(timeout=10_000)

    page.get_by_role("button", name="New").click()
    page.get_by_role("textbox").fill("../escape")
    page.get_by_role("button", name="Create").click()
    expect(page.get_by_role("dialog")).to_contain_text("name")
    assert not (server.root / "escape").exists(), "a refused creation left something on disk"


def test_the_memory_footer_reports_what_is_free(page: Page, server) -> None:
    server.seed(stopped=["vessel"], available_mb=8192)
    page.goto(server.base)
    expect(page.get_by_role("contentinfo")).to_contain_text("8.0 GB")
    # `memPct` in the canvas alongside `memLabel`: the figure and the
    # proportion, because "12.8 GB free" means nothing without the total.
    expect(page.locator("[data-mem-pct]")).to_have_attribute("data-mem-pct", "50")
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run to verify passing, then the gates**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): starting, the memory refusals, the drawer and the sheet (#56)"
```

---

### Task 22: Live updates, and reconnection after a backgrounded tab

**Files:**
- Modify: `src/hitchrail/web/app.js`
- Create: `tests/e2e/test_stream.py`

**Interfaces:**
- Consumes: `GET /api/events`, the SSE stream from Task 16.
- Produces: an `EventSource` whose events patch rows in place.

**Reconnection is the reason this tier exists.** A phone suspends a
backgrounded tab, the stream drops, and the list must be CORRECT afterwards,
not merely reconnected. `EventSource` retries on its own; what it cannot do is
tell you what changed while it was away, so the reconnect has to re-fetch the
listing rather than trust the stream to catch up.

- [ ] **Step 1: Write the failing tests**

```python
# tests/e2e/test_stream.py
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_a_change_made_elsewhere_arrives_without_a_reload(page: Page, server) -> None:
    """Two clients, or one client and a CLI. The design's whole reason for a
    stream is that the list is right without anybody refreshing it."""
    server.seed(running=["vessel"])
    page.goto(server.base)
    expect(page.locator('[data-project="vessel"]')).to_have_attribute("data-state", "running")
    server.kill("vessel")
    expect(page.locator('[data-project="vessel"]')).to_have_attribute(
        "data-state", "stopped", timeout=15_000
    )


def test_the_list_is_correct_after_the_tab_comes_back(page: Page, server) -> None:
    """The one no other tier can see. The change happens while the stream is
    DOWN, so a page that only applies events and never re-fetches shows a row
    that has been wrong since it was suspended."""
    server.seed(running=["vessel"], stopped=["koala"])
    page.goto(server.base)
    expect(page.locator('[data-project="vessel"]')).to_have_attribute("data-state", "running")

    page.evaluate("() => window.__hitchrail.stream.close()")
    server.kill("vessel")
    page.wait_for_timeout(500)
    page.dispatch_event("body", "visibilitychange")

    expect(page.locator('[data-project="vessel"]')).to_have_attribute(
        "data-state", "stopped", timeout=15_000
    )


def test_the_stream_reconnects_on_its_own(page: Page, server) -> None:
    server.seed(running=["vessel"])
    page.goto(server.base)
    page.evaluate("() => window.__hitchrail.stream.close()")
    expect(page.locator("[data-stream]")).to_have_attribute(
        "data-stream", "open", timeout=20_000
    )


def test_a_dropped_stream_is_visible_rather_than_silent(page: Page, server) -> None:
    """A list that has quietly stopped updating looks exactly like a list where
    nothing is happening, and this tool's normal state is nothing happening."""
    server.seed(running=["vessel"])
    page.goto(server.base)
    server.stop_serving()
    expect(page.locator("[data-stream]")).to_have_attribute(
        "data-stream", "down", timeout=20_000
    )
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**

`window.__hitchrail` exists so the tier can reach the stream. It is a test
seam and it is the only one: exposing the whole application state would let a
test assert on internals rather than on what a person sees.

- [ ] **Step 4: Run to verify passing, then the gates**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): live updates, and a list that is right after a reconnect (#57)"
```

---
### Task 23: The token screen, and moving the grant into a fragment

**Files:**
- Modify: `src/hitchrail/web/app.js`, `index.html`, `src/hitchrail/security.py`, `src/hitchrail/cli.py`
- Create: `tests/e2e/test_token.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `TokenMiddleware`, `GRANT_PARAM`, the banner from Task 17.
- Produces: `#token=` as the grant carrier; the token screen; the banner
  printing a fragment link.

**This closes #21, which #20 could only mitigate.** A query string is written
down by everything it passes through: the reverse proxy the README recommends
for TLS logs `$request` including the query, the `Referer` header carries it on
any outbound request, and browser history sync carries it to every signed in
device. A fragment is never sent to any server, which removes all three at
once.

**The decision, which #21 already made and this plan initially got wrong.** No
token reaches the server, so something has to be reachable unauthenticated or
there is no JavaScript to read the fragment and the flow cannot start. Two
candidates, both in the ticket:

- A dedicated `GET /grant`, a single purpose page whose only job is to read the
  fragment and post it. The rest of the app stays fully behind the token.
- The app shell served on `401` for `Accept: text/html`. One URL, nicer to
  paste.

**Build the dedicated route.** A first draft of this plan chose the shell,
reasoning about how to make one URL work, which quietly accepted the one URL
goal as the premise. The ticket had already answered it and answered it better:
the link is GENERATED, by `banner()` in `cli.py`, so its length costs nobody
anything, and a single purpose page cannot accrete. The shell exemption is the
one that gets worse over time, because every future addition to the shell
inherits it, and this project has spent two phases removing guards that eroded
exactly that way.

So: `GET /grant` is the only unauthenticated route, it serves a page with no
data on it, and `/` stays behind the token like everything else.

- [ ] **Step 1: Write the failing tests**

```python
# tests/e2e/test_token.py
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_the_fragment_never_reaches_the_server(page: Page, server) -> None:
    """The whole point. Asserted against what the server SAW, not against the
    address bar, because the address bar is what #20 already fixed."""
    server.start_with_token("s3cret")
    page.goto(f"{server.base}/grant#token=s3cret")
    expect(page.get_by_role("heading", name="hitchrail")).to_be_visible(timeout=10_000)
    assert all("s3cret" not in line for line in server.access_log), server.access_log


def test_the_grant_leaves_the_address_bar(page: Page, server) -> None:
    server.start_with_token("s3cret")
    page.goto(f"{server.base}/grant#token=s3cret")
    expect(page.get_by_role("heading", name="hitchrail")).to_be_visible(timeout=10_000)
    assert "s3cret" not in page.url, page.url


def test_the_cookie_survives_a_reload_so_the_link_is_used_once(page: Page, server) -> None:
    server.start_with_token("s3cret")
    page.goto(f"{server.base}/grant#token=s3cret")
    expect(page.get_by_role("heading", name="hitchrail")).to_be_visible(timeout=10_000)
    page.goto(server.base)
    expect(page.get_by_role("heading", name="hitchrail")).to_be_visible()


def test_the_grant_page_is_the_only_unauthenticated_route(page: Page, server) -> None:
    """`/grant` serves a page with no data. `/` does not, and neither does
    anything else: that is the whole reason for a separate route."""
    server.start_with_token("s3cret")
    expect_page = page.request.get(f"{server.base}/grant")
    assert expect_page.status == 200
    assert "text/html" in expect_page.headers["content-type"]
    for path in ("/", "/app.js", "/api/projects"):
        assert page.request.get(f"{server.base}{path}").status == 401, path


def test_the_grant_page_carries_no_project_data(page: Page, server) -> None:
    """A page reachable without a token must not name what is on the machine.
    Folder names are the thing the token protects."""
    server.start_with_token("s3cret")
    server.seed(running=["vessel"])
    body = page.request.get(f"{server.base}/grant").text()
    assert "vessel" not in body


def test_an_unauthenticated_browser_gets_the_token_screen_not_json(page: Page, server) -> None:
    """A person who opens the grant address with no fragment must see something
    they can act on. A raw JSON 401 in a browser window is a dead end."""
    server.start_with_token("s3cret")
    page.goto(f"{server.base}/grant")
    expect(page.get_by_role("dialog")).to_contain_text(
        "Anyone with this key can run code on that machine as you."
    )
    expect(page.get_by_role("button", name="Unlock")).to_be_visible()


def test_the_token_field_is_masked(page: Page, server) -> None:
    server.start_with_token("s3cret")
    page.goto(server.base)
    assert page.get_by_role("textbox").get_attribute("type") == "password"


def test_a_wrong_token_says_so_without_confirming_anything(page: Page, server) -> None:
    """A wrong token and a missing one are already indistinguishable at the
    API. The screen must not become the oracle the middleware refuses to be."""
    server.start_with_token("s3cret")
    page.goto(server.base)
    page.get_by_role("textbox").fill("wrong")
    page.get_by_role("button", name="Unlock").click()
    text = page.get_by_role("dialog").inner_text().lower()
    assert "did not work" in text or "not accepted" in text
    assert "wrong" not in text, "the screen echoed the attempt back"


def test_an_api_request_still_gets_json(page: Page, server) -> None:
    """The exemption is one ROUTE, not a content type rule. If it were
    `Accept: text/html` on any 401, the API would start answering a script
    with HTML the moment somebody sent a browser-shaped header."""
    server.start_with_token("s3cret")
    response = page.request.get(f"{server.base}/api/projects")
    assert response.status == 401
    assert "application/json" in response.headers["content-type"]
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement `/grant`, the screen, and the fragment read**

`/grant` is registered BEFORE the token middleware would refuse it, and it is
the only route with that property. It serves a page carrying the token screen
and nothing else: no project names, no memory figures, no root path. A page
reachable without a token must not name what is on the machine, and there is a
test that asserts a seeded project name does not appear in its body.

That page reads `location.hash`, posts the token to the grant endpoint, which
sets the same cookie `TokenMiddleware` already accepts, then calls
`history.replaceState` to drop the fragment and redirects to `/`.
`replaceState` rather than `pushState`, or the back button walks into a URL
that still carries the token.

- [ ] **Step 4: Update the banner and the README**

`banner()` prints `http://{host}:{port}/grant#token={token}`. The README's phone
flow, its security section and any `curl` example that shows `?token=` change
with it. `GRANT_PARAM` stays supported on the query for one release so an
operator's saved link does not break, and `docs/versioning.md` decides whether
its removal is the MAJOR that section says an operator visible change is.

- [ ] **Step 5: Run to verify passing, then the gates**
- [ ] **Step 6: Commit**

```bash
git commit -m "feat(web): the grant travels in a fragment, which no server sees (#21)"
```

---

## Self review against the design

Checked section by section after writing this plan, the way the Phase 5 plan
was.

| Design decision, section 7 | Covered by |
|---|---|
| Row asymmetry carries the mobile case | Task 19, measured rather than described |
| Nothing depends on hover | Task 18, and no `:hover` only affordance anywhere |
| 44px minimum hit target | Task 18, measured at a phone viewport |
| The controller session is visibly protected | Task 19, lock and no stop control |
| Stopping escalates, it does not branch | Task 20, four tests |
| The timeout states the risk before offering the kill | Task 20 |
| The token screen states the consequence plainly | Task 23 |
| Dark theme is first class | Task 18, a token swap under both triggers |
| Palette and type from the canvas | Task 18, the table above |

| Roadmap "done when" | Covered by |
|---|---|
| SSE reconnecting after a backgrounded tab | Task 22 |
| The stop escalation in the state the user is really in | Task 20 |
| The layout holding at a phone viewport | Task 18 |
| A forged `Host` rejected on a live socket | Already covered in Phase 2's live tier; the browser tier does not duplicate it |

**What this plan does not do**, deliberately: the Desktop artboard is a
LAYOUT of the same data at a wider viewport, not a second interface. It is one
media query in Task 18's stylesheet and it gets no task of its own, because a
task implies a separate deliverable and there is not one.

## Phase 6 exit criteria

- [ ] All five gates green on 3.11, 3.12 and 3.13, and the `e2e` tier runs in CI.
- [ ] Every flow in the design canvas works on a real phone against a real machine.
- [ ] The four derived states each render as themselves, `detached` with its pid.
- [ ] A running row is measurably taller than a stopped one at a 390px viewport.
- [ ] No control is under 44px at a phone viewport, asserted rather than eyeballed.
- [ ] The stop sequence escalates: no kill control at the confirm step, kill reachable for the whole wait, and the timeout does not kill by itself.
- [ ] The two memory refusals are different screens, and the hard one offers no override.
- [ ] The list is correct after a backgrounded tab reconnects, not merely reconnected.
- [ ] The grant travels in a fragment and no token appears in the server's access log or the address bar.
- [ ] Dark theme renders from the same stylesheet under `prefers-color-scheme` and under an explicit toggle.
- [ ] `uvx hitchrail` serves the page from the installed wheel, not from the working tree.

When these hold, write the Phase 7 plan from `docs/roadmap.md`.
