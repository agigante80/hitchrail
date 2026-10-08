/* -- the list ----------------------------------------------------------
   State lives here and nowhere else. Every render reads it; nothing reads
   the DOM to find out what is true. */
export const state = {
  projects: [],
  unsupported: [],
  unsupportedTotal: 0,
  root: "",
  memory: { available_mb: null, total_mb: null },
  server: {
    version: null,
    user: null,
    started_at: null,
    stop_timeout: null,
    stop_prompt_set: false,
    stop_prompt_timeout: null,
    stop_policy: "ask",
  },
  tab: "all",
  query: "",
  // #146. Root labels to show; empty means all. A Set, never persisted as
  // the source of truth: `localStorage` is a convenience that survives a
  // reload and is intersected with the roots actually present on every
  // listing, so a stale or forged value can only ever show MORE rows.
  rootFilter: new Set(),
  // #154. Labels of configured roots absent from the listing today, so the
  // empty state can say "hidden" rather than "no folder".
  hiddenRoots: [],
  // #256. Of those, the ones a request can bring back, so the empty state
  // does not send somebody to a page with no checkbox on it.
  hiddenRootsEditable: [],
  // #107. `name:pid` pairs this page has already sent SIGTERM to, so the
  // row offers the escalation and not the same request again. Per page:
  // another client's SIGTERM is not this person's decision to escalate.
  // The pid is in the key so a later agent under the same name starts
  // from End again.
  signalled: new Set(),
  // #164. The identifier a suggestion chose, or null. Choosing is exact where
  // typing is a substring: picking `vessel` from the list must not also show
  // `vessel-social`, and the suggestion carried its root, so this is the
  // whole identifier. Cleared the moment the text is edited again.
  chosen: null,
};
