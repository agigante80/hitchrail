import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";
import { $ } from "/dom.js";
import { refresh } from "/listing.js";
import { paneView } from "/log_drawer.js";
import { stopTimeoutMs, wrapUpSeconds, wrapUpTimeoutMs } from "/patience.js";
import { showRefusal } from "/refusal.js";
import { state } from "/state.js";

/* #242. The words follow the row's phase: `closing` while the wrap up runs
   behind the task, `exiting` once the exit is sent, and the ceiling named
   when that is why. Repainted only on a change of phase, and only while this
   wait is the dialog on screen: a hidden wait must stay hidden, and a
   rebuild on every listing takes focus from under the thumb (#71). */
export function waitingPhase(wait, current) {
  // #408. Still typing the prompt, which only the tapping browser knew of
  // itself: a DELETE now is the no-op 202, so no Exit now.
  if (current?.stopping_phase === "closing" && current.stop_typing) return "sending";
  if (current?.stopping_phase === "closing") return "closing";
  if (current?.stop_ceiling) return "ceiling";
  return wait.sawClosing ? "exiting" : "waiting";
}

function waitingBody(wait, phase) {
  const note = endAnywayNote(wait.policy);
  return note ? `${phaseBody(wait, phase)} ${note}` : phaseBody(wait, phase);
}

/* #239. A kill the operator configured a week ago must not surprise them:
   said on the confirm and through the whole wait, before it happens. */
export function endAnywayNote(policy = state.server.stop_policy) {
  if (policy !== "end_anyway") return "";
  // "Once asked to exit": a wrap up that ends on a question is reported and
  // never killed, since the exit it would refuse was never sent (#239 review).
  return "If it stops on a question once asked to exit, it will be ended, as this server is configured to.";
}

function phaseBody(wait, phase) {
  if (phase === "sending") return "Asking it to wrap up, after its current task.";
  if (phase === "closing") {
    const seconds = Math.max(0, Math.round((Date.now() - wait.began) / 1000));
    return `Asking it to wrap up, after its current task. ${seconds}s so far.`;
  }
  if (phase === "ceiling") {
    return `Wrap up did not finish in ${wrapUpSeconds()}s; asked it to exit.`;
  }
  if (phase === "exiting") return "Asking it to exit.";
  // Waiting for it to exit, not to finish. The sequence interrupts before it
  // asks anything, so once the request lands there is no grace period being
  // observed: the wait is for the process to go.
  //
  // Careful with "already": `beginStop` paints this BEFORE it awaits the
  // DELETE, so for the first moments nothing has been sent at all. An
  // earlier version of this comment said the interrupt had already happened
  // when the screen appeared, which is the wrong way round.
  return "Waiting for it to exit.";
}

export function showWaiting(project, wait, phase) {
  const actions = [
    // "Hide, keep stopping" first: a modal that owns a phone screen for
    // thirty seconds is one people kill the app to escape.
    ["Hide, keep stopping", "ghost", () => closeDialog()],
  ];
  // A graceful way out of a long wrap up short of the kill: a second DELETE
  // during `closing` sends the exit now and never retypes the prompt. Not
  // while `sending`, before the first DELETE has answered: the row already
  // reads `closing` while the prompt is typed, and a DELETE then is a no-op
  // 202, so the button would answer and do nothing. Another browser learns
  // of that window from the row's `stop_typing` (#408).
  if (phase === "closing") actions.push(["Exit now", "", () => exitNow(project, wait)]);
  // Phrased as impatience rather than as an alternative, and available
  // for the WHOLE wait rather than only at the end.
  actions.push(["Do not wait, kill it now", "danger", () => killNow(project)]);
  showDialog({
    title: `Stopping ${project.name}`,
    body: waitingBody(wait, phase),
    forProject: project.name,
    actions,
  });
  const dialog = $("[data-dialog]");
  if (dialog) dialog.dataset.waiting = phase;
}

