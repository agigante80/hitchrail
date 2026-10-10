import { buildActions } from "/actions.js";
import { formatMemory, formatUptime } from "/format.js";
import { TALL_STATES, agentChip, severalRoots, splitProject } from "/roots.js";
import { chipWords } from "/wrapup_tick.js";

function badgeFor(project) {
  // The canvas: `live && live.controller ? 'controller' : 'running'`. The
  // controller badge replaces the state badge rather than sitting beside it.
  if (project.protected) return "controller";
  // `stopping` outranks `waiting`, and the order of these lines is the
  // statement, not an accident (#183). A stop in flight is the action the
  // person already took, and the wait dialog is where a prompt met during it
  // is reported, with the pane and the keys. A row that is both is one whose
  // stop ran into a question, and the badge names the thing they are waiting
  // ON rather than the thing they are waiting FOR.
  if (project.stopping) return "stopping";
  // #88. `running` is true and useless here: the agent is alive and sitting on
  // a prompt that only somebody at a terminal can answer, so it will sit there
  // forever. A row saying nothing but "running" is the interface asserting
  // something it knows to be misleading, which the design forbids everywhere
  // else. An overlay like `stopping`, not a fifth state.
  //
  // #183. Every clause of that is true of `awaiting_input` too. The two flags
  // are kept apart in `sessions.py` because they are FOUND differently and
  // cost differently, which is a fact about derivation and not about what a
  // row should look like: both answers are "go to the pane", so the badge
  // means "a person is needed" rather than naming which prompt. The meta line
  // still says which. Descriptive only, as #91 requires of a signal an agent
  // can produce: the badge gates nothing.
  if (project.awaiting_trust || project.awaiting_input) return "waiting";
  return project.state;
}

function metaFor(project) {
  if (project.state === "detached") {
    // The pid, and who owns the agent when anything we can see does (#85).
    // This is the state a naive tool gets wrong, so it is never rendered as an
    // ordinary stopped row.
    //
    // **The two branches are not the same claim, and the old single line made
    // the stronger one.** It said "no tmux session", which the server cannot
    // know: ownership is read from one `list-panes -a`, covering the tmux
    // server on Hitchrail's own socket and nothing else. An agent under a
    // different socket, under screen, or under a plain terminal arrives here
    // with `foreign_session` null and is not orphaned at all.
    //
    // Telling somebody their agent is unowned when it is sitting in a terminal
    // they have open invites the wrong action, and the wrong action here is the
    // destructive one.
    if (project.foreign_session) {
      return `pid ${project.pid}  ·  in tmux session ${project.foreign_session}`;
    }
    // #189. A tmux server above the agent that is not the one Hitchrail
    // talks to: the row can say a tmux holds it, and cannot name the session.
    if (project.foreign_server_pid) {
      return `pid ${project.pid}  ·  in a tmux server Hitchrail is not configured for (pid ${project.foreign_server_pid})`;
    }
    return `pid ${project.pid}  ·  no session Hitchrail can address`;
  }
  if (project.state === "stale") return "no agent in the session";
  // Says what to do, because nothing here can do it. Hitchrail cannot answer
  // that prompt on the operator's behalf: that would be agreeing to trust a
  // folder for them, silently, which needs its own argument and does not have
  // one (#88).
  if (project.awaiting_trust) return "waiting to be trusted  ·  open the pane to answer";
  // #101. Set when a stop's wait ended with the agent on a prompt. The row has
  // to carry it too: the dialog can be dismissed, and the session is still
  // sitting there waiting for somebody.
  if (project.awaiting_input) return "waiting for an answer  ·  open the pane to answer";
  // #472. A start that followed a restart was refused: the row stays stopped,
  // and this is the only place the reason is, so it is not dismissible.
  if (project.restart_refused) return `restart not started  ·  ${project.restart_refused}`;
  if (project.pid === null) return project.restarting ? RESTARTING : "";
  const usual = `${formatMemory(project)}  ·  up ${formatUptime(project.uptime_s)}`;
  return project.restarting ? `${RESTARTING}  ·  ${usual}` : usual;
}

const RESTARTING = "restarting  ·  a new session starts once it exits";

export function renderRow(project) {
  const row = document.createElement("article");
  row.className = "row";
  row.dataset.project = project.name;
  row.dataset.state = project.state;
  if (project.protected) row.dataset.protected = "true";
  if (project.stopping) row.dataset.stopping = "true";
  if (project.restarting) row.dataset.restarting = "true";

  const head = document.createElement("div");
  head.className = "row-head";

  const { label, folder } = splitProject(project.name);

  const name = document.createElement("span");
  name.className = "row-name";
  // textContent, never innerHTML. A project name is a folder name and
  // therefore attacker chosen by anybody who can write to the root. The label
  // is not: it comes from `--root`, which the operator typed. Both go through
  // textContent anyway, because the rule is about the sink and not the source.
  name.textContent = folder;
  head.append(name);

  // Only with something to tell apart. One root means one possible answer, and
  // a chip repeating it on every row is noise on the scarcest screen.
  if (severalRoots() && label) {
    const where = document.createElement("span");
    where.className = "row-root";
    where.dataset.rootLabel = label;
    where.textContent = label;
    head.append(where);
  }

  const agent = agentChip(project);
  if (agent) {
    const which = document.createElement("span");
    which.className = "row-root row-agent";
    which.dataset.agent = agent;
    which.textContent = agent;
    head.append(which);
  }

  const badge = document.createElement("span");
  badge.className = "badge";
  const word = badgeFor(project);
  badge.dataset.badge = word;
  // #150. The glyph beside the word, never instead of it: decorative to a
  // screen reader, which hears the word, and a shape a scanning eye picks
  // out before it reads. One `<use>` into the inline sprite in index.html.
  const glyph = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  glyph.setAttribute("aria-hidden", "true");
  glyph.setAttribute("class", "badge-glyph");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#badge-${word}`);
  glyph.append(use);
  // #474. The glyph and the colour stay `stopping`; only the words change, and
  // only while the wrap up runs. `exiting` keeps "stopping".
  const closing = word === "stopping" && project.stopping_phase === "closing";
  if (closing) badge.dataset.wrapUp = "";
  badge.append(glyph, closing ? chipWords(project) : word);
  head.append(badge);

  const actions = document.createElement("div");
  actions.className = "row-actions";
  // WHERE the actions go is the whole of the mobile layout, and it depends on
  // how many there are (#75, found on a real phone).
  //
  // A stopped row has one control, so it sits on the name's line and the row
  // stays one line tall: that asymmetry is the design's argument for scanning
  // forty rows with a thumb.
  //
  // A tall row has up to three, plus a badge, and they do NOT fit beside a
  // name at 390px. `.row-actions` is `flex-shrink: 0`, so with them inside the
  // head the name was the only thing that could give, and `overflow-wrap:
  // anywhere` let it give down to ONE CHARACTER per line: a five letter
  // project rendered as five stacked letters with `Stop` cut off past the
  // edge. They get their own line instead.
  //
  // The stylesheet already assumed this. `.row[data-state="running"]
  // .row-actions { margin-left: 0 }` only means anything for actions that are
  // a child of the row, and the desktop query putting `auto` back only means
  // anything on a line of their own. The markup was the half that disagreed.
  const ownLine = TALL_STATES.has(project.state);
  if (!ownLine) head.append(actions);
  row.append(head);
  if (ownLine) row.append(actions);

  const meta = metaFor(project);
  if (meta) {
    const line = document.createElement("p");
    line.className = "meta";
    line.textContent = meta;
    row.append(line);
  }

  buildActions(project, actions);
  return row;
}
