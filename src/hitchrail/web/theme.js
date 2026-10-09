import { $ } from "/dom.js";

/* -- theme -------------------------------------------------------------
   The stylesheet defines the palette three times: bare :root, the system
   preference, and an explicit [data-theme]. All this does is set the third,
   so a person who chooses keeps their choice under either system setting.
   Stored per browser, and a failure to store must never stop the page: a
   private window throws on localStorage in some browsers. */
const THEME_KEY = "hitchrail-theme";

export function storedTheme() {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch {
    return null;
  }
}

/* #323. `null` is System: the key is removed, which is the state the header
   toggle can never return to once it has stored a choice. */
export function storeTheme(theme) {
  try {
    if (theme) localStorage.setItem(THEME_KEY, theme);
    else localStorage.removeItem(THEME_KEY);
  } catch {
    /* The choice still applies to this page view; it just is not remembered. */
  }
}

/* The theme-color metas still follow the system, so Chrome's address bar keeps
   the system colour under an explicit choice (#470). Accepted: rewriting the
   metas from here would put a second copy of the palette in script, and the
   bar is outside the page. */
export function applyTheme(theme) {
  if (theme) {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  const dark = theme
    ? theme === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;
  const toggle = $("[data-theme-toggle]");
  if (toggle) {
    // The button offers the OTHER theme, so its name is what you will get. An
    // icon since #322, with the word kept as its accessible name.
    const glyph = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    glyph.setAttribute("class", "icon-glyph");
    glyph.setAttribute("aria-hidden", "true");
    glyph.setAttribute("focusable", "false");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", dark ? "#icon-sun" : "#icon-moon");
    glyph.append(use);
    const word = document.createElement("span");
    word.className = "offscreen";
    word.textContent = dark ? "Light" : "Dark";
    toggle.replaceChildren(glyph, word);
  }
}

export function toggleTheme() {
  const dark = document.documentElement.getAttribute("data-theme") === "dark"
    || (!document.documentElement.hasAttribute("data-theme")
        && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const next = dark ? "light" : "dark";
  storeTheme(next);
  applyTheme(next);
}
