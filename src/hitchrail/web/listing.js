import { api } from "/api.js";
import { closeDetachedDialog, closeDialog } from "/dialogs.js";
import { $ } from "/dom.js";
import { render } from "/list.js";
import { showRefusal } from "/refusal.js";
import { storedRoots } from "/roots.js";
import { state } from "/state.js";
import { currentStream, setStreamState } from "/stream.js";

/* A listing fetched at T0 knows nothing about an event that arrived at T0+1,
   and it lands AFTER it. Without an ordering rule, stopping a session from a
   laptop while the phone happens to be fetching puts the row back to `running`
   and nothing ever corrects it: there is no polling, and a session that
   reached a terminal state sends no further event. So an event that arrives
   while a listing is in flight is kept and re-applied on top of it. */
let fetchesInFlight = 0;

const seenDuringFetch = new Map();

/* Patch one row in place. The whole listing is not re-fetched per event: the
   stream carries the entire session shape precisely so a change costs no
   subprocesses on the server. */
export function applySession(session) {
  if (!session || typeof session.name !== "string") {
    // Not a session. The bus carries one shape and a test asserts it, so this
    // is the belt to that braces: an unrecognised frame must not become a
    // refetch, which is how one publisher's mistake turns into a root scan per
    // client per event.
    return;
  }
  stampStop(session);
  if (fetchesInFlight > 0) {
    // Stamped with the generation current AT ARRIVAL, which is how a listing
    // later decides whether this event predates it or not.
    seenDuringFetch.set(session.name, { generation: listingGeneration, session });
  }
  const index = state.projects.findIndex((p) => p.name === session.name);
  if (index === -1) {
    // A project we do not know about, which on this wire means a folder
    // somebody just created. The listing decides what EXISTS, so ask it rather
    // than inventing a row from an event.
    refreshSoon();
    return;
  }
  state.projects[index] = session;
  // #165. The confirm, the wait and the waiting dialog all carry `forProject`,
  // and all three are about a RUNNING session's stop. When the row leaves
  // `running`, the process they were about is gone and a waiting dialog would
  // go on showing a prompt nobody can answer, inviting a key into nothing.
  // Any other dialog, a log view or a new folder sheet, carries no `for` and
  // is left alone.
  if (session.state !== "running") closeDialog(session.name);
  closeDetachedDialog(session);
  render();
}

/* #411. `stop_age_s` is an age, so it becomes an instant on THIS clock at
   the moment it arrives. Converted later, a row that sat unchanged for a
   minute would read a minute young. */
function stampStop(session) {
  if (typeof session.stop_age_s === "number") {
    session.stopBeganHere = Date.now() - session.stop_age_s * 1000;
  }
  return session;
}

/* One refetch for a burst, not one per event. Creating several folders in a
   script would otherwise cost each connected client a full root scan apiece.

   A real delay, not zero. A due zero millisecond timer runs before the next
   network delivered message, so a zero latch coalesces only frames that arrive
   inside one task, which is not the case this exists for. */
const COALESCE_MS = 150;

let refreshQueued = false;

function refreshSoon() {
  if (refreshQueued) return;
  refreshQueued = true;
  setTimeout(() => {
    refreshQueued = false;
    refresh();
  }, COALESCE_MS);
}

/* -- start ------------------------------------------------------------- */

/* Take what this listing is allowed to be overruled by, and drop the rest.

   The rule is NOT "an event during any fetch beats that fetch". It is "an
   event beats a listing that was asked for BEFORE it arrived", which is what
   the generation on each held event records. A fetch issued AFTER the event
   is fresher and must win: an agent that exits on its own announces nothing,
   so a listing is the only thing that can ever report it, and overwriting one
   with an older event would hide exactly that.

   Called on every completed listing that is still the newest, failed ones
   included. Anything held at that point is either applied here or already
   stale, since no later fetch can carry a smaller generation. Clearing only on
   success was this fix's own bug: a 503 left an entry behind for some
   arbitrarily later listing to apply. */
function takeHeld(generation) {
  const owed = new Map();
  for (const [name, held] of seenDuringFetch) {
    if (held.generation >= generation) owed.set(name, held.session);
  }
  seenDuringFetch.clear();
  return owed;
}

let listingGeneration = 0;

