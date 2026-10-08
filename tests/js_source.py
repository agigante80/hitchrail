"""Reading the web scripts as code, for the guards in `test_web.py`.

Not a JavaScript parser: enough of one to tell code from comments, string
bodies and regex literals, which is what a guard needs so that it matches
code that runs and not prose that explains it (#308), and so that a quote
inside a regex literal does not swallow the code after it (#342).
"""

from __future__ import annotations

import re

# The names whose assignment, call or keyed access renders a string as markup.
SINK_NAMES = ("innerHTML", "outerHTML", "insertAdjacentHTML")

# A `/` after one of these starts a regex literal; after anything else (an
# identifier, a number, `)` or `]`) it divides. The keyword list covers the
# words a regex can follow; an identifier that merely ends in one of them is
# told apart by the word boundary.
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = re.compile(r"(?:^|[^\w$])(?:return|typeof|case|do|else|in|of|void|yield)$")


def _regex_allowed(out: list[str], start: int) -> bool:
    k = start - 1
    while k >= 0 and out[k].isspace():
        k -= 1
    if k < 0:
        return True
    if out[k] in _REGEX_AFTER:
        return True
    return bool(_REGEX_KEYWORDS.search("".join(out[max(0, k - 8) : k + 1])))


def stripped(source: str) -> str:
    """The same source with every comment, string body and regex literal
    blanked to spaces, length preserved.

    Two exceptions, both #342's. A template literal's `${...}` is code, and
    is kept: `${(el.innerHTML = x)}` runs. And a string whose whole content is
    a sink name is kept, so `el["innerHTML"] = x` and `{"innerHTML": x}` stay
    visible to `SINK`; prose that merely mentions one is blanked as before.
    """
    out = list(source)
    n = len(source)

    def blank(start: int, end: int) -> None:
        for k in range(start, end):
            if out[k] != "\n":
                out[k] = " "

    def string(i: int, quote: str) -> int:
        j = i + 1
        while j < n and source[j] != quote:
            j += 2 if source[j] == "\\" else 1
        end = min(j + 1, n)
        if source[i + 1 : end - 1] not in SINK_NAMES:
            blank(i + 1, end - 1)
        return end

    def regex(i: int) -> int:
        j, in_class = i + 1, False
        while j < n and source[j] != "\n":
            c = source[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
            j += 1
        blank(i + 1, j)
        return j + 1

    def template(i: int) -> int:
        """From the opening backtick to just past the closing one, keeping
        each `${...}` as code by handing it back to `code`."""
        j = i + 1
        while j < n:
            c = source[j]
            if c == "\\":
                blank(j, min(j + 2, n))
                j += 2
            elif c == "`":
                return j + 1
            elif source[j : j + 2] == "${":
                j = code(j + 2, closing="}")
            else:
                if c != "\n":
                    out[j] = " "
                j += 1
        return n

    def code(i: int, closing: str | None = None) -> int:
        depth = 0
        while i < n:
            two = source[i : i + 2]
            c = source[i]
            if two == "//":
                end = source.find("\n", i)
                end = n if end == -1 else end
                blank(i, end)
                i = end
            elif two == "/*":
                close = source.find("*/", i)
                end = n if close == -1 else close + 2
                blank(i, end)
                i = end
            elif c in "\"'":
                i = string(i, c)
            elif c == "`":
                i = template(i)
            elif c == "/" and _regex_allowed(out, i):
                i = regex(i)
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                if closing and depth == 0:
                    return i + 1
                depth -= 1
                i += 1
            else:
                i += 1
        return n

    code(0)
    return "".join(out)


# Any appearance of a sink name in code: a property, a call, a quoted key or
# an object key. Nothing in `web/` reads one either, so no legitimate use is
# caught by matching the bare name.
SINK = re.compile(r"\b(?:" + "|".join(SINK_NAMES) + r")\b")
