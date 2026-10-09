import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";
import { $ } from "/dom.js";
import { isRunning } from "/filters.js";
import { refresh } from "/listing.js";
import { stopTimeoutMs, wrapUpSeconds, wrapUpTimeoutMs } from "/patience.js";
import { displayProject } from "/roots.js";
import { state } from "/state.js";
import { endAnywayNote } from "/wait.js";

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
  // A row wrapping up is left out too: Stop all would send it the exit,
  // interrupting a wrap up the confirmation says it is waiting for. A row
  // already `exiting` stays in, so a second Stop all resends the exit.
  return state.projects.filter(
    (p) => isRunning(p) && !p.protected && p.stopping_phase !== "closing",
  );
}

function sessionCount(n) {
  return n === 1 ? "1 session" : `${n} sessions`;
}

export function renderStopAll() {
  const button = $("[data-stop-all]");
  if (button) button.hidden = stoppableRows().length === 0;
}

export function confirmStopAll() {
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
  // #416: an `exiting` row is in the set and gets its exit resent, never a
  // wrap up, so it is named rather than covered by "each".
  const again = rows.filter((p) => p.stopping_phase === "exiting");
  const fresh = rows.length - again.length;
  showDialog({
    title: `Stop ${sessionCount(rows.length)}?`,
    body: [
      fresh === 0
        ? ""
        : state.server.stop_prompt_set
          ? `${fresh === 1 ? "It" : "Each"} will be asked to wrap up after its current `
            + `task, then to exit. A wrap up longer than ${wrapUpSeconds()}s has its task `
            + "interrupted."
          : fresh === 1
            ? "It will be interrupted, then asked to exit. "
              + "Anything it is part way through may be lost."
            : "Each will be interrupted, then asked to exit, one at a time. "
              + "Anything they are part way through may be lost.",
      again.length === 0
        ? ""
        : `${again.map((p) => displayProject(p.name)).join(", ")} `
          + `${again.length === 1 ? "is" : "are"} already asked to exit, `
          + "and will only be asked again."
          // The exit is resent whatever `stop_prompt` says (#416), so this
          // clause owes the warning the single row confirm gives an exiting
          // row (#433). Not twice: the fresh clause above already says it
          // when no wrap up prompt is set and there is a fresh row.
          + (fresh > 0 && !state.server.stop_prompt_set
            ? ""
            : ` Anything ${again.length === 1 ? "it is" : "they are"} part way through `
              + "may be lost."),
      endAnywayNote(),
    ].filter(Boolean).join(" "),
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
  // #242: every row's wrap up runs in parallel, so one ceiling covers them.
  // `killRemaining` keeps `stopTimeoutMs()` alone: a kill waits on no wrap up.
  bulk.deadline = Date.now() + wrapUpTimeoutMs() + stopTimeoutMs();
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
  if (!bulk.over && current?.stopping_phase === "closing") return "wrapping up";
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
  const live = ["queued", "requesting", "requested", "wrapping up", "not finished"];
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
    title: `Stopping ${sessionCount(bulk.rows.length)}`,
    body: bulk.rows.length === 1 ? "Waiting for it to exit." : "Waiting for them to exit.",
    extra: list,
    actions: [
      ["Hide, keep stopping", "ghost", () => closeDialog()],
      [
        bulk.rows.length === 1 ? "Do not wait, kill it now" : "Do not wait, kill them all",
        "danger",
        () => killRemaining(),
      ],
    ],
  });
  $("[data-dialog]").dataset.bulk = "";
  renderBulk();
}

/* Updated in place, never rebuilt: `showDialog` starts with `replaceChildren`,
   and a wait that redraws its whole dialog on every listing takes focus from
   under the thumb, which is #71's defect in a new place. */
export function renderBulk() {
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
        + (bulk.rows.length === 1
          ? "it cannot say whether the session finished."
          : "it cannot say which sessions finished.");
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
      + `${unfinished === 1 ? "it" : "them"} immediately, and anything not written to disk is lost.`;
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
