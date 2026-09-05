"""#54: the list, its four states, search, the tab filter and the lock."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from playwright.async_api import Page, expect

from support import DEFAULT_LABEL

from .conftest import Harness

pytestmark = pytest.mark.e2e


async def test_every_derived_state_renders_as_itself(page: Page, server: Harness) -> None:
    """All four from section 4.1. `detached` is the one a naive tool gets
    wrong, so it is drawn with its pid and never silently reconciled."""
    server.seed(running=["vessel"], stopped=["koala"])
    await page.goto(server.base)
    await expect(page.locator('[data-project="main~hrx-vessel"]')).to_have_attribute(
        "data-state", "running"
    )
    await expect(page.locator('[data-project="main~hrx-koala"]')).to_have_attribute(
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
    row = page.locator('[data-project="main~hrx-forge-kit"]')
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
    row = page.locator('[data-project="main~hrx-forge-kit"]')
    await expect(row).to_have_attribute("data-state", "detached")

    await expect(row).to_contain_text("in tmux session e2eother-hrx-forge-kit")
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
    tall = await page.locator('[data-project="main~hrx-vessel"]').bounding_box()
    short = await page.locator('[data-project="main~hrx-long-hyphenated-name"]').bounding_box()
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
    row = page.locator('[data-project="main~hrx-hitchrail"]')
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
    await page.get_by_role("searchbox").fill("med")
    await expect(page.locator("[data-project]")).to_have_count(1)
    await page.get_by_role("searchbox").fill("zzz")
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
    await expect(page.locator('[data-project="main~hrx-forge-kit"]')).to_be_visible()
    await expect(page.locator('[data-project="main~hrx-vessel"]')).to_have_count(0)


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
    await expect(page.locator('[data-project="main~hrx-vessel"]')).to_be_visible()
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

    await page.get_by_role("searchbox").fill("nothing-matches-this")
    await expect(region).to_have_text("No folders match.")
    # Not the words the visible empty state uses. Two nodes carrying the same
    # string would be read out twice, and would put the page's own search test
    # into a strict mode violation, since `.offscreen` clips rather than hides.
    await expect(page.get_by_text("Nothing matches")).to_be_visible()

    await page.get_by_role("searchbox").fill("")
    await expect(region).to_have_text("")


async def test_a_running_session_offers_the_link_you_talk_to_it_through(
    page: Page, server: Harness
) -> None:
    """Hitchrail is a launcher, not a terminal.

    It has no input control and the log drawer is read only, so this link is
    the whole of how a person reaches the agent it started. Claude Code prints
    it on startup as "Continue here, on your phone, or at ...", which is where
    the label comes from.
    """
    server.seed(running=["vessel"])
    expected = server.publish_link("vessel")
    await page.goto(server.base)

    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    link = row.get_by_role("link", name="Continue")
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
    assert await row.get_by_role("link", name="Continue").count() == 0

    await row.get_by_role("button", name="Get link").click()
    dialog = page.locator("[data-dialog]")
    await expect(dialog).to_contain_text("No link yet")
    await expect(dialog).to_contain_text("waiting for an answer in the terminal")


async def test_asking_again_picks_up_a_link_that_has_since_appeared(
    page: Page, server: Harness
) -> None:
    server.seed(running=["vessel"])
    await page.goto(server.base)
    row = page.locator(f'[data-project="{server.project("vessel")}"]')
    await expect(row.get_by_role("button", name="Get link")).to_be_visible()

    expected = server.publish_link("vessel")
    await row.get_by_role("button", name="Get link").click()

    link = row.get_by_role("link", name="Continue")
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
    await expect(row.get_by_role("link", name="Continue")).to_be_visible()

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
    await expect(row).to_contain_text("open it once in a terminal")


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
    server: Harness, tmp_path: Path
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
    controls: Open, Get link, Stop. `.row-actions` is `flex-shrink: 0` and sat
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
    await expect(row.get_by_role("button", name="Get link")).to_be_visible()

    overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"the page scrolls sideways by {overflow}px at a phone width"

    name_lines = await row.locator(".row-name").evaluate(
        "el => el.getBoundingClientRect().height /"
        " parseFloat(getComputedStyle(el).lineHeight || '20')"
    )
    assert name_lines < 2, f"the project name wrapped onto {name_lines:.1f} lines"
