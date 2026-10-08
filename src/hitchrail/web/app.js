/* The interface. No build step: this is an ES module the browser runs as
   written, which is what keeps `uvx hitchrail` a single install with nothing
   to compile. See the design's section 9.1. */

import { api } from "/api.js";
import { trackFooterHeight, trackKeyboardInset, trackScroll } from "/chrome.js";
import { $ } from "/dom.js";
import { render, renderList } from "/list.js";
import { refresh } from "/listing.js";
import { showNewFolder } from "/new_folder.js";
import { setStopPatience, setWrapUpPatience, stopTimeoutMs } from "/patience.js";
import {
  clearSearch,
  closeSuggestions,
  onSearchKey,
  renderSuggestions,
  resetActiveSuggestion,
  syncClearButton,
} from "/search.js";
import { state } from "/state.js";
import { confirmStopAll } from "/stop_all.js";
import { currentStream, onVisible, openStream, setReopenPace } from "/stream.js";
import { applyTheme, storedTheme, toggleTheme } from "/theme.js";

/* What this file exported before it was split, so the entry point still names
   it. Nothing imports it today: the tests reach the page through
   `window.__hitchrail` below. */
export { ANSWER_KEYS } from "/answer.js";
export { api } from "/api.js";
export { formatMb, formatMemory, formatUptime } from "/format.js";
export { render } from "/list.js";
export { setStopPatience, setWrapUpPatience } from "/patience.js";
export { setReopenPace } from "/stream.js";

function boot() {
  applyTheme(storedTheme());
  trackKeyboardInset();
  trackFooterHeight();
  $("[data-theme-toggle]")?.addEventListener("click", toggleTheme);
  $("[data-new]")?.addEventListener("click", () => showNewFolder());
  $("[data-stop-all]")?.addEventListener("click", confirmStopAll);
  document.addEventListener("visibilitychange", onVisible);
  openStream();
  trackScroll();
  const search = $("[data-search]");
  search?.addEventListener("input", (event) => {
    state.query = event.target.value;
    state.chosen = null;
    resetActiveSuggestion();
    syncClearButton();
    renderList();
    renderSuggestions();
  });
  $("[data-search-clear]")?.addEventListener("click", clearSearch);
  search?.addEventListener("keydown", onSearchKey);
  search?.addEventListener("focus", renderSuggestions);
  search?.addEventListener("blur", closeSuggestions);
  refresh();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

/* The ONLY test seam. The browser tier needs to reach the stream to simulate
   a suspended tab (#57); exposing application state as well would let tests
   assert on internals and then pass through a rewrite that broke the page. */
window.__hitchrail = {
  applyTheme,
  toggleTheme,
  refresh,
  render,
  state,
  api,
  setStopPatience,
  setWrapUpPatience,
  stopTimeoutMs,
  setReopenPace,
  openStream,
  get stream() {
    return currentStream();
  },
};
