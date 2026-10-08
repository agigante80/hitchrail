import { $ } from "/dom.js";
import { render } from "/list.js";
import { rememberRoots, splitProject } from "/roots.js";
import { state } from "/state.js";

/* `Stopped` is NOT the stopped STATE. The canvas computes it as
   `all.length - runNames.length`, so a stale or detached row belongs there:
   it is not running, and those are the two rows a person most needs to find.
   Filtering on the state string would hide exactly them. */
export const isRunning = (project) => project.state === "running";

export function visibleProjects() {
  const query = state.query.trim().toLowerCase();
  return state.projects.filter((project) => {
    if (state.tab === "running" && !isRunning(project)) return false;
    if (state.tab === "stopped" && isRunning(project)) return false;
    // #146. OR among roots, AND with the rest: an empty set is no filter.
    if (state.rootFilter.size > 0 && !state.rootFilter.has(splitProject(project.name).label)) {
      return false;
    }
    // #164. The FOLDER, not the qualified string: roots have chips, and a
    // search over `root~folder` matched the `work` root by coincidence and a
    // folder called `homework` in any root on purpose nobody had.
    if (state.chosen !== null) return project.name === state.chosen;
    if (query && !splitProject(project.name).folder.toLowerCase().includes(query)) return false;
    return true;
  });
}

/* #146. One button per root, pressed or not, with how many rows it holds.
   Nothing here is a server side parameter: it filters a list the client
   already has in full, and the failure direction is showing MORE rows than
   asked for, never fewer. Labels reach the DOM as text. */
export function renderChips() {
  const strip = $("[data-roots]");
  if (!strip) return;
  const roots = state.roots ?? [];
  if (roots.length <= 1) {
    strip.hidden = true;
    strip.replaceChildren();
    return;
  }
  strip.hidden = false;
  const counts = new Map();
  for (const project of state.projects) {
    const { label } = splitProject(project.name);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  strip.replaceChildren(
    ...roots.map((root) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-pressed", String(state.rootFilter.has(root.label)));
      button.dataset.root = root.label;
      // A space before the count, so the accessible name is "bravo 10" and
      // not "bravo10": read aloud, one is a root and a number and the other
      // is a word nobody named anything.
      button.append(`${root.label} `);
      const count = document.createElement("span");
      count.className = "tab-count";
      count.textContent = String(counts.get(root.label) ?? 0);
      button.append(count);
      button.addEventListener("click", () => {
        if (state.rootFilter.has(root.label)) state.rootFilter.delete(root.label);
        else state.rootFilter.add(root.label);
        rememberRoots();
        render();
      });
      return button;
    }),
  );
}

/* Why the list is empty, in the filters' own words, so a person is not told
   "nothing matches" by a filter they set and forgot. */
export function emptyReason() {
  const where = state.rootFilter.size > 0 ? ` in ${[...state.rootFilter].join(", ")}` : " here";
  const query = state.query.trim();
  if (query) return `No folder${where} is called that.`;
  if (state.tab === "running") return `Nothing${where} is running.`;
  if (state.tab === "stopped") return `Nothing${where} is stopped.`;
  // #154. Every root hidden is not "no folder": the honest empty state
  // names the roots that are not being listed, and settings is where they
  // come back.
  //
  // Two corrections from #256, both about saying something that is not
  // true. It used to fire on zero PROJECTS, so a visible root that is
  // merely empty beside a hidden one read as "every root is hidden"; the
  // question is whether any root is being listed at all, which is
  // `state.roots`. And it said "show one in settings" for roots the
  // operator's file disables, where the settings page has no checkbox:
  // `hidden_roots_editable` is the ones a request can bring back, and
  // when there are none the sentence names the file instead.
  if ((state.roots ?? []).length === 0 && state.hiddenRoots.length > 0) {
    const named = state.hiddenRoots.join(", ");
    return state.hiddenRootsEditable.length > 0
      ? `Every root is hidden (${named}). Show one in settings.`
      : `Every root is hidden (${named}), by the config file. Enable one there.`;
  }
  return `No folder${where}.`;
}

export function renderTabs() {
  const running = state.projects.filter(isRunning).length;
  const counts = {
    all: state.projects.length,
    running,
    stopped: state.projects.length - running,
  };
  const strip = $("[data-tabs]");
  if (!strip) return;
  strip.replaceChildren(
    ...[
      ["all", "All"],
      ["running", "Running"],
      ["stopped", "Stopped"],
    ].map(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(state.tab === key));
      button.dataset.tab = key;
      button.append(label);
      const count = document.createElement("span");
      count.className = "tab-count";
      count.textContent = String(counts[key]);
      button.append(count);
      button.addEventListener("click", () => {
        state.tab = key;
        render();
      });
      return button;
    }),
  );
}
