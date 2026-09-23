/* The settings page (#238): what this instance is pointed at, and the two
   things a request may change.

   Deliberately NOT app.js, for the reason logs.js gives: that file boots the
   list, the stream and the dialogs, and this page shows one document. What
   it needs is a fetch of `/api/config`, a render that keeps the two kinds of
   setting apart, and a PATCH for the two the server will take. Every other
   value is rendered as text with where it came from; nothing here is a
   disabled input, because a disabled input says "not now" where the truth
   is "not from here".

   Refusals are shown in the server's words. The server is the authority on
   what is editable, and this page never guesses: a root the config file
   disabled arrives `editable: false` and gets no checkbox, and a stop wait
   pinned by a flag arrives the same way and gets no input. */

const THEME_KEY = "hitchrail-theme";
try {
  const theme = localStorage.getItem(THEME_KEY);
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
  }
} catch {
  /* a private window; the system preference applies */
}

const $ = (selector) => document.querySelector(selector);

function note(message) {
  const strip = $("[data-note]");
  strip.textContent = message;
  strip.style.display = message ? "block" : "none";
}

/* One request at a time and the last answer wins, as logs.js does: a slow
   GET landing after a PATCH must not paint the older document. */
let generation = 0;

/* #256. A request that SUCCEEDS clears the strip; one that carries a
   refusal sets it, and the repaint that follows must not wipe it. `toggle`
   refuses, then repaints from a GET so the checkbox goes back where the
   truth is, and that GET's `note("")` left a checkbox that would not stay
   checked with no sentence saying why. Set here rather than in `toggle`,
   because every caller repaints and the rule is about the pair, not about
   one of them: a refusal's words survive until the next request the person
   makes. */
let keepNote = false;

