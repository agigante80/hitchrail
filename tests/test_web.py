"""Structural guards over `web/app.js`, read as source.

There is no JavaScript unit tier here: no `package.json`, no jsdom, no runner.
`app.js` is exercised end to end through a real browser, which is the right
tier for behaviour and the wrong one for "every branch of this module obeys a
rule", because reaching all eighteen dialogs would mean driving eighteen
states and some of them cannot be reached on demand at all.

So this reads the file. That is the same instrument
`test_the_engine_never_iterates_the_stop_keys` uses on `engine.py`, and it
carries the same limit: it sees the shape of the source, not what it does.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "src" / "hitchrail" / "web" / "app.js"

# -- #169: every dialog either lets the operator act, or says why not --------
#
# The defect this exists for: `stop_unsafe` rendered one Close and nothing
# else, so a session whose input box would not clear could not be ended from
# Hitchrail at all. The comment above it justified that by saying "Kill is
# still on the row", and no row has ever rendered a kill. A false justification
# survived review because nothing checked the claim.
#
# Keyed by the `title:` expression as it appears in the source. That is
# deliberately brittle: rewording a dialog's title makes it a new entry and
# forces somebody to classify it again, which is the whole point. A new dialog
# with no entry fails this test rather than shipping unclassified.
#
# The value is the reason the dialog offers no action beyond dismissal. An
# empty string means it MUST offer one, and the test checks that it does.
_MUST_ACT = ""

DIALOGS: dict[str, str] = {
    '"No link yet",': (
        "Informational. There is no link yet because none has been published, "
        "and no control on this screen could produce one."
    ),
    '"That link cannot be opened",': (
        "Informational. The link is malformed, and the only repair is upstream."
    ),
    '"Found in the pane",': (
        "Informational, and it carries the link itself in `extra`. Reading it IS the action."
    ),
    "`Stop ${displayProject(project.name)}?`,": _MUST_ACT,
    "`Clear ${project.name}?`,": _MUST_ACT,
    "`Stopping ${project.name}`,": _MUST_ACT,
    "`Lost track of ${project.name}`,": (
        "Argued in place, and the argument is the opposite of #169's: the page "
        "cannot read the machine, so offering to end a process it cannot "
        "currently see would be proposing a kill on a guess."
    ),
    "`${project.name} is waiting for you`,": _MUST_ACT,
    "`No answer from ${project.name}`,": _MUST_ACT,
    '"Not signed in any more",': _MUST_ACT,
    '"Hitchrail cannot reach it",': (
        "`no_agent`. Either there is no agent, or the row is detached and has "
        "no session to kill, so there is nothing this screen could offer that "
        "would work. Do not offer a tap that refuses."
    ),
    '"It was not asked to exit",': _MUST_ACT,
    'code === "self_protected" ? "That one is protected" : "That did not work",': (
        "Two situations, one screen. `self_protected` offers nothing because "
        "protected means protected and that is the control working. The "
        "fallback is a refusal nobody has classified, so there is no action "
        "known to be safe to offer."
    ),
    '"Tight on memory",': _MUST_ACT,
    '"Not enough memory",': _MUST_ACT,
    "`${project.name} died`,": _MUST_ACT,
    "project.name,": (
        "The log drawer. Its content is the point and `extra` carries it; "
        "reading is the action."
    ),
    '"New folder",': _MUST_ACT,
}


def _dialog_calls(source: str) -> list[tuple[str, str]]:
    """Every `showDialog({...})` call as (title expression, body text).

    Brace balanced rather than regex matched, because the object literals hold
    arrow functions, template literals and nested arrays.
    """
    out: list[tuple[str, str]] = []
    for match in re.finditer(r"(?<!function )showDialog\(\{", source):
        start = source.index("{", match.start())
        depth = 0
        end = start
        for i in range(start, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        block = source[start : end + 1]
        title = re.search(r"^\s*title:\s*(.+)$", block, re.M)
        assert title, f"a showDialog call has no title:\n{block[:200]}"
        out.append((title.group(1).strip(), block))
    return out


def _resolves_actions(block: str, source: str, call_start: int) -> str:
    """The actions text for one call, following the shorthand when it is used.

    Two dialogs build their actions conditionally and pass `actions,` rather
    than a literal: `showHardMemory`, whose second action depends on there
    being something to suggest, and the `stop_unsafe` refusal, whose kill needs
    a row to name. Both are resolved by reading backwards to the `const
    actions = [` that feeds them.
    """
    literal = re.search(r"actions:\s*\[", block)
    if literal:
        start = block.index("[", literal.start())
        depth = 0
        for i in range(start, len(block)):
            if block[i] == "[":
                depth += 1
            elif block[i] == "]":
                depth -= 1
                if depth == 0:
                    return block[start : i + 1]
        raise AssertionError(f"unbalanced actions array:\n{block[:200]}")

    assert re.search(r"^\s*actions,\s*$", block, re.M), (
        f"a showDialog call passes actions in a form this guard cannot read. "
        f"Teach it the new form rather than deleting the entry:\n{block[:300]}"
    )
    before = source[:call_start]
    built = before.rindex("const actions = [")
    return source[built:call_start]


def test_every_dialog_either_offers_an_action_or_is_a_named_exception() -> None:
    """#169's third deliverable, and the one that stops it being one button.

    A dialog that can be the last thing on screen and offers only a way to
    dismiss it is a dead end. Some are correct: there is genuinely nothing to
    offer. This asserts that the difference is a decision somebody wrote down,
    rather than the state a screen happened to ship in.
    """
    source = APP_JS.read_text(encoding="utf-8")
    calls = _dialog_calls(source)

    # Guard the guard. A rename or a refactor that this parser silently stops
    # matching would make every assertion below vacuous.
    assert len(calls) >= 15, (
        f"the parser found only {len(calls)} dialogs, which means it has "
        f"stopped matching rather than that they were deleted"
    )

    found = {title for title, _ in calls}
    unclassified = found - DIALOGS.keys()
    assert not unclassified, (
        "a dialog with no entry in DIALOGS. Classify it: give it an empty "
        "reason if it must offer an action, or a reason if it may not.\n  "
        + "\n  ".join(sorted(unclassified))
    )
    stale = DIALOGS.keys() - found
    assert not stale, (
        "DIALOGS names a dialog `app.js` no longer has. Remove the entry.\n  "
        + "\n  ".join(sorted(stale))
    )

    for match, (title, block) in zip(
        re.finditer(r"(?<!function )showDialog\(\{", source), calls, strict=True
    ):
        actions = _resolves_actions(block, source, match.start())
        # An action that only dismisses is not an action. Strip those and see
        # whether any handler is left.
        acts = re.sub(r"\(\)\s*=>\s*closeDialog\(\)", "", actions)
        offers = "=>" in acts
        reason = DIALOGS[title]
        if reason == _MUST_ACT:
            assert offers, (
                f"{title} offers only a way to dismiss it, and DIALOGS says it "
                f"must let the operator act. This is #169's defect: a screen "
                f"that reports a situation and leaves no way out of it."
            )
        else:
            assert not offers, (
                f"{title} now offers an action, but DIALOGS still carries the "
                f"reason it does not:\n  {reason}\nUpdate the entry to "
                f"_MUST_ACT, so the reason does not outlive the fact."
            )


def test_the_refusal_dialog_reaches_the_kill_route() -> None:
    """The narrow half of #169, asserted on the source because the browser tier
    proves the behaviour and this proves the wiring did not quietly change.

    `showRefusal` takes the row precisely so `stop_unsafe` can name a session
    to kill. A signature that loses it again would leave the E2E test failing
    for a reason nobody could read off the diff.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert "function showRefusal(result, project)" in source, (
        "showRefusal no longer takes the row, so the kill it offers has nothing to name"
    )
    stop_unsafe = source[source.index('if (code === "stop_unsafe")') :]
    stop_unsafe = stop_unsafe[: stop_unsafe.index("\n  }\n")]
    assert "killNow(project)" in stop_unsafe, (
        "the stop_unsafe refusal no longer reaches the kill route, which is "
        "the dead end #169 exists to close"
    )
    assert '"danger"' in stop_unsafe, "the kill is no longer styled as destructive"
