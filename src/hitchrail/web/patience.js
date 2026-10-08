import { state } from "/state.js";

/* The server owns the real timeout and reports it on the listing's `server`
   object (#238), so the interface's patience is that number and never a
   second copy of the rule: an operator who started with `--stop-timeout 60`
   used to get a page that gave up at 30 and said "it has not finished"
   while the server was still waiting. Erring long is right: showing "no
   answer" while the engine is still waiting would offer a kill the
   situation does not call for.

   The override exists only so the browser tier can reach the timeout screen
   without waiting thirty seconds per test, and it wins over the server's
   figure until the page is reloaded; a client that shortened it would only
   make itself impatient. */
let stopPatienceMs = null;

export function stopTimeoutMs() {
  if (stopPatienceMs !== null) return stopPatienceMs;
  const seconds = state.server.stop_timeout;
  return typeof seconds === "number" && seconds > 0 ? seconds * 1000 : 30_000;
}

export function setStopPatience(ms) {
  stopPatienceMs = ms;
}

/* #242. The wrap up's ceiling, from the same listing and with the same
   override rule as the stop's; zero when no prompt is set, so every deadline
   that adds it is today's. */
let wrapUpPatienceMs = null;

export function wrapUpSeconds() {
  const seconds = state.server.stop_prompt_timeout;
  return typeof seconds === "number" && seconds > 0 ? seconds : 300;
}

export function wrapUpTimeoutMs() {
  if (!state.server.stop_prompt_set) return 0;
  if (wrapUpPatienceMs !== null) return wrapUpPatienceMs;
  return wrapUpSeconds() * 1000;
}

export function setWrapUpPatience(ms) {
  wrapUpPatienceMs = ms;
}