async function call(method, body) {
  const mine = ++generation;
  let response;
  try {
    response = await fetch("/api/config", {
      method,
      headers: {
        accept: "application/json",
        ...(body === undefined ? {} : { "content-type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    if (mine === generation) {
      note("Not connected. Retrying is up to you: nothing was changed.");
      keepNote = true;
    }
    return null;
  }
  if (mine !== generation) return null;
  if (response.status === 401) {
    location.assign("/grant");
    return null;
  }
  let parsed = null;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  if (!response.ok || parsed === null) {
    // The refusal in the server's words. `code` is the contract and the
    // message is for a person; both are shown, because a person reading
    // `operator_pinned` on a phone still deserves the sentence.
    const message = parsed?.message ?? "The answer could not be read.";
    note(`Not changed. ${message}`);
    keepNote = true;
    return null;
  }
  if (keepNote) keepNote = false;
  else note("");
  return parsed;
}

const SOURCE_WORDS = {
  flag: "from the command line",
  file: "from the config file",
  env: "from the environment",
  state: "set here",
  default: "the default",
  generated: "generated at startup",
  none: "none: loopback only",
};

function sourceText(source) {
  return SOURCE_WORDS[source] ?? source;
}

function renderRoots(config) {
  const list = $("[data-roots]");
  list.replaceChildren(
    ...config.roots.map((root) => {
      const item = document.createElement("li");
      item.className = "settings-root";
      item.dataset.label = root.label;
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = root.enabled;
      box.dataset.rootToggle = root.label;
      // No checkbox for a root the operator disabled: a disabled control
      // would say "not now" where the truth is "not from here". The text
      // says which.
      if (root.editable) {
        box.addEventListener("change", () => toggle(root.label, box.checked, box));
        label.append(box);
      }
      const name = document.createElement("span");
      name.className = "settings-root-name";
      name.textContent = root.label;
      const path = document.createElement("span");
      path.className = "settings-root-path";
      path.textContent = root.path;
      const status = document.createElement("span");
      status.className = "settings-source";
      status.textContent = root.editable
        ? root.enabled
          ? "shown"
          : "hidden here"
        : "disabled in the config file";
      label.append(name, path, status);
      item.append(label);
      return item;
    }),
  );
}

async function toggle(label, enabled, box) {
  box.disabled = true;
  const config = await call("PATCH", { roots: { [label]: { enabled } } });
  box.disabled = false;
  // Either way the page is repainted from what the server holds: on a
  // refusal that puts the checkbox back where the truth is.
  if (config) render(config);
  else refresh();
}

function renderStop(config) {
  const field = $("[data-stop-field]");
  const input = $("[data-stop-timeout]");
  const save = $("[data-stop-save]");
  const source = $("[data-stop-source]");
  const stop = config.stop_timeout;
  input.value = String(stop.value);
  source.textContent = stop.editable
    ? `Currently ${stop.value}s, ${sourceText(stop.source)}.`
    : `${stop.value}s, ${sourceText(stop.source)}. Change the flag to change it.`;
  // Not a disabled input: when a flag pins the wait the number is text.
  field.dataset.editable = String(stop.editable);
  input.hidden = !stop.editable;
  save.hidden = !stop.editable;
}

async function saveStop() {
  const input = $("[data-stop-timeout]");
  const seconds = Number(input.value);
  const ceiling = Number(input.max);
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > ceiling) {
    note(`Not changed. The wait is a whole number of seconds, 1 to ${ceiling}.`);
    keepNote = true;
    return;
  }
  const config = await call("PATCH", { stop_timeout: seconds });
  if (config) render(config);
}

/* Read only, as text, each with where it came from. The token is its
   source alone: the value is never on the wire, by the server's rule. */
const FACTS = [
  ["host", "Bound to"],
  ["port", "Port"],
  ["allow_hosts", "Also answers to"],
  ["allow_origins", "Also allows origins"],
  ["token", "Token"],
  ["self_project", "Protected project"],
  ["agent_binary", "Agent"],
  ["session_prefix", "Session prefix"],
  ["tls", "TLS certificate"],
  ["expect_gateway_mac", "Expected gateway"],
  ["hard_floor_mb", "Hard memory floor, MB"],
  ["soft_floor_mb", "Soft memory floor, MB"],
  ["session_mb", "Per session estimate, MB"],
  ["config_file", "Config file"],
  ["state_file", "State file"],
];

function factValue(key, fact) {
  if (key === "token") return "";
  const value = fact.value;
  if (value === null || value === undefined) return "none";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  return String(value);
}

function renderFacts(config) {
  const facts = $("[data-facts]");
  facts.replaceChildren(
    ...FACTS.flatMap(([key, title]) => {
      const fact = config[key];
      if (!fact) return [];
      const dt = document.createElement("dt");
      dt.textContent = title;
      const dd = document.createElement("dd");
      dd.dataset.fact = key;
      const value = document.createElement("span");
      value.className = "settings-value";
      value.textContent = factValue(key, fact);
      const source = document.createElement("span");
      source.className = "settings-source";
      source.textContent = fact.source ? sourceText(fact.source) : "";
      dd.append(value, source);
      return [dt, dd];
    }),
  );
}

function render(config) {
  renderRoots(config);
  renderStop(config);
  renderFacts(config);
  $("[data-settings]").dataset.loaded = "";
}

async function refresh() {
  const config = await call("GET");
  if (config) render(config);
}

$("[data-stop-save]").addEventListener("click", saveStop);
$("[data-stop-timeout]").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveStop();
  }
});

/* #297. The plugin update. Every render is of the WHOLE record, from the GET
   or from a `plugins` event alike, because the stream does not replay: a page
   opened mid run, or back from a dropped connection, reads the GET and is
   then exactly as current as one that watched from the start. */
const PLUGIN_FAILURES = {
  agent_missing: "The agent could not be run, so nothing was updated.",
  marketplace_refresh_failed: "The marketplaces did not refresh, so no plugin was updated.",
  plugins_unreadable:
    "The list of installed plugins could not be understood, so nothing was updated.",
  internal_error: "The update stopped on an error in Hitchrail. The journal has the details.",
};

let runningSessions = 0;

