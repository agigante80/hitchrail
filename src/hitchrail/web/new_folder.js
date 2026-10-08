import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";
import { refresh } from "/listing.js";
import { state } from "/state.js";

/* -- the new folder sheet ---------------------------------------------- */

export function showNewFolder(message) {
  const field = document.createElement("input");
  field.type = "text";
  field.setAttribute("aria-label", "Folder name");
  field.className = "sheet-field";
  field.value = "";

  const wrapper = document.createElement("div");
  const path = document.createElement("p");
  path.className = "meta";

  // #129. A folder is created IN a root, so with more than one the person
  // picks. **An explicit control rather than a guess**, and the losing
  // candidate is worth recording: defaulting to whatever root the current
  // search or filter implied would be right most of the time and silent when
  // it was wrong, and creating in the wrong tree is cheap to undo and
  // expensive to notice. An explicit choice is wrong only when somebody
  // chooses wrongly, and then the screen said so.
  //
  // With ONE root there is no control at all. The same rule the row chip
  // follows: a single root deployment does not pay for a feature it is not
  // using, and a select with one option is a question with one answer.
  const roots = state.roots ?? [];
  let picker = null;
  if (roots.length > 1) {
    picker = document.createElement("select");
    picker.setAttribute("aria-label", "Root");
    picker.className = "sheet-field";
    for (const root of roots) {
      const option = document.createElement("option");
      option.value = root.label;
      // textContent, because the label came from `--root` and this is a sink.
      option.textContent = root.label;
      picker.append(option);
    }
    const showPath = () => {
      const chosen = roots.find((r) => r.label === picker.value);
      path.textContent = `${chosen ? chosen.path : ""}/`;
    };
    picker.addEventListener("change", showPath);
    showPath();
    wrapper.append(picker, path, field);
  } else {
    path.textContent = `${roots[0]?.path ?? state.root}/`;
    wrapper.append(path, field);
  }

  showDialog({
    title: "New folder",
    // No client side name rule. The API decides, and a second copy of that
    // rule here would drift from it; the copy that drifts is the one a person
    // sees.
    body: message || "",
    extra: wrapper,
    actions: [
      ["Cancel", "ghost", () => closeDialog()],
      ["Create", "accent", () => createProject(field.value, picker?.value)],
    ],
  });
  field.focus();
}

async function createProject(name, chosen) {
  // #120: the API names a project `<root-label>~<folder>`, so a folder has to
  // be created IN a root. The person typed a folder name, not an identifier,
  // and asking them to type `main~thing` would leak the wire format into the
  // one place the interface is meant to be a folder name box.
  //
  // `chosen` is the picker's value when there is one, and with a single root
  // there is no picker and no question to ask.
  const roots = state.roots ?? [];
  const label = chosen ?? roots[0]?.label;
  if (!label) {
    // **Refuse rather than guess.** No label means the listing did not carry
    // its roots, and sending an unqualified name would either be rejected or,
    // worse, be accepted by some future server and land somewhere nobody
    // chose. Guessing is the defect this ticket exists to remove.
    showNewFolder("Hitchrail does not know which root to create this in.");
    return;
  }
  const identifier = `${label}~${name}`;
  const result = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name: identifier }),
  });
  if (!result.ok) {
    showNewFolder(result.body.message);
    return;
  }
  closeDialog();
  await refresh();
}
