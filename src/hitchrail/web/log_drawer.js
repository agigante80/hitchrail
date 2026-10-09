import { answerPad } from "/answer.js";
import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";

/* -- the log drawer ---------------------------------------------------- */

/* The pane, with the keypad when the row is waiting on a person. ONE renderer,
   used by the log drawer and by the waiting dialog (#165). Never null: an
   unreadable pane yields a note saying so, because a dialog built on this
   must not show an empty box that reads as "nothing is being asked". */
export async function paneView(project) {
  const result = await api(
    `/api/sessions/${encodeURIComponent(project.name)}/logs?lines=40`,
  );
  const extra = document.createElement("div");
  if (!result.ok) {
    const note = document.createElement("p");
    note.className = "meta";
    note.textContent = `The pane could not be read: ${result.body.message}`;
    extra.appendChild(note);
    return extra;
  }
  const pane = document.createElement("pre");
  pane.className = "log-pane";
  pane.textContent = result.body.text || "The pane has printed nothing yet.";
  // #204. The keypad appears only for a row the sweep has already flagged as
  // waiting on a person. Not on every log view: a keypad under a healthy
  // session invites a keystroke into a working agent, and the flag is the same
  // one the row badge uses, so what the list says and what this offers agree.
  //
  // The flag is a hint, never the guard. It is up to 30s old by `attention.TTL_S`,
  // and the server re-reads the pane inside the send regardless.
  extra.appendChild(pane);
  if (project.awaiting_trust || project.awaiting_input) {
    extra.appendChild(answerPad(project, pane));
  }
  return extra;
}

export async function openLogs(project) {
  const waiting = project.awaiting_trust || project.awaiting_input;
  const extra = await paneView(project);
  // #151. The same tail in a tab of its own, bookmarkable and sized by the
  // window. The drawer stays: reading forty lines without leaving the list
  // is the common case, and this is for watching one project while acting
  // on another. Same origin, so no rel is needed, and a real anchor for the
  // reason the session link is one: it is what long press and open in new
  // tab reach for.
  const tab = document.createElement("a");
  tab.className = "btn ghost";
  tab.href = `/logs/${encodeURIComponent(project.name)}`;
  tab.target = "_blank";
  tab.textContent = "Open in a tab";
  extra.append(tab);
  showDialog({
    title: project.name,
    body: waiting
      ? "this session is waiting for an answer"
      : "last 40 lines of the pane",
    extra,
    wide: true,
    actions: [["Close", "ghost", () => closeDialog()]],
  });
}
