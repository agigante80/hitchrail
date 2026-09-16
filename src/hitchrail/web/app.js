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

/* #90. The figure and what bounds it, in one phrase: "1.4 GB of 4.0 GB" is
   a different sentence from "1.4 GB", and "no limit" is a fact worth reading
   beside a number rather than an absence. The ceiling is the tightest one
   on the process's cgroup ancestry, read by the server; null means nothing
   Hitchrail can see bounds it, which reads the same to the person holding
   the phone whether the tree was unreadable or genuinely unlimited. */
export function formatMemory(project) {
  const used = formatMb(project.ram_mb);
  const limit = project.ram_limit_mb;
  return typeof limit === "number" ? `${used} of ${formatMb(limit)}` : `${used}, no limit`;
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
  server: { version: null, user: null, started_at: null, stop_timeout: null },
  tab: "all",
  query: "",
  // #146. Root labels to show; empty means all. A Set, never persisted as
  // the source of truth: `localStorage` is a convenience that survives a
  // reload and is intersected with the roots actually present on every
  // listing, so a stale or forged value can only ever show MORE rows.
  rootFilter: new Set(),
  // #154. Labels of configured roots absent from the listing today, so the
  // empty state can say "hidden" rather than "no folder".
  hiddenRoots: [],
  // #107. Detached projects this page has already sent SIGTERM to, so the
  // row offers the escalation and not the same request again. Per page:
  // another client's SIGTERM is not this person's decision to escalate.
  signalled: new Set(),
  // #164. The identifier a suggestion chose, or null. Choosing is exact where
  // typing is a substring: picking `vessel` from the list must not also show
  // `vessel-social`, and the suggestion carried its root, so this is the
  // whole identifier. Cleared the moment the text is edited again.
  chosen: null,
};

const ROOTS_KEY = "hitchrail.roots";

function storedRoots() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ROOTS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : [];
  } catch {
    return [];
  }
}

function rememberRoots() {
  try {
    localStorage.setItem(ROOTS_KEY, JSON.stringify([...state.rootFilter]));
  } catch {
    /* a private window; the filter still applies for this page */
  }
}

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
    // #146. OR among roots, AND with the rest: an empty set is no filter.
    if (state.rootFilter.size > 0 && !state.rootFilter.has(splitProject(project.name).label)) {
      return false;
    }
    // #164. The FOLDER, not the qualified string: roots have chips, and a
    // search over `root~folder` matched the `work` root by coincidence and a
    // folder called `homework` in any root on purpose nobody had.
    if (state.chosen !== null) return project.name === state.chosen;
    if (query && !splitProject(project.name).folder.toLowerCase().includes(query)) return false;
    return true;
  });
}

/* -- #164: the search suggests ----------------------------------------
   The suggestions are the rows the query would show, from `state.projects`
   and nothing fetched: the filter and the popup are two views of one query,
   so the list underneath is always right while the popup is open. */
const SUGGESTION_CAP = 8;
let activeSuggestion = -1;

function suggestions() {
  // #248. A choice is the end of the interaction: the chosen row is the one
  // match and it is on the list already, so the popup stays closed until
  // the text is edited again, whatever renders in between.
  if (state.chosen !== null) return [];
  return state.query.trim() ? visibleProjects().slice(0, SUGGESTION_CAP) : [];
}

function renderSuggestions() {
  const box = $("[data-search]");
  const list = $("[data-suggestions]");
  if (!box || !list) return;
  const items = suggestions();
  if (items.length === 0 || document.activeElement !== box) {
    closeSuggestions();
    return;
  }
  if (activeSuggestion >= items.length) activeSuggestion = -1;
  list.replaceChildren(
    ...items.map((project, index) => {
      const { label, folder } = splitProject(project.name);
      const item = document.createElement("li");
      item.id = `search-option-${index}`;
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(index === activeSuggestion));
      item.textContent = folder;
      if (severalRoots() && label) {
        const where = document.createElement("span");
        where.className = "row-root";
        where.textContent = label;
        item.append(where);
      }
      // `mousedown` rather than `click`: a click follows the input's blur, and
      // the blur has closed the popup by then.
      item.addEventListener("mousedown", (event) => {
        event.preventDefault();
        chooseSuggestion(project);
      });
      return item;
    }),
  );
  list.hidden = false;
  box.setAttribute("aria-expanded", "true");
  const active = activeSuggestion >= 0 ? `search-option-${activeSuggestion}` : "";
  if (active) box.setAttribute("aria-activedescendant", active);
  else box.removeAttribute("aria-activedescendant");
}

function closeSuggestions() {
  const box = $("[data-search]");
  const list = $("[data-suggestions]");
  if (list) {
    list.hidden = true;
    list.replaceChildren();
  }
  if (box) {
    box.setAttribute("aria-expanded", "false");
    box.removeAttribute("aria-activedescendant");
  }
  activeSuggestion = -1;
}

function chooseSuggestion(project) {
  const box = $("[data-search]");
  const { folder } = splitProject(project.name);
  state.query = folder;
  state.chosen = project.name;
  if (box) box.value = folder;
  closeSuggestions();
  renderList();
}

/* The reference pattern's keys and nothing invented: Down and Up move the
   active option, Enter chooses it, Escape closes the popup and leaves the
   text, and a second Escape clears the field. Nothing is chosen by typing. */
