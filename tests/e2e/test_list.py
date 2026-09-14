"""#54: the list, its four states, search, the tab filter and the lock."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from playwright.async_api import Page, expect

from hitchrail import attention
from support import DEFAULT_LABEL

from .conftest import Harness, e2e_name

pytestmark = pytest.mark.e2e


async def test_every_derived_state_renders_as_itself(page: Page, server: Harness) -> None:
    """All four from section 4.1. `detached` is the one a naive tool gets
    wrong, so it is drawn with its pid and never silently reconciled."""
    server.seed(running=["vessel"], stopped=["koala"])
    await page.goto(server.base)
    await expect(
        page.locator(f'[data-project="{server.project("vessel")}"]')
    ).to_have_attribute("data-state", "running")
    await expect(page.locator(f'[data-project="{server.project("koala")}"]')).to_have_attribute(
        "data-state", "stopped"
    )


async def test_a_detached_row_names_its_pid_and_offers_nothing_that_cannot_act(
    page: Page, server: Harness
) -> None:
    """The state the design surfaces loudly and deliberately does not act on.

    Section 4.1: "`detached` is surfaced in the UI with its pid and an
    explanation. Hitchrail never silently reconciles it, because the safe
    action depends on what that agent is doing, which Hitchrail cannot know."

    **This test used to assert a `Kill pid N` button was VISIBLE**, and that is
    how #83 shipped: the control had no handler and no route behind it, and a
    test asserting appearance passed against a dead button forever. Visibility
    is not behaviour, and a test that only checks the first will pin the second
    at whatever it happens to be.

    The button is gone rather than wired. Every destructive path in this tool
    is scoped by construction, `kill_session` can only address `hr-<name>`, and
    a bare pid has no such scope. Adding the first unscoped one is a decision
    with a security argument attached, and it is #107 rather than a handler.
    """
    server.seed(detached=["forge-kit"])
    assert server.engine is not None
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")

    # The pid and the reason, which is the whole of what the design promises.
    pid = server.engine.get(server.project("forge-kit")).pid
    # **Not "no tmux session", which is what this said until #85.** Ownership
    # is read from one `list-panes -a`, which covers the server on Hitchrail's
    # own socket and nothing else, so the row can say it has not found an owner
    # and cannot say there is none.
    await expect(row).to_contain_text("no session Hitchrail can address")
    await expect(row).to_contain_text(f"pid {pid}")

    # And no control at all, because every one this row could offer either does
    # nothing or needs a power the tool does not have.
    assert await row.get_by_role("button").count() == 0, (
        "a detached row is offering a control; if it cannot act, it is #83 again"
    )


async def test_an_agent_in_another_tools_tmux_session_says_where_it_is(
    page: Page, server: Harness
) -> None:
    """#85, through the whole stack, in the state the development machine was in.

    Eight live agents rendered as orphans at once because another tool's
    sessions were on the same tmux server. Every tier below this one builds the
    pane map from a dict; this one puts a real foreign session on the real
    socket and reads what the row ends up saying.

    The row stays `detached`, because it behaves exactly like an orphan: there
    is no session of ours to type into or to kill. What changes is that it
    stops claiming the agent is unowned, which is the claim that invites
    somebody to reach for the destructive option.
    """
    server.seed(foreign=["forge-kit"])
    assert server.engine is not None
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("forge-kit")}"]')
    await expect(row).to_have_attribute("data-state", "detached")

    await expect(row).to_contain_text(f"in tmux session e2eother-{e2e_name('forge-kit')}")
    await expect(row).not_to_contain_text("no session Hitchrail can address")

    # Still nothing to tap. Knowing where the agent is does not give Hitchrail
    # a way to end it, and #107 is where that argument is had.
    assert await row.get_by_role("button").count() == 0


async def test_a_running_row_is_taller_than_a_stopped_one(page: Page, server: Harness) -> None:
    """The canvas annotation, asserted rather than described. Three actions
    against one button is the whole mobile argument."""
    server.seed(running=["vessel"], stopped=["long-hyphenated-name"])
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(server.base)
    tall = await page.locator(f'[data-project="{server.project("vessel")}"]').bounding_box()
    short = await page.locator(
        f'[data-project="{server.project("long-hyphenated-name")}"]'
    ).bounding_box()
    assert tall is not None and short is not None, "a row was not laid out"
    assert tall["height"] > short["height"], (
        f"running {tall['height']} is not taller than stopped {short['height']}"
    )


async def test_the_controller_row_is_badged_and_has_no_stop(
    page: Page, server: Harness
) -> None:
    """Refusing after the tap is worse than not offering the tap. The canvas
    is specific about the label: `controller`, not a lock glyph."""
    server.seed(running=["hitchrail"], self_project="hitchrail")
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("hitchrail")}"]')
    await expect(row).to_have_attribute("data-protected", "true")
    await expect(row.locator("[data-badge]")).to_have_attribute("data-badge", "controller")
    assert await row.get_by_role("button", name="Stop").count() == 0


# The visible empty state and the announced one deliberately use DIFFERENT
# words. `.offscreen` clips rather than hides, so both are visible to a locator,
# and two nodes carrying "Nothing matches" would put `get_by_text` below into a
# strict mode violation. It would also be read out twice. See
# `test_an_empty_list_announces_itself_once`.
async def test_search_filters_and_says_so_when_nothing_matches(
    page: Page, server: Harness
) -> None:
    server.seed(stopped=["vessel", "koala", "media-sync"])
    await page.goto(server.base)
    # A fragment of one seeded name and of no other. The previous term matched
    # a fixture name that has since been renamed, and became meaningless
    # without failing anything the non-browser suite runs: a search term that
    # matches nothing is a passing unit test and an empty list here. Any rename
    # of the seeds above has to come back to this line.
    await page.get_by_role("combobox", name="Search folders").fill("med")
    await expect(page.locator("[data-project]")).to_have_count(1)
    await page.get_by_role("combobox", name="Search folders").fill("zzz")
    await expect(page.get_by_text("Nothing matches")).to_be_visible()
    await expect(page.get_by_text("No folder here is called that.")).to_be_visible()


async def test_the_tabs_filter_and_carry_their_own_counts(page: Page, server: Harness) -> None:
    """Three tabs from the canvas, each with a count."""
    server.seed(running=["vessel"], stopped=["koala", "media-sync"])
    await page.goto(server.base)
    await expect(page.get_by_role("tab", name="All")).to_contain_text("3")
    await expect(page.get_by_role("tab", name="Running")).to_contain_text("1")
    await expect(page.get_by_role("tab", name="Stopped")).to_contain_text("2")
    await page.get_by_role("tab", name="Running").click()
    await expect(page.locator("[data-project]")).to_have_count(1)


async def test_stopped_means_not_running_rather_than_the_stopped_state(
    page: Page, server: Harness
) -> None:
    """`Stopped` is `all.length - runNames.length` in the canvas, not a state
    match. A detached row is not running, so it belongs there: it is one of
    the two rows a person most needs to find, and a state string filter would
    hide it."""
    server.seed(running=["vessel"], detached=["forge-kit"])
    await page.goto(server.base)
    await page.get_by_role("tab", name="Stopped").click()
    await expect(
        page.locator(f'[data-project="{server.project("forge-kit")}"]')
    ).to_be_visible()
    await expect(page.locator(f'[data-project="{server.project("vessel")}"]')).to_have_count(0)


async def test_a_folder_that_cannot_be_a_project_is_accounted_for(
    page: Page, server: Harness
) -> None:
    """#7: dropping them silently made a folder called `my app` look like one
    Hitchrail could not see."""
    server.seed(stopped=["vessel"], unsupported=["my app"])
    await page.goto(server.base)
    # Qualified, like every other name the interface shows. "`my app` is not a
    # project" is a puzzle when two roots are configured and only one has it.
    await expect(page.locator(f'[data-unsupported="{DEFAULT_LABEL}~my app"]')).to_be_visible()
    await expect(page.locator(f'[data-unsupported="{DEFAULT_LABEL}~my app"]')).to_contain_text(
        "space"
    )
    await expect(page.locator('[data-project="my app"]')).to_have_count(0)


async def test_a_project_name_is_rendered_as_text_and_never_as_markup(
    page: Page, server: Harness
) -> None:
    """A project name is a FOLDER name, so anybody who can write to the root
    chooses it. The API escapes what is unprintable; the page must not then
    hand what is left to an HTML parser."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    # Wait for the initial fetch to have rendered before injecting. `boot`
    # kicks off `refresh` without awaiting it, so a state written before that
    # resolves is overwritten by the real listing and the test flakes.
    await expect(page.locator(f'[data-project="{server.project("vessel")}"]')).to_be_visible()
    hostile = "<img src=x onerror=alert(1)>"
    await page.evaluate(
        """(name) => {
             const app = window.__hitchrail;
             app.state.projects = [{ name, state: 'stopped', pid: null, ram_mb: 0,
                                     uptime_s: 0, url: null, stopping: false,
                                     protected: false }];
             app.render();
           }""",
        hostile,
    )
    assert await page.locator("img").count() == 0, "a project name became an element"
    await expect(page.locator(f'[data-project="{hostile}"] .row-name')).to_have_text(hostile)


