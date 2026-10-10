/* #474. What a row wrapping up says, as arithmetic and nothing else: no
   imports, no DOM, no clock of its own, so the tests can hand it any "now".

   `stopBeganHere` is an instant on THIS device's clock, made by `listing.js`
   from the server's `stop_age_s` at the moment the row arrived. The time left
   is the server's ceiling minus the time elapsed on this clock since then, so
   the phone's clock is never compared with a server timestamp, and a reload
   resumes from the age the server reports instead of from the full ceiling. */

export const SENDING_EXIT = "sending the exit";

/* Whole seconds left, or null when the row is not in its wrap up or its start
   is not known. Rounded UP and floored at zero: zero then means the ceiling
   has passed, and a wrap up never reads a negative time. */
export function wrapUpLeft(session, nowMs, ceilingS) {
  if (session?.stopping_phase !== "closing") return null;
  if (typeof session.stopBeganHere !== "number" || !Number.isFinite(ceilingS)) return null;
  const elapsed = (nowMs - session.stopBeganHere) / 1000;
  return Math.max(0, Math.ceil(ceilingS - elapsed));
}

/* The chip's words for a `closing` row. Without a time, plain "wrapping up". */
export function wrapUpWords(left) {
  if (left === null) return "wrapping up";
  if (left === 0) return SENDING_EXIT;
  const seconds = String(left % 60).padStart(2, "0");
  return `wrapping up ${Math.floor(left / 60)}:${seconds}`;
}
