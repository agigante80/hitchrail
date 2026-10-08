import { $ } from "/dom.js";
import { emptyReason, isRunning, renderChips, renderTabs, visibleProjects } from "/filters.js";
import { formatMb } from "/format.js";
import { renderRow } from "/row.js";
import { renderSuggestions } from "/search.js";
import { state } from "/state.js";
import { renderBulk, renderStopAll } from "/stop_all.js";

export function renderList() {
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

/* #272. `state.signalled` is keyed by `name:pid` and grew for the life of
   the tab: every row ended in a long session stayed in it forever. Nothing
   breaks while pids are unique, and on a box with a small `pid_max` a reused
   pid under the same name would find its key already there and offer Kill as
   the row's FIRST control, which is the rule #169 exists to keep. Pruned on
   render against the rows the listing actually carries: a key survives only
   while its row is still detached at that pid, which is exactly the state the
   escalation is about. */
function pruneSignalled() {
  if (state.signalled.size === 0) return;
  const live = new Set(
    state.projects
      .filter((project) => project.state === "detached" && project.pid)
      .map((project) => `${project.name}:${project.pid}`),
  );
  for (const key of state.signalled) {
    if (!live.has(key)) state.signalled.delete(key);
  }
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
  pruneSignalled();
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