function onSearchKey(event) {
  const items = suggestions();
  const open = !$("[data-suggestions]")?.hidden;
  if (event.key === "ArrowDown" && items.length) {
    event.preventDefault();
    activeSuggestion = (activeSuggestion + 1) % items.length;
    renderSuggestions();
  } else if (event.key === "ArrowUp" && items.length) {
    event.preventDefault();
    activeSuggestion = activeSuggestion <= 0 ? items.length - 1 : activeSuggestion - 1;
    renderSuggestions();
  } else if (event.key === "Enter" && open && activeSuggestion >= 0) {
    event.preventDefault();
    chooseSuggestion(items[activeSuggestion]);
  } else if (event.key === "Escape") {
    event.preventDefault();
    if (open) {
      closeSuggestions();
    } else {
      state.query = "";
      state.chosen = null;
      event.target.value = "";
      renderList();
    }
  }
}

/* #146. One button per root, pressed or not, with how many rows it holds.
   Nothing here is a server side parameter: it filters a list the client
   already has in full, and the failure direction is showing MORE rows than
   asked for, never fewer. Labels reach the DOM as text. */
function renderChips() {
  const strip = $("[data-roots]");
  if (!strip) return;
  const roots = state.roots ?? [];
  if (roots.length <= 1) {
    strip.hidden = true;
    strip.replaceChildren();
    return;
  }
  strip.hidden = false;
  const counts = new Map();
  for (const project of state.projects) {
    const { label } = splitProject(project.name);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  strip.replaceChildren(
    ...roots.map((root) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-pressed", String(state.rootFilter.has(root.label)));
      button.dataset.root = root.label;
      // A space before the count, so the accessible name is "bravo 10" and
      // not "bravo10": read aloud, one is a root and a number and the other
      // is a word nobody named anything.
      button.append(`${root.label} `);
      const count = document.createElement("span");
      count.className = "tab-count";
      count.textContent = String(counts.get(root.label) ?? 0);
      button.append(count);
      button.addEventListener("click", () => {
        if (state.rootFilter.has(root.label)) state.rootFilter.delete(root.label);
        else state.rootFilter.add(root.label);
        rememberRoots();
        render();
      });
      return button;
    }),
  );
}

/* Why the list is empty, in the filters' own words, so a person is not told
   "nothing matches" by a filter they set and forgot. */
function emptyReason() {
  const where = state.rootFilter.size > 0 ? ` in ${[...state.rootFilter].join(", ")}` : " here";
  const query = state.query.trim();
  if (query) return `No folder${where} is called that.`;
  if (state.tab === "running") return `Nothing${where} is running.`;
  if (state.tab === "stopped") return `Nothing${where} is stopped.`;
  // #154. Every root hidden is not "no folder": the honest empty state
  // names the roots that are not being listed, and settings is where they
  // come back.
  if (state.projects.length === 0 && state.hiddenRoots.length > 0) {
    return `Every root is hidden (${state.hiddenRoots.join(", ")}). Show one in settings.`;
  }
  return `No folder${where}.`;
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
  // `stopping` outranks `waiting`, and the order of these lines is the
  // statement, not an accident (#183). A stop in flight is the action the
  // person already took, and the wait dialog is where a prompt met during it
  // is reported, with the pane and the keys. A row that is both is one whose
  // stop ran into a question, and the badge names the thing they are waiting
  // ON rather than the thing they are waiting FOR.
  if (project.stopping) return "stopping";
  // #88. `running` is true and useless here: the agent is alive and sitting on
  // a prompt that only somebody at a terminal can answer, so it will sit there
  // forever. A row saying nothing but "running" is the interface asserting
  // something it knows to be misleading, which the design forbids everywhere
  // else. An overlay like `stopping`, not a fifth state.
  //
  // #183. Every clause of that is true of `awaiting_input` too. The two flags
  // are kept apart in `sessions.py` because they are FOUND differently and
  // cost differently, which is a fact about derivation and not about what a
  // row should look like: both answers are "go to the pane", so the badge
  // means "a person is needed" rather than naming which prompt. The meta line
  // still says which. Descriptive only, as #91 requires of a signal an agent
  // can produce: the badge gates nothing.
  if (project.awaiting_trust || project.awaiting_input) return "waiting";
  return project.state;
}

