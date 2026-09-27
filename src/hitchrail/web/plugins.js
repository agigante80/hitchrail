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
//
// #317. `internal_error` used to carry its own trailing clause, "; the
// journal has the details", which put the appended "after N plugins" right
// after "details" and read as though the JOURNAL had details after N
// plugins rather than as though the UPDATE stopped after N plugins. Kept
// short here, like every other entry, so the appended clause attaches to
// "stopped" the way it is meant to; the journal mention moved to its own
// trailing sentence in `failureText`.
const PLUGIN_FAILURES = {
  agent_missing: "The agent could not be run",
  marketplace_refresh_failed: "The marketplaces did not refresh",
  plugins_unreadable: "The list of installed plugins could not be understood",
  internal_error: "The update stopped on an error in Hitchrail",
};

let shownEpoch = null;
let shownSeq = -1;
// Every epoch a newer one has ever painted over. Retirement is permanent:
// nothing revives an epoch once replaced, which is what closes the ABA gap
// (see `isStale` below) a plain "different epoch always wins" left open.
const retiredEpochs = new Set();
let runningSessions = 0;
let strip = { note: () => {}, keep: () => {}, settle: () => {} };

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
  // #317. A trailing sentence, not folded into `why`: appended after the
  // outcomes clause so "after N plugins" still reads as attached to "the
  // update stopped", not to this.
  const journal = record.code === "internal_error" ? " The journal has the details." : "";
  // A failure is never a count of updated plugins: `counts` is null. What it
  // can honestly say is whether anything ran before it stopped.
  if (!n) return `${why}, so nothing was updated.${journal}`;
  return `${why} after ${n} ${n === 1 ? "plugin" : "plugins"}, listed below; the rest were not updated.${journal}`;
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

// #314, wrong three times running. Epochs are a random token per SERVER
// PROCESS (plugin_runs.py mints one with secrets.token_hex(8) once, when it
// is built), so two epochs carry no order between them: seeing a DIFFERENT
// one never means a NEWER one, only a different process, and the two
// strings alone say nothing more. An epoch that gets painted over is dead
// for good, because the process that minted it is either gone or has
// nothing left to send this page: once a newer epoch has shown on screen,
// every record of the one it replaced is retired, whatever `seq` it still
// carries.
//
// Each earlier version got exactly one interleaving wrong, and the fix for
// it broke another. Comparing epochs with nothing but `isStale` twice let a
// record suspended here with the OLD epoch win when it resumed after a
// SEPARATE, un-awaited call had already painted the NEW epoch's idle
// record: the two epochs were merely different, never compared, so the
// dead one was let through. Task 134's fix, a snapshot of epoch and seq
// taken before the await, then broke the case that version got right:
// WITHIN one epoch, any repaint at all while suspended, even a genuinely
// older record a concurrent GET answered, changed the snapshot, and the
// check bailed on a record that was still the newer of the two. Batch 2's
// round 2 fix for THAT, bailing only when the live epoch no longer matched
// what was shown before the await, then broke the case where THIS record's
// own epoch is the one that first paints while it sits suspended: the live
// epoch moves from the old value to this record's own epoch during the
// await, the two no longer match, and the check bailed on a record that IS
// the live epoch's newest.
//
// `retiredEpochs` answers all three at once. An epoch is retired the
// instant something else paints over it and never un-retired, so a record
// of a retired epoch is stale no matter when it resumes or what `seq` it
// carries; an epoch that has not been retired and has not changed is
// ordered exactly the way `seq` already says.
//
// What it cannot decide: a record from an epoch that was never shown at
// all, arriving after a later epoch already is. That needs one in-flight
// request answered by a server process whose entire life fits inside
// another request's round trip on loopback, which the shipped
// `RestartSec=5` (packaging/hitchrail.service) keeps seconds apart, far
// outside that window; not proven impossible in general, just not reachable
// the way this page and this unit actually run.
function isStale(record) {
  return retiredEpochs.has(record.epoch) || (record.epoch === shownEpoch && record.seq < shownSeq);
}

async function onPluginRecord(record) {
  // Checked twice: once so a stale record costs no listing fetch, and again
  // after the await, which is where a newer one can overtake it.
  if (isStale(record)) return;
  if (record.state === "done" && record.counts.updated) await countRunning();
  if (isStale(record)) return;
  // Retire the epoch this record is replacing, not the one it carries: a
  // record only ever displaces whatever is currently shown.
  if (shownEpoch !== null && record.epoch !== shownEpoch) retiredEpochs.add(shownEpoch);
  shownEpoch = record.epoch;
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
    // that follows says which, so the note is kept past that one repaint. A
    // GET lost started nothing and is not kept: the next GET that succeeds,
    // a reconnect's included, has the answer and clears it.
    if (method === "POST") {
      strip.note("Not connected. Whether the update started is shown below once the page reconnects.");
      strip.keep(true);
    } else {
      strip.note("Not connected. The plugin update's state could not be read.");
    }
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
  // settings.js's rule, not a plain clear: a refused POST repaints through
  // a GET, and clearing on that GET wiped the refusal before anyone could
  // read it (round 1 of batch 2's review; #256 is the same lesson on the
  // roots). Never clearing instead left "Not started" above the next run
  // that did start (round 2). The keep is consumed by one success, as there.
  strip.settle();
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
  // #313. The stream can stay open while the ONE event marking a run's end
  // is the frame the server's bus drops for a slow client, and a phone that
  // sleeps mid run is exactly that: the connection never notices anything
  // is wrong, so no reconnect ever fires to correct the screen. Reading on
  // `visibilitychange` back to visible, which is when a phone that slept
  // comes back, is the same recovery a reconnect already has, and it goes
  // through the same `loadPlugins` a reconnect uses rather than painting
  // anything directly: `onPluginRecord`'s staleness gate (#314) is what
  // stops a dead run's record from overtaking one a meanwhile delivered
  // stream event already painted, and a second entry point here would have
  // to reimplement that rather than share it.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadPlugins();
  });
  window.__plugins = { loadPlugins };
  loadPlugins();
}
