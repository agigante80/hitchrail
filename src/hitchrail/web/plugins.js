/* #297. The plugin update's section of the settings page.

   Every render is of the WHOLE record, from the GET or from a `plugins`
   event alike, because the stream does not replay: a page opened mid run,
   or back from a dropped connection, reads the GET and is then exactly as
   current as one that watched from the start.

   **Records arrive out of order, and the older one must lose.** The GET a
   reconnect sends can be answered before the run's last event and delivered
   after it; painted, it put "running" back over "done" and disabled the
   button for good, since no later event comes (round 1 of batch 2's review,
   the high). Every record carries a `seq` the server bumps on each change,
   and one older than what is on screen is dropped.

   Its own module rather than more of settings.js, which it shares only the
   note strip with. */

const $ = (selector) => document.querySelector(selector);

// Why a run could not go on, without the consequence: `failureText` adds
// "so nothing was updated" or "after N" from the outcomes actually listed,
// because a run can fail part way (the agent removed mid run) with rows
// already updated above the sentence.
const PLUGIN_FAILURES = {
  agent_missing: "The agent could not be run",
  marketplace_refresh_failed: "The marketplaces did not refresh",
  plugins_unreadable: "The list of installed plugins could not be understood",
  internal_error: "The update stopped on an error in Hitchrail; the journal has the details",
};

let shownSeq = -1;
let runningSessions = 0;
let strip = { note: () => {}, keep: () => {} };

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

function failureText(record) {
  const why = PLUGIN_FAILURES[record.code] ?? record.message ?? "The update did not finish";
  const n = record.outcomes.length;
  // A failure is never a count of updated plugins: `counts` is null. What it
  // can honestly say is whether anything ran before it stopped.
  if (!n) return `${why}, so nothing was updated.`;
  return `${why} after ${n} ${n === 1 ? "plugin" : "plugins"}, listed below; the rest were not updated.`;
}

function pluginStatus(record) {
  if (record.state === "idle") return "Not run since this server started.";
  if (record.state === "running") {
    const n = record.outcomes.length;
    return n ? `Updating: ${n} done so far.` : "Refreshing the marketplaces.";
  }
  if (record.state === "failed") return failureText(record);
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
  section.dataset.seq = String(record.seq);
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
  // Checked twice: once so a stale record costs no listing fetch, and again
  // after the await, which is where a newer one can overtake it.
  if (record.seq < shownSeq) return;
  if (record.state === "done" && record.counts.updated) await countRunning();
  if (record.seq < shownSeq) return;
  shownSeq = record.seq;
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
    // A POST lost on the network may or may not have started a run; the GET
    // that follows says which. A GET lost on load started nothing.
    strip.note(
      method === "POST"
        ? "Not connected. Whether the update started is shown below once the page reconnects."
        : "Not connected. The plugin update's state could not be read.",
    );
    strip.keep(true);
    return null;
  }
  if (response.status === 401) {
    location.assign("/grant");
    return null;
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    strip.note(`Not started. ${body?.message ?? "The answer could not be read."}`);
    strip.keep(true);
    return null;
  }
  // Deliberately no clearing of the strip here. A refused POST repaints
  // through the GET below, and clearing on that GET wiped the refusal before
  // anyone could read it (round 1 of batch 2's review; #256 is the same
  // lesson on the roots). The next settings request clears it, as there.
  return body;
}

async function loadPlugins() {
  const record = await pluginRequest("GET");
  if (record) await onPluginRecord(record);
}

async function startRun() {
  $("[data-plugins-update]").disabled = true;
  const record = await pluginRequest("POST");
  // Refused or not, repaint from what the server holds.
  if (record) await onPluginRecord(record);
  else await loadPlugins();
}

export function startPlugins(noteStrip) {
  strip = noteStrip;
  $("[data-plugins-update]").addEventListener("click", startRun);
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
  window.__plugins = { loadPlugins };
  loadPlugins();
}
