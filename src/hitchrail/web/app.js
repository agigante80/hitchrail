/* The interface. No build step: this is an ES module the browser runs as
   written, which is what keeps `uvx hitchrail` a single install with nothing
   to compile. See the design's section 9.1. */

const $ = (sel) => document.querySelector(sel);

/* -- theme -------------------------------------------------------------
   The stylesheet defines the palette three times: bare :root, the system
   preference, and an explicit [data-theme]. All this does is set the third,
   so a person who chooses keeps their choice under either system setting.
   Stored per browser, and a failure to store must never stop the page: a
   private window throws on localStorage in some browsers. */
const THEME_KEY = "hitchrail-theme";

function storedTheme() {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch {
    return null;
  }
}

function applyTheme(theme) {
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
    // The button offers the OTHER theme, so its label is what you will get.
    toggle.textContent = dark ? "Light" : "Dark";
  }
}

function toggleTheme() {
  const dark = document.documentElement.getAttribute("data-theme") === "dark"
    || (!document.documentElement.hasAttribute("data-theme")
        && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const next = dark ? "light" : "dark";
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    /* A viewer who cannot store still gets the theme for this page view. */
  }
  applyTheme(next);
}

/* -- talking to the API ------------------------------------------------
   One helper, so every call handles a refusal the same way. The API answers
   every failure with {code, message} except a 413, which Starlette refuses
   before the application exists. */
export async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (response.ok) {
    return { ok: true, status: response.status, body: await response.json() };
  }
  let body = { code: "unreachable", message: response.statusText };
  try {
    body = await response.json();
  } catch {
    /* A 413 is text/plain, and so is anything a proxy inserts. */
  }
  return { ok: false, status: response.status, body };
}

/* -- start ------------------------------------------------------------- */

async function refresh() {
  const result = await api("/api/projects");
  if (!result.ok) {
    return result;
  }
  const root = $("[data-root]");
  if (root) {
    root.textContent = result.body.root;
  }
  return result;
}

function boot() {
  applyTheme(storedTheme());
  $("[data-theme-toggle]")?.addEventListener("click", toggleTheme);
  refresh();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

/* The ONLY test seam. The browser tier needs to reach the stream to simulate
   a suspended tab (#57); exposing application state as well would let tests
   assert on internals and then pass through a rewrite that broke the page. */
window.__hitchrail = { applyTheme, toggleTheme, refresh };
