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
/* Status 0, which no HTTP response carries, so a caller can tell "we never got
   an answer we can use" from any answer the server actually gave. */
function unreachable(message) {
  return { ok: false, status: 0, body: { code: "unreachable", message } };
}

export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "content-type": "application/json" },
      ...options,
    });
  } catch {
    // `fetch` REJECTS when the network is gone, where a REFUSED request
    // resolves. Caught HERE and not at each call site, because this helper
    // exists so every caller treats a failure the same way, and a rejection
    // that escapes lands in a click handler that has already rendered a
    // success: tapping Stop with the wifi off left "Waiting for it to finish"
    // on screen for a request that was never made. An error rendered as a
    // success is worse than no guard.
    return unreachable("The connection dropped.");
  }
  if (response.ok) {
    try {
      return { ok: true, status: response.status, body: await response.json() };
    } catch {
      // A 200 whose body does not arrive or does not parse. The connection
      // dropping AFTER the headers is the same wifi in a lift as above, and a
      // captive portal answering `200 text/html` is the other one. The server
      // refused nothing, so this is not a refusal, and it must not reach a
      // caller as a success carrying an undefined body.
      //
      // Reading the body was outside the catch when it was first written, so
      // `api` still rejected on this path while the comment below said it did
      // not, and removing `refresh`'s own catch on the strength of that made
      // the page keep asserting it was live when the listing had failed.
      //
      // The REAL status, not 0. We reached the server and it answered; what
      // failed was reading the answer. That is a different thing from never
      // having got one, and the listing turns the two into different words on
      // screen: "not live" sends somebody to look at their network, and this
      // one should not.
      return {
        ok: false,
        status: response.status,
        body: { code: "unreadable_answer", message: "The answer could not be read." },
      };
    }
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
  // #88. `running` is true and useless here: the agent is alive and sitting on
  // a prompt that only somebody at a terminal can answer, so it will sit there
  // forever. A row saying nothing but "running" is the interface asserting
  // something it knows to be misleading, which the design forbids everywhere
  // else. An overlay like `stopping`, not a fifth state.
  if (project.awaiting_trust) return "waiting";
  return project.state;
}

function metaFor(project) {
  if (project.state === "detached") {
    // The pid, and that no tmux session owns it. This is the state a naive
    // tool gets wrong, so it is never rendered as an ordinary stopped row.
    return `pid ${project.pid}  ·  no tmux session`;
  }
  if (project.state === "stale") return "no agent in the session";
  // Says what to do, because nothing here can do it. Hitchrail cannot answer
  // that prompt on the operator's behalf: that would be agreeing to trust a
  // folder for them, silently, which needs its own argument and does not have
  // one (#88).
  if (project.awaiting_trust) return "waiting to be trusted  ·  open it once in a terminal";
  // #101. Set when a stop's wait ended with the agent on a prompt. The row has
  // to carry it too: the dialog can be dismissed, and the session is still
  // sitting there waiting for somebody.
  if (project.awaiting_input) return "waiting for an answer  ·  open it in a terminal";
  if (project.pid === null) return "";
  return `${formatMb(project.ram_mb)}  ·  up ${formatUptime(project.uptime_s)}`;
}

/* The states whose row is a column: a badge and up to three controls cannot
   share a line with a name on a phone. Named once, because the stylesheet
   lists the same three and the two must not drift. */
const TALL_STATES = new Set(["running", "detached", "stale"]);

/* -- #122: the root a row is in ----------------------------------------
 *
 * A project is `<root-label>~<folder>` on the wire. The interface shows the
 * FOLDER, because that is what the person named, and adds the label only when
 * there is more than one root to tell apart. A single root deployment does not
 * pay for a feature it is not using, which is what #122 asks for and what
 * keeps the one line row the design argues for.
 *
 * Splitting on the FIRST `~` is exact rather than lenient: neither half can
 * contain one, because both are held to the same folder allowlist. */
function splitProject(identifier) {
  const cut = identifier.indexOf("~");
  if (cut < 0) return { label: "", folder: identifier };
  return { label: identifier.slice(0, cut), folder: identifier.slice(cut + 1) };
}

function severalRoots() {
  return (state.roots ?? []).length > 1;
}

/* What to call a project where a person reads it, as opposed to where the API
 * addresses it. With one root that is the bare folder, exactly as before. */