function metaFor(project) {
  if (project.state === "detached") {
    // The pid, and who owns the agent when anything we can see does (#85).
    // This is the state a naive tool gets wrong, so it is never rendered as an
    // ordinary stopped row.
    //
    // **The two branches are not the same claim, and the old single line made
    // the stronger one.** It said "no tmux session", which the server cannot
    // know: ownership is read from one `list-panes -a`, covering the tmux
    // server on Hitchrail's own socket and nothing else. An agent under a
    // different socket, under screen, or under a plain terminal arrives here
    // with `foreign_session` null and is not orphaned at all.
    //
    // Telling somebody their agent is unowned when it is sitting in a terminal
    // they have open invites the wrong action, and the wrong action here is the
    // destructive one.
    if (project.foreign_session) {
      return `pid ${project.pid}  ·  in tmux session ${project.foreign_session}`;
    }
    return `pid ${project.pid}  ·  no session Hitchrail can address`;
  }
  if (project.state === "stale") return "no agent in the session";
  // Says what to do, because nothing here can do it. Hitchrail cannot answer
  // that prompt on the operator's behalf: that would be agreeing to trust a
  // folder for them, silently, which needs its own argument and does not have
  // one (#88).
  if (project.awaiting_trust) return "waiting to be trusted  ·  open the pane to answer";
  // #101. Set when a stop's wait ended with the agent on a prompt. The row has
  // to carry it too: the dialog can be dismissed, and the session is still
  // sitting there waiting for somebody.
  if (project.awaiting_input) return "waiting for an answer  ·  open the pane to answer";
  if (project.pid === null) return "";
  return `${formatMemory(project)}  ·  up ${formatUptime(project.uptime_s)}`;
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
  const word = badgeFor(project);
  badge.dataset.badge = word;
  // #150. The glyph beside the word, never instead of it: decorative to a
  // screen reader, which hears the word, and a shape a scanning eye picks
  // out before it reads. One `<use>` into the inline sprite in index.html.
  const glyph = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  glyph.setAttribute("aria-hidden", "true");
  glyph.setAttribute("class", "badge-glyph");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#badge-${word}`);
  glyph.append(use);
  badge.append(glyph, word);
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
  // #163. The only control on a row that leaves the page, so it says so. The
  // mark is decorative and hidden from the accessible name, which stays the
  // words: a screen reader and a sighted person hear and read the same label.
  const mark = document.createElement("span");
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = " \u2197";
  link.append(mark);
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
    extra: sessionLink(href, "Open it anyway"),
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
    // #162. The word the route, `docs/api.md` and `openLogs` use. It was
    // `Open`, the one control on the row that did not open the session.
    add("Logs", "ghost").addEventListener("click", () => openLogs(project));
  }
  if (isRunning(project)) {
    // #163. The action and its object, no vendor word. One label for one
    // action in two states: a link when the session has published one, and
    // a button that asks for it when it has not, because the listing will not
    // learn of a link arriving on its own. The stream announces state changes
    // and this is not one, so it is asked for rather than waited for.
    const href = sessionHref(project.url);
    if (href !== null) {
      actions.append(sessionLink(href, "Open session"));
    } else {
      add("Open session", "ghost").addEventListener("click", () => showSessionLink(project));
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
  // ONE control on a detached row nothing visible owns (#107), and it is
  // the first destructive control here that names a pid rather than a
  // session. #83 removed a `Kill pid N` that had no route behind it; the
  // route exists now, and the row and the route land together or neither
  // does. Two things keep it honest: the confirmation says what Hitchrail
  // does and does not know, and the server refuses everything the row is
  // wrong about (an owner it can see, a pid that changed, a process that
  // left) rather than the page guessing. A row a visible session owns gets
  // no control: the answer there is "attach there", and it is in the meta.
  //
  // SIGTERM first, and SIGKILL only as a second explicit tap on the same
  // row once the first has been sent: #169's rule that a kill is always
  // available and never the default, kept by rendering the escalation only
  // after the request that precedes it.
  if (!project.protected && project.state === "detached" && !project.foreign_session) {
    const escalate = state.signalled.has(project.name);
    add(escalate ? "Kill" : "End", "danger").addEventListener("click", () =>
      confirmSignal(project, escalate),
    );
  }
}

/* The honest sentence (#107). Not a predicate claiming to know ownership:
   `foreign_session` null means no owner was SEEN, from one `list-panes -a`
   against our own tmux server, and a terminal, screen or another socket
   would all arrive here looking the same. */
function confirmSignal(project, escalate) {
  showDialog({
    title: escalate ? `Kill ${project.name}?` : `End ${project.name}?`,
    body:
      "Hitchrail can see no session that owns this agent. If it is open on a "
      + "screen somewhere, this will end it there too."
      + (escalate
        ? " Kill ends the process immediately, and anything it has not written "
          + "to disk is lost."
        : ""),
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      [escalate ? "Kill it" : "End it", "danger", () => signalNow(project, escalate)],
    ],
  });
}