function outcomeItem(outcome) {
  const item = document.createElement("li");
  item.className = "plugin-outcome";
  item.dataset.result = outcome.result;
  const head = document.createElement("span");
  head.className = "plugin-outcome-head";
  const result = document.createElement("span");
  result.className = "plugin-result";
  result.textContent = outcome.result;
  const name = document.createElement("span");
  name.className = "settings-value";
  name.textContent = outcome.plugin;
  head.append(result, name);
  item.append(head);
  // The agent's own words, rendered as text: the server escaped control
  // characters, and textContent means nothing here is parsed as markup.
  const lines = [];
  if (outcome.result === "skipped") lines.push(`${outcome.scope} scope, left alone`);
  else if (outcome.detail) lines.push(outcome.detail);
  if (outcome.approved_command) lines.push(`approved: ${outcome.approved_command}`);
  for (const text of lines) {
    const line = document.createElement("span");
    line.className = "settings-source";
    line.textContent = text;
    item.append(line);
  }
  return item;
}

function pluginStatus(record) {
  if (record.state === "idle") return "Not run since this server started.";
  if (record.state === "running") {
    const n = record.outcomes.length;
    return n ? `Updating: ${n} done so far.` : "Refreshing the marketplaces.";
  }
  if (record.state === "failed") {
    // A failure is never a count: `counts` is null, and the sentence says
    // that nothing, or nothing further, was updated.
    return PLUGIN_FAILURES[record.code] ?? record.message ?? "The update did not finish.";
  }
  const c = record.counts;
  let text = `${c.updated} updated, ${c.failed} failed, ${c.skipped} left alone.`;
  if (c.updated && runningSessions) {
    text += ` ${runningSessions === 1 ? "The running session keeps" : `The ${runningSessions} running sessions keep`} the old versions until restarted.`;
  }
  return text;
}

function renderPlugins(record) {
  const section = $("[data-plugins]");
  section.dataset.state = record.state;
  $("[data-plugins-update]").disabled = record.state === "running";
  $("[data-plugins-status]").textContent = pluginStatus(record);
  $("[data-plugins-list]").replaceChildren(...record.outcomes.map(outcomeItem));
}

async function countRunning() {
  try {
    const response = await fetch("/api/projects", { headers: { accept: "application/json" } });
    if (!response.ok) return;
    const listing = await response.json();
    runningSessions = listing.projects.filter((p) => p.state === "running").length;
  } catch {
    /* the notice is a courtesy; without the count it is left off */
  }
}

async function onPluginRecord(record) {
  if (record.state === "done" && record.counts.updated) await countRunning();
  renderPlugins(record);
}

async function pluginRequest(method) {
  let response;
  try {
    response = await fetch("/api/plugins/update", {
      method,
      headers: { accept: "application/json" },
    });
  } catch {
    note("Not connected. Nothing was started.");
    return null;
  }
  if (response.status === 401) {
    location.assign("/grant");
    return null;
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    note(`Not started. ${body?.message ?? "The answer could not be read."}`);
    return null;
  }
  note("");
  return body;
}

async function loadPlugins() {
  const record = await pluginRequest("GET");
  if (record) await onPluginRecord(record);
}

async function startPlugins() {
  $("[data-plugins-update]").disabled = true;
  const record = await pluginRequest("POST");
  // Refused or not, repaint from what the server holds.
  if (record) await onPluginRecord(record);
  else await loadPlugins();
}

function watchPlugins() {
  const stream = new EventSource("/api/events");
  stream.addEventListener("plugins", (event) => {
    let record;
    try {
      record = JSON.parse(event.data);
    } catch {
      return;
    }
    onPluginRecord(record);
  });
  // Every open, the first and each reconnect, reads the GET: what happened
  // while the stream was down is not replayed.
  stream.addEventListener("open", loadPlugins);
}

$("[data-plugins-update]").addEventListener("click", startPlugins);

window.__settings = { refresh, loadPlugins };
refresh();
loadPlugins();
watchPlugins();
