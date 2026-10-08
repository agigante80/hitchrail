"""The list as the phone it is for holds it (#450).

Every layout test and every screenshot before this used one root and short
names, so a row never had to fit a root chip, a long name, a badge and a button
at once, and the chip strip never held five roots. Three layout defects (#447,
#448, #449) reached a real phone for that reason. This is the world that phone
has: five roots, sixty folders, names that run from short to a full line, and
every state present.

Not a conftest fixture: a test asks for it by name, so a test that does not
need sixty folders does not pay for them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .conftest import SHOT_PREFIX, Harness, e2e_name

# The primary root is always labelled `main` by the harness (4 characters), so
# the four others carry the lengths: 9, 10, 11 and 12.
EXTRA_ROOTS = ("northwind", "greenhouse", "experiments", "side-project")

# What a root holds. Five roots of twelve make sixty.
PER_ROOT = 12

# The widths a phone is held at: the daily phone, and WCAG 1.4.10 Reflow's.
PHONE_VIEWPORTS = (
    {"width": 360, "height": 740},
    {"width": 320, "height": 640},
)

_WORDS = (
    "anchor", "harbour", "personal", "finance", "social", "site", "notes",
    "lab", "archive", "tools", "kit", "api", "garden", "ledger", "scratch",
)  # fmt: skip

# Total displayed lengths of the generic folders, cycled. 6 is unreachable
# under a long harness prefix and is raised to what the prefix leaves room for.
_LENGTHS = (6, 9, 11, 13, 16, 18, 21, 24, 8, 12, 15, 20)


def _shaped(index: int, total: int) -> str:
    """A folder name `total` characters long as the screenshot tier shows it,
    built from words joined by hyphens and underscores, and ending in a
    character that makes it unique within its root.

    **Sized against `SHOT_PREFIX`, not the live prefix.** The e2e prefix
    carries the run's pid and is 5 to 11 characters, which would leave a
    "9 character" name no stem at all. So the rows here run up to seven
    characters longer than their nominal length, which is the harsher
    direction. Indices must differ among names sharing a root, or two clamp
    to the same stem."""
    room = max(total - len(SHOT_PREFIX), 3)
    body = ""
    step = 0
    while len(body) < room:
        body += _WORDS[(index * 3 + step) % len(_WORDS)] + ("-" if step % 2 == 0 else "_")
        step += 1
    body = body[: room - 1]
    if body[-1] in "-_":
        body = body[:-1] + "x"
    return body + "0123456789ab"[index]


def sixteen(tag: str) -> str:
    """A name 16 characters long once the harness prefix is on it, which is
    what the phone showed crushed. The prefix carries the run's pid, so the
    stem's length varies."""
    return f"{tag}-sixteen-letter"[: 16 - len(e2e_name(""))]


@dataclass(frozen=True)
class Busy:
    """What `seed_busy` made, by the names tests need to find."""

    sixteen: dict[str, str]  # state -> the folder, 16 characters displayed
    widest: str  # a running row with no session link and an untrusted folder
    total: int


def seed_busy(server: Harness) -> Busy:
    names = {state: sixteen(state) for state in ("stopped", "running", "stale", "detached")}
    widest = _shaped(11, 14)
    generic = [_shaped(i, _LENGTHS[i % len(_LENGTHS)]) for i in range(PER_ROOT)]
    # `main` also holds the seven rows below, so it gets the first five.
    other_running = [_shaped(7, 11), _shaped(8, 13)]
    server.seed(
        running=[names["running"], widest, *other_running],
        stopped=[names["stopped"], *generic[: PER_ROOT - 7]],
        stale=[names["stale"]],
        detached=[names["detached"]],
        untrusted=[widest],
        stopped_in=dict.fromkeys(EXTRA_ROOTS, generic),
    )
    return Busy(sixteen=names, widest=widest, total=PER_ROOT * (1 + len(EXTRA_ROOTS)))
