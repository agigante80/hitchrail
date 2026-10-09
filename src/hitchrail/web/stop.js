import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";
import { refresh } from "/listing.js";
import { wrapUpSeconds } from "/patience.js";
import { showRefusal } from "/refusal.js";
import { displayProject } from "/roots.js";
import { state } from "/state.js";
import {
  awaitStopped,
  endAnywayNote,
  killNow,
  repaintWaiting,
  showWaiting,
  waitingPhase,
} from "/wait.js";

/* -- stopping ----------------------------------------------------------
   Confirm, then a wait during which the kill is reachable, then a timeout
   that reports and does NOT escalate on its own. The engine refuses to
   escalate by itself; the interface must not do it on the engine's behalf. */

export function confirmStop(project) {
  showDialog({
    // The name a PERSON reads, which with several roots says which one.
    // A confirmation naming the wrong project is worse than none.
    title: `Stop ${displayProject(project.name)}?`,
    // #89: this used to say "It will be asked to finish what it is doing",
    // which no version of the sequence has ever done. The first thing sent is
    // an interrupt. Say that, and carry the warning about part done work here
    // rather than only on the kill screen, because the interrupt is where the
    // work is lost and the kill screen is thirty seconds too late to say so.
    //
    // #242: with a wrap up prompt set the first thing sent is the prompt,
    // queued behind the current task, and nothing is interrupted unless the
    // wrap up outlasts its ceiling. The warning moves to that case.
    //
    // #416: on an `exiting` row the server resends the exit and types no
    // prompt, whatever `stop_prompt` says, so promising a wrap up there is
    // the mismatch #242's round 1 objected to.
    body: [
      project.stopping_phase === "exiting"
        ? "It was asked to exit and has not yet, and will be asked again. "
          + "Anything it is part way through may be lost."
        : state.server.stop_prompt_set
          ? "It will be asked to wrap up after its current task, then to exit. "
            + `If that takes longer than ${wrapUpSeconds()}s, the task is interrupted.`
          : "It will be interrupted, then asked to exit. "
            + "Anything it is part way through may be lost.",
      endAnywayNote(),
    ].filter(Boolean).join(" "),
    // Cancel and Stop, and nothing else. A kill control at this step puts the
    // destructive path under the thumb at the same weight as the safe one.
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Stop", "", () => beginStop(project)],
    ],
  });
}

export function confirmClear(project) {
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

/* The live wait per project, so a second look at a stopping row reuses its
   ticker. Two tickers for one project read the phase differently, and each
   repaint then rebuilds the dialog every tick, taking focus (#71). */
const waits = new Map();

function newWait(project, began = Date.now(), policy = state.server.stop_policy) {
  // `over` lets Exit now's refusal end the ticker, which would otherwise
  // paint "no answer" over the refusal it just showed.
  const previous = waits.get(project.name);
  if (previous) previous.over = true;
  // The policy the person was shown, kept for the whole wait: the server acts
  // on the one in force at the Stop, whatever is chosen meanwhile (#419).
  const wait = {
    began,
    over: false,
    sawClosing: false,
    exitSeen: false,
    policy,
  };
  waits.set(project.name, wait);
  return wait;
}

export function reopenStop(project) {
  const live = waits.get(project.name);
  if (live && !live.over) {
    showWaiting(project, live, waitingPhase(live, project));
    return;
  }
  // Stopped from another browser, or before this page loaded. The deadline
  // starts now, later than the server's, which errs long as `stopTimeoutMs`
  // says it should. The count and the policy come from the row instead: the
  // count is what a person reads to decide on Exit now (#411), and today's
  // policy may not be the one the server will act on (#428). The newest row,
  // since the one this button was drawn from can be a listing old.
  const current = state.projects.find((p) => p.name === project.name) ?? project;
  const wait = newWait(
    project,
    current.stopBeganHere ?? Date.now(),
    current.stop_policy ?? state.server.stop_policy,
  );
  wait.sawClosing = current.stopping_phase === "closing";
  wait.armed = true;
  showWaiting(project, wait, waitingPhase(wait, current));
  awaitStopped(project, wait);
}

async function beginStop(project) {
  const wait = newWait(project);
  // A resent exit (#416) is watched as the exit after a wrap up is: its
  // deadline starts from the first `exiting` reading, not a wrap up away.
  const resend = project.stopping_phase === "exiting";
  if (resend) wait.sawClosing = true;
  const first = resend ? "exiting" : state.server.stop_prompt_set ? "sending" : "waiting";
  showWaiting(project, wait, first);
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}`, {
    method: "DELETE",
  });
  if (!result.ok) {
    // The row goes with it: `stop_unsafe` is refused here and nowhere else,
    // and the dialog that reports it offers a kill that has to name a session.
    // Over, or a later Stop on the row reopens a wait no ticker drives.
    wait.over = true;
    showRefusal(result, project);
    return;
  }
  // With no prompt the exit's wait starts once the DELETE has answered, as
  // it did before #242: from the tap it would end before the server's own
  // expiry most times, and say "no answer" before the server's one look at
  // the pane could say the agent is waiting on a question (#242 review).
  if (!state.server.stop_prompt_set || resend) wait.armed = true;
  // #433. The answer is the row with the marker this stop wrote, so its policy
  // is the one the server will act on, where `state.server` can be older than
  // `prefs.stop_policy()` (#428). Repainted at once rather than left to the
  // ticker, which starts only after the listing. A no-op 202 carries the
  // marker already in flight, which is the right one to follow.
  repaintWaiting(project, wait, result.body);
  await refresh();
  awaitStopped(project, wait);
}
