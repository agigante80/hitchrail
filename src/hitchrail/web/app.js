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
    add("Open", "ghost").addEventListener("click", () => openLogs(project));
  }
  if (project.state === "stopped") {
    add("Start", "accent").addEventListener("click", () => startProject(project));
  }
  // No Stop control on the controller row, ever. The API answers 423, and an
  // interface that lets you reach a 423 has already failed the person holding
  // the phone: refusing after the tap is worse than not offering the tap.
  if (!project.protected && (isRunning(project) || project.state === "stale")) {
    add("Stop", "").addEventListener("click", () => confirmStop(project));
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

/* -- dialogs -----------------------------------------------------------
   One dialog element, reused, because the stop sequence ESCALATES rather than
   branching: the same surface changes what it offers as the situation
   changes. A second dialog for the kill would put the destructive path on
   screen beside the safe one. */

/* `onlyIfFor` is passed DELIBERATELY, never by a listener.
 *
 * This function is handed to `addEventListener` in several places, and a
 * listener receives the click event as its first argument. When this gained a
 * parameter, that event silently became `onlyIfFor`, never matched, and every
 * Cancel and Close stopped working. The call sites wrap it for that reason. */
function closeDialog(onlyIfFor) {
  const dialog = $("[data-dialog]");
  if (!dialog?.open) return;
  // A background stop finishing must not close a dialog somebody opened
  // afterwards. Hide, keep stopping leaves the stop running, so by the time
  // it completes the person may be reading a log drawer or naming a new
  // folder, and closing that out from under them looks like a crash.
  if (onlyIfFor !== undefined && dialog.dataset.for !== onlyIfFor) return;
  dialog.close();
}

/* `actions` are given SAFEST FIRST. The column layout means first is topmost
   and furthest from the thumb, which is the placement section 7 asks for. */
function showDialog({ title, body, actions, extra, forProject }) {
  const dialog = $("[data-dialog]");
  if (!dialog) return;
  dialog.replaceChildren();
  if (forProject === undefined) {
    delete dialog.dataset.for;
  } else {
    dialog.dataset.for = forProject;
  }

  const heading = document.createElement("h2");
  heading.className = "dialog-title";
  heading.textContent = title;
  dialog.append(heading);

  if (body) {
    const paragraph = document.createElement("p");
    paragraph.className = "dialog-body";
    paragraph.textContent = body;
    dialog.append(paragraph);
  }
  if (extra) dialog.append(extra);

  const row = document.createElement("div");
  row.className = "dialog-actions";
  for (const [label, className, onClick] of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    row.append(button);
  }
  dialog.append(row);
  if (!dialog.open) dialog.showModal();
}

/* -- stopping ----------------------------------------------------------
   Confirm, then a wait during which the kill is reachable, then a timeout
   that reports and does NOT escalate on its own. The engine refuses to
   escalate by itself; the interface must not do it on the engine's behalf. */

function confirmStop(project) {
  showDialog({
    title: `Stop ${project.name}?`,
    body: "It will be asked to finish what it is doing.",
    // Cancel and Stop, and nothing else. A kill control at this step puts the
    // destructive path under the thumb at the same weight as the safe one.
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Stop", "", () => beginStop(project)],
    ],
  });
}

async function beginStop(project) {
  showWaiting(project);
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}`, {
    method: "DELETE",
  });
  if (!result.ok) {
    showRefusal(result);
    return;
  }
  await refresh();
  awaitStopped(project);
}

function showWaiting(project) {
  showDialog({
    title: `Stopping ${project.name}`,
    body: "Waiting for it to finish.",
    forProject: project.name,
    actions: [
      // "Hide, keep stopping" first: a modal that owns a phone screen for
      // thirty seconds is one people kill the app to escape.
      ["Hide, keep stopping", "ghost", () => closeDialog()],
      // Phrased as impatience rather than as an alternative, and available
      // for the WHOLE wait rather than only at the end.
      ["Do not wait, kill it now", "danger", () => killNow(project)],
    ],
  });
}

function awaitStopped(project) {
  const deadline = Date.now() + stopTimeoutMs();
  const tick = async () => {
    const current = state.projects.find((p) => p.name === project.name);
    if (!current || !current.stopping) {
      closeDialog(project.name);
      return;
    }
    if (Date.now() >= deadline) {
      showTimedOut(project);
      return;
    }
    await refresh();
    window.setTimeout(tick, 700);
  };
  window.setTimeout(tick, 700);
}

function showTimedOut(project) {
  showDialog({
    title: `No answer from ${project.name}`,
    // The risk BEFORE the kill is offered. This is the moment a person is
    // most likely to reach for it and least likely to have thought about
    // work that is not saved.
    body:
      "It has not finished. Killing it now ends the process immediately, "
      + "and anything it has not written to disk is lost.",
    actions: [
      ["Leave it", "ghost", () => closeDialog()],
      ["Kill it", "danger", () => killNow(project)],
    ],
  });
}

async function killNow(project) {
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}/kill`, {
    method: "POST",
  });
  closeDialog();
  if (!result.ok) {
    showRefusal(result);
    return;
  }
  await refresh();
}

