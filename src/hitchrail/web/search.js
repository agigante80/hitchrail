import { $ } from "/dom.js";
import { visibleProjects } from "/filters.js";
import { renderList } from "/list.js";
import { severalRoots, splitProject } from "/roots.js";
import { state } from "/state.js";

/* -- #164: the search suggests ----------------------------------------
   The suggestions are the rows the query would show, from `state.projects`
   and nothing fetched: the filter and the popup are two views of one query,
   so the list underneath is always right while the popup is open. */
const SUGGESTION_CAP = 8;

let activeSuggestion = -1;

/* An imported `let` is read only in the importer, so the page's input handler
   asks this module to forget the highlighted row instead of assigning it. */
export function resetActiveSuggestion() {
  activeSuggestion = -1;
}

/* #451. The clear control is present only while the field holds text. */
export function syncClearButton() {
  const clear = $("[data-search-clear]");
  const box = $("[data-search]");
  if (clear && box) clear.hidden = box.value === "";
}

/* #451. Clears the TEXT and nothing else. The status tab and the root chips
   are filters with controls of their own, and a person who tapped X to retype
   a name did not ask to lose them; a later change that "resets the view" here
   would re-decide that without anyone having decided it. Focus stays in the
   field so the keyboard stays up and the next character lands in it. */
export function clearSearch() {
  const box = $("[data-search]");
  state.query = "";
  state.chosen = null;
  resetActiveSuggestion();
  if (box) {
    box.value = "";
    box.focus();
  }
  syncClearButton();
  renderList();
  renderSuggestions();
}

function suggestions() {
  // #248. A choice is the end of the interaction: the chosen row is the one
  // match and it is on the list already, so the popup stays closed until
  // the text is edited again, whatever renders in between.
  if (state.chosen !== null) return [];
  return state.query.trim() ? visibleProjects().slice(0, SUGGESTION_CAP) : [];
}

export function renderSuggestions() {
  const box = $("[data-search]");
  const list = $("[data-suggestions]");
  if (!box || !list) return;
  const items = suggestions();
  if (items.length === 0 || document.activeElement !== box) {
    closeSuggestions();
    return;
  }
  if (activeSuggestion >= items.length) activeSuggestion = -1;
  list.replaceChildren(
    ...items.map((project, index) => {
      const { label, folder } = splitProject(project.name);
      const item = document.createElement("li");
      item.id = `search-option-${index}`;
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(index === activeSuggestion));
      item.textContent = folder;
      if (severalRoots() && label) {
        const where = document.createElement("span");
        where.className = "row-root";
        where.textContent = label;
        item.append(where);
      }
      // `mousedown` rather than `click`: a click follows the input's blur, and
      // the blur has closed the popup by then.
      item.addEventListener("mousedown", (event) => {
        event.preventDefault();
        chooseSuggestion(project);
      });
      return item;
    }),
  );
  list.hidden = false;
  box.setAttribute("aria-expanded", "true");
  const active = activeSuggestion >= 0 ? `search-option-${activeSuggestion}` : "";
  if (active) box.setAttribute("aria-activedescendant", active);
  else box.removeAttribute("aria-activedescendant");
}

export function closeSuggestions() {
  const box = $("[data-search]");
  const list = $("[data-suggestions]");
  if (list) {
    list.hidden = true;
    list.replaceChildren();
  }
  if (box) {
    box.setAttribute("aria-expanded", "false");
    box.removeAttribute("aria-activedescendant");
  }
  activeSuggestion = -1;
}

function chooseSuggestion(project) {
  const box = $("[data-search]");
  const { folder } = splitProject(project.name);
  state.query = folder;
  state.chosen = project.name;
  if (box) box.value = folder;
  syncClearButton();
  closeSuggestions();
  renderList();
}

/* The reference pattern's keys and nothing invented: Down and Up move the
   active option, Enter chooses it, Escape closes the popup and leaves the
   text, and a second Escape clears the field. Nothing is chosen by typing. */
export function onSearchKey(event) {
  const items = suggestions();
  const open = !$("[data-suggestions]")?.hidden;
  if (event.key === "ArrowDown" && items.length) {
    event.preventDefault();
    activeSuggestion = (activeSuggestion + 1) % items.length;
    renderSuggestions();
  } else if (event.key === "ArrowUp" && items.length) {
    event.preventDefault();
    activeSuggestion = activeSuggestion <= 0 ? items.length - 1 : activeSuggestion - 1;
    renderSuggestions();
  } else if (event.key === "Enter" && open && activeSuggestion >= 0) {
    event.preventDefault();
    chooseSuggestion(items[activeSuggestion]);
  } else if (event.key === "Escape") {
    event.preventDefault();
    if (open) {
      closeSuggestions();
    } else {
      clearSearch();
    }
  }
}