async def test_the_memory_footer_reports_the_figure_and_the_proportion(
    page: Page, server: Harness
) -> None:
    """`memLabel` and `memPct` in the canvas. A free figure means nothing
    without a total: reassuring on 16 GB, alarming on 128."""
    server.seed(stopped=["vessel"], available_mb=8192)
    await page.goto(server.base)
    footer = page.get_by_role("contentinfo")
    await expect(footer).to_contain_text("8.0 GB free")
    await expect(page.locator("[data-mem-pct]")).to_have_attribute("data-mem-pct", "25")


async def test_an_empty_list_announces_itself_once(page: Page, server: Harness) -> None:
    """#57 took `aria-live` off the list, because a live stream re-renders it
    whenever anything changes on the machine and forty rows would be read out
    for a stop somebody made on a laptop. This is what replaced it.

    A region that is already in the markup, written to only when the answer
    CHANGES. Inserting a live region together with its text is the case
    assistive technology misses, and re-inserting it on every event is the
    churn that removing `aria-live` was meant to end.
    """
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    region = page.locator("[data-list-status]")
    await expect(region).to_have_count(1)
    await expect(region).to_have_text("")

    await page.get_by_role("combobox", name="Search folders").fill("nothing-matches-this")
    await expect(region).to_have_text("No folders match.")
    # Not the words the visible empty state uses. Two nodes carrying the same
    # string would be read out twice, and would put the page's own search test
    # into a strict mode violation, since `.offscreen` clips rather than hides.
    await expect(page.get_by_text("Nothing matches")).to_be_visible()

    await page.get_by_role("combobox", name="Search folders").fill("")
    await expect(region).to_have_text("")


