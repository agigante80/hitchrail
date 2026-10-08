import { api } from "/api.js";
import { closeDialog, showDialog } from "/dialogs.js";
import { refresh } from "/listing.js";
import { showRefusal } from "/refusal.js";

/* Where a session link is allowed to point.

   Claude Code prints it as "Continue here, on your phone, or at
   https://claude.ai/code/<id>", and that link is the whole of how a person
   talks to the agent Hitchrail started: this is a launcher, with no input
   control of its own and a read only log drawer.

   Checked here as well as on the server, which allowlists the bridge id's
   SHAPE. This is the second lock, on the whole value, because the string ends
   up in an `href`: anything that is not this exact origin and path is not
   rendered as a link at all, so a `javascript:` value cannot become one. */
const SESSION_URL_BASE = "https://claude.ai/code/";

export function sessionHref(url) {
  return typeof url === "string" && url.startsWith(SESSION_URL_BASE) ? url : null;
}

export function sessionLink(href, label) {
  const link = document.createElement("a");
  link.className = "btn ghost";
  link.textContent = label;
  // #163. The only control on a row that leaves the page, so it says so. The
  // mark is decorative and hidden from the accessible name, which stays the
  // words: a screen reader and a sighted person hear and read the same label.
  const mark = document.createElement("span");
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = " \u2197";
  link.append(mark);
  link.href = href;
  link.target = "_blank";
  // `noreferrer` as much as `noopener`. Without it the outbound request
  // carries this page's URL, which names a machine on somebody's LAN and the
  // port it serves agents on, to a third party. The token is in a fragment and
  // never sent; the hostname is not.
  link.rel = "noopener noreferrer";
  return link;
}

/* The link, asked for on demand.

   The listing carries only the BRIDGE url, which is read from a file and is
   known good. This route also captures the pane and may come back with one
   scraped out of it, which can be scrollback from a session that ended hours
   ago. #29 decided those must not be shown as equals, so the scraped one
   arrives with its provenance attached rather than as an ordinary link. */
export async function showSessionLink(project) {
  const result = await api(`/api/sessions/${encodeURIComponent(project.name)}/url`);
  if (!result.ok) {
    if (result.body.code === "url_pending") {
      showDialog({
        title: "No link yet",
        body:
          "This session has not published one. It may still be starting, or "
          + "waiting for an answer in the terminal that only you can give.",
        actions: [["Close", "ghost", () => closeDialog()]],
      });
      return;
    }
    showRefusal(result);
    return;
  }
  const href = sessionHref(result.body.url);
  if (href === null) {
    showDialog({
      title: "That link cannot be opened",
      body: "The session reported a link that does not point at claude.ai.",
      actions: [["Close", "ghost", () => closeDialog()]],
    });
    return;
  }
  if (result.body.source === "bridge") {
    // The row can carry it itself now.
    closeDialog();
    await refresh();
    return;
  }
  showDialog({
    title: "Found in the pane",
    body:
      "This link was read off the terminal rather than published by the "
      + "session, so it may belong to an earlier session in the same pane.",
    actions: [["Close", "ghost", () => closeDialog()]],
    extra: sessionLink(href, "Open it anyway"),
  });
}
