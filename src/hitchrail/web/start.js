import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";
import { isRunning } from "/filters.js";
import { formatMb, formatMemory } from "/format.js";
import { refresh } from "/listing.js";
import { showRefusal } from "/refusal.js";
import { state } from "/state.js";
import { confirmStop } from "/stop.js";

/* -- starting ----------------------------------------------------------
   The two memory refusals are DIFFERENT SCREENS, not one with a variable.
   The soft one asks and can be overridden; the hard one refuses and offers a
   way out. Rendering both from one template with a boolean is how "Start
   anyway" ends up on a screen that cannot start anything. */

export async function startProject(project, { acknowledged = false } = {}) {
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
