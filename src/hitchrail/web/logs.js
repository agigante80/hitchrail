/* The logs page (#151): one project's pane tail, at a URL of its own.

   Deliberately NOT app.js. That file is the whole interface, and loading it
   here would boot the list, the stream and the dialogs into a page that
   shows one pane. What this needs is a fetch, a render and the honesty rules
   the drawer already follows: a pane that cannot be read says so and never
   reads as "printed nothing", a session that is not running says that, and
   a refused token sends you to the grant flow rather than a dead JSON page.

   Polled, never streamed. `docs/roadmap.md` lists streaming logs under
   "deliberately later"; if this page makes the case for a stream, the case
   goes on its own ticket with the evidence. */

const LINES = 200;
const EVERY_MS = 2000;

const THEME_KEY = "hitchrail-theme";
try {
  const theme = localStorage.getItem(THEME_KEY);
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
  }
} catch {
  /* a private window; the system preference applies */
}

/* The project, from the URL and nowhere else. The server validated it before
   serving this page, and the API validates it again on every fetch, so this
   is a display value: rendered as text, never as markup. */
const name = decodeURIComponent(location.pathname.split("/").pop() ?? "");
const $ = (selector) => document.querySelector(selector);
$("[data-title]").textContent = name;
document.title = `${name} logs`;

function note(message) {
  const strip = $("[data-note]");
  strip.textContent = message;
  strip.style.display = message ? "block" : "none";
}

/* One fetch at a time, and the LAST answer wins: a slow reply arriving after
   a faster one must not paint an older pane over a newer one. */
let generation = 0;
let timer = null;

async function refresh() {
  const mine = ++generation;
  let response;
  try {
    response = await fetch(`/api/sessions/${encodeURIComponent(name)}/logs?lines=${LINES}`, {
      headers: { accept: "application/json" },
    });
  } catch {
    if (mine === generation) note("Not connected. Retrying.");
    return;
  }
  if (mine !== generation) return;
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.status === 401) {
    // The way back in, not a dead end. Same argument as app.js: reloading
    // answers a raw 401 into a browser window, and /grant takes a typed key.
    location.assign("/grant");
    return;
  }
  const pane = $("[data-pane]");
  if (!response.ok || body === null) {
    // Honest refusal. `not_running` is the session having ended while this
    // tab was open; everything else is the pane being unreadable. Neither is
    // rendered as an empty pane, which reads as "it printed nothing".
    const code = body?.code ?? "unreadable_answer";
    const message = body?.message ?? "The answer could not be read.";
    note(code === "not_running" ? `${name} is not running. ${message}` : `Cannot read the pane. ${message}`);
    if (code !== "not_running") pane.dataset.stale = "";
    return;
  }
  note("");
  delete pane.dataset.stale;
  paint(body.text || "The pane has printed nothing yet.");
}

/* #246. The PAGE scrolls, not the pane, so scrolling the pane was a no-op
   and a tab opened on the oldest of two hundred lines. The first render
   lands on the newest; later ones follow the tail only while the reader
   was already at it, the way a terminal does, and leave a person who
   scrolled up to read where they are. */
let first = true;

function atBottom() {
  const root = document.documentElement;
  return window.innerHeight + window.scrollY >= root.scrollHeight - 4;
}

/* Decided BEFORE the text changes: whether the reader was at the tail is a
   fact about the page as it was, and the new text moves the bottom. */
function paint(text) {
  const following = first || atBottom();
  $("[data-pane]").textContent = text;
  if (following) window.scrollTo(0, document.documentElement.scrollHeight);
  first = false;
}

/* The one test seam: the render step itself, so the tier can hand it more
   text than a screen holds without a shim that prints that much, and the
   test cannot drift from the path a real refresh takes. */
window.__logs = { paint };

function schedule() {
  if (timer !== null) clearInterval(timer);
  timer = setInterval(() => {
    if (document.visibilityState === "visible") refresh();
  }, EVERY_MS);
}

$("[data-refresh]").addEventListener("click", refresh);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refresh();
});
refresh();
schedule();
