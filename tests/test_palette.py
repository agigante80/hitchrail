"""Every foreground and background pair the stylesheets produce passes AA.

#69, and Phase 11's second done-when: "every token pair passes AA". The
criterion is a computation, not a judgement. Tokens retuned by eye until the
badge looks fine is a claim with no check behind it, and the ticket measured
four pairs by hand where this derivation found many more, most of them in
dark mode, which nobody had held up to a number.

The pairs are DERIVED from the rules, not listed here. A rule that sets
`color` and a background is one pair; a rule that sets only `color` inherits
its background from whatever it sits on, and in this interface that is the
ground, a surface or the alternate surface, so it is checked against all
three. Resolved under each of the three palette blocks, because dark is a
token swap and a pair can pass in light and fail in dark.
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

import pytest

from hitchrail import pages

WEB = Path(pages.WEB)
THRESHOLD = 4.5  # WCAG 1.4.3 for text under 18pt; every label here is smaller

# Inactive controls are exempt by WCAG 1.4.3 itself ("text that is part of an
# inactive user interface component has no contrast requirement"), and that is
# the only exemption. Everything else on the page is read.
EXEMPT = {"button[disabled]"}


def _luminance(colour: str) -> float:
    r, g, b = (int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _uncommented(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str) -> list[tuple[str, bool, dict[str, str]]]:
    """Every `:root` declaration block: (selector, inside a dark media query,
    tokens), in file order. By position rather than keyed on the selector,
    because the grant page spells both of its blocks `:root` and only the
    media query around the second one tells them apart."""
    found: list[tuple[str, bool, dict[str, str]]] = []
    for match in re.finditer(r"(:root[^{]*)\{([^}]*)\}", css):
        before = css[: match.start()]
        # Inside a media query if the last `@media` opened before this block
        # has not been closed: its own `{` is still unbalanced at this point.
        opened = before.rfind("@media")
        inside = opened != -1 and before.count("{", opened) > before.count("}", opened)
        tokens = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", match.group(2)))
        found.append((match.group(1).strip(), inside, tokens))
    return found


def themes(css: str) -> dict[str, dict[str, str]]:
    """Light, dark by system preference, dark by explicit choice.

    The dark blocks are overlaid on light, which is how the cascade reads
    them: a token a dark block does not mention keeps its light value.
    """
    blocks = _blocks(css)
    light = next(t for s, inside, t in blocks if s == ":root" and not inside)
    dark_system = next(t for _, inside, t in blocks if inside)
    dark_explicit = next(
        (t for s, inside, t in blocks if not inside and "data-theme" in s), dark_system
    )
    return {
        "light": light,
        "dark (system)": {**light, **dark_system},
        "dark (chosen)": {**light, **dark_explicit},
    }


def _resolve(value: str, tokens: dict[str, str]) -> str | None:
    """A hex colour, through one level of `var()`. Anything else (`transparent`,
    `inherit`, an rgba with alpha) is not a pair this can judge."""
    value = value.strip()
    if match := re.fullmatch(r"var\((--[\w-]+)\)", value):
        value = tokens.get(match.group(1), "").strip()
    return value if re.fullmatch(r"#[0-9A-Fa-f]{6}", value) else None


def pairs(css: str) -> list[tuple[str, str, str, str]]:
    """(theme, selector, foreground, background) for every text rule."""
    css = _uncommented(css)
    # Flatten `@media { ... }` so its inner rules read like top level ones.
    flat = re.sub(r"@media[^{]*\{(.*?)\}\s*\}", lambda m: m.group(1) + "}", css, flags=re.S)
    out: list[tuple[str, str, str, str]] = []
    for theme, tokens in themes(css).items():
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", flat):
            selector = " ".join(selector.split())
            if selector.startswith(":root") and "--" in body:
                continue
            decls = {k.strip(): v for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body)}
            if "color" not in decls:
                continue
            fg = _resolve(decls["color"], tokens)
            if fg is None:
                continue
            explicit = decls.get("background-color") or decls.get("background")
            if explicit is not None:
                backgrounds = [_resolve(explicit, tokens)]
            else:
                backgrounds = [
                    _resolve(f"var({name})", tokens)
                    for name in ("--ground", "--surface", "--surface-alt")
                    if name in tokens
                ]
            out.extend((theme, selector, fg, bg) for bg in backgrounds if bg is not None)
    return out


def _sheets() -> list[tuple[str, str]]:
    app = WEB.joinpath("app.css").read_text()
    grant = WEB.joinpath("grant.html").read_text()
    style = re.search(r"<style>(.*?)</style>", grant, re.S)
    assert style, "the grant page carries no inline stylesheet to check"
    return [("app.css", app), ("grant.html", style.group(1))]


@pytest.mark.parametrize(("name", "css"), _sheets(), ids=[name for name, _ in _sheets()])
def test_every_text_pair_the_stylesheet_produces_passes_aa(name: str, css: str) -> None:
    found = pairs(css)
    assert len(found) > 20, f"{name}: only {len(found)} pairs derived, so this checks little"
    failing = [
        f"{theme}: {selector} puts {fg} on {bg} at {contrast(fg, bg):.2f}:1"
        for theme, selector, fg, bg in found
        if selector not in EXEMPT and contrast(fg, bg) < THRESHOLD
    ]
    assert not failing, f"{name}: {len(failing)} pair(s) under {THRESHOLD}:1\n  " + "\n  ".join(
        failing
    )


def test_the_derivation_sees_the_pairs_the_ticket_measured() -> None:
    """The guard's own guard. #69 named the two badge pairs by hand; if the
    derivation stopped producing them, the test above would go green on a
    stylesheet nobody had checked. Pinned by selector and by the two tokens
    whose whole purpose is these pairs."""
    css = WEB.joinpath("app.css").read_text()
    selectors = {selector for _, selector, _, _ in pairs(css)}
    for badge in ('.badge[data-badge="detached"]', '.badge[data-badge="stale"]'):
        assert badge in selectors, f"{badge} no longer yields a pair"
    for theme, tokens in themes(_uncommented(css)).items():
        for token in ("--danger-on-tint", "--warn-on-tint"):
            assert token in tokens, f"{token} is missing under {theme}"


def test_the_contrast_arithmetic_is_wcag() -> None:
    """Black on white is 21:1 and a colour against itself is 1:1, per the
    formula in WCAG 2.x. A derivation with the wrong arithmetic would pass or
    fail every pair for the wrong reason."""
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#9A3B2B", "#9A3B2B") == pytest.approx(1.0)
    # The pair the ticket called unreadable, at the ratio it measured.
    assert contrast("#9A3B2B", "#4A3E31") == pytest.approx(1.50, abs=0.01)


def _lightness(colour: str) -> float:
    r, g, b = (int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)[1]


def test_the_on_tint_tokens_lean_the_right_way() -> None:
    """A tint is light in light mode and dark in dark mode, so the colour on it
    goes the other way. Pinned so a future retune cannot swap the two blocks."""
    css = _uncommented(WEB.joinpath("app.css").read_text())
    palette = themes(css)
    for token in ("--danger-on-tint", "--warn-on-tint"):
        assert _lightness(palette["light"][token]) < _lightness(palette["dark (chosen)"][token])
