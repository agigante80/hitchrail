import { $ } from "/dom.js";
import { applySession, refresh } from "/listing.js";

/* -- the stream --------------------------------------------------------
   The stream is an INVALIDATION SIGNAL, not the source of truth.

   `EventSource` reconnects on its own; what it cannot do is tell you what
   changed while it was away. A page that only applies events shows a row that
   has been wrong since the tab was suspended, and that looks exactly like a
   row where nothing is happening, which is this tool's normal state.

   So a reconnect re-fetches the listing. The source of truth stays the same
   derivation every other caller gets, which is the design's whole position on
   state. */

let stream = null;

/* Same reason as `resetActiveSuggestion`: the listing and the test seam read the
   stream, and an imported `let` would hand them a binding that cannot be
   reassigned underneath them when `openStream` replaces it. */
export function currentStream() {
  return stream;
}

let reopenTimer = null;

/* `connecting` and `open` carry no message: a permanent "live" badge is noise
   on a phone, and the state worth a person's attention is the one where the
   list has stopped being true. */
const STREAM_MESSAGE = {
  down: "Not live. Reconnecting.",
  blind: "Live, but this machine cannot be read.",
};

export function setStreamState(value) {
  // Reveal FIRST, then write. The text is written rather than selected by CSS
  // from spans already in the markup, because a live region announces a DOM
  // mutation and not a change of computed style: picking a span would mutate
  // nothing at all on the `down` to `blind` step. But writing into a subtree
  // that is still `display: none` puts the mutation somewhere that is not in
  // the accessibility tree yet, which is the same miss by a different route.
  document.documentElement.setAttribute("data-stream", value);
  const note = $("[data-stream-note]");
  if (note) {
    note.textContent = STREAM_MESSAGE[value] ?? "";
  }
}

/* Three states, not two.
   `open`  we are connected.
   `down`  we are not connected.
   `blind` we are connected and the machine cannot be read.
   The third is `503 machine_unreadable` on the re-fetch, and collapsing it
   into `down` would hide a broken tmux behind a network message. */
/* `EventSource` retries a NETWORK error on its own. It does not retry a
   response it refuses: a non 200 status closes it for good, by specification.
   The reachable case is not exotic. Restarting Hitchrail mints a new token, a
   phone still holding the old cookie is answered 401, and the stream is then
   dead forever while the strip says "Reconnecting", which would be a lie of
   exactly the kind this whole feature exists to prevent. */
const REOPEN_MS = 5000;

const REOPEN_CEILING_MS = 60000;

let reopenDelay = REOPEN_MS;

/* Backed off and capped. The motivating case is a token the server stopped
   accepting, which no amount of asking will fix, so a fixed five seconds would
   be one refused request every five seconds for as long as the tab is open. */
/* Overridable only so the browser tier can watch several reopen attempts
   without waiting fifteen seconds per test (#71). Same shape and same
   argument as `setStopPatience`: not read from the server, and a client that
   shortened it would only make itself impatient. */
let reopenPaceMs = null;

export function setReopenPace(ms) {
  reopenPaceMs = ms;
  reopenDelay = ms;
}

function scheduleReopen() {
  if (reopenTimer !== null) return;
  const delay = reopenDelay;
  reopenDelay = reopenPaceMs ?? Math.min(reopenDelay * 2, REOPEN_CEILING_MS);
  reopenTimer = setTimeout(() => {
    reopenTimer = null;
    openStream();
  }, delay);
}

export function openStream() {
  if (reopenTimer !== null) {
    clearTimeout(reopenTimer);
    reopenTimer = null;
  }
  if (stream) stream.close();
  stream = new EventSource("/api/events");
  // Scoped to this EventSource, so it distinguishes the object's FIRST open
  // from one of its own reconnects. A reopen through `openStream` starts a
  // new object and so starts false again, which is right: whoever called it
  // is responsible for the fetch, and `onVisible` does exactly that.
  let connected = false;

  stream.addEventListener("open", () => {
    setStreamState("open");
    reopenDelay = REOPEN_MS;
    if (connected) {
      // A RECONNECT. The stream was away and cannot say what it missed, so
      // the listing is re-read. The first open needs nothing: `boot` fetches.
      refresh();
    }
    connected = true;
  });

  stream.addEventListener("message", (event) => {
    let session;
    try {
      session = JSON.parse(event.data);
    } catch {
      // A malformed frame is not a reason to tear down a working stream.
      return;
    }
    applySession(session);
  });

  stream.addEventListener("error", (event) => {
    // Fires for a transient drop and for a final one alike. Both are `down`:
    // a list that has quietly stopped updating is indistinguishable from a
    // quiet one, and quiet is this tool's normal state.
    setStreamState("down");
    // `event.target`, not the module's `stream`: this handler belongs to ONE
    // EventSource, and a superseded one would otherwise read the readyState of
    // whichever object replaced it.
    if (event.target.readyState !== EventSource.CLOSED) return;
    // Fatal. Nothing else would ever reopen it: `onVisible` needs the tab to
    // be backgrounded and brought back, which a phone left on this page never
    // does.
    scheduleReopen();
    // And ASK, once, because the reachable fatal case is a token that stopped
    // being accepted. The strip saying "not live" is honest and useless: the
    // listing is what turns a 401 into the screen that says how to get back
    // in, and nothing else would call it.
    refresh();
  });

  return stream;
}

/* The tab came back. `EventSource` may already have reconnected, but it
   cannot replay what it missed, so the listing is re-read. */
export function onVisible() {
  if (document.visibilityState !== "visible") return;
  if (!stream || stream.readyState === EventSource.CLOSED) openStream();
  refresh();
}
