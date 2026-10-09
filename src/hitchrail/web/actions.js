import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";
import { isRunning } from "/filters.js";
import { refresh } from "/listing.js";
import { openLogs } from "/log_drawer.js";
import { showRefusal } from "/refusal.js";
import { sessionHref, sessionLink, showSessionLink } from "/session_link.js";
import { startProject } from "/start.js";
import { state } from "/state.js";
import { confirmClear, confirmStop, reopenStop } from "/stop.js";

export function buildActions(project, actions) {
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
    // A row wrapping up reopens its wait rather than confirming a second
    // stop: that DELETE is the Exit now, which interrupts the task, behind a
    // confirmation promising a wrap up (#242 review). Only `closing`, though:
    // on `exiting` a repeated Stop resends the exit, as before #242, and is
    // the only way short of Kill to ask an agent that ignored the first one
    // (#242 review round 2).
    const onStop =
      project.stopping_phase === "closing"
        ? () => reopenStop(project)
        : () => confirmStop(project);
    add("Stop", "").addEventListener("click", onStop);
    // #472. Not while a stop is in flight: a Restart then would be the
    // route's second Stop, which on a `closing` row is Exit now, behind a
    // confirmation that promised a wrap up (#242 review). The row's wait and
    // its Stop are where a stop in flight is steered.
    if (!project.stopping) {
      add("Restart", "").addEventListener("click", () => confirmStop(project, true));
    }
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
  if (
    !project.protected
    && project.state === "detached"
    && !project.foreign_session
    && !project.foreign_server_pid
  ) {
    // Keyed by name AND pid (review round 1): keyed by name alone, a later
    // agent under the same name on a page left open got Kill as its first
    // control, SIGKILL before SIGTERM, the rule this exists to keep.
    const escalate = state.signalled.has(`${project.name}:${project.pid}`);
    add(escalate ? "Kill" : "End", "danger").addEventListener("click", () =>
      confirmSignal(project, escalate),
    );
  }
}

/* The honest sentence (#107). Not a predicate claiming to know ownership:
   `foreign_session` null means no owner was SEEN, from one `list-panes -a`
   against our own tmux server, and a terminal, screen or another socket
   would all arrive here looking the same. */
export function confirmSignal(project, escalate) {
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
  // The pid this row showed, which is the one the person confirmed (#279). The
  // server refuses `not_ours` when its agent for the folder is another one now,
  // rather than end an agent nobody was asked about.
  const result = await api(path, {
    method: "POST",
    body: JSON.stringify({ pid: project.pid }),
  });
  closeDialog();
  if (!result.ok) {
    showRefusal(result, project);
    return;
  }
  // Remembered so the row offers the escalation next: the server will not
  // send SIGKILL without a second explicit request, and neither will this.
  state.signalled.add(`${project.name}:${project.pid}`);
  await refresh();
}