/* The server owns the real timeout and does not report it, so this is a
   ceiling for the interface's own patience rather than a second copy of the
   rule. Erring long is right: showing "no answer" while the engine is still
   waiting would offer a kill the situation does not call for.

   Overridable only so the browser tier can reach the timeout screen without
   waiting thirty seconds per test. It is not read from the server, and a
   client that shortened it would only make itself impatient. */
let stopPatienceMs = 30_000;

function stopTimeoutMs() {
  return stopPatienceMs;
}

export function setStopPatience(ms) {
  stopPatienceMs = ms;
}

function showRefusal(result) {
  const { code, message } = result.body;
  if (result.status === 401) {
    // The token is the whole auth model, so an expired or revoked one is a
    // situation a person can actually be in, and "That did not work" leaves
    // them with nothing to do. Reloading reaches the token screen.
    showDialog({
      title: "Not signed in any more",
      body: "This browser is no longer accepted. Open the link with the token again.",
      actions: [["Reload", "accent", () => window.location.reload()]],
    });
    return;
  }
  showDialog({
    title: code === "self_protected" ? "That one is protected" : "That did not work",
    body: message,
    actions: [["Close", "ghost", () => closeDialog()]],
  });
}

/* -- starting ----------------------------------------------------------
   The two memory refusals are DIFFERENT SCREENS, not one with a variable.
   The soft one asks and can be overridden; the hard one refuses and offers a
   way out. Rendering both from one template with a boolean is how "Start
   anyway" ends up on a screen that cannot start anything. */

async function startProject(project, { acknowledged = false } = {}) {
  const query = acknowledged ? "?acknowledged=1" : "";
  const result = await api(
    `/api/sessions/${encodeURIComponent(project.name)}${query}`,
    { method: "POST" },
  );
  if (result.ok) {
    closeDialog();
    await refresh();
    return;
  }
  if (result.body.code === "ram_soft") {
    showSoftMemory(project, result.body);
    return;
  }
  if (result.body.code === "ram_hard") {
    showHardMemory(project, result.body);
    return;
  }
  if (result.body.code === "start_died") {
    showDeadStart(project, result.body);
    return;
  }
  showRefusal(result);
}

function showSoftMemory(project, body) {
  const left = body.available_mb - body.needed_mb;
  showDialog({
    title: "Tight on memory",
    // What would be LEFT, not what is needed. That is the number the decision
    // turns on, and it is what the canvas puts on this screen.
    body:
      `Starting ${project.name} would leave about ${formatMb(left)} free. `
      + "Sessions have been killed by the kernel below that.",
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Start anyway", "", () => startProject(project, { acknowledged: true })],
    ],
  });
}

function showHardMemory(project, body) {
  // NO "Start anyway" anywhere on this screen. 507 is not overridable, and a
  // control that cannot work is worse than no control.
  const largest = [...state.projects]
    .filter((candidate) => candidate.pid !== null && !candidate.protected)
    .sort((a, b) => b.ram_mb - a.ram_mb)[0];

  const actions = [["Cancel", "ghost", () => closeDialog()]];
  if (largest) {
    actions.push([
      `Stop ${largest.name}`,
      "danger",
      () => confirmStop(largest),
    ]);
  }
  showDialog({
    title: "Not enough memory",
    body:
      `Only ${formatMb(body.available_mb)} free. Hitchrail will not start a `
      + "session into that."
      + (largest ? ` The largest is ${largest.name}, ${formatMb(largest.ram_mb)}.` : ""),
    actions,
  });
}

function showDeadStart(project, body) {
  const pane = document.createElement("pre");
  pane.className = "log-pane";
  pane.textContent = body.output || "It printed nothing.";
  pane.hidden = true;

  showDialog({
    title: `${project.name} died`,
    body: "Started, then exited almost immediately.",
    extra: pane,
    actions: [
      ["Read what it printed", "ghost", () => { pane.hidden = false; }],
      ["Close", "ghost", () => closeDialog()],
    ],
  });
}

/* -- the log drawer ---------------------------------------------------- */

async function openLogs(project) {
  const result = await api(
    `/api/sessions/${encodeURIComponent(project.name)}/logs?lines=40`,
  );
  if (!result.ok) {
    showRefusal(result);
    return;
  }
  const pane = document.createElement("pre");
  pane.className = "log-pane";
  pane.textContent = result.body.text || "The pane has printed nothing yet.";
  showDialog({
    title: project.name,
    body: "last 40 lines of the pane",
    extra: pane,
    actions: [["Close", "ghost", () => closeDialog()]],
  });
}