export function repaintWaiting(project, wait, current) {
  const dialog = $("[data-dialog]");
  if (!dialog?.open || dialog.dataset.for !== project.name) return;
  if (!("waiting" in dialog.dataset)) return;
  // #433. The policy the server recorded for THIS stop, which a second
  // browser's Stop can replace with the live one while this wait is open: the
  // note must match the marker the expiry acts on, not the one first shown.
  if (current?.stop_policy) wait.policy = current.stop_policy;
  const phase = waitingPhase(wait, current);
  if (dialog.dataset.waiting !== phase) {
    showWaiting(project, wait, phase);
    return;
  }
  const body = dialog.querySelector(".dialog-body");
  if (body) body.textContent = waitingBody(wait, phase);
}

async function exitNow(project, wait) {
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}`, {
    method: "DELETE",
  });
  if (!result.ok) {
    wait.over = true;
    showRefusal(result, project);
    return;
  }
  await refresh();
}

export function awaitStopped(project, wait) {
  // #242: a wrap up gets its own ceiling before the exit's wait begins, so
  // the page's patience is both while the row reads `closing`, and the exit's
  // alone from the first `exiting` reading, which is never earlier than the
  // server's `exit_at`: erring long, for the reason `stopTimeoutMs` gives.
  let deadline = (wait.armed ? Date.now() : wait.began) + stopTimeoutMs() + wrapUpTimeoutMs();
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
    if (wait.over) return;
    const current = state.projects.find((p) => p.name === project.name);
    if (!current) {
      // Gone from the listing entirely: the folder was removed under us.
      wait.over = true;
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
      wait.over = true;
      if (current.state === "stopped") closeDialog(project.name);
      else showTimedOut(project);
      return;
    }
    if (current.stopping_phase === "closing") {
      wait.sawClosing = true;
    } else if (wait.sawClosing && !wait.exitSeen) {
      wait.exitSeen = true;
      deadline = Date.now() + stopTimeoutMs();
    }
    repaintWaiting(project, wait, current);
    // The marker still being there at the deadline means the server's own
    // expiry, on a one second sweep, has not run yet, and that expiry is the
    // one look at the pane that can say the agent is asking a question. Two
    // sweeps of grace, once, so "no answer" is not said over it (#242 review).
    if (Date.now() >= deadline && !wait.graced) {
      wait.graced = true;
      deadline = Date.now() + 2000;
    }
    if (Date.now() >= deadline) {
      // The LAST reading, not "did they all fail". At the deadline the question
      // is what is true NOW, and the answer comes from the most recent listing.
      // If that one failed, the page cannot answer, and one blip costing an
      // honest screen instead of a claim is the right way round to be wrong.
      wait.over = true;
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
  // #457, decided on #463. The page's deadline and the server's expiry are
  // independent timers, and under `end_anyway` the server kills on its own:
  // a row that already left `running` has nothing to answer, and "No answer"
  // offering Kill over a row the list shows stopped was the defect.
  //
  // Not every other state is the same, which is the case the first wording
  // hid. `stopped` and `stale` have no agent to ask or to kill (Clear is on
  // the stale row), so the dialog closes. `detached` is an agent ALIVE with no
  // session to type into, so a stop that ran out on it is still "no answer":
  // the dialog stays, and its Kill is answered by the server's own refusal
  // saying why a kill cannot reach it, rather than by a dialog that vanishes.
  if (current.state !== "running" && current.state !== "detached") {
    closeDialog(project.name);
    return;
  }
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
    // The await is a window. Under `end_anyway` the server kills right after
    // the flag, and the stream's close for a row leaving `running` can run
    // before this dialog exists, which then opened over a killed session.
    if (state.projects.find((p) => p.name === project.name)?.state !== "running") return;
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
    // A `for` like the rest of the stop sequence, so a row leaving `running`
    // after this opened closes it rather than leaving a Kill for nothing.
    forProject: project.name,
    actions: [
      ["Leave it", "ghost", () => closeDialog()],
      ["Kill it", "danger", () => killNow(project)],
    ],
  });
}

export async function killNow(project) {
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
