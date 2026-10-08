import { api } from "/api.js";
import { showRefusal } from "/refusal.js";

/* -- answering a prompt the agent is blocked on (#204) ------------------ */

// The keys this interface offers, and the only ones the server will carry.
// Mirrors `ANSWER_KEYS` in `claude_ipc/keys.py`, and a test asserts the two lists
// are the same, because a key offered here and refused there is a button that
// does nothing.
//
// **There is deliberately no text field, and adding one is the line.** The
// safety of this whole path is that the operator reads Claude Code's own words
// in the pane above and presses the key those words name. A field would let
// Hitchrail carry an instruction the pane never offered, which is the terminal
// `docs/roadmap.md` defers.
//
// The digits are shown WITHOUT reading the prompt to see which it names.
// Parsing the options is the version-volatile thing this project has got wrong
// three times, and offering a wrong list means a keypress that means something
// other than its label.
export const ANSWER_KEYS = [
  "Up", "Down", "Enter", "Escape",
  "1", "2", "3", "4", "5", "6", "7", "8", "9",
];

// One send at a time. A phone double-tap would otherwise queue two POSTs, and
// while the server's re-read refuses the second in the ordinary case, "the
// second one is usually refused" is not a thing to rely on for a keystroke into
// a shell. Module scoped rather than per-button: the hazard is two KEYS, not
// one button twice.
let answerInFlight = false;

async function sendAnswer(project, key, pane) {
  if (answerInFlight) return;
  answerInFlight = true;
  try {
    await sendAnswerOnce(project, key, pane);
  } finally {
    answerInFlight = false;
  }
}

async function sendAnswerOnce(project, key, pane) {
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}/answer`, {
    method: "POST",
    body: JSON.stringify({ key }),
  });
  if (!result.ok) {
    // Includes `not_asking`, which is the ordinary case rather than an error:
    // the screen moved on between the capture and the press.
    showRefusal(result);
    return;
  }
  // Re-read rather than assuming. The operator pressed a key at a screen and
  // the only honest confirmation is the screen afterwards.
  const fresh = await api(`/api/sessions/${encodeURIComponent(project.name)}/logs?lines=40`);
  if (fresh.ok) {
    pane.textContent = fresh.body.text || "The pane has printed nothing yet.";
  }
}

export function answerPad(project, pane) {
  const pad = document.createElement("div");
  pad.className = "answer-pad";

  const note = document.createElement("p");
  note.className = "meta";
  note.textContent = "Read the question above, then press the key it names.";
  pad.appendChild(note);

  const keys = document.createElement("div");
  keys.className = "answer-keys";
  for (const key of ANSWER_KEYS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "answer-key";
    button.textContent = key;
    button.setAttribute("aria-label", `Send ${key}`);
    button.addEventListener("click", () => sendAnswer(project, key, pane));
    keys.appendChild(button);
  }
  pad.appendChild(keys);
  return pad;
}