async function signalNow(project, escalate) {
  const path = `/api/sessions/${encodeURIComponent(project.name)}/signal${escalate ? "/force" : ""}`;
  const result = await api(path, { method: "POST" });
  closeDialog();
  if (!result.ok) {
    showRefusal(result, project);
    return;
  }
  // Remembered so the row offers the escalation next: the server will not
  // send SIGKILL without a second explicit request, and neither will this.
  state.signalled.add(project.name);
  await refresh();
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
  const shown = $("[data-shown]");
  if (shown) {
    shown.textContent =
      visible.length === state.projects.length
        ? ""
        : `${visible.length} of ${state.projects.length} shown`;
  }
  if (visible.length === 0) {
    const template = $("[data-empty-template]");
    const empty = template.content.cloneNode(true);
    const reason = empty.querySelector("[data-empty-reason]");
    if (reason) reason.textContent = emptyReason();
    list.replaceChildren(empty);
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

  // #147. Omitted, not guessed, when the server cannot say: a bare checkout
  // has no distribution metadata, and a wrong number here defeats the one
  // question the line exists to answer.
  const version = $("[data-version]");
  if (version) {
    version.textContent = state.server.version === null ? "" : `hitchrail ${state.server.version}`;
  }
  // #148. Since when, as whom. Formatted HERE, in the viewer's own locale and
  // timezone, and that is not a preference: the server's timezone is the
  // machine's and the phone's is the person's, and a server rendered 15:45
  // is wrong for anybody elsewhere in a way that looks right. Absolute with
  // the relative beside it: relative alone cannot be compared against a
  // journal entry, absolute alone makes a person do arithmetic on a phone.
  const since = $("[data-since]");
  if (since) since.textContent = describeStart(state.server);
}

function describeStart({ user, started_at: startedAt }) {
  const parts = [];
  if (typeof startedAt === "number") {
    const started = new Date(startedAt * 1000);
    const sameDay = started.toDateString() === new Date().toDateString();
    const clock = sameDay
      ? started.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : started.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
    parts.push(`since ${clock} (${formatAgo(Date.now() / 1000 - startedAt)})`);
  }
  if (typeof user === "string" && user !== "") parts.push(`as ${user}`);
  return parts.join("  \u00b7  ");
}

/* Coarse on purpose: the number answers "did this restart while I was not
   looking", and minutes are the finest that question needs. */
function formatAgo(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function render() {
  renderTabs();
  renderChips();
  renderStopAll();
  renderList();
  renderBulk();
  // A listing or an event arriving while somebody is typing: the popup is a
  // view of the same query and must not go on showing the old answer, or
  // stay closed because the first keystroke beat the first listing.
  renderSuggestions();
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
function showDialog({ title, body, actions, extra, forProject, wide = false }) {
  const dialog = $("[data-dialog]");
  if (!dialog) return;
  dialog.replaceChildren();
  delete dialog.dataset.refusal;
  delete dialog.dataset.bulk;
  // #168. Only the pane view asks for room, and only the stylesheet's wide
  // breakpoint grants it: the confirmation and the rest of the stop sequence
  // share this element and keep the phone's column at every width.
  if (wide) dialog.dataset.wide = "";
  else delete dialog.dataset.wide;
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
    // The row goes with it: `stop_unsafe` is refused here and nowhere else,
    // and the dialog that reports it offers a kill that has to name a session.
    showRefusal(result, project);
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

async function showTimedOut(project) {
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
    // #165. The engine captured this pane one screen ago to set the flag this
    // dialog renders, and the first version then sent the reader to "that
    // terminal", which is the one surface the prompt is never on: an operator
    // opened the session link, saw nothing, and concluded the exit request
    // had never been sent. So the question is shown here, in the same pane
    // view `openLogs` renders, keys included, and this is the second capture
    // of that screen: one from the sweep and one for the dialog, affordable
    // because a wait expiring on a prompt is rare and this is the moment the
    // person is deciding whether to kill a process with unsaved work.
    //
    // Fails closed if the pane cannot be read: a note saying so, never an
    // empty box that reads as "the agent is asking nothing".
    const extra = await paneView(current);
    showDialog({
      title: `${project.name} is waiting for you`,
      body:
        "It was asked to exit and answered with a prompt, shown below. Reply "
        + "with a key here or at the pane; Hitchrail has stopped waiting.",
      extra,
      wide: true,
      forProject: project.name,
      // Kill is still here, and still last. The person may well want it, and
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
    showRefusal(result, project);
    return;
  }
  await refresh();
}

/* The server owns the real timeout and reports it on the listing's `server`
   object (#238), so the interface's patience is that number and never a
   second copy of the rule: an operator who started with `--stop-timeout 60`
   used to get a page that gave up at 30 and said "it has not finished"
   while the server was still waiting. Erring long is right: showing "no
   answer" while the engine is still waiting would offer a kill the
   situation does not call for.

   The override exists only so the browser tier can reach the timeout screen
   without waiting thirty seconds per test, and it wins over the server's
   figure until the page is reloaded; a client that shortened it would only
   make itself impatient. */
let stopPatienceMs = null;

function stopTimeoutMs() {
  if (stopPatienceMs !== null) return stopPatienceMs;
  const seconds = state.server.stop_timeout;
  return typeof seconds === "number" && seconds > 0 ? seconds * 1000 : 30_000;
}

export function setStopPatience(ms) {
  stopPatienceMs = ms;
}

function showRefusal(result, project) {
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
    //
    // #71. Left alone if it is already up. The stream's fatal branch asks
    // once per fatal error and the reopen backs off forever, so a phone
    // holding a stale token reached this once a minute, and `showDialog`
    // starts with `replaceChildren`: the screen was torn down and rebuilt
    // under the reader, focus on Sign in included. Same reason, same dialog,
    // nothing to redraw. `showDialog` clears the tag, so any other dialog
    // opened in between makes this one fresh again.
    const dialog = $("[data-dialog]");
    if (dialog?.open && dialog.dataset.refusal === "signed-out") return;
    showDialog({
      title: "Not signed in any more",
      body: "This browser is no longer accepted. Sign in again with your access key.",
      actions: [["Sign in", "accent", () => window.location.assign("grant")]],
    });
    if (dialog) dialog.dataset.refusal = "signed-out";
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
    // #169 put the kill here, and the comment this replaces is why the ticket
    // was filed. It read "Kill is still on the row, which is where they chose
    // it deliberately", and that was false: `renderRow` renders Open, Get
    // link, Start, Stop and Clear, and no kill at all. `killNow` was reachable
    // from three places and all three sit downstream of a `DELETE` that
    // SUCCEEDED, so a refusal here ended the flow before any of them. The
    // session could not be ended from Hitchrail at all.
    //
    // Section 7 forbids escalation by DEFAULT, not availability. Close is
    // first, the kill is second and `danger`, and the warning is the same one
    // `showTimedOut` carries: that is the shape the two timeout dialogs
    // already use for the identical situation reached by a different road.
    // Offering it stays ours; choosing it stays the operator's.
    //
    // Still NOT on the row. A kill control on every running row is the
    // escalation by default the rule does forbid, and it is deliberately a
    // separate question.
    // `stop_unsafe` comes back from the stop route alone, and that route
    // passes the row it acted on, so every path that reaches here has one.
    // The guard is for the other five call sites `showRefusal` serves, which
    // have no row to give: a Kill that cannot name a session is a tap that
    // refuses, and `showHardMemory` builds its own second action this way for
    // the same reason.
    //
    // No `forProject`. That key exists so a background stop finishing can
    // close its OWN waiting dialog and nothing else, and setting it here would
    // let a stop still running on this row shut this refusal out from under
    // the person reading it.
    const actions = [["Close", "ghost", () => closeDialog()]];
    if (project !== undefined) {
      actions.push(["Kill it", "danger", () => killNow(project)]);
    }
    showDialog({
      // One paragraph, concatenated. `showDialog` assigns `textContent` and
      // `.dialog-body` sets no `white-space`, so a `\n\n` here would render as
      // a single space: a paragraph break to whoever wrote it and to nobody
      // reading the page.
      title: "It was not asked to exit",
      body:
        message
        + " Killing it now ends the process immediately, and anything it has "
        + "not written to disk is lost.",
      actions,
    });
    return;
  }
  if (code === "unreadable_answer") {
    // #82. The server answered and the answer did not arrive in one piece.
    // For a stop, a kill, a start or a create, "That did not work" is a guess
    // and it guesses wrong: on a 2xx the action DID happen on the machine, and
    // the next thing a person does about "did not work" is tap Stop again or
    // reach for Kill. The page says exactly what it knows, which is that the
    // request was sent and the reply was unusable, and lets the listing say
    // the rest. `api` keeps the real status for this code, so this branch
    // cannot be reached by a refusal.
    showDialog({
      title: "The reply could not be read",
      body:
        "The request was sent and the server answered, but the answer did "
        + "not arrive in one piece. Nothing here says whether it worked. The "
        + "list will catch up.",
      actions: [["Close", "ghost", () => closeDialog()]],
    });
    return;
  }
  if (["gone", "not_ours", "owned_elsewhere", "not_detached"].includes(code)) {
    // #107. The row was wrong about the world by the time of the tap, and
    // the server refused rather than guessed: the process left, or changed
    // identity, or a session took it, or the row is no longer detached at
    // all. Not a dead end (#169): the next decision is to look again, so
    // the dialog offers the refresh.
    showDialog({
      title: code === "owned_elsewhere" ? "A session owns it" : "Nothing was signalled",
      body: message,
      actions: [
        ["Close", "ghost", () => closeDialog()],
        ["Refresh", "accent", () => {
          closeDialog();
          refresh();
        }],
      ],
    });
    return;
  }
  showDialog({
    title: code === "self_protected" ? "That one is protected" : "That did not work",
    body: message,
    actions: [["Close", "ghost", () => closeDialog()]],
  });
}

/* -- #240: Stop all ----------------------------------------------------
   The stop each row already has, issued for each row, and no new route: a
   DELETE per row can refuse on its own terms, and those refusals are per row
   facts the operator needs per row. Sequentially, never in parallel:
   `request_stop` captures the pane between key groups on the executor that
   serves the operator, and fifty captures at once is the load #180 moved the
   sweep off the request path to avoid. The bulk kill lives inside this wait
   as the escalation, second and styled danger, and reaches only the rows
   still in flight: a row that exited or refused is not killed by it. A
   standalone Kill all was decided against (#241, design section 7). */

let bulk = null;

function stoppableRows() {
  // Stale rows get Clear, not Stop (#98), and are left out; the self project
  // never enters the set.
  return state.projects.filter((p) => isRunning(p) && !p.protected);
}

function renderStopAll() {
  const button = $("[data-stop-all]");
  if (button) button.hidden = stoppableRows().length === 0;
}

function confirmStopAll() {
  // #247. One bulk at a time. A wait that was hidden and is still ticking
  // is reopened rather than started again under its own ticker. A wait
  // whose ticker has stopped is OVER, done or not: its rows were reported,
  // and reopening it forever would leave a person who has started more
  // sessions since with no way to stop them short of killing the old ones.
  //
  // "Over" is a flag the ticker flips where it gives up at the deadline,
  // and nothing else: it is false while the stops are being requested and
  // while they are awaited, which is what makes this guard hold during the
  // request phase too. Round 2 of the review found `ticking` used here,
  // which is unset until the ticker starts, after the LAST request returns,
  // so the guard fell through for the whole phase it was written for.
  if (bulk !== null && !bulk.done && !bulk.over) {
    showBulkWait();
    return;
  }
  const rows = stoppableRows();
  if (rows.length === 0) return;
  showDialog({
    title: `Stop ${rows.length} sessions?`,
    body:
      "Each will be interrupted, then asked to exit, one at a time. "
      + "Anything they are part way through may be lost.",
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Stop all", "", () => beginStopAll(rows)],
    ],
  });
}

async function beginStopAll(rows) {
  bulk = {
    rows: rows.map((p) => ({ name: p.name, status: "queued", message: "" })),
    deadline: null,
    done: false,
    // #247. The ticker belongs to this object: a tick that finds `bulk` is
    // no longer the object it was started for returns without judging it.
    id: Symbol("bulk"),
    // #81's rule, for the bulk case: whether the LAST listing could be read.
    // A deadline reached on failed listings is "lost track", not "not
    // finished", and offers no kill, because that would be proposing to end
    // processes the page cannot currently see.
    lastReadOk: true,
    lost: false,
    over: false,
  };
  showBulkWait();
  for (const row of bulk.rows) {
    // Skipped if the escalation reached it first.
    if (row.status !== "queued") continue;
    row.status = "requesting";
    renderBulk();
    const result = await api(`/api/sessions/${encodeURIComponent(row.name)}`, {
      method: "DELETE",
    });
    if (row.status !== "requesting") {
      // Killed while the request was out. The kill's own outcome stands.
    } else if (result.status === 0) {
      // Never left. Reported as such, never as requested (#74's rule), and
      // the sequence carries on: the next one may get through.
      row.status = "not requested";
      row.message = result.body.message;
    } else if (!result.ok) {
      row.status = "refused";
      row.message = result.body.message;
    } else {
      row.status = "requested";
    }
    renderBulk();
  }
  // The same two fields `killRemaining` resets, and for the same reason
  // (#254): a ticker started by a kill during the request phase can give up
  // before the last request returns, and a fresh wait must not start over.
  bulk.deadline = Date.now() + stopTimeoutMs();
  bulk.over = false;
  await awaitBulk();
}

/* What each row is now, from the listing and the request's own outcome. The
   dialog never says "exited" from anything but the listing. */
function bulkStatus(row) {
  if (row.status !== "requested") return row.status;
  const current = state.projects.find((p) => p.name === row.name);
  if (current && current.state === "stopped") return "exited";
  if (bulk.lost) return "unknown";
  // "Not finished" is the ticker's verdict at the deadline, never the clock's
  // on some other render: the words and the flag flip together.
  if (bulk.over) return "not finished";
  return "requested";
}

/* Every row that is not yet terminal: waiting to be asked, being asked,
   asked, or out of time. "Do not wait" reaches all of them, because the stop
   for the SET was confirmed and begun before the kill became reachable,
   which is the affordance rule; a row that exited or refused is terminal and
   is not touched. */
function bulkInFlight() {
  const live = ["queued", "requesting", "requested", "not finished"];
  return bulk.rows.filter((row) => live.includes(bulkStatus(row)));
}

async function awaitBulk() {
  const mine = bulk;
  if (mine.ticking) return; // #247: one ticker per bulk, however many callers
  mine.ticking = true;
  const tick = async () => {
    // Read once, and compared by identity after every await: Close nulls
    // `bulk`, and a tick must never judge an object it was not started for.
    if (bulk !== mine) return;
    const ok = (await refresh()).ok;
    if (bulk !== mine) return;
    mine.lastReadOk = ok;
    // A reading that succeeded ends "lost": the page can tell again.
    if (ok) mine.lost = false;
    settleBulk();
    renderBulk();
    if (mine.done) return;
    if (mine.deadline !== null && Date.now() >= mine.deadline) {
      // Reports, and does not kill on its own: the engine refuses to
      // escalate by itself and the interface must not do it on its behalf.
      // And if the last reading failed, it does not even report "not
      // finished": the answer is that the page cannot tell.
      if (!ok) mine.lost = true;
      mine.over = true;
      mine.ticking = false;
      renderBulk();
      return;
    }
    window.setTimeout(tick, 700);
  };
  await tick();
}

/* Done is decided here, from the tick AND from every render, so a hidden
   wait stops polling once every row exited and a row exiting after the
   deadline still finishes the dialog. */
function settleBulk() {
  if (bulk === null || bulk.done || bulk.lost) return;
  if (bulk.deadline !== null && bulkInFlight().length === 0) bulk.done = true;
}

function showBulkWait() {
  const list = document.createElement("ul");
  list.className = "bulk-rows";
  list.dataset.bulkRows = "";
  for (const row of bulk.rows) {
    const item = document.createElement("li");
    item.dataset.name = row.name;
    const name = document.createElement("span");
    name.dataset.bulkName = "";
    name.textContent = row.name;
    const status = document.createElement("span");
    status.dataset.bulkStatus = "";
    item.append(name, status);
    list.append(item);
  }
  showDialog({
    title: `Stopping ${bulk.rows.length} sessions`,
    body: "Waiting for them to exit.",
    extra: list,
    actions: [
      ["Hide, keep stopping", "ghost", () => closeDialog()],
      ["Do not wait, kill them all", "danger", () => killRemaining()],
    ],
  });
  $("[data-dialog]").dataset.bulk = "";
  renderBulk();
}

/* Updated in place, never rebuilt: `showDialog` starts with `replaceChildren`,
   and a wait that redraws its whole dialog on every listing takes focus from
   under the thumb, which is #71's defect in a new place. */
function renderBulk() {
  settleBulk();
  const dialog = $("[data-dialog]");
  if (bulk === null || !dialog?.open || !("bulk" in dialog.dataset)) return;
  for (const row of bulk.rows) {
    const item = dialog.querySelector(`[data-bulk-rows] li[data-name="${CSS.escape(row.name)}"]`);
    if (!item) continue;
    const status = bulkStatus(row);
    item.dataset.status = status;
    item.querySelector("[data-bulk-status]").textContent =
      row.message ? `${status}: ${row.message}` : status;
  }
  const body = dialog.querySelector(".dialog-body");
  const unfinished = bulk.rows.filter((row) => bulkStatus(row) === "not finished").length;
  if (bulk.done) {
    if (body) body.textContent = "Done.";
    const actions = dialog.querySelector(".dialog-actions");
    if (actions && actions.children.length !== 1) {
      const close = document.createElement("button");
      close.type = "button";
      close.className = "ghost";
      close.textContent = "Close";
      close.addEventListener("click", () => {
        bulk = null;
        closeDialog();
      });
      actions.replaceChildren(close);
    }
  } else if (bulk.lost) {
    if (body) {
      body.textContent =
        "The stops were requested. This browser cannot read the machine, so "
        + "it cannot say which sessions finished.";
    }
    // NO kill, for the reason `showLostTrack` gives.
    const actions = dialog.querySelector(".dialog-actions");
    if (actions && actions.children.length !== 1) {
      const close = document.createElement("button");
      close.type = "button";
      close.className = "ghost";
      close.textContent = "Close";
      close.addEventListener("click", () => {
        bulk = null;
        closeDialog();
      });
      actions.replaceChildren(close);
    }
  } else if (unfinished > 0 && body) {
    // The risk before the kill is offered, as the single row timeout does.
    body.textContent =
      `${unfinished} ${unfinished === 1 ? "has" : "have"} not finished. Killing now ends `
      + "them immediately, and anything not written to disk is lost.";
  }
}

async function killRemaining() {
  if (bulk === null) return;
  // Only the rows still in flight, one at a time for the same reason the
  // stops are.
  for (const row of bulkInFlight()) {
    const result = await api(`/api/sessions/${encodeURIComponent(row.name)}/kill`, {
      method: "POST",
    });
    if (!result.ok) {
      row.status = "refused";
      row.message = result.body.message;
    } else {
      // A kill is a request too: the listing says whether it exited.
      row.status = "requested";
    }
    renderBulk();
  }
  bulk.deadline = Date.now() + stopTimeoutMs();
  bulk.over = false;
  await awaitBulk();
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
      + (largest ? ` The largest is ${largest.name}, ${formatMemory(largest)}.` : ""),
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

/* -- answering a prompt the agent is blocked on (#204) ------------------ */

// The keys this interface offers, and the only ones the server will carry.
// Mirrors `ANSWER_KEYS` in `claude_ipc.py`, and a test asserts the two lists
// are the same, because a key offered here and refused there is a button that
// does nothing.
//
// **There is deliberately no text field, and adding one is the line.** The
// safety of this whole path is that the operator reads Claude Code's own words
// in the pane above and presses the key those words name. A field would let
// Hitchrail carry an instruction the pane never offered, which is the terminal
// `docs/roadmap.md` defers.
//
// The digits are shown WITHOUT reading the prompt to see which it names.
// Parsing the options is the version-volatile thing this project has got wrong
// three times, and offering a wrong list means a keypress that means something
// other than its label.
export const ANSWER_KEYS = [
  "Up", "Down", "Enter", "Escape",
  "1", "2", "3", "4", "5", "6", "7", "8", "9",
];

// One send at a time. A phone double-tap would otherwise queue two POSTs, and
// while the server's re-read refuses the second in the ordinary case, "the
// second one is usually refused" is not a thing to rely on for a keystroke into
// a shell. Module scoped rather than per-button: the hazard is two KEYS, not
// one button twice.
let answerInFlight = false;

async function sendAnswer(project, key, pane) {
  if (answerInFlight) return;
  answerInFlight = true;
  try {
    await sendAnswerOnce(project, key, pane);
  } finally {
    answerInFlight = false;
  }
}

async function sendAnswerOnce(project, key, pane) {
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}/answer`, {
    method: "POST",
    body: JSON.stringify({ key }),
  });
  if (!result.ok) {
    // Includes `not_asking`, which is the ordinary case rather than an error:
    // the screen moved on between the capture and the press.
    showRefusal(result);
    return;
  }
  // Re-read rather than assuming. The operator pressed a key at a screen and
  // the only honest confirmation is the screen afterwards.
  const fresh = await api(`/api/sessions/${encodeURIComponent(project.name)}/logs?lines=40`);
  if (fresh.ok) {
    pane.textContent = fresh.body.text || "The pane has printed nothing yet.";
  }
}

function answerPad(project, pane) {
  const pad = document.createElement("div");
  pad.className = "answer-pad";

  const note = document.createElement("p");
  note.className = "meta";
  note.textContent = "Read the question above, then press the key it names.";
  pad.appendChild(note);

  const keys = document.createElement("div");
  keys.className = "answer-keys";
  for (const key of ANSWER_KEYS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "answer-key";
    button.textContent = key;
    button.setAttribute("aria-label", `Send ${key}`);
    button.addEventListener("click", () => sendAnswer(project, key, pane));
    keys.appendChild(button);
  }
  pad.appendChild(keys);
  return pad;
}

/* -- the log drawer ---------------------------------------------------- */

/* The pane, with the keypad when the row is waiting on a person. ONE renderer,
   used by the log drawer and by the waiting dialog (#165): `app.js` is past
   the size guideline and #68 is open about it, and the size guard does not
   read `web/`, so this comment is the rule. Never null: an unreadable pane
   yields a note saying so, because a dialog built on this must not show an
   empty box that reads as "nothing is being asked". */
async function paneView(project) {
  const result = await api(
    `/api/sessions/${encodeURIComponent(project.name)}/logs?lines=40`,
  );
  const extra = document.createElement("div");
  if (!result.ok) {
    const note = document.createElement("p");
    note.className = "meta";
    note.textContent = `The pane could not be read: ${result.body.message}`;
    extra.appendChild(note);
    return extra;
  }
  const pane = document.createElement("pre");
  pane.className = "log-pane";
  pane.textContent = result.body.text || "The pane has printed nothing yet.";
  // #204. The keypad appears only for a row the sweep has already flagged as
  // waiting on a person. Not on every log view: a keypad under a healthy
  // session invites a keystroke into a working agent, and the flag is the same
  // one the row badge uses, so what the list says and what this offers agree.
  //
  // The flag is a hint, never the guard. It is up to 30s old by `attention.TTL_S`,
  // and the server re-reads the pane inside the send regardless.
  extra.appendChild(pane);
  if (project.awaiting_trust || project.awaiting_input) {
    extra.appendChild(answerPad(project, pane));
  }
  return extra;
}

async function openLogs(project) {
  const waiting = project.awaiting_trust || project.awaiting_input;
  const extra = await paneView(project);
  // #151. The same tail in a tab of its own, bookmarkable and sized by the
  // window. The drawer stays: reading forty lines without leaving the list
  // is the common case, and this is for watching one project while acting
  // on another. Same origin, so no rel is needed, and a real anchor for the
  // reason the session link is one: it is what long press and open in new
  // tab reach for.
  const tab = document.createElement("a");
  tab.className = "btn ghost";
  tab.href = `/logs/${encodeURIComponent(project.name)}`;
  tab.target = "_blank";
  tab.textContent = "Open in a tab";
  extra.append(tab);
  showDialog({
    title: project.name,
    body: waiting
      ? "this session is waiting for an answer"
      : "last 40 lines of the pane",
    extra,
    wide: true,
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
/* Overridable only so the browser tier can watch several reopen attempts
   without waiting fifteen seconds per test (#71). Same shape and same
   argument as `setStopPatience`: not read from the server, and a client that
   shortened it would only make itself impatient. */
let reopenPaceMs = null;

export function setReopenPace(ms) {
  reopenPaceMs = ms;
  reopenDelay = ms;
}

function scheduleReopen() {
  if (reopenTimer !== null) return;
  const delay = reopenDelay;
  reopenDelay = reopenPaceMs ?? Math.min(reopenDelay * 2, REOPEN_CEILING_MS);
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
  // #165. The confirm, the wait and the waiting dialog all carry `forProject`,
  // and all three are about a RUNNING session's stop. When the row leaves
  // `running`, the process they were about is gone and a waiting dialog would
  // go on showing a prompt nobody can answer, inviting a key into nothing.
  // Any other dialog, a log view or a new folder sheet, carries no `for` and
  // is left alone.
  if (session.state !== "running") closeDialog(session.name);
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
    //
    // #72. Unless the stream is provably NOT live. The fatal branch calls this
    // after the stream closed for good, and "Live, but this machine cannot be
    // read" at that moment is the lie the strip exists to prevent. CLOSED is
    // the test, not OPEN: at boot this runs while the stream is still
    // connecting, and an unreadable machine then is still `blind`, which the
    // recovery branch below already agrees with when it clears it.
    if (!stream || stream.readyState !== EventSource.CLOSED) {
      setStreamState("blind");
    }
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
  // #146. The remembered selection, intersected with what is actually here:
  // a root removed from the command line drops out of the filter, and one
  // root means no filter at all, so a selection stored by an earlier multi
  // root configuration cannot filter the one root to nothing.
  const present = new Set(roots.map((r) => r.label));
  state.rootFilter = new Set(
    roots.length > 1 ? [...state.rootFilter, ...storedRoots()].filter((l) => present.has(l)) : [],
  );
  state.hiddenRoots = result.body.hidden_roots ?? [];
  state.memory = result.body.memory;
  state.server = result.body.server ?? state.server;
  render();
  return result;
}

/* #149. Collapse the header once the list has scrolled under it, and bring
   it back at the top. With hysteresis: collapsing takes ~30px out of the
   page, and on a page barely taller than the viewport that alone can move
   `scrollY` back under a single threshold and flip the header forever. So
   the collapse waits for 48px and the return waits for under 16px, and a
   page that cannot scroll that far never collapses at all. */
function trackScroll() {
  const root = document.documentElement;
  const update = () => {
    const scrolled = "scrolled" in root.dataset;
    const y = window.scrollY;
    if (!scrolled && y > 48 && root.scrollHeight - window.innerHeight > 96) {
      root.dataset.scrolled = "";
    } else if (scrolled && y < 16) {
      delete root.dataset.scrolled;
    }
  };
  window.addEventListener("scroll", update, { passive: true });
  update();
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
  $("[data-stop-all]")?.addEventListener("click", confirmStopAll);
  document.addEventListener("visibilitychange", onVisible);
  openStream();
  trackScroll();
  const search = $("[data-search]");
  search?.addEventListener("input", (event) => {
    state.query = event.target.value;
    state.chosen = null;
    activeSuggestion = -1;
    renderList();
    renderSuggestions();
  });
  search?.addEventListener("keydown", onSearchKey);
  search?.addEventListener("focus", renderSuggestions);
  search?.addEventListener("blur", closeSuggestions);
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
  stopTimeoutMs,
  setReopenPace,
  openStream,
  get stream() {
    return stream;
  },
};
