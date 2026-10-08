/* #149. Collapse the header once the list has scrolled under it, and bring
   it back at the top. With hysteresis: collapsing takes ~30px out of the
   page, and on a page barely taller than the viewport that alone can move
   `scrollY` back under a single threshold and flip the header forever. So
   the collapse waits for 48px and the return waits for under 16px, and a
   page that cannot scroll that far never collapses at all. */
export function trackScroll() {
  const root = document.documentElement;
  const update = () => {
    const scrolled = "scrolled" in root.dataset;
    const y = window.scrollY;
    if (!scrolled && y > 48 && root.scrollHeight - window.innerHeight > 96) {
      root.dataset.scrolled = "";
    } else if (scrolled && y < 16) {
      delete root.dataset.scrolled;
    }
  };
  window.addEventListener("scroll", update, { passive: true });
  update();
}

/* Report how much of the viewport an on screen keyboard is covering (#103).

   Only Safari on iOS needs this. `interactive-widget=resizes-content` in the
   viewport meta makes Chromium and Firefox on Android shrink the LAYOUT
   viewport, so the dialog's own centring puts it back in view and both numbers
   below stay zero. iOS has no such key, resizes only the visual viewport, and
   would otherwise leave a centred sheet with its primary action underneath the
   keyboard.

   `visualViewport` is supported everywhere including iOS, which is why the
   fallback is this and not the VirtualKeyboard API: that one is precise and
   Chromium only, which is the wrong trade for a page opened on whatever phone
   somebody has.

   Guarded, because `visualViewport` is absent in older browsers and the page
   has to work without it: the two custom properties simply keep their
   defaults. */
export function trackKeyboardInset() {
  const vv = window.visualViewport;
  if (!vv) return;
  const apply = () => {
    const style = document.documentElement.style;
    style.setProperty("--visible-height", `${Math.round(vv.height)}px`);
    // What the keyboard covers: everything below the visible area's bottom
    // edge. `offsetTop` matters because iOS scrolls the visual viewport rather
    // than only shrinking it, so the visible band can start part way down.
    const covered = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    style.setProperty("--keyboard-inset", `${Math.round(covered)}px`);
  };
  vv.addEventListener("resize", apply);
  vv.addEventListener("scroll", apply);
  apply();
}

/* The list's end reserves the footer's REAL height (#447). The footer is fixed
   and wraps, so a filter's "12 of 67 shown" line makes it taller than any
   constant measured for the unfiltered one, and the last row stayed under it. */
export function trackFooterHeight() {
  const footer = document.querySelector(".footer");
  if (!footer || !window.ResizeObserver) return;
  new ResizeObserver(() => {
    const height = Math.ceil(footer.getBoundingClientRect().height);
    document.documentElement.style.setProperty("--footer-h", `${height}px`);
  }).observe(footer);
}