async def test_a_running_session_offers_the_link_you_talk_to_it_through(
    page: Page, server: Harness
) -> None:
    """Hitchrail is a launcher, not a terminal.

    It has no input control and the log drawer is read only, so this link is
    the whole of how a person reaches the agent it started. The label used to
    be the vendor's own word for it, borrowed out of the sentence that
    explained it (#163); it now names the action and its object, and the
    accessible name is exactly that, with the external mark hidden from it.
    """
    server.seed(running=["vessel"])
    expected = server.publish_link("vessel")
    await page.goto(server.base)

    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    link = row.get_by_role("link", name="Open session")
    await expect(link).to_be_visible()
    await expect(link).to_have_attribute("href", expected)
    await expect(link).to_have_attribute("target", "_blank")
    # `noreferrer` as much as `noopener`: without it the outbound request tells
    # claude.ai the hostname and port of a machine on somebody's LAN.
    await expect(link).to_have_attribute("rel", "noopener noreferrer")

    # A real link, not a button that opens a window. On a phone this is what
    # long press, copy, share and open in app all reach for.
    box = await link.bounding_box()
    assert box is not None and box["height"] >= 44, box


async def test_a_stopped_row_offers_no_link(page: Page, server: Harness) -> None:
    server.seed(stopped=["koala"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("koala")}"]')
    await expect(row).to_have_attribute("data-state", "stopped")
    assert await row.get_by_role("link").count() == 0


async def test_a_session_with_no_link_yet_says_so_rather_than_pretending(
    page: Page, server: Harness
) -> None:
    """The bridge file is written a second or two after the agent starts, and
    a link arriving is not a state change, so the stream never announces it.
    The row asks instead of waiting."""
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    assert await row.get_by_role("link", name="Open session").count() == 0

    await row.get_by_role("button", name="Open session").click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("No link yet")
    await expect(dialog).to_contain_text("waiting for an answer in the terminal")


async def test_no_row_control_is_labelled_open_or_after_the_vendor(
    page: Page, server: Harness
) -> None:
    """#162 and #163, the negatives. `Open` was the one control that did not
    open the session, and `Continue` was the vendor's word. Neither may come
    back by copy-paste while the other label is being edited, and no label
    names the vendor: a second vendor must never make an operator relearn a
    row, which is the rule `test_no_vendor_name_is_in_the_operator_contract`
    applies to flags.
    """
    server.seed(running=["vessel"], stopped=["alpha"])
    server.publish_link("vessel")
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row.get_by_role("link", name="Open session")).to_be_visible()
    labels = await page.locator(".row-actions button, .row-actions a").all_inner_texts()
    assert len(labels) >= 3, f"too few row controls rendered to assert on: {labels}"
    for label in labels:
        assert label.strip() != "Open", labels
        assert label.strip() != "Continue", labels
        assert "claude" not in label.lower(), labels


