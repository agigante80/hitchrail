import { $ } from "/dom.js";

/* -- dialogs -----------------------------------------------------------
   One dialog element, reused, because the stop sequence ESCALATES rather than
   branching: the same surface changes what it offers as the situation
   changes. A second dialog for the kill would put the destructive path on
   screen beside the safe one. */

/* `onlyIfFor` is passed DELIBERATELY, never by a listener.
 *
 * This function is handed to `addEventListener` in several places, and a
 * listener receives the click event as its first argument. When this gained a
 * parameter, that event silently became `onlyIfFor`, never matched, and every
 * Cancel and Close stopped working. The call sites wrap it for that reason. */
export function closeDialog(onlyIfFor) {
  const dialog = $("[data-dialog]");
  if (!dialog?.open) return;
  // A background stop finishing must not close a dialog somebody opened
  // afterwards. Hide, keep stopping leaves the stop running, so by the time
  // it completes the person may be reading a log drawer or naming a new
  // folder, and closing that out from under them looks like a crash.
  if (onlyIfFor !== undefined && dialog.dataset.for !== onlyIfFor) return;
  dialog.close();
}

/* #479. A dialog about a DETACHED agent cannot carry `forProject`, whose
   close rule is "the row left running" and which a detached row never is.
   It carries `detachedFor` instead, and closes when the row leaves
   `detached` (the agent died, or a terminal took it over): the End it offers
   would otherwise be answered with a 409 `not_detached`. */
export function closeDetachedDialog(session) {
  const dialog = $("[data-dialog]");
  if (!dialog?.open || dialog.dataset.detachedFor === undefined) return;
  if (dialog.dataset.detachedFor !== session?.name) return;
  if (session.state !== "detached") dialog.close();
}

/* `actions` are given SAFEST FIRST. The column layout means first is topmost
   and furthest from the thumb, which is the placement section 7 asks for. */
export function showDialog({ title, body, actions, extra, forProject, detachedFor, wide = false }) {
  const dialog = $("[data-dialog]");
  if (!dialog) return;
  dialog.replaceChildren();
  delete dialog.dataset.refusal;
  delete dialog.dataset.bulk;
  delete dialog.dataset.waiting;
  delete dialog.dataset.detachedFor;
  if (detachedFor !== undefined) dialog.dataset.detachedFor = detachedFor;
  // #168. Only the pane view asks for room, and only the stylesheet's wide
  // breakpoint grants it: the confirmation and the rest of the stop sequence
  // share this element and keep the phone's column at every width.
  if (wide) dialog.dataset.wide = "";
  else delete dialog.dataset.wide;
  if (forProject === undefined) {
    delete dialog.dataset.for;
  } else {
    dialog.dataset.for = forProject;
  }

  const heading = document.createElement("h2");
  heading.className = "dialog-title";
  heading.textContent = title;
  dialog.append(heading);

  if (body) {
    const paragraph = document.createElement("p");
    paragraph.className = "dialog-body";
    paragraph.textContent = body;
    dialog.append(paragraph);
  }
  if (extra) dialog.append(extra);

  const row = document.createElement("div");
  row.className = "dialog-actions";
  for (const [label, className, onClick] of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    row.append(button);
  }
  dialog.append(row);
  if (!dialog.open) dialog.showModal();
}
