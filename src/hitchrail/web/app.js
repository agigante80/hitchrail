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

/* -- formatting --------------------------------------------------------
   One place, because the footer figure and the row memory column sit on the
   same screen and inconsistency between them reads as a bug. */
export function formatMb(mb) {
  if (mb === null || mb === undefined) return "";
  if (mb < 1024) return `${Math.round(mb)} MB`;
  return `${(mb / 1024).toFixed(1)} GB`;
}

export function formatUptime(seconds) {
  if (!seconds || seconds < 60) return `${Math.max(0, Math.round(seconds || 0))}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

/* -- the list ----------------------------------------------------------
   State lives here and nowhere else. Every render reads it; nothing reads
   the DOM to find out what is true. */
const state = {
  projects: [],
  unsupported: [],
  unsupportedTotal: 0,
  root: "",
  memory: { available_mb: null, total_mb: null },
  tab: "all",
  query: "",
};

/* `Stopped` is NOT the stopped STATE. The canvas computes it as
   `all.length - runNames.length`, so a stale or detached row belongs there:
   it is not running, and those are the two rows a person most needs to find.
   Filtering on the state string would hide exactly them. */
const isRunning = (project) => project.state === "running";

function visibleProjects() {
  const query = state.query.trim().toLowerCase();
  return state.projects.filter((project) => {
    if (state.tab === "running" && !isRunning(project)) return false;
    if (state.tab === "stopped" && isRunning(project)) return false;
    if (query && !project.name.toLowerCase().includes(query)) return false;
    return true;
  });
}

function renderTabs() {
  const running = state.projects.filter(isRunning).length;
  const counts = {
    all: state.projects.length,
    running,
    stopped: state.projects.length - running,
  };
  const strip = $("[data-tabs]");
  if (!strip) return;
  strip.replaceChildren(
    ...[
      ["all", "All"],
      ["running", "Running"],
      ["stopped", "Stopped"],
    ].map(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(state.tab === key));
      button.dataset.tab = key;
      button.append(label);
      const count = document.createElement("span");
      count.className = "tab-count";
      count.textContent = String(counts[key]);
      button.append(count);
      button.addEventListener("click", () => {
        state.tab = key;
        render();
      });
      return button;
    }),
  );
}

function badgeFor(project) {
  // The canvas: `live && live.controller ? 'controller' : 'running'`. The
  // controller badge replaces the state badge rather than sitting beside it.
  if (project.protected) return "controller";
  if (project.stopping) return "stopping";
  return project.state;
}

function metaFor(project) {
  if (project.state === "detached") {
    // The pid, and that no tmux session owns it. This is the state a naive
    // tool gets wrong, so it is never rendered as an ordinary stopped row.
    return `pid ${project.pid}  ·  no tmux session`;
  }
  if (project.state === "stale") return "no agent in the session";
  if (project.pid === null) return "";
  return `${formatMb(project.ram_mb)}  ·  up ${formatUptime(project.uptime_s)}`;
}

function renderRow(project) {
  const row = document.createElement("article");
  row.className = "row";
  row.dataset.project = project.name;
  row.dataset.state = project.state;
  if (project.protected) row.dataset.protected = "true";
  if (project.stopping) row.dataset.stopping = "true";

  const head = document.createElement("div");
  head.className = "row-head";

  const name = document.createElement("span");
  name.className = "row-name";
  // textContent, never innerHTML. A project name is a folder name and
  // therefore attacker chosen by anybody who can write to the root.
  name.textContent = project.name;
  head.append(name);

  const badge = document.createElement("span");
  badge.className = "badge";
  badge.dataset.badge = badgeFor(project);
  badge.textContent = badgeFor(project);
  head.append(badge);

  const actions = document.createElement("div");
  actions.className = "row-actions";
  head.append(actions);
  row.append(head);

  const meta = metaFor(project);
  if (meta) {
    const line = document.createElement("p");
    line.className = "meta";
    line.textContent = meta;
    row.append(line);
  }

  buildActions(project, actions);
  return row;
}

function buildActions(project, actions) {
  const add = (label, className) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    actions.append(button);
    return button;
  };

  if (isRunning(project) || project.state === "stale") {
    add("Open", "ghost");
  }
  if (project.state === "stopped") {
    add("Start", "accent");
  }
  // No Stop control on the controller row, ever. The API answers 423, and an
  // interface that lets you reach a 423 has already failed the person holding
  // the phone: refusing after the tap is worse than not offering the tap.
  if (!project.protected && (isRunning(project) || project.state === "stale")) {
    add("Stop", "");
  }
  if (project.state === "detached" && !project.protected) {
    add(`Kill pid ${project.pid}`, "danger");
  }
}

function renderList() {
  const list = $("[data-list]");
  if (!list) return;
  const visible = visibleProjects();
  if (visible.length === 0) {
    const template = $("[data-empty-template]");
    list.replaceChildren(template.content.cloneNode(true));
    return;
  }
  list.replaceChildren(...visible.map(renderRow));
}

function renderUnsupported() {
  const section = $("[data-unsupported]");
  if (!section) return;
  if (state.unsupported.length === 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  // The TRUE count, not the shown one. Hiding the excess silently is the bug
  // `unsupported_total` exists to fix (#7).
  const shown = state.unsupported.length;
  $("[data-unsupported-title]").textContent =
    state.unsupportedTotal > shown
      ? `${shown} of ${state.unsupportedTotal} folders Hitchrail cannot use`
      : `${shown} folder${shown === 1 ? "" : "s"} Hitchrail cannot use`;
  $("[data-unsupported-list]").replaceChildren(
    ...state.unsupported.map((entry) => {
      const item = document.createElement("li");
      item.dataset.unsupported = entry.name;
      item.textContent = `${entry.name}: ${entry.reason}`;
      return item;
    }),
  );
}

function renderFooter() {
  const { available_mb: available, total_mb: total } = state.memory;
  const label = $("[data-mem-label]");
  if (label) label.textContent = available === null ? "" : `${formatMb(available)} free`;

  const bar = $("[data-mem-bar]");
  if (bar) {
    // No total means no bar. A proportion drawn from a guessed denominator is
    // worse than none at the moment somebody decides whether to start one.
    const usable = total !== null && total > 0;
    bar.style.width = usable ? `${Math.round(((total - available) / total) * 100)}%` : "0";
    bar.parentElement.hidden = !usable;
    if (usable) bar.parentElement.dataset.memPct = String(Math.round((available / total) * 100));
  }

  const count = $("[data-run-count]");
  if (count) count.textContent = `${state.projects.filter(isRunning).length} running`;
}

export function render() {
  renderTabs();
  renderList();
  renderUnsupported();
  renderFooter();
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
  state.projects = result.body.projects;
  state.unsupported = result.body.unsupported;
  state.unsupportedTotal = result.body.unsupported_total;
  state.root = result.body.root;
  state.memory = result.body.memory;
  render();
  return result;
}

function boot() {
  applyTheme(storedTheme());
  $("[data-theme-toggle]")?.addEventListener("click", toggleTheme);
  $("[data-search]")?.addEventListener("input", (event) => {
    state.query = event.target.value;
    renderList();
  });
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
window.__hitchrail = { applyTheme, toggleTheme, refresh, render, state };