async def test_the_session_link_is_visibly_a_link_that_leaves_the_page(
    page: Page, server: Harness
) -> None:
    """#163. The row's other controls are buttons that act here; this one
    navigates to another origin, and a control identical to its neighbours
    hides that. The mark is decorative: the accessible name stays the words."""
    server.seed(running=["vessel"])
    server.publish_link("vessel")
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    link = row.get_by_role("link", name="Open session", exact=True)
    await expect(link).to_be_visible()
    await expect(link.locator("[aria-hidden='true']")).to_have_text("\u2197")


async def test_asking_again_picks_up_a_link_that_has_since_appeared(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row.get_by_role("button", name="Open session")).to_be_visible()

    expected = server.publish_link("vessel")
    await row.get_by_role("button", name="Open session").click()

    link = row.get_by_role("link", name="Open session")
    await expect(link).to_be_visible()
    await expect(link).to_have_attribute("href", expected)


async def test_a_link_that_does_not_point_at_claude_is_not_rendered(
    page: Page, server: Harness
) -> None:
    """The refusal, and it is the reason the client checks at all.

    The server allowlists the bridge id's SHAPE, so it cannot emit this today.
    This is the second lock, on the whole value, because the string ends up in
    an `href` and a `javascript:` one would be script execution rather than a
    bad link. Injected into the page's own state, since the point is that the
    client does not trust what it was handed.
    """
    server.seed(running=["vessel"])
    server.publish_link("vessel")
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row.get_by_role("link", name="Open session")).to_be_visible()

    for hostile in ("javascript:alert(1)", "https://evil.example/code/session_1", "/code/x"):
        rendered = await page.evaluate(
            """(url) => {
                const hr = window.__hitchrail;
                hr.state.projects = hr.state.projects.map(
                    (p) => (p.state === "running" ? { ...p, url } : p)
                );
                hr.render();
                return document.querySelectorAll('.row a.btn').length;
            }""",
            hostile,
        )
        assert rendered == 0, f"{hostile} was rendered as a link"


# -- #88: a running agent that is waiting for a person ---------------------


async def test_an_untrusted_folder_does_not_render_as_an_ordinary_running_row(
    page: Page, server: Harness
) -> None:
    """#88, through the whole stack.

    Observed on a real machine: the row said `running`, `url` was null, and the
    agent sat on a trust prompt forever. `running` is true by the derivation's
    own definition and it is also useless, because nothing in this interface
    can answer that prompt and neither can a person holding a phone.

    The flow that guarantees this is Hitchrail's own: every folder its New
    folder button creates is one Claude Code has never seen.
    """
    server.seed(running=["vessel"], untrusted=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_be_visible()

    # Still running, because it is. The badge is what must not say so alone.
    await expect(row).to_have_attribute("data-state", "running")
    await expect(row).to_contain_text("waiting")
    # #204 changed what the hint tells you to do. It used to say "open it once
    # in a terminal", which from a phone was the end of the road; the pane
    # dialog now carries a keypad that can answer the prompt.
    await expect(row).to_contain_text("open the pane to answer")


async def test_a_trusted_folder_renders_as_an_ordinary_running_row(
    page: Page, server: Harness
) -> None:
    """The positive half. Without it, a warning on every row would pass."""
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row).to_have_attribute("data-state", "running")
    assert "waiting to be trusted" not in (await row.inner_text())


# -- #99: the teardown's own leak detectors --------------------------------