function displayProject(identifier) {
  const { label, folder } = splitProject(identifier);
  return severalRoots() && label ? `${folder} in ${label}` : folder;
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

  const { label, folder } = splitProject(project.name);

  const name = document.createElement("span");
  name.className = "row-name";
  // textContent, never innerHTML. A project name is a folder name and
  // therefore attacker chosen by anybody who can write to the root. The label
  // is not: it comes from `--root`, which the operator typed. Both go through
  // textContent anyway, because the rule is about the sink and not the source.
  name.textContent = folder;
  head.append(name);

  // Only with something to tell apart. One root means one possible answer, and
  // a chip repeating it on every row is noise on the scarcest screen.
  if (severalRoots() && label) {
    const where = document.createElement("span");
    where.className = "row-root";
    where.dataset.rootLabel = label;
    where.textContent = label;
    head.append(where);
  }

  const badge = document.createElement("span");
  badge.className = "badge";
  badge.dataset.badge = badgeFor(project);
  badge.textContent = badgeFor(project);
  head.append(badge);

  const actions = document.createElement("div");
  actions.className = "row-actions";
  // WHERE the actions go is the whole of the mobile layout, and it depends on
  // how many there are (#75, found on a real phone).
  //
  // A stopped row has one control, so it sits on the name's line and the row
  // stays one line tall: that asymmetry is the design's argument for scanning
  // forty rows with a thumb.
  //
  // A tall row has up to three, plus a badge, and they do NOT fit beside a
  // name at 390px. `.row-actions` is `flex-shrink: 0`, so with them inside the
  // head the name was the only thing that could give, and `overflow-wrap:
  // anywhere` let it give down to ONE CHARACTER per line: a five letter
  // project rendered as five stacked letters with `Stop` cut off past the
  // edge. They get their own line instead.
  //
  // The stylesheet already assumed this. `.row[data-state="running"]
  // .row-actions { margin-left: 0 }` only means anything for actions that are
  // a child of the row, and the desktop query putting `auto` back only means
  // anything on a line of their own. The markup was the half that disagreed.
  const ownLine = TALL_STATES.has(project.state);
  if (!ownLine) head.append(actions);
  row.append(head);
  if (ownLine) row.append(actions);

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

/* Where a session link is allowed to point.

   Claude Code prints it as "Continue here, on your phone, or at
   https://claude.ai/code/<id>", and that link is the whole of how a person
   talks to the agent Hitchrail started: this is a launcher, with no input
   control of its own and a read only log drawer.

   Checked here as well as on the server, which allowlists the bridge id's
   SHAPE. This is the second lock, on the whole value, because the string ends
   up in an `href`: anything that is not this exact origin and path is not
   rendered as a link at all, so a `javascript:` value cannot become one. */
const SESSION_URL_BASE = "https://claude.ai/code/";

function sessionHref(url) {
  return typeof url === "string" && url.startsWith(SESSION_URL_BASE) ? url : null;
}

function sessionLink(href, label) {
  const link = document.createElement("a");
  link.className = "btn ghost";
  link.textContent = label;
  link.href = href;
  link.target = "_blank";
  // `noreferrer` as much as `noopener`. Without it the outbound request
  // carries this page's URL, which names a machine on somebody's LAN and the
  // port it serves agents on, to a third party. The token is in a fragment and
  // never sent; the hostname is not.
  link.rel = "noopener noreferrer";
  return link;
}

/* The link, asked for on demand.

   The listing carries only the BRIDGE url, which is read from a file and is
   known good. This route also captures the pane and may come back with one
   scraped out of it, which can be scrollback from a session that ended hours
   ago. #29 decided those must not be shown as equals, so the scraped one
   arrives with its provenance attached rather than as an ordinary link. */
async function showSessionLink(project) {
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}/url`);
  if (!result.ok) {
    if (result.body.code === "url_pending") {
      showDialog({
        title: "No link yet",
        body:
          "This session has not published one. It may still be starting, or "
          + "waiting for an answer in the terminal that only you can give.",
        actions: [["Close", "ghost", () => closeDialog()]],
      });
      return;
    }
    showRefusal(result);
    return;
  }
  const href = sessionHref(result.body.url);
  if (href === null) {
    showDialog({
      title: "That link cannot be opened",
      body: "The session reported a link that does not point at claude.ai.",
      actions: [["Close", "ghost", () => closeDialog()]],
    });
    return;
  }
  if (result.body.source === "bridge") {
    // The row can carry it itself now.
    closeDialog();
    await refresh();
    return;
  }
  showDialog({
    title: "Found in the pane",
    body:
      "This link was read off the terminal rather than published by the "
      + "session, so it may belong to an earlier session in the same pane.",
    actions: [["Close", "ghost", () => closeDialog()]],
    extra: sessionLink(href, "Continue anyway"),
  });
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
  if (isRunning(project)) {
    // "Continue" is Claude Code's own word for it, from the line it prints on
    // start. `Open` next to it is the pane; this is the conversation.
    const href = sessionHref(project.url);
    if (href !== null) {
      actions.append(sessionLink(href, "Continue"));
    } else {
      // A session that has not published a link yet. The listing will not
      // learn of one arriving, because the stream announces state changes and
      // this is not one, so it is asked for rather than waited for.
      add("Get link", "ghost").addEventListener("click", () => showSessionLink(project));
    }
  }
  if (project.state === "stopped") {
    add("Start", "accent").addEventListener("click", () => startProject(project));
  }
  // No Stop control on the controller row, ever. The API answers 423, and an
  // interface that lets you reach a 423 has already failed the person holding
  // the phone: refusing after the tap is worse than not offering the tap.
  if (!project.protected && isRunning(project)) {
    add("Stop", "").addEventListener("click", () => confirmStop(project));
  }
  // A stale session gets Clear, not Stop (#98). Stop asks the agent to exit
  // and there is no agent here, so the API answers `no_agent` every time: the
  // comment above says what that costs, and it applies to a 409 exactly as it
  // does to a 423. Verified against a real tmux rather than assumed, because
  // the old sequence looked like it worked: the quit command an agent
  // understands is not one a shell does, so bash answered "No such file or
  // directory" and the session survived the whole thirty second wait.
  //
  // Clear is the kill route, and it is styled and confirmed as destructive
  // even though no agent can be lost, because `stale` says only that no AGENT
  // is in the session. The pane can be running anything else.
  if (!project.protected && project.state === "stale") {
    add("Clear", "danger").addEventListener("click", () => confirmClear(project));
  }
  // NO control on a detached row, and the absence is the decision (#83).
  //
  // It carried `Kill pid N`, styled `danger`, with no handler and no route
  // behind it: the most consequential tap in the interface, and it did
  // nothing. A browser test asserted the button was VISIBLE and so passed
  // against that forever.
  //
  // Wiring it was the other option and was declined. Every destructive path
  // here is scoped by construction rather than by a check: `kill_session` can
  // only address `hr-<name>`, which is why `Tmux.__init__` refuses an empty
  // prefix. A bare pid has no such scope, and this pid is DERIVED, matched out
  // of `ps` by an argv tail that has been wrong twice this month (#84, and #96
  // still open). Adding the first unscoped destructive path on top of that
  // needs a security argument in the design's section 5, which is #107.
  //
  // The design already chose this shape: `detached` is surfaced with its pid
  // and an explanation, and never silently reconciled, "because the safe
  // action depends on what that agent is doing, which Hitchrail cannot know".
  // The row says what is true and leaves the choice with the person, who has
  // the pid in front of them.
}

function renderList() {
  const list = $("[data-list]");
  if (!list) return;
  const visible = visibleProjects();
  // Announced through a region that is already in the markup, and only when
  // the answer CHANGES. Inserting a live region together with its text is the
  // case assistive technology misses, and `renderList` now runs on every event
  // from any client, so re-cloning the empty state would announce "nothing
  // matches" every time anything happened on the machine.
  // Not the same words as the visible empty state. Two nodes carrying the
  // same string put the page's own test into a strict mode violation, and
  // saying it twice is what a person navigating the page would then hear.
  announce(visible.length === 0 ? "No folders match." : "");
  if (visible.length === 0) {
    const template = $("[data-empty-template]");
    list.replaceChildren(template.content.cloneNode(true));
    return;
  }
  list.replaceChildren(...visible.map(renderRow));
}

function announce(message) {
  const region = $("[data-list-status]");
  if (!region || region.textContent === message) return;
  region.textContent = message;
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
    // The name a PERSON reads, which with several roots says which one.
    // A confirmation naming the wrong project is worse than none.
    title: `Stop ${displayProject(project.name)}?`,
    // #89: this used to say "It will be asked to finish what it is doing",
    // which no version of the sequence has ever done. The first thing sent is
    // an interrupt. Say that, and carry the warning about part done work here
    // rather than only on the kill screen, because the interrupt is where the
    // work is lost and the kill screen is thirty seconds too late to say so.
    body:
      "It will be interrupted, then asked to exit. " +
      "Anything it is part way through may be lost.",
    // Cancel and Stop, and nothing else. A kill control at this step puts the
    // destructive path under the thumb at the same weight as the safe one.
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Stop", "", () => beginStop(project)],
    ],
  });
}

function confirmClear(project) {
  showDialog({
    title: `Clear ${project.name}?`,
    body:
      "The session has no agent in it. Clearing removes the session, and "
      + "anything else still running in it goes too.",
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Clear", "danger", () => killNow(project)],
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
    // Waiting for it to exit, not to finish. The sequence interrupts before it
    // asks anything, so once the request lands there is no grace period being
    // observed: the wait is for the process to go.
    //
    // Careful with "already": `beginStop` paints this BEFORE it awaits the
    // DELETE, so for the first moments nothing has been sent at all. An
    // earlier version of this comment said the interrupt had already happened
    // when the screen appeared, which is the wrong way round.
    body: "Waiting for it to exit.",
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
  // #81. `refresh()` returns whether the listing could be read, and this loop
  // used to discard it. Every listing during the wait could fail and the
  // timeout screen would still state, as fact, that the session has not
  // finished, and offer Kill on the strength of it.
  //
  // That is the project's own rule inverted, at the worst moment. The design
  // says an unreadable machine is an error rather than a state, and control 7
  // says Hitchrail says so rather than guessing. Here it guessed, in the
  // direction of the destructive action, at the point the design itself calls
  // the one where a person is "most likely to reach for it and least likely to
  // have thought about uncommitted work".
  //
  // Starts true because the DELETE that got us here succeeded, so the page did
  // have a good reading a moment ago.
  let lastReadOk = true;
  const tick = async () => {
    const current = state.projects.find((p) => p.name === project.name);
    if (!current) {
      // Gone from the listing entirely: the folder was removed under us.
      closeDialog(project.name);
      return;
    }
    if (!current.stopping) {
      // The marker cleared. That is EITHER the agent having gone, which is the
      // success this dialog is waiting for, OR the engine's own patience
      // running out first and dropping it.
      //
      // This used to close the dialog for both, so a stop that timed out
      // server side vanished from the screen and left the row still running:
      // the page concluding "finished" from the absence of a marker, which is
      // the mistake #81 fixed one branch over. The two timers are independent
      // and either can be the shorter, so this cannot assume its own fires
      // first.
      if (current.state === "stopped") closeDialog(project.name);
      else showTimedOut(project);
      return;
    }
    if (Date.now() >= deadline) {
      // The LAST reading, not "did they all fail". At the deadline the question
      // is what is true NOW, and the answer comes from the most recent listing.
      // If that one failed, the page cannot answer, and one blip costing an
      // honest screen instead of a claim is the right way round to be wrong.
      if (lastReadOk) showTimedOut(project);
      else showLostTrack(project);
      return;
    }
    lastReadOk = (await refresh()).ok;
    window.setTimeout(tick, 700);
  };
  window.setTimeout(tick, 700);
}

function showLostTrack(project) {
  showDialog({
    title: `Lost track of ${project.name}`,
    body:
      "The stop was requested. This browser cannot read the machine, so it "
      + "cannot say whether the session finished.",
    forProject: project.name,
    // NO Kill. Offering the destructive path as the resolution to a reading
    // that failed is the thing this whole change exists to stop: the page
    // would be proposing to end a process it cannot currently see.
    actions: [["Close", "ghost", () => closeDialog()]],
  });
}

function showTimedOut(project) {
  // #101. The wait can end two ways and they need different words.
  //
  // The engine looks at the pane ONCE when the wait expires, and says whether
  // the agent is sitting on something only a person can answer. It often is,
  // and by our own doing: asked to exit with background work running, Claude
  // Code opens a confirmation and waits on it. Telling somebody "it has not
  // finished" then is true and useless, and it offers a kill for a session
  // that is asking them a question.
  //
  // The current row rather than the one captured when the wait began: the flag
  // arrives on the stream after the expiry, so the object this was called with
  // predates it.
  const current = state.projects.find((p) => p.name === project.name) ?? project;
  if (current.awaiting_input) {
    showDialog({
      title: `${project.name} is waiting for you`,
      body:
        "It was asked to exit and answered with a prompt. Only somebody at "
        + "that terminal can reply to it, so Hitchrail has stopped waiting.",
      forProject: project.name,
      // Kill is still here, and still second. The person may well want it, and
      // the warning is the same one: the difference is that they now know what
      // they would be interrupting rather than being told nothing happened.
      actions: [
        ["Leave it", "ghost", () => closeDialog()],
        ["Kill it", "danger", () => killNow(project)],
      ],
    });
    return;
  }
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
    // them with nothing to do.
    //
    // It used to say "open the link with the token again" and offer Reload,
    // which was true when this page was the only one there was. #21 built
    // `/grant`, which takes a key TYPED as well as one in a fragment, so the
    // way back in no longer needs the original link. Reloading, meanwhile,
    // stopped working the moment `/` went behind the token: it answers a raw
    // JSON 401 into a browser window, which is the dead end `/grant` exists to
    // prevent. #57 made this dialog appear on its own, so the wrong button was
    // about to be offered to somebody who never tapped anything.
    //
    // Relative, for the reason `grant.html` argues at length: this page is
    // served from the app root, wherever that is.
    showDialog({
      title: "Not signed in any more",
      body: "This browser is no longer accepted. Sign in again with your access key.",
      actions: [["Sign in", "accent", () => window.location.assign("grant")]],
    });
    return;
  }
  if (code === "no_agent") {
    // #98. Reachable even though no row offers Stop where this applies: a
    // running row can go stale between the render and the tap. Falling through
    // to "That did not work" would describe a request that failed, and this
    // one was declined before anything was sent, which is the distinction the
    // `stop_unsafe` comment below argues at length.
    showDialog({
      // Not "there is no agent to ask": this code now comes back from the KILL
      // route too, where a detached row has a live agent and simply no session
      // to kill. The engine's message names which case it is; the title has to
      // be true of both.
      title: "Hitchrail cannot reach it",
      body: message,
      actions: [["Close", "ghost", () => closeDialog()]],
    });
    return;
  }
  if (code === "stop_unsafe") {
    // #89. Not a failure: the stop looked at the agent's input box, would not
    // vouch for it, and stopped before asking it to exit. "That did not work"
    // describes a request that was made and refused, and this one was never
    // made.
    //
    // It does NOT say "nothing was sent", which was the first wording here and
    // was false. The sequence clears the box and interrupts before either
    // check runs, so keys have gone out by the time this dialog appears and a
    // turn in progress may have been cut short. Claiming the session is
    // untouched is the same untruth this ticket exists to remove, one screen
    // over. The exit command is the thing that was not sent, and that is what
    // the title says.
    //
    // No Kill button here. The person asked to stop gently and got an honest
    // "not from here"; putting the destructive path in front of them as the
    // answer to that is the escalation-by-default section 7 forbids. Kill is
    // still on the row, which is where they chose it deliberately.
    showDialog({
      title: "It was not asked to exit",
      body: message,
      actions: [["Close", "ghost", () => closeDialog()]],
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
  // `isRunning`, not "has a pid". A `detached` row has one and no tmux session
  // to type into, so the API answers `no_agent` and this screen would offer a
  // Stop that cannot work. That is the same defect the stale row had in the
  // commit that added this comment, one screen over, and the same rule
  // decides it: do not offer a tap that refuses.
  //
  // A detached agent can still be the largest thing on the machine. Leaving it
  // out of the SUGGESTION does not hide it: it is on the list with its pid and
  // its memory, which is where it can be acted on.
  const largest = [...state.projects]
    .filter((candidate) => isRunning(candidate) && !candidate.protected)
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

  // #129. A folder is created IN a root, so with more than one the person
  // picks. **An explicit control rather than a guess**, and the losing
  // candidate is worth recording: defaulting to whatever root the current
  // search or filter implied would be right most of the time and silent when
  // it was wrong, and creating in the wrong tree is cheap to undo and
  // expensive to notice. An explicit choice is wrong only when somebody
  // chooses wrongly, and then the screen said so.
  //
  // With ONE root there is no control at all. The same rule the row chip
  // follows: a single root deployment does not pay for a feature it is not
  // using, and a select with one option is a question with one answer.
  const roots = state.roots ?? [];
  let picker = null;
  if (roots.length > 1) {
    picker = document.createElement("select");
    picker.setAttribute("aria-label", "Root");
    picker.className = "sheet-field";
    for (const root of roots) {
      const option = document.createElement("option");
      option.value = root.label;
      // textContent, because the label came from `--root` and this is a sink.
      option.textContent = root.label;
      picker.append(option);
    }
    const showPath = () => {
      const chosen = roots.find((r) => r.label === picker.value);
      path.textContent = `${chosen ? chosen.path : ""}/`;
    };
    picker.addEventListener("change", showPath);
    showPath();
    wrapper.append(picker, path, field);
  } else {
    path.textContent = `${roots[0]?.path ?? state.root}/`;
    wrapper.append(path, field);
  }

  showDialog({
    title: "New folder",
    // No client side name rule. The API decides, and a second copy of that
    // rule here would drift from it; the copy that drifts is the one a person
    // sees.
    body: message || "",
    extra: wrapper,
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Create", "accent", () => createProject(field.value, picker?.value)],
    ],
  });
  field.focus();
}

async function createProject(name, chosen) {
  // #120: the API names a project `<root-label>~<folder>`, so a folder has to
  // be created IN a root. The person typed a folder name, not an identifier,
  // and asking them to type `main~thing` would leak the wire format into the
  // one place the interface is meant to be a folder name box.
  //
  // `chosen` is the picker's value when there is one, and with a single root
  // there is no picker and no question to ask.
  const roots = state.roots ?? [];
  const label = chosen ?? roots[0]?.label;
  if (!label) {
    // **Refuse rather than guess.** No label means the listing did not carry
    // its roots, and sending an unqualified name would either be rejected or,
    // worse, be accepted by some future server and land somewhere nobody
    // chose. Guessing is the defect this ticket exists to remove.
    showNewFolder("Hitchrail does not know which root to create this in.");
    return;
  }
  const identifier = `${label}~${name}`;
  const result = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name: identifier }),
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
let reopenTimer = null;

/* `connecting` and `open` carry no message: a permanent "live" badge is noise
   on a phone, and the state worth a person's attention is the one where the
   list has stopped being true. */
const STREAM_MESSAGE = {
  down: "Not live. Reconnecting.",
  blind: "Live, but this machine cannot be read.",
};

function setStreamState(value) {
  // Reveal FIRST, then write. The text is written rather than selected by CSS
  // from spans already in the markup, because a live region announces a DOM
  // mutation and not a change of computed style: picking a span would mutate
  // nothing at all on the `down` to `blind` step. But writing into a subtree
  // that is still `display: none` puts the mutation somewhere that is not in
  // the accessibility tree yet, which is the same miss by a different route.
  document.documentElement.setAttribute("data-stream", value);
  const note = $("[data-stream-note]");
  if (note) {
    note.textContent = STREAM_MESSAGE[value] ?? "";
  }
}

/* Three states, not two.
   `open`  we are connected.
   `down`  we are not connected.
   `blind` we are connected and the machine cannot be read.
   The third is `503 machine_unreadable` on the re-fetch, and collapsing it
   into `down` would hide a broken tmux behind a network message. */
/* `EventSource` retries a NETWORK error on its own. It does not retry a
   response it refuses: a non 200 status closes it for good, by specification.
   The reachable case is not exotic. Restarting Hitchrail mints a new token, a
   phone still holding the old cookie is answered 401, and the stream is then
   dead forever while the strip says "Reconnecting", which would be a lie of
   exactly the kind this whole feature exists to prevent. */
const REOPEN_MS = 5000;
const REOPEN_CEILING_MS = 60000;
let reopenDelay = REOPEN_MS;

/* Backed off and capped. The motivating case is a token the server stopped
   accepting, which no amount of asking will fix, so a fixed five seconds would
   be one refused request every five seconds for as long as the tab is open. */
function scheduleReopen() {
  if (reopenTimer !== null) return;
  const delay = reopenDelay;
  reopenDelay = Math.min(reopenDelay * 2, REOPEN_CEILING_MS);
  reopenTimer = setTimeout(() => {
    reopenTimer = null;
    openStream();
  }, delay);
}

function openStream() {
  if (reopenTimer !== null) {
    clearTimeout(reopenTimer);
    reopenTimer = null;
  }
  if (stream) stream.close();
  stream = new EventSource("/api/events");
  // Scoped to this EventSource, so it distinguishes the object's FIRST open
  // from one of its own reconnects. A reopen through `openStream` starts a
  // new object and so starts false again, which is right: whoever called it
  // is responsible for the fetch, and `onVisible` does exactly that.
  let connected = false;

  stream.addEventListener("open", () => {
    setStreamState("open");
    reopenDelay = REOPEN_MS;
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

  stream.addEventListener("error", (event) => {
    // Fires for a transient drop and for a final one alike. Both are `down`:
    // a list that has quietly stopped updating is indistinguishable from a
    // quiet one, and quiet is this tool's normal state.
    setStreamState("down");
    // `event.target`, not the module's `stream`: this handler belongs to ONE
    // EventSource, and a superseded one would otherwise read the readyState of
    // whichever object replaced it.
    if (event.target.readyState !== EventSource.CLOSED) return;
    // Fatal. Nothing else would ever reopen it: `onVisible` needs the tab to
    // be backgrounded and brought back, which a phone left on this page never
    // does.
    scheduleReopen();
    // And ASK, once, because the reachable fatal case is a token that stopped
    // being accepted. The strip saying "not live" is honest and useless: the
    // listing is what turns a 401 into the screen that says how to get back
    // in, and nothing else would call it.
    refresh();
  });

  return stream;
}

/* A listing fetched at T0 knows nothing about an event that arrived at T0+1,
   and it lands AFTER it. Without an ordering rule, stopping a session from a
   laptop while the phone happens to be fetching puts the row back to `running`
   and nothing ever corrects it: there is no polling, and a session that
   reached a terminal state sends no further event. So an event that arrives
   while a listing is in flight is kept and re-applied on top of it. */
let fetchesInFlight = 0;
const seenDuringFetch = new Map();

/* Patch one row in place. The whole listing is not re-fetched per event: the
   stream carries the entire session shape precisely so a change costs no
   subprocesses on the server. */
function applySession(session) {
  if (!session || typeof session.name !== "string") {
    // Not a session. The bus carries one shape and a test asserts it, so this
    // is the belt to that braces: an unrecognised frame must not become a
    // refetch, which is how one publisher's mistake turns into a root scan per
    // client per event.
    return;
  }
  if (fetchesInFlight > 0) {
    // Stamped with the generation current AT ARRIVAL, which is how a listing
    // later decides whether this event predates it or not.
    seenDuringFetch.set(session.name, { generation: listingGeneration, session });
  }
  const index = state.projects.findIndex((p) => p.name === session.name);
  if (index === -1) {
    // A project we do not know about, which on this wire means a folder
    // somebody just created. The listing decides what EXISTS, so ask it rather
    // than inventing a row from an event.
    refreshSoon();
    return;
  }
  state.projects[index] = session;
  render();
}

/* One refetch for a burst, not one per event. Creating several folders in a
   script would otherwise cost each connected client a full root scan apiece.

   A real delay, not zero. A due zero millisecond timer runs before the next
   network delivered message, so a zero latch coalesces only frames that arrive
   inside one task, which is not the case this exists for. */
const COALESCE_MS = 150;
let refreshQueued = false;

function refreshSoon() {
  if (refreshQueued) return;
  refreshQueued = true;
  setTimeout(() => {
    refreshQueued = false;
    refresh();
  }, COALESCE_MS);
}

/* The tab came back. `EventSource` may already have reconnected, but it
   cannot replay what it missed, so the listing is re-read. */
function onVisible() {
  if (document.visibilityState !== "visible") return;
  if (!stream || stream.readyState === EventSource.CLOSED) openStream();
  refresh();
}

/* -- start ------------------------------------------------------------- */

/* Take what this listing is allowed to be overruled by, and drop the rest.

   The rule is NOT "an event during any fetch beats that fetch". It is "an
   event beats a listing that was asked for BEFORE it arrived", which is what
   the generation on each held event records. A fetch issued AFTER the event
   is fresher and must win: an agent that exits on its own announces nothing,
   so a listing is the only thing that can ever report it, and overwriting one
   with an older event would hide exactly that.

   Called on every completed listing that is still the newest, failed ones
   included. Anything held at that point is either applied here or already
   stale, since no later fetch can carry a smaller generation. Clearing only on
   success was this fix's own bug: a 503 left an entry behind for some
   arbitrarily later listing to apply. */
function takeHeld(generation) {
  const owed = new Map();
  for (const [name, held] of seenDuringFetch) {
    if (held.generation >= generation) owed.set(name, held.session);
  }
  seenDuringFetch.clear();
  return owed;
}

let listingGeneration = 0;

async function refresh() {
  // Two refetches racing is the ordinary case, not a corner: a phone returning
  // to the foreground fires `visibilitychange` and the stream's own reopen in
  // the same tick. Whichever was issued last owns the list, however they land.
  const generation = ++listingGeneration;
  fetchesInFlight += 1;
  let result;
  try {
    result = await api("/api/projects");
  } finally {
    // `api` does not reject. A dead network and an unreadable body both come
    // back as `ok: false`, the first with status 0 and the second with the
    // status the server actually sent, which is the distinction the branch
    // below turns into "not live" versus "cannot be read". This is here for a
    // throw from `api` itself, and the counter has to come back either way,
    // since leaving it high would hold every later event as owed to a fetch
    // that ended.
    fetchesInFlight -= 1;
  }
  // Superseded. Say nothing and touch nothing: a newer listing owns the page,
  // and reporting THIS one's failure would put "Not live" on a page that is.
  if (generation !== listingGeneration) return result;
  const owed = takeHeld(generation);
  if (!result.ok) {
    if (result.status === 0) {
      setStreamState("down");
      return result;
    }
    if (result.status === 401) {
      // Actionable, and the only failure that is. The stream is being refused
      // too and says so; what a person needs here is the way back in.
      showRefusal(result);
      return result;
    }
    // Connected, and the listing could not be read. Every remaining failure is
    // that, whether the root went away, tmux broke or the server faulted.
    // None of them is `down`: reporting a network problem for a root that was
    // unmounted sends somebody to look at their wifi instead of their mount.
    setStreamState("blind");
    return result;
  }
  if (document.documentElement.getAttribute("data-stream") === "blind") {
    setStreamState(stream && stream.readyState === EventSource.OPEN ? "open" : "down");
  }
  // #120: the payload carries a LIST of labelled roots, one root included.
  // One root still reads as its bare path, because a label the operator never
  // sees does not earn a line on a phone; several read as their labels, which
  // is what the badge on each row matches.
  const roots = result.body.roots ?? [];
  const rootEl = $("[data-root]");
  if (rootEl) {
    rootEl.textContent =
      roots.length === 1 ? roots[0].path : roots.map((r) => r.label).join(", ");
  }
  // `owed` holds only what arrived after this listing was asked for, so those
  // are newer than it whatever order the two landed in.
  state.projects = result.body.projects.map((p) => owed.get(p.name) ?? p);
  state.unsupported = result.body.unsupported;
  state.unsupportedTotal = result.body.unsupported_total;
  state.roots = roots;
  state.root = roots.length === 1 ? roots[0].path : "";
  state.memory = result.body.memory;
  render();
  return result;
}

/* Report how much of the viewport an on screen keyboard is covering (#103).

   Only Safari on iOS needs this. `interactive-widget=resizes-content` in the
   viewport meta makes Chromium and Firefox on Android shrink the LAYOUT
   viewport, so the dialog's own centring puts it back in view and both numbers
   below stay zero. iOS has no such key, resizes only the visual viewport, and
   would otherwise leave a centred sheet with its primary action underneath the
   keyboard.

   `visualViewport` is supported everywhere including iOS, which is why the
   fallback is this and not the VirtualKeyboard API: that one is precise and
   Chromium only, which is the wrong trade for a page opened on whatever phone
   somebody has.

   Guarded, because `visualViewport` is absent in older browsers and the page
   has to work without it: the two custom properties simply keep their
   defaults. */
function trackKeyboardInset() {
  const vv = window.visualViewport;
  if (!vv) return;
  const apply = () => {
    const style = document.documentElement.style;
    style.setProperty("--visible-height", `${Math.round(vv.height)}px`);
    // What the keyboard covers: everything below the visible area's bottom
    // edge. `offsetTop` matters because iOS scrolls the visual viewport rather
    // than only shrinking it, so the visible band can start part way down.
    const covered = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    style.setProperty("--keyboard-inset", `${Math.round(covered)}px`);
  };
  vv.addEventListener("resize", apply);
  vv.addEventListener("scroll", apply);
  apply();
}

function boot() {
  applyTheme(storedTheme());
  trackKeyboardInset();
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
