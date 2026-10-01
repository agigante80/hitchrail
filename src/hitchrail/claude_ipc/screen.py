"""Reading a Claude Code pane: whether its input box is clear, and whether it waits on a person.

Part of the `claude_ipc` quarantine (#368); the package docstring says why it exists.
Every rule here is a fact about the vendor's screen layout, captured rather than described.
"""

from __future__ import annotations

# The prompt ornament, captured from a real session rather than described.
# Written as an escape rather than pasted: U+276F is confusable with a plain
# `>` in every editor.
#
# **The ornament ALONE, deliberately.** The input box renders it followed by a
# non breaking space, and the first version of this anchor included that NBSP.
# The trust modal (#88) renders the same ornament with a colour reset and an
# ORDINARY space after it, so the longer anchor matched nothing on a modal, the
# row came back unjudged, and the sequence would have typed into a prompt whose
# entries are actionable. That is the case this check most needs to catch, so
# the anchor is the part both rows share.
_PROMPT = "\u276f"

# Dim. Claude Code renders its own suggested prompt with this and a person's
# draft without it, which is the only thing that tells the two apart.
_DIM = "\x1b[2m"

# #208. How many rows of content may follow the ornament row for it to be the
# LIVE one. A modal is drawn where the input box was, so below the selected
# option there are only the modal's own rows: the remaining options and the
# hint. Both captured screens (the exit modal on #165, the trust modal on #88)
# show two. Three is one row of slack for a modal with one more option, and no
# more, because the failure direction to prefer is a missing warning over a
# key into a working agent. A number, and a fact about the vendor's layout,
# which is why it lives here and nowhere else.
_MODAL_TAIL_ROWS = 3