/* -- the new folder sheet ---------------------------------------------- */

function showNewFolder(message) {
  const field = document.createElement("input");
  field.type = "text";
  field.setAttribute("aria-label", "Folder name");
  field.className = "sheet-field";
  field.value = "";

  const wrapper = document.createElement("div");
  const path = document.createElement("p");
  path.className = "meta";
  path.textContent = `${state.root}/`;
  wrapper.append(path, field);

  showDialog({
    title: "New folder",
    // No client side name rule. The API decides, and a second copy of that
    // rule here would drift from it; the copy that drifts is the one a person
    // sees.
    body: message || "",
    extra: wrapper,
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Create", "accent", () => createProject(field.value)],
    ],
  });
  field.focus();
}

async function createProject(name) {
  const result = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  if (!result.ok) {
    showNewFolder(result.body.message);
    return;
  }
  closeDialog();
  await refresh();
}

/* -- the stream --------------------------------------------------------
   The stream is an INVALIDATION SIGNAL, not the source of truth.

   `EventSource` reconnects on its own; what it cannot do is tell you what
   changed while it was away. A page that only applies events shows a row that
   has been wrong since the tab was suspended, and that looks exactly like a
   row where nothing is happening, which is this tool's normal state.

   So a reconnect re-fetches the listing. The source of truth stays the same
   derivation every other caller gets, which is the design's whole position on
   state. */

let stream = null;

function setStreamState(value) {
  document.documentElement.setAttribute("data-stream", value);
}

/* Three states, not two.
   `open`  we are connected.
   `down`  we are not connected.
   `blind` we are connected and the machine cannot be read.
   The third is `503 machine_unreadable` on the re-fetch, and collapsing it
   into `down` would hide a broken tmux behind a network message. */
function openStream() {
  if (stream) stream.close();
  stream = new EventSource("/api/events");
  // Scoped to this EventSource, so it distinguishes the object's FIRST open
  // from one of its own reconnects. A reopen through `openStream` starts a
  // new object and so starts false again, which is right: whoever called it
  // is responsible for the fetch, and `onVisible` does exactly that.
  let connected = false;

  stream.addEventListener("open", () => {
    setStreamState("open");
    if (connected) {
      // A RECONNECT. The stream was away and cannot say what it missed, so
      // the listing is re-read. The first open needs nothing: `boot` fetches.
      refresh();
    }
    connected = true;
  });

  stream.addEventListener("message", (event) => {
    let session;
    try {
      session = JSON.parse(event.data);
    } catch {
      // A malformed frame is not a reason to tear down a working stream.
      return;
    }
    applySession(session);
  });

  stream.addEventListener("error", () => {
    // `EventSource` retries on its own, so this fires for a transient drop as
    // well as a final one. Both are `down`: what a person needs to know is
    // that the list is not live, and distinguishing "retrying" from "gave up"
    // would be a distinction they cannot act on differently. A list that has
    // quietly stopped updating is indistinguishable from a quiet one, and
    // quiet is this tool's normal state.
    setStreamState("down");
  });

  return stream;
}

/* Patch one row in place. The whole listing is not re-fetched per event: the
   stream carries the entire session shape precisely so a change costs no
   subprocesses on the server. */
function applySession(session) {
  const index = state.projects.findIndex((p) => p.name === session.name);
  if (index === -1) {
    // A project we do not know about. The listing decides what exists, so ask
    // it rather than inventing a row from an event.
    refresh();
    return;
  }
  state.projects[index] = session;
  render();
}

/* The tab came back. `EventSource` may already have reconnected, but it
   cannot replay what it missed, so the listing is re-read. */
function onVisible() {
  if (document.visibilityState !== "visible") return;
  if (!stream || stream.readyState === EventSource.CLOSED) openStream();
  refresh();
}

/* -- start ------------------------------------------------------------- */

async function refresh() {
  const result = await api("/api/projects");
  if (!result.ok) {
    // Connected, and the machine cannot be read. Distinct from `down`, which
    // means we are not connected at all.
    if (result.body.code === "machine_unreadable" || result.body.code === "root_unavailable") {
      setStreamState("blind");
    }
    return result;
  }
  if (document.documentElement.getAttribute("data-stream") === "blind") {
    setStreamState(stream && stream.readyState === EventSource.OPEN ? "open" : "down");
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
  $("[data-new]")?.addEventListener("click", () => showNewFolder());
  document.addEventListener("visibilitychange", onVisible);
  openStream();
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
window.__hitchrail = {
  applyTheme,
  toggleTheme,
  refresh,
  render,
  state,
  api,
  setStopPatience,
  openStream,
  get stream() {
    return stream;
  },
};
