/* The settings page (#238): what this instance is pointed at, and the things
   it changes. Two are requests (the stop wait, and the policy since #409).
   The third, Appearance (#323), is NOT a request: the theme is stored in this
   browser's localStorage and nothing is sent, so it has no Save and applies
   the moment it is picked.

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

import { startPlugins } from "/plugins.js";
import { applyTheme, storedTheme, storeTheme } from "/theme.js";

const $ = (selector) => document.querySelector(selector);

/* The stored theme, through the one module that owns it. Module scripts run
   after the document is parsed and before its first paint, so this is as early
   as a copy at the top of the file ever was (imports are hoisted above it). */
applyTheme(storedTheme());

/* #315. WHO wrote the text currently on the strip, "settings" or "plugins",
   or null when it is empty. The strip is one DOM element shared by two
   independent async flows (this module's own `/api/config` calls, and
   plugins.js's `/api/plugins/update` calls, wired together at the bottom of
   this file), and neither flow's generation counter guards the OTHER flow's
   right to clear it: a settings refusal sets `keepNote` expecting its own
   follow up GET to consume it, but if a plugins.js request resolves first in
   that async gap, its unconditional `settle()` used to consume the flag
   believing itself the owed repaint, and the settings GET that then arrived
   found nothing left to consume and wiped the refusal before anyone read it
   (round 3 of Phase 21's batch 2 review, reproduced twice). Recording the
   owner on every write, and checking it before any clear, is what stops that:
   a flow's success may only settle a strip it owns or that is already empty.
   If a third async writer is ever added, it must go through `note()` and
   `settle()` like the other two, or this stops meaning anything. */
let noteOwner = null;

function note(message, owner) {
  const strip = $("[data-note]");
  strip.textContent = message;
  strip.style.display = message ? "block" : "none";
  if (message) {
    // A different owner overwriting the strip retires whatever repaint the
    // PREVIOUS owner's message was still owed (round 1 of batch 2's review):
    // `keepNote` says "the next settle for this text must not clear it yet",
    // and that text is gone now, so the flag would otherwise survive to be
    // consumed by the new owner's own next settle, which believes it is
    // protecting ITS OWN message and instead leaves that message stuck.
    if (noteOwner !== null && noteOwner !== owner) keepNote = false;
    noteOwner = owner;
  }
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

// A success clears the strip unless a refusal is still owed its one repaint,
// AND unless the strip is currently owned by the other flow (#315): a flow
// settling its own request must never take away the other flow's message,
// whether that message is a kept refusal or one just painted this instant.
// Shared with plugins.js so both sections keep the same rule on one strip.
function settle(owner) {
  if (noteOwner !== null && noteOwner !== owner) return;
  if (keepNote) keepNote = false;
  else {
    note("", owner);
    noteOwner = null;
  }
}

// A new action by the person retires a settings refusal's owed repaint
// (#281): the flag belonged to the repaint after THAT refusal, and a local
// refusal or an offline one gets none, so it was spent by the next success
// instead and "Not changed" stood over a change that was made. Never the
// other flow's flag, by #315's rule.
function begin() {
  if (noteOwner !== "plugins") keepNote = false;
}

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
      note("Not connected. Retrying is up to you: nothing was changed.", "settings");
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
    note(`Not changed. ${message}`, "settings");
    keepNote = true;
    return null;
  }
  settle("settings");
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
  begin();
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
  begin();
  const input = $("[data-stop-timeout]");
  const seconds = Number(input.value);
  const ceiling = Number(input.max);
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > ceiling) {
    note(`Not changed. The wait is a whole number of seconds, 1 to ${ceiling}.`, "settings");
    keepNote = true;
    return;
  }
  const config = await call("PATCH", { stop_timeout: seconds });
  if (config) render(config);
}

/* #409. The page says what the policy DOES, in the source line under the
   control, every time it renders: with `end_anyway` that is a kill nobody
   taps, and the person who chose it reads that sentence under the Save they
   pressed. Pinned by the flag or the config file, it is text, like the wait. */
const POLICY_WORDS = {
  ask: "A stop that runs out of time on a question is reported, and waits for you.",
  end_anyway:
    "A stop that runs out of time on a question, once asked to exit, is ended without a tap.",
};

function renderPolicy(config) {
  const field = $("[data-policy-field]");
  const select = $("[data-stop-policy]");
  const save = $("[data-policy-save]");
  const source = $("[data-policy-source]");
  const policy = config.stop_policy;
  select.value = policy.value;
  const words = POLICY_WORDS[policy.value] ?? policy.value;
  const where = policy.source === "flag" ? "on the command line" : "in the config file";
  source.textContent = policy.editable
    ? `${words} Currently ${sourceText(policy.source)}.`
    : `${words} Set ${where}; change it there.`;
  field.dataset.editable = String(policy.editable);
  select.hidden = !policy.editable;
  save.hidden = !policy.editable;
}

async function savePolicy() {
  begin();
  const config = await call("PATCH", { stop_policy: $("[data-stop-policy]").value });
  if (config) render(config);
  else refresh();
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
  // #242. Shown, never editable: what Stop types is set in the config file.
  ["stop_prompt", "Wrap up prompt"],
  ["stop_prompt_timeout", "Wrap up waits up to, seconds"],
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
  renderPolicy(config);
  renderFacts(config);
  $("[data-settings]").dataset.loaded = "";
}

async function refresh() {
  const config = await call("GET");
  if (config) render(config);
}

$("[data-stop-save]").addEventListener("click", saveStop);
$("[data-policy-save]").addEventListener("click", savePolicy);
$("[data-stop-timeout]").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveStop();
  }
});

/* #323. Light, Dark and System. System is the stored key's absence, so a
   value this page did not write (or none) reads as System. */
const radios = [...document.querySelectorAll("[data-theme-choice]")];
const current = storedTheme();
for (const radio of radios) {
  radio.checked = radio.value === (current === "light" || current === "dark" ? current : "system");
  radio.addEventListener("change", () => {
    if (!radio.checked) return;
    const theme = radio.value === "system" ? null : radio.value;
    storeTheme(theme);
    applyTheme(theme);
  });
}

window.__settings = { refresh };
refresh();
// #297. Its own module: it shares the note strip and nothing else. Its
// `note` and `settle` are bound to the "plugins" owner (#315), so its own
// success can never clear a refusal this module wrote, and vice versa.
startPlugins({
  note: (message) => note(message, "plugins"),
  keep: (on) => (keepNote = on),
  settle: () => settle("plugins"),
});