async def test_the_leak_detectors_can_actually_see_a_stray_server(
    server: Harness, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """#99 added two checks to teardown, and a check that cannot fire is worse
    than none: it reports safety it is not providing.

    Exercised against a server on a DIFFERENT socket, created and killed here,
    because the fixture's own `kill-server` takes everything on its socket and
    so cannot leave the thing these are looking for. The real leak arrives when
    a session is created after that kill, which a test body cannot arrange.
    """
    # A SHORT socket path, from `tempfile.mkdtemp`, not from `tmp_path`. The
    # `server` fixture goes out of its way to do the same: a unix socket path is
    # capped near 108 bytes and a pytest temp path plus a name can exceed it,
    # which surfaces as an opaque tmux error rather than as a length problem,
    # and `check=True` below would turn that into a puzzling failure.
    sock_dir = tempfile.mkdtemp(prefix="hrleak")
    # **Removed at teardown, not here.** The asserts after the `finally` below
    # still read `sock`, so deleting the directory inside that block would
    # change what they check from "the server is gone" to "the path is gone".
    # A finalizer runs after the body either way, so a failing run cleans up
    # too: six of these accumulated in /tmp in one afternoon before this line,
    # each holding a dead socket, because the test killed its SESSION and never
    # removed its DIRECTORY.
    request.addfinalizer(lambda: shutil.rmtree(sock_dir, ignore_errors=True))
    sock = str(Path(sock_dir) / "s")
    subprocess.run(
        [
            "env",
            "-u",
            "TMUX",
            "tmux",
            "-S",
            sock,
            "new-session",
            "-d",
            "-s",
            "hrleak",
            "sleep",
            "60",
        ],
        check=True,
        capture_output=True,
    )
    try:
        assert server.sessions_on_the_socket(sock) == ["hrleak"]
        naming = server.processes_still_naming(sock)
        assert naming, "a tmux server holding this socket was not seen in ps"
        assert any(sock in row for row in naming)
    finally:
        subprocess.run(
            ["env", "-u", "TMUX", "tmux", "-S", sock, "kill-session", "-t", "=hrleak"],
            check=False,
            capture_output=True,
        )

    # And they go quiet once it is gone, or every run would fail on nothing.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and server.processes_still_naming(sock):
        time.sleep(0.1)
    assert server.sessions_on_the_socket(sock) == []
    assert server.processes_still_naming(sock) == []


async def test_a_running_row_with_every_control_does_not_crush_its_name(
    page: Page, server: Harness
) -> None:
    """Found on a real phone, which is what #75 is for, and missed by every
    test here until now.

    A running row whose session link has not arrived carries a badge and three
    controls: Logs, Open session, Stop. `.row-actions` is `flex-shrink: 0` and sat
    INSIDE `.row-head`, so the name was the only thing in that line that could
    give, and `overflow-wrap: anywhere` let it give all the way down to one
    character per line. The screenshot showed `alpha` as five stacked letters
    and `Stop` cut off past the right edge.

    Two assertions, because either alone passes the broken layout: nothing may
    overflow the viewport horizontally, and the name must occupy one line.
    """
    await page.set_viewport_size({"width": 390, "height": 844})
    server.seed(running=["alpha"], untrusted=["alpha"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("alpha")}"]')
    await expect(row).to_be_visible()
    # The state that produces the widest row: no session link yet, so `Get
    # link` is there too.
    await expect(row.get_by_role("button", name="Open session")).to_be_visible()

    overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"the page scrolls sideways by {overflow}px at a phone width"

    name_lines = await row.locator(".row-name").evaluate(
        "el => el.getBoundingClientRect().height /"
        " parseFloat(getComputedStyle(el).lineHeight || '20')"
    )
    assert name_lines < 2, f"the project name wrapped onto {name_lines:.1f} lines"


async def test_a_stuck_row_says_so_without_the_page_asking(
    page: Page, server: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#100 through the running application, which is the half no other tier has.

    The unit tier proves the engine records it and the live tmux tier proves a
    real `capture-pane` carries the byte the predicate reads. Neither can see
    the thing that actually matters to a person: that the sweep runs on the
    server's own task, and that the answer reaches a page nobody touched.

    **Nobody touches the page.** Outside a stop wait the interface does not
    poll, so this passing means the announcement went out over the event stream
    and the row redrew itself. Review found that half missing, with everything
    else already working.

    `MIN_UPTIME_S` is patched to zero because it is not what is under test: it
    exists so a session still painting its first frame is not flagged, and
    waiting fifteen real seconds here would buy a slower suite and no more
    confidence. The server runs in this process, so the constant it reads is
    this one.
    """
    monkeypatch.setattr(attention, "MIN_UPTIME_S", 0)
    server.seed(running=["alpha"], agent_shows_a_modal=True)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("alpha")}"]')
    await expect(row).to_have_attribute("data-state", "running")

    # Not "waiting to be trusted", which is #88's overlay and reaches the same
    # badge by a different route. The seeded folder IS trusted, so this is the
    # sweep's answer or nothing.
    await expect(row).to_contain_text("waiting for an answer", timeout=15_000)

    # And the badge says so too (#183). It used to read `running` while the
    # meta line carried the truth: `awaiting_trust` replaced the badge and
    # `awaiting_input` did not, so the one row on a fifty row list that needed
    # a person looked exactly like the forty nine that did not. Both overlays
    # mean "go to the pane", so both are `waiting`; the state underneath is
    # still `running`, because this is an overlay and not a fifth state.
    await expect(row.locator(".badge")).to_have_text("waiting")
    await expect(row).to_have_attribute("data-state", "running")


# -- #90: the figure, and what bounds it -------------------------------------


async def test_a_running_row_says_what_bounds_its_memory(page: Page, server: Harness) -> None:
    """#90. "1.4 GB" beside nothing is a different sentence from "1.4 GB of
    4 GB", and the reading is free where the setting is not ours."""
    server.seed(running=["vessel"], ceiling_mb=4096)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row.locator(".meta")).to_contain_text("of 4.0 GB")


async def test_a_running_row_says_plainly_when_nothing_bounds_it(
    page: Page, server: Harness
) -> None:
    """The other half, and the one that matters on the reporting machine:
    "no limit" is a fact worth reading next to a figure, not an absence."""
    server.seed(running=["vessel"], ceiling_mb=None)
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row.locator(".meta")).to_contain_text("no limit")
    await expect(row.locator(".meta")).not_to_contain_text(" of ")


# -- Phase 13: fifty rows ----------------------------------------------------


async def test_fifty_rows_across_five_roots_all_render(page: Page, server: Harness) -> None:
    """The fixture the phase's premortem asked for, proved before anything is
    built on it: fifty folders, five roots, every one a row, at the phone
    viewport, with two of them running."""
    server.seed_fifty(running=["p00", "p01"])
    await page.goto(server.base)
    rows = page.locator("[data-project]")
    await expect(rows).to_have_count(50, timeout=15_000)
    await expect(page.locator("[data-run-count]")).to_have_text("2 running")
    labels = {
        (await row.get_attribute("data-project") or "").split("~")[0]
        for row in await rows.all()
    }
    assert labels == set(Harness.FIFTY_LABELS), labels


# -- #146: filtering by root -------------------------------------------------


def _chip(page: Page, label: str):  # type: ignore[no-untyped-def]
    return page.locator("[data-roots]").get_by_role("button", name=re.compile(rf"^{label}\b"))


async def test_root_chips_or_together_and_and_with_the_state_tab(
    page: Page, server: Harness
) -> None:
    """#146. Roots compose with OR among themselves and with AND against the
    state tab and the search, the convention a person already expects and
    the one that is classically got backwards."""
    server.seed_fifty(running=["p00", "p01"])
    await page.goto(server.base)
    rows = page.locator("[data-project]")
    await expect(rows).to_have_count(50, timeout=15_000)

    await _chip(page, "bravo").click()
    await expect(rows).to_have_count(10)
    await _chip(page, "charlie").click()
    await expect(rows).to_have_count(20)
    for row in await rows.all():
        label = (await row.get_attribute("data-project") or "").split("~")[0]
        assert label in {"bravo", "charlie"}, label

    # AND with the state tab: nothing in bravo or charlie is running.
    await page.get_by_role("tab", name=re.compile("^Running")).click()
    await expect(rows).to_have_count(0)
    # And the machine's own count is untouched by the filter.
    await expect(page.locator("[data-run-count]")).to_contain_text("2 running")


async def test_every_chip_deselected_is_all_and_never_none(page: Page, server: Harness) -> None:
    """Zero rows for a full machine is the failure worth a named test: a
    filter silently hiding a running session is the dangerous direction."""
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    rows = page.locator("[data-project]")
    await expect(rows).to_have_count(50, timeout=15_000)
    await _chip(page, "delta").click()
    await expect(rows).to_have_count(10)
    await _chip(page, "delta").click()
    await expect(rows).to_have_count(50)


async def test_a_single_root_renders_no_chip_strip(page: Page, server: Harness) -> None:
    """The same rule the row chip follows (#121): a single root deployment
    does not pay for a feature it is not using. And a selection stored by a
    previous multi root configuration must not filter the one root to
    nothing."""
    server.seed(stopped=["vessel", "koala"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(2)
    await page.evaluate("() => localStorage.setItem('hitchrail.roots', '[\"bravo\"]')")
    await page.reload()
    await expect(page.locator("[data-project]")).to_have_count(2)
    assert await page.locator("[data-roots]").is_hidden()


async def test_the_selection_survives_a_reload_and_a_vanished_root_is_dropped(
    page: Page, server: Harness
) -> None:
    """A filter that survives a reload is the difference between a filter and
    a fidget. The restored value is untrusted browser input: intersected
    with the roots actually present, and an unparseable value is no filter
    rather than an exception."""
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    rows = page.locator("[data-project]")
    await expect(rows).to_have_count(50, timeout=15_000)
    await _chip(page, "echo").click()
    await expect(rows).to_have_count(10)

    await page.reload()
    await expect(rows).to_have_count(10, timeout=15_000)
    await expect(_chip(page, "echo")).to_have_attribute("aria-pressed", "true")

    await page.evaluate("() => localStorage.setItem('hitchrail.roots', '[\"echo\", \"gone\"]')")
    await page.reload()
    await expect(rows).to_have_count(10, timeout=15_000)
    assert await page.locator("[data-roots] button[aria-pressed='true']").count() == 1

    await page.evaluate("() => localStorage.setItem('hitchrail.roots', '{not json')")
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.reload()
    await expect(rows).to_have_count(50, timeout=15_000)
    assert errors == [], errors


async def test_the_applied_filter_is_visible_from_the_bottom_of_the_list(
    page: Page, server: Harness
) -> None:
    """Applied filters must remain readable from the list screen itself: on a
    phone the strip that set them has scrolled away. The fixed footer says
    how many of the machine's rows are shown, so a filtered list never reads
    as the whole machine."""
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    rows = page.locator("[data-project]")
    await expect(rows).to_have_count(50, timeout=15_000)
    await expect(page.locator("[data-shown]")).to_have_text("")
    await _chip(page, "bravo").click()
    await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    await expect(page.locator("[data-shown]")).to_have_text("10 of 50 shown")
    assert await page.locator("[data-shown]").is_visible()


async def test_the_empty_state_says_which_filter_emptied_the_list(
    page: Page, server: Harness
) -> None:
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(50, timeout=15_000)
    await _chip(page, "bravo").click()
    await page.get_by_role("tab", name=re.compile("^Running")).click()
    empty = page.locator(".empty-body")
    await expect(empty).to_contain_text("bravo")
    await expect(empty).to_contain_text("running")


# -- #164: the search suggests -----------------------------------------------


async def test_typing_suggests_folders_and_a_tap_chooses_one(
    page: Page, server: Harness
) -> None:
    """#164. On a phone keyboard the distinguishing part of a folder name is
    the cost; a suggestion list under the field makes it one tap. Built from
    the projects already in memory: no request produces a suggestion."""
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(50, timeout=15_000)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url) if "/api/" in r.url else None)

    box = page.get_by_role("combobox", name="Search folders")
    await box.fill("p0")
    listbox = page.get_by_role("listbox")
    await expect(listbox).to_be_visible()
    await expect(box).to_have_attribute("aria-expanded", "true")
    options = listbox.get_by_role("option")
    assert await options.count() > 0
    # Each suggestion names its root, since there is more than one.
    await expect(options.first).to_contain_text("main")

    await options.first.click()
    await expect(box).to_have_attribute("aria-expanded", "false")
    # Choosing is exact: the one project the suggestion named, not every
    # folder called p00 across the five roots and not p01 to p09 either.
    await expect(page.locator("[data-project]")).to_have_count(1)
    assert not [u for u in requests if "/api/projects" in u], "a suggestion cost a request"


async def test_the_suggestion_list_follows_the_reference_keyboard_pattern(
    page: Page, server: Harness
) -> None:
    """The ARIA editable combobox with list autocomplete: focus stays on the
    input while `aria-activedescendant` moves attention, nothing is
    auto-selected as you type, Down and Up move, Enter chooses, Escape closes
    the popup and leaves the text, a second Escape clears the field."""
    server.seed(stopped=["vessel", "vessel-social", "koala"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(3)
    box = page.get_by_role("combobox", name="Search folders")
    await box.fill("ves")
    listbox = page.get_by_role("listbox")
    await expect(listbox).to_be_visible()
    # Typing selected nothing.
    assert await box.get_attribute("aria-activedescendant") in (None, "")
    await expect(page.locator("[data-project]")).to_have_count(2)

    await box.press("ArrowDown")
    active = await box.get_attribute("aria-activedescendant")
    assert active, "Down did not move the active option"
    focused = await page.evaluate("() => document.activeElement.getAttribute('role')")
    assert focused == "combobox", "focus left the input"
    await box.press("ArrowDown")
    assert await box.get_attribute("aria-activedescendant") != active
    await box.press("ArrowUp")
    assert await box.get_attribute("aria-activedescendant") == active

    await box.press("Enter")
    await expect(box).to_have_attribute("aria-expanded", "false")
    await expect(page.locator("[data-project]")).to_have_count(1)
    # #248. A choice is the end of the interaction: the next render, which
    # any event or listing produces, must not reopen the popup with the one
    # row that was just chosen. Forced here rather than waited for.
    await page.evaluate("() => window.__hitchrail.render()")
    await expect(box).to_have_attribute("aria-expanded", "false")
    assert await page.get_by_role("listbox").is_hidden()

    await box.fill("ves")
    await expect(listbox).to_be_visible()
    await box.press("Escape")
    await expect(box).to_have_attribute("aria-expanded", "false")
    assert await box.input_value() == "ves"
    await box.press("Escape")
    assert await box.input_value() == ""
    await expect(page.locator("[data-project]")).to_have_count(3)


async def test_the_search_matches_the_folder_and_not_the_root_label(
    page: Page, server: Harness
) -> None:
    """`includes` over the qualified string matched the `work` root for `work`
    and a folder called `homework` in any root. Roots have chips now."""
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(50, timeout=15_000)
    await page.get_by_role("combobox", name="Search folders").fill("bravo")
    await expect(page.locator("[data-project]")).to_have_count(0)
    await expect(page.get_by_role("listbox")).to_be_hidden()


# -- #149: the header stays ---------------------------------------------------

# Measured on 2026-09-13 at 390x844 with five roots, before this change: the
# bar 80px, the tabs 56, the chips 54, the search 68, 258 in all. Premortem 3
# of the Phase 13 plan: every strip is individually right and together they
# eat the screen, so the header may cost no more at rest than it did.
TOP_AT_REST_BEFORE = 258


async def _top_height(page: Page) -> float:
    height = await page.locator("[data-top]").evaluate("e => e.getBoundingClientRect().height")
    return float(height)


async def test_new_and_the_filters_are_reachable_at_the_bottom_of_fifty_rows(
    page: Page, server: Harness
) -> None:
    """#149. The header scrolled away with the list, so on a fifty row list
    New and the filters were gone as soon as you started scrolling. The
    controls that act on the whole list survive scrolling; the identity can
    shrink."""
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(50, timeout=15_000)
    await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(200)

    new = page.get_by_role("button", name="New")
    box = await new.bounding_box()
    assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= 844, box
    for control in (
        page.get_by_role("tab", name=re.compile("^Running")),
        _chip(page, "bravo"),
        page.get_by_role("combobox", name="Search folders"),
    ):
        b = await control.bounding_box()
        assert b is not None and b["y"] >= 0 and b["y"] + b["height"] <= 844, b

    await new.click()
    await expect(page.get_by_label("Folder name")).to_be_visible()


async def test_the_header_costs_no_more_at_rest_and_less_when_scrolled(
    page: Page, server: Harness
) -> None:
    """Measured, not felt. At rest the top stack is no taller than it was
    before it became sticky, and scrolled it is shorter: the root line goes
    and the title shrinks, because identity can give way and controls
    cannot."""
    server.seed_fifty(running=["p00"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(50, timeout=15_000)
    at_rest = await _top_height(page)
    assert at_rest <= TOP_AT_REST_BEFORE, f"the header grew to {at_rest}px at rest"

    await page.evaluate("() => window.scrollTo(0, 600)")
    await page.wait_for_timeout(200)
    scrolled = await _top_height(page)
    assert scrolled < at_rest - 20, f"scrolled {scrolled}px is not under {at_rest}px by much"
    assert await page.locator("[data-top]").evaluate("e => e.getBoundingClientRect().top") == 0

    await page.evaluate("() => window.scrollTo(0, 0)")
    await page.wait_for_timeout(200)
    assert await _top_height(page) == at_rest, "the header did not come back at the top"


async def test_a_short_list_leaves_no_gap_under_the_header(page: Page, server: Harness) -> None:
    """With the list shorter than the viewport the sticky block must sit
    exactly where the static one did: no gap and no double border."""
    server.seed(stopped=["vessel"])
    await page.goto(server.base)
    await expect(page.locator("[data-project]")).to_have_count(1)
    top = page.locator("[data-top]")
    top_bottom = await top.evaluate("e => e.getBoundingClientRect().bottom")
    list_top = await page.locator("main").evaluate("e => e.getBoundingClientRect().top")
    assert abs(top_bottom - list_top) < 1, (top_bottom, list_top)


# -- #150: shapes beside the words --------------------------------------------


async def test_every_badge_carries_its_glyph_and_keeps_its_word(
    page: Page, server: Harness
) -> None:
    """The badge is the one place a shape does something a word cannot: a list
    of fifty is scanned, not read, and shape stops six states being told
    apart by colour alone. The word stays beside it, and the glyph is
    decorative to a screen reader, which still hears the word."""
    server.seed(running=["vessel"], stopped=["koala"], stale=["ghost"], detached=["loose"])
    await page.goto(server.base)
    rows = page.locator("[data-project]")
    await expect(rows).to_have_count(4, timeout=15_000)
    seen: dict[str, str] = {}
    for row in await rows.all():
        badge = row.locator(".badge")
        word = (await badge.get_attribute("data-badge")) or ""
        await expect(badge).to_have_text(word)
        use = badge.locator("svg use")
        href = await use.get_attribute("href")
        assert href == f"#badge-{word}", (word, href)
        assert await badge.locator("svg").get_attribute("aria-hidden") == "true"
        # #252. A drawn box, not only a reference: a sprite hidden in a way
        # the engine refuses to draw from would pass every other line here.
        box = await badge.locator("svg").bounding_box()
        assert box is not None and box["width"] > 8 and box["height"] > 8, (word, box)
        drawn = await badge.locator("svg").evaluate("s => s.getBBox && s.getBBox().width > 0")
        assert drawn, f"the {word} glyph draws nothing"
        seen[word] = href or ""
    assert {"running", "stopped", "stale", "detached"} <= set(seen), seen