export async function refresh() {
  // Two refetches racing is the ordinary case, not a corner: a phone returning
  // to the foreground fires `visibilitychange` and the stream's own reopen in
  // the same tick. Whichever was issued last owns the list, however they land.
  const generation = ++listingGeneration;
  fetchesInFlight += 1;
  let result;
  try {
    result = await api("/api/projects");
  } finally {
    // `api` does not reject. A dead network and an unreadable body both come
    // back as `ok: false`, the first with status 0 and the second with the
    // status the server actually sent, which is the distinction the branch
    // below turns into "not live" versus "cannot be read". This is here for a
    // throw from `api` itself, and the counter has to come back either way,
    // since leaving it high would hold every later event as owed to a fetch
    // that ended.
    fetchesInFlight -= 1;
  }
  // Superseded. Say nothing and touch nothing: a newer listing owns the page,
  // and reporting THIS one's failure would put "Not live" on a page that is.
  if (generation !== listingGeneration) return result;
  const owed = takeHeld(generation);
  if (!result.ok) {
    if (result.status === 0) {
      setStreamState("down");
      return result;
    }
    if (result.status === 401) {
      // Actionable, and the only failure that is. The stream is being refused
      // too and says so; what a person needs here is the way back in.
      showRefusal(result);
      return result;
    }
    // Connected, and the listing could not be read. Every remaining failure is
    // that, whether the root went away, tmux broke or the server faulted.
    // None of them is `down`: reporting a network problem for a root that was
    // unmounted sends somebody to look at their wifi instead of their mount.
    //
    // #72. Unless the stream is provably NOT live. The fatal branch calls this
    // after the stream closed for good, and "Live, but this machine cannot be
    // read" at that moment is the lie the strip exists to prevent. CLOSED is
    // the test, not OPEN: at boot this runs while the stream is still
    // connecting, and an unreadable machine then is still `blind`, which the
    // recovery branch below already agrees with when it clears it.
    if (!currentStream() || currentStream().readyState !== EventSource.CLOSED) {
      setStreamState("blind");
    }
    return result;
  }
  if (document.documentElement.getAttribute("data-stream") === "blind") {
    setStreamState(
      currentStream() && currentStream().readyState === EventSource.OPEN ? "open" : "down",
    );
  }
  // #120: the payload carries a LIST of labelled roots, one root included.
  // One root still reads as its bare path, because a label the operator never
  // sees does not earn a line on a phone; several read as their labels, which
  // is what the badge on each row matches.
  const roots = result.body.roots ?? [];
  const rootEl = $("[data-root]");
  if (rootEl) {
    rootEl.textContent =
      roots.length === 1 ? roots[0].path : roots.map((r) => r.label).join(", ");
    // One line in the bar (#320), cut with an ellipsis. The title is for a
    // pointer: Android Chrome shows no tooltip for it (a tap or a long press
    // opens tap to search, seen on a Pixel, #466), and the chips and the
    // settings page carry the same text.
    rootEl.title = rootEl.textContent;
  }
  // `owed` holds only what arrived after this listing was asked for, so those
  // are newer than it whatever order the two landed in.
  state.projects = result.body.projects.map((p) => owed.get(p.name) ?? stampStop(p));
  state.unsupported = result.body.unsupported;
  state.unsupportedTotal = result.body.unsupported_total;
  state.roots = roots;
  state.root = roots.length === 1 ? roots[0].path : "";
  // #146. The remembered selection, intersected with what is actually here:
  // a root removed from the command line drops out of the filter, and one
  // root means no filter at all, so a selection stored by an earlier multi
  // root configuration cannot filter the one root to nothing.
  const present = new Set(roots.map((r) => r.label));
  state.rootFilter = new Set(
    roots.length > 1 ? [...state.rootFilter, ...storedRoots()].filter((l) => present.has(l)) : [],
  );
  state.hiddenRoots = result.body.hidden_roots ?? [];
  state.hiddenRootsEditable = result.body.hidden_roots_editable ?? [];
  state.memory = result.body.memory;
  // #479. A listing is the only report of an agent that died unannounced.
  const detachedFor = $("[data-dialog]")?.dataset.detachedFor;
  if (detachedFor !== undefined) {
    closeDetachedDialog(state.projects.find((p) => p.name === detachedFor) ?? { name: detachedFor });
  }
  state.server = result.body.server ?? state.server;
  render();
  return result;
}
