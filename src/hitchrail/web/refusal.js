import { closeDialog, showDialog } from "/dialogs.js";
import { $ } from "/dom.js";
import { refresh } from "/listing.js";
import { killNow } from "/wait.js";

export function showRefusal(result, project) {
  const { code, message } = result.body;
  if (result.status === 401) {
    // The token is the whole auth model, so an expired or revoked one is a
    // situation a person can actually be in, and "That did not work" leaves
    // them with nothing to do.
    //
    // It used to say "open the link with the token again" and offer Reload,
    // which was true when this page was the only one there was. #21 built
    // `/grant`, which takes a key TYPED as well as one in a fragment, so the
    // way back in no longer needs the original link. Reloading, meanwhile,
    // stopped working the moment `/` went behind the token: it answers a raw
    // JSON 401 into a browser window, which is the dead end `/grant` exists to
    // prevent. #57 made this dialog appear on its own, so the wrong button was
    // about to be offered to somebody who never tapped anything.
    //
    // Relative, for the reason `grant.html` argues at length: this page is
    // served from the app root, wherever that is.
    //
    // #71. Left alone if it is already up. The stream's fatal branch asks
    // once per fatal error and the reopen backs off forever, so a phone
    // holding a stale token reached this once a minute, and `showDialog`
    // starts with `replaceChildren`: the screen was torn down and rebuilt
    // under the reader, focus on Sign in included. Same reason, same dialog,
    // nothing to redraw. `showDialog` clears the tag, so any other dialog
    // opened in between makes this one fresh again.
    const dialog = $("[data-dialog]");
    if (dialog?.open && dialog.dataset.refusal === "signed-out") return;
    showDialog({
      title: "Not signed in any more",
      body: "This browser is no longer accepted. Sign in again with your access key.",
      actions: [["Sign in", "accent", () => window.location.assign("grant")]],
    });
    if (dialog) dialog.dataset.refusal = "signed-out";
    return;
  }
  if (code === "no_agent") {
    // #98. Reachable even though no row offers Stop where this applies: a
    // running row can go stale between the render and the tap. Falling through
    // to "That did not work" would describe a request that failed, and this
    // one was declined before anything was sent, which is the distinction the
    // `stop_unsafe` comment below argues at length.
    showDialog({
      // Not "there is no agent to ask": this code now comes back from the KILL
      // route too, where a detached row has a live agent and simply no session
      // to kill. The engine's message names which case it is; the title has to
      // be true of both.
      title: "Hitchrail cannot reach it",
      body: message,
      actions: [["Close", "ghost", () => closeDialog()]],
    });
    return;
  }
  if (code === "stop_unsafe") {
    // #89. Not a failure: the stop looked at the agent's input box, would not
    // vouch for it, and stopped before asking it to exit. "That did not work"
    // describes a request that was made and refused, and this one was never
    // made.
    //
    // It does NOT say "nothing was sent", which was the first wording here and
    // was false. The sequence clears the box and interrupts before either
    // check runs, so keys have gone out by the time this dialog appears and a
    // turn in progress may have been cut short. Claiming the session is
    // untouched is the same untruth this ticket exists to remove, one screen
    // over. The exit command is the thing that was not sent, and that is what
    // the title says.
    //
    // #169 put the kill here, and the comment this replaces is why the ticket
    // was filed. It read "Kill is still on the row, which is where they chose
    // it deliberately", and that was false: `renderRow` renders Open, Get
    // link, Start, Stop and Clear, and no kill at all. `killNow` was reachable
    // from three places and all three sit downstream of a `DELETE` that
    // SUCCEEDED, so a refusal here ended the flow before any of them. The
    // session could not be ended from Hitchrail at all.
    //
    // Section 7 forbids escalation by DEFAULT, not availability. Close is
    // first, the kill is second and `danger`, and the warning is the same one
    // `showTimedOut` carries: that is the shape the two timeout dialogs
    // already use for the identical situation reached by a different road.
    // Offering it stays ours; choosing it stays the operator's.
    //
    // Still NOT on the row. A kill control on every running row is the
    // escalation by default the rule does forbid, and it is deliberately a
    // separate question.
    // `stop_unsafe` comes back from the stop route alone, and that route
    // passes the row it acted on, so every path that reaches here has one.
    // The guard is for the other five call sites `showRefusal` serves, which
    // have no row to give: a Kill that cannot name a session is a tap that
    // refuses, and `showHardMemory` builds its own second action this way for
    // the same reason.
    //
    // No `forProject`. That key exists so a background stop finishing can
    // close its OWN waiting dialog and nothing else, and setting it here would
    // let a stop still running on this row shut this refusal out from under
    // the person reading it.
    const actions = [["Close", "ghost", () => closeDialog()]];
    if (project !== undefined) {
      actions.push(["Kill it", "danger", () => killNow(project)]);
    }
    showDialog({
      // One paragraph, concatenated. `showDialog` assigns `textContent` and
      // `.dialog-body` sets no `white-space`, so a `\n\n` here would render as
      // a single space: a paragraph break to whoever wrote it and to nobody
      // reading the page.
      title: "It was not asked to exit",
      body:
        message
        + " Killing it now ends the process immediately, and anything it has "
        + "not written to disk is lost.",
      actions,
    });
    return;
  }
  if (code === "unreadable_answer") {
    // #82. The server answered and the answer did not arrive in one piece.
    // For a stop, a kill, a start or a create, "That did not work" is a guess
    // and it guesses wrong: on a 2xx the action DID happen on the machine, and
    // the next thing a person does about "did not work" is tap Stop again or
    // reach for Kill. The page says exactly what it knows, which is that the
    // request was sent and the reply was unusable, and lets the listing say
    // the rest. `api` keeps the real status for this code, so this branch
    // cannot be reached by a refusal.
    showDialog({
      title: "The reply could not be read",
      body:
        "The request was sent and the server answered, but the answer did "
        + "not arrive in one piece. Nothing here says whether it worked. The "
        + "list will catch up.",
      actions: [["Close", "ghost", () => closeDialog()]],
    });
    return;
  }
  if (code === "not_restarting") {
    // #511. Not a failure: the restart was already called off, or the new
    // session has started. The list says which.
    showDialog({
      title: "No restart to call off",
      body: "The restart was already called off, or the new session has started. The list shows which.",
      actions: [["Close", "ghost", () => closeDialog()]],
    });
    refresh();
    return;
  }
  if (["gone", "not_ours", "owned_elsewhere", "not_detached"].includes(code)) {
    // #107. The row was wrong about the world by the time of the tap, and
    // the server refused rather than guessed: the process left, or changed
    // identity, or a session took it, or the row is no longer detached at
    // all. Not a dead end (#169): the next decision is to look again, so
    // the dialog offers the refresh.
    showDialog({
      title: code === "owned_elsewhere" ? "A session owns it" : "Nothing was signalled",
      body: message,
      actions: [
        ["Close", "ghost", () => closeDialog()],
        ["Refresh", "accent", () => {
          closeDialog();
          refresh();
        }],
      ],
    });
    return;
  }
  showDialog({
    title: code === "self_protected" ? "That one is protected" : "That did not work",
    body: message,
    actions: [["Close", "ghost", () => closeDialog()]],
  });
}
