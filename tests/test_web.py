"""Structural guards over the scripts in `web/`, read as source.

There is no JavaScript unit tier here: no `package.json`, no jsdom, no runner.
The interface is exercised end to end through a real browser, which is the right
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

import pytest

from js_source import SINK, stripped

WEB = Path(__file__).resolve().parents[1] / "src" / "hitchrail" / "web"


def web_scripts() -> dict[str, str]:
    """Every script in `web/` by file name, read fresh.

    #68 split `app.js` into modules, so a guard that read one file would pass
    over whatever moved out of it. Globbed rather than listed.
    """
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB.glob("*.js"))}


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
    '"The reply could not be read",': (
        "#82. The request was sent and the server answered; only the reply was "
        "unusable. Offering an action here would be the guess this screen "
        "replaces: a second Stop or a Kill for a session that is already "
        "stopping. The list catches up on its own."
    ),
    "`Stop ${displayProject(project.name)}?`,": _MUST_ACT,
    "`Stop ${sessionCount(rows.length)}?`,": _MUST_ACT,
    "`Stopping ${sessionCount(bulk.rows.length)}`,": _MUST_ACT,
    "`Clear ${project.name}?`,": _MUST_ACT,
    "`Stopping ${project.name}`,": _MUST_ACT,
    "`Lost track of ${project.name}`,": (
        "Argued in place, and the argument is the opposite of #169's: the page "
        "cannot read the machine, so offering to end a process it cannot "
        "currently see would be proposing a kill on a guess."
    ),
    "`${project.name} is waiting for you`,": _MUST_ACT,
    "`No answer from ${project.name}`,": _MUST_ACT,
    "`${project.name} is still running`,": _MUST_ACT,
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
    "escalate ? `Kill ${project.name}?` : `End ${project.name}?`,": _MUST_ACT,
    'code === "owned_elsewhere" ? "A session owns it" : "Nothing was signalled",': _MUST_ACT,
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
    scripts = web_scripts()
    per_file = {name: _dialog_calls(source) for name, source in scripts.items()}
    calls = [call for found_in_file in per_file.values() for call in found_in_file]

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
        "DIALOGS names a dialog no web script has any more. Remove the entry.\n  "
        + "\n  ".join(sorted(stale))
    )

    # One file at a time: `_resolves_actions` reads backwards to a `const
    # actions = [`, and that has to be the one in the same module as the call.
    for name, source in scripts.items():
        matches = re.finditer(r"(?<!function )showDialog\(\{", source)
        for match, (title, block) in zip(matches, per_file[name], strict=True):
            actions = _resolves_actions(block, source, match.start())
            # An action that only dismisses is not an action. Strip those and
            # see whether any handler is left.
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
    source = web_scripts()["refusal.js"]
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


# -- #150: the badge glyphs ----------------------------------------------------

INDEX = WEB / "index.html"


def _badge_words() -> set[str]:
    """Every word `badgeFor` can return, read from the function's own source:
    the returned string literals, plus the four states it falls back to."""
    source = web_scripts()["row.js"]
    start = source.index("function badgeFor(")
    body = source[start : source.index("\n}\n", start)]
    words = set(re.findall(r'return "([a-z]+)"', body))
    assert "project.state" in body, "badgeFor no longer falls back to the state"
    return words | {"running", "stopped", "stale", "detached"}


def _sprite_symbols() -> set[str]:
    html = INDEX.read_text(encoding="utf-8")
    return set(re.findall(r'<symbol id="badge-([a-z]+)"', html))


def test_every_badge_word_has_a_glyph_and_every_glyph_a_word() -> None:
    """#150. Seven glyphs for the seven things the badge can say, no more: a
    set that grows to fill a number is how an icon set stops meaning
    anything, and a word with no glyph renders a broken `<use>`."""
    words = _badge_words()
    assert len(words) == 7, sorted(words)
    assert _sprite_symbols() == words


def test_the_sprite_names_its_source_licence_and_version() -> None:
    """Vendored, not depended on, and MIT requires the notice be preserved.
    The version is recorded so the next glyph comes from the same family at
    the same stroke weight, which is what makes a small set look deliberate."""
    html = INDEX.read_text(encoding="utf-8")
    opened = html.index("data-badge-sprite")
    # The notice is the comment immediately above the sprite, part of it in
    # every sense but the markup's.
    sprite = html[html.rindex("<!--", 0, opened) : html.index("</svg>", opened)]
    assert "Tabler Icons" in sprite and "MIT" in sprite and "Paweł Kuna" in sprite
    assert re.search(r"v3\.\d+\.\d+", sprite), "no version recorded"


def test_detached_and_stale_are_different_shapes() -> None:
    """The pair to get right: opposites the interface treats as opposites, and
    confusing them is confusing "there is a live agent" with "there is not".
    Pinned on the paths, since two symbols with the same drawing would pass
    every other test here."""
    html = INDEX.read_text(encoding="utf-8")

    def paths(name: str) -> str:
        start = html.index(f'<symbol id="badge-{name}"')
        return html[start : html.index("</symbol>", start)]

    assert paths("detached") != paths("stale")
    for name in _badge_words():
        assert "<path" in paths(name), f"{name} has no drawing"


GRANT = WEB / "grant.html"


# -- #308: no page renders vendor text as markup ------------------------------


def test_no_web_script_assigns_vendor_text_as_markup() -> None:
    """#308. `settings.js` renders every vendor string (a plugin id, its
    `detail`, its `approved_command`) with `textContent`, which is correct
    today; nothing noticed when a past review briefly switched two of those
    sites to `innerHTML` and all fifteen e2e cases stayed green, because none
    of them puts markup-shaped text in a vendor field. Every page, not only
    that one (the ticket's own recommendation): a future page gets the same
    guard for free rather than needing its own ticket filed against it.
    """
    scripts = sorted(WEB.glob("*.js"))
    names = {p.name for p in scripts}
    assert {"settings.js", "plugins.js"} <= names, (
        f"expected settings.js and plugins.js in {WEB}, found {sorted(names)}"
    )
    for path in scripts:
        match = SINK.search(stripped(path.read_text(encoding="utf-8")))
        assert match is None, (
            f"{path.name} assigns HTML as a string ({match.group(0)!r} once "
            f"comments and literals are stripped); render vendor text with "
            f"textContent instead"
        )


@pytest.mark.parametrize(
    "source",
    [
        "el.innerHTML = x;",
        "el.outerHTML = x;",
        "el.insertAdjacentHTML('beforeend', x);",
        'el["innerHTML"] = x;',
        "el['outerHTML'] = x;",
        "Object.assign(el, {innerHTML: x});",
        'Object.assign(el, {"innerHTML": x});',
        "const s = `${(el.innerHTML = x)}`;",
        "const t = `a ${`b ${el.innerHTML = x}`} c`;",
        "const y = s.replace(/'/g, ''); el.innerHTML = y;",
        'const y = s.replace(/"/g, ""); el.innerHTML = y;',
        "const y = s.replace(/[/']/g, ''); el.innerHTML = y;",
        "if (ok) return /'/.test(s) && (el.innerHTML = s);",
    ],
)
def test_the_markup_guard_sees_every_shape_of_sink(source: str) -> None:
    """#342. Each of these renders a string as markup and runs; the guard
    must see all of them, not only the dotted property."""
    assert SINK.search(stripped(source)), stripped(source)


@pytest.mark.parametrize(
    "source",
    [
        "// never innerHTML\nel.textContent = x;",
        "/* innerHTML is refused */ el.textContent = x;",
        "el.textContent = 'set with innerHTML elsewhere';",
        "el.textContent = `not innerHTML ${name}`;",
        "const half = total / 2 / count; el.textContent = 'no innerHTML';",
        "const r = /innerHTML/; el.textContent = x;",
    ],
)
def test_the_markup_guard_passes_prose_and_division(source: str) -> None:
    """The other side of #308: a comment, a sentence or a regex that names a
    sink is not one, and a division is not a regex that would blank the code
    after it."""
    assert SINK.search(stripped(source)) is None, stripped(source)


def test_a_division_does_not_hide_the_code_after_it() -> None:
    """Read as a regex, `a / b` would blank up to the next slash, and a sink
    between the two would vanish."""
    assert SINK.search(stripped("const q = a / b; el.innerHTML = q; const r = c / d;"))


def test_the_key_field_hints_a_password_manager_and_has_no_name() -> None:
    """#171's two decisions on the grant page, pinned (#260 item 7). The
    `autocomplete` value is what lets a password manager offer the entry it
    holds for this address; `off` would make every enrolment a retype. The
    ABSENCE of `name` is what keeps a native submit from becoming
    `GET /grant?token=<key>`: only a named field joins a form submission, and
    the script reads the field through `data-key` instead."""
    html = GRANT.read_text(encoding="utf-8")
    start = html.index('<input id="key"')
    field = html[start : html.index(">", start) + 1]
    assert 'autocomplete="current-password"' in field, field
    assert 'type="password"' in field, field
    assert " name=" not in field and "data-key" in field, field


# -- #433, #463: the stop dialogs agree with their count and their row --------


def _code(name: str) -> str:
    return stripped((WEB / name).read_text(encoding="utf-8"))


def test_stop_alls_plural_strings_branch_on_the_size_of_the_set() -> None:
    """#433 item 2. Each string has a conditional on `bulk.rows.length` just
    before it, so a set of one reads in the singular."""
    source = (WEB / "stop_all.js").read_text(encoding="utf-8")
    for plural, singular in (
        ("Do not wait, kill them all", "Do not wait, kill it now"),
        ("which sessions finished", "whether the session finished"),
    ):
        assert plural in source and singular in source, (plural, singular)
        for text in (plural, singular):
            before = source[: source.index(text)]
            assert "bulk.rows.length === 1" in before[-220:], text


def test_a_wait_follows_the_policy_of_the_row_and_of_the_answer() -> None:
    """#433 item 1, as structure: the e2e tests are what prove the words."""
    assert re.search(r"wait\.policy\s*=\s*current\.stop_policy", _code("wait.js"))
    assert re.search(
        r"repaintWaiting\(\s*project\s*,\s*wait\s*,\s*result\.body\s*\)", _code("stop.js")
    )


def test_the_timed_out_dialog_gives_a_detached_agent_the_signal_route_and_never_kill() -> None:
    """#463. A `detached` agent is alive, so the dialog stays, but the engine
    refuses /kill for every detached row. The branch must precede the guard
    that closes for a row that is not running, and must reach /signal through
    `confirmSignal` and not `killNow`. Read from the lines that are not
    comments, since the comments name the same words."""
    source = (WEB / "wait.js").read_text(encoding="utf-8")
    code = " ".join(
        line.strip() for line in source.splitlines() if not line.strip().startswith("//")
    )
    detached = code.index('current.state === "detached"')
    guard = code.index('current.state !== "running"')
    assert detached < guard
    branch = code[detached:guard]
    assert "confirmSignal(" in branch
    assert "killNow" not in branch
