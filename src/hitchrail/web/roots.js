import { state } from "/state.js";

const ROOTS_KEY = "hitchrail.roots";

export function storedRoots() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ROOTS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function rememberRoots() {
  try {
    localStorage.setItem(ROOTS_KEY, JSON.stringify([...state.rootFilter]));
  } catch {
    /* a private window; the filter still applies for this page */
  }
}

/* The states whose row is a column: a badge and up to three controls cannot
   share a line with a name on a phone. Named once, because the stylesheet
   lists the same three and the two must not drift. */
export const TALL_STATES = new Set(["running", "detached", "stale"]);

/* -- #122: the root a row is in ----------------------------------------
 *
 * A project is `<root-label>~<folder>` on the wire. The interface shows the
 * FOLDER, because that is what the person named, and adds the label only when
 * there is more than one root to tell apart. A single root deployment does not
 * pay for a feature it is not using, which is what #122 asks for and what
 * keeps the one line row the design argues for.
 *
 * Splitting on the FIRST `~` is exact rather than lenient: neither half can
 * contain one, because both are held to the same folder allowlist. */
export function splitProject(identifier) {
  const cut = identifier.indexOf("~");
  if (cut < 0) return { label: "", folder: identifier };
  return { label: identifier.slice(0, cut), folder: identifier.slice(cut + 1) };
}

export function severalRoots() {
  return (state.roots ?? []).length > 1;
}

/* -- #294: the agent a row runs ----------------------------------------
 *
 * Named on a row only when the roots shown start more than one agent, for
 * the reason the root chip is: one possible answer is noise. The row's own
 * `agent` wins over its root's, because it is the agent derivation found
 * running, and that is the one a Stop types into; it differs from the root's
 * when the config changed under a running session, and then the chip shows
 * even with one agent configured, since that is the row that surprises. */
function rootAgent(identifier) {
  const { label } = splitProject(identifier);
  return (state.roots ?? []).find((root) => root.label === label)?.agent ?? null;
}

export function agentChip(project) {
  const configured = rootAgent(project.name);
  const running = project.agent ?? configured;
  if (!running) return null;
  const several = new Set((state.roots ?? []).map((root) => root.agent)).size > 1;
  return several || running !== configured ? running : null;
}

/* What to call a project where a person reads it, as opposed to where the API
 * addresses it. With one root that is the bare folder, exactly as before. */
export function displayProject(identifier) {
  const { label, folder } = splitProject(identifier);
  return severalRoots() && label ? `${folder} in ${label}` : folder;
}
