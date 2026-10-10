import { wrapUpSeconds } from "/patience.js";
import { state } from "/state.js";
import { wrapUpLeft, wrapUpWords } from "/wrapup.js";

/* #474. The chip's words for a project, read at the moment of asking. */
export function chipWords(project) {
  return wrapUpWords(wrapUpLeft(project, Date.now(), wrapUpSeconds()));
}

/* Once a second, only the text of the chips that count down. Not a render:
   `render` rebuilds every row, and a rebuild each second would take focus
   from under a thumb (#71). A row whose phase changed arrives as an event and
   is rebuilt by it, so this never has to notice a change of phase. */
export function tickWrapUps() {
  for (const badge of document.querySelectorAll(".badge[data-wrap-up]")) {
    const name = badge.closest("[data-project]")?.dataset.project;
    const project = state.projects.find((p) => p.name === name);
    if (project) badge.lastChild.textContent = chipWords(project);
  }
}