# CSI and OSC sequences, for deciding whether what is left is only padding.
#
# **Narrower than it looks like it should be, on purpose.** Round 2 of #89's
# review widened this to strip any two character escape as well, because an
# `ESC ( B` charset designator surviving into an otherwise empty box makes the
# box read as dirty and refuses every graceful stop on that terminal.
#
# That widening introduced something worse than the problem. `\x1b[@-Z\\-_]`
# followed by an optional trailing character ate one PRINTABLE character after
# a two character escape, so a one character draft read as an empty box and the
# exit command would have been appended to it and submitted with the
# operator's authority: the guard producing the exact failure it exists to
# prevent (#91).
#
# Round 3 found that, which put two consecutive review rounds on defects inside
# the previous round's fix. The project's own rule is to stop there rather than
# patch again, so this went BACK to the narrower pattern instead of being
# adjusted a third time. The `ESC ( B` case is still open, as #97, and it fails
# CLOSED: such a terminal refuses stops rather than mistyping into them, which
# is the direction to be wrong in.
def _without_escapes(text: str) -> str:
    """Every escape sequence removed, and NOTHING else.

    #97, and a parser rather than a third regex, because the two regexes before
    it failed in opposite directions and that is evidence about the approach
    rather than about the attempts.

    The first matched CSI and OSC only, so the charset designator `ESC ( B`
    survived and an EMPTY box read as dirty: on a terminal that emits it every
    graceful stop was refused, permanently. Failing closed is the right
    direction and failing closed TOTALLY is the worst shape a working guard can
    have.

    The second widened the pattern to any two character escape, and its
    trailing `[0-9A-Za-z]?` ate one PRINTABLE character after one. `ESC M`
    swallowed the `a` in a one character draft, an empty box was reported, and
    the stop would type into a half written sentence. That is failing OPEN on
    the one guard whose whole job is to fail closed, which is worse than what it
    fixed.

    A regex cannot express "consume exactly this sequence and not the character
    after it" for every form at once without becoming unreadable, so this walks
    the string. Each branch consumes precisely its own sequence and stops:

    - `ESC [` ... a final byte in `@` to `~`, which is CSI, colours included.
    - `ESC ]` ... terminated by BEL or by a string terminator, which is OSC, the title.
    - `ESC` then one of `( ) * +` then ONE character: a charset designator, the
      case #97 is named for.
    - `ESC` then one other character: everything else, and the byte after the
      escape is consumed, never the one after THAT.

    An `ESC` at the very end of the capture is dropped rather than treated as
    text, because a truncated read is not a draft.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch != "\x1b":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        kind = text[i]
        if kind == "[":
            i += 1
            while i < n and not ("\x40" <= text[i] <= "\x7e"):
                i += 1
            i += 1
        elif kind == "]":
            i += 1
            while i < n:
                if text[i] == "\x07":
                    i += 1
                    break
                if text[i] == "\x1b" and i + 1 < n and text[i + 1] == "\\":
                    i += 2
                    break
                i += 1
        elif kind in "()*+":
            # The designator's argument is one character, and exactly one.
            i += 2
        else:
            i += 1
    return "".join(out)


def input_is_clear(pane: str) -> bool | None:
    """Whether the agent's input box holds nothing the operator typed.

    `None` means the question could not be answered, and it is deliberately not
    `False`: a capture that failed, a pane still painting, or a layout we have
    not seen is not evidence of a draft, and reporting one would refuse a stop
    on no evidence. What the caller does with `None` depends on whether it saw
    a pane at all, and `_require_clear` is where that is decided; this function
    only reports what it can and cannot see.

    The three states, captured from a real session on 2026-09-02:

        clear        '\x1b[39m\u276f\xa0                     '
        placeholder  '\x1b[39m\u276f\xa0\x1b[2mTry "how does <filepath> work?"'
        draft        '\x1b[39m\u276f\xa0draft text here          '

    **The placeholder is transient**, which is the part every description of
    this row has missed. It appeared about nine seconds after start and was
    gone on the next sample, and a box cleared with `C-u` comes back with no
    placeholder at all. A check written as "the dim placeholder came back"
    therefore fails on the ordinary resting state of an idle session, which is
    most stops, and it fails closed so it would have looked like the mechanism
    working.

    The last matching row is the input box, because that box is at the bottom
    of the screen and agent output above it may say anything.

    #88's trust modal renders its selected entry with the same ornament and
    bright colour, so it reads as not clear and the stop is refused. That is
    the right answer arrived at without a list of modal wordings to maintain,
    and there is a test for it built from the captured row rather than from a
    description of it, which is what caught the anchor being too long.
    """
    row = next((line for line in reversed(pane.splitlines()) if _PROMPT in line), None)
    if row is None:
        return None
    after = row.split(_PROMPT, 1)[1]
    if after.lstrip().startswith(_DIM):
        return True
    return _without_escapes(after).strip() == ""


def _live_ornament_row(pane: str) -> str | None:
    """The last row carrying the ornament, if it is still the live UI (#208).

    Scanning backwards finds the last ornament row, and the last one is not
    always the current one: a modal that was answered and scrolled up still
    wins while the agent works, if nothing newer has drawn an ornament row.
    The agent's output below it is the evidence that it moved on. Rows that
    are blank once their escapes are gone do not count: a terminal pads to the
    pane height, and a redraw can leave a bare colour reset behind.
    """
    rows = pane.splitlines()
    index = next((i for i in range(len(rows) - 1, -1, -1) if _PROMPT in rows[i]), None)
    if index is None:
        return None
    below = sum(1 for row in rows[index + 1 :] if _without_escapes(row).strip())
    return rows[index] if below <= _MODAL_TAIL_ROWS else None


def shows_input_box(pane: str) -> bool | None:
    """Whether the agent is sitting at an ORDINARY input box (#100).

    A different question from `input_is_clear`, which asks whether it is safe
    to type. That one cannot answer this: #89 deliberately shortened `_PROMPT`
    to the ornament alone so a modal and an input box would BOTH match, which
    is right for a stop and useless for a listing. It returns False for a modal
    and equally for a person's half typed draft, and a row built on it would
    say "waiting for an answer" about a session somebody is typing in.

    What separates them is the character the anchor gave up. Captured from a
    real session on 2026-09-02:

        input box    '\x1b[39m\u276f\xa0                     '
        trust modal  '\x1b[39m \x1b[38;5;153m\u276f\x1b[39m \x1b[38;5;153mNo,'

    The box renders the ornament followed by a NON BREAKING space. The modal
    renders the same ornament followed by a colour reset and an ORDINARY one.

    **The escapes are deliberately NOT stripped first**, and that is the whole
    of the correctness here. `_without_escapes` exists for the other predicate
    and carries a documented history of eating one printable character after a
    two character escape (#97). The character it would eat here is the U+00A0
    itself, which inverts the answer and reports a healthy box as stuck. So
    this looks at the character IMMEDIATELY after the ornament and nothing
    else.

    `None` when no ornament row is present at all, which is an ordinary state:
    an agent mid turn has printed over it. Also `None` when the last ornament
    row has more than `_MODAL_TAIL_ROWS` rows of content below it (#208): that
    is a modal or a box the agent has scrolled past, and the output under it
    is the evidence. Unknown is not "stuck", and the caller must test
    `is False` rather than falsiness.

    **This covers modals nobody has captured yet, but only those that reuse the
    ornament.** One drawn without it returns `None` and goes unflagged, which
    is the honest failure direction: a missing warning rather than a false one.
    """
    row = _live_ornament_row(pane)
    if row is None:
        return None
    return row.split(_PROMPT, 1)[1].startswith("\xa0")


def awaits_answer(pane: str) -> bool | None:
    """Whether the pane holds a question a person could answer (#204).

    Built on `shows_input_box`, and deliberately NOT its plain negation. That
    function has three answers and only one of them means a keystroke would
    help:

        True   an ordinary input box. Nothing is being asked. NOT answerable.
        False  the ornament is there and the box is not. A modal. Answerable.
        None   no ornament row at all. Cannot tell, so NOT answerable.

    **`None` must not collapse into answerable**, which is what `not box` would
    do. A capture that failed, or an agent mid turn that has printed over its
    own prompt, is not evidence of a question. Sending a key on no evidence is
    a key into whatever happens to be on the screen, and for `Enter` on a
    returned input box that means submitting whatever it holds.

    So this returns the same three-valued answer and the caller must test
    `is True`. Control 7: refuse rather than guess.

    **A modal still in the scrollback used to read as live (#208).** The row
    is found by scanning backwards for the ornament, so a modal that had been
    answered and scrolled up still won while the agent worked, if nothing
    newer had drawn an ornament row. Harmless while #100 only drew a badge;
    #204 turned the same answer into a keystroke into a working agent. Fixed
    in `_live_ornament_row`, which `shows_input_box` and therefore this share:
    the output below the row is the evidence it is no longer the live UI, and
    the allowance is a captured fact about the vendor's layout, kept here.
    """
    box = shows_input_box(pane)
    if box is None:
        return None
    return not box
