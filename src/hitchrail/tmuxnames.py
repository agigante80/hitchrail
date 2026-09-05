"""What a valid tmux name IS, and what a tmux invocation looks like.

Pure functions over strings. No subprocess, no state, no server, and a test
asserts it cannot acquire one.

**Split out of `tmux.py` at #93**, along the seam this project has now taken
three times: `hostnames.py` beside `config.py`, `projectnames.py` beside
`discovery.py`, and this beside the adapter. The sentence from the first one is
true here with the nouns changed: the vocabulary is what the adapter reaches
for, the adapter holds the footguns and the spawning, and the dependency runs
one way.

`tmuxnames`, not `tmux_names`: the two modules it is modelled on carry no
underscore, and a third spelling of the same idea is a small tax on everyone who
later has to remember which one this was.

**This module IS security relevant, and `.claude/rules/security.md` names it.**
#93 proposed that the rules should load for "the half that spawns", on the
reading that the vocabulary is inert. It is not. `sanitize`'s injectivity is
what stops two projects reaching one tmux session, and since #119 made a project
`<root-label>~<folder>` that property carries the multi root guarantee too: a
collision here means tapping Stop on one project stops another's agent.
`is_tmux_argv` decides whether a tmux server's own argv is mistaken for an agent
(#84). `projectnames.py` is in that list for exactly this reason and is the
precedent.
"""

from __future__ import annotations

from pathlib import PurePosixPath

# tmux reads both of these as target separators, so neither may appear in a
# session name. `-` is the escape character, which is why it is escaped too.
_SEPARATORS = (".", ":")

# Marks a name that went through the encoding below. A name that would
# otherwise start with it is encoded as well, which is what keeps the encoded
# and unencoded forms disjoint and therefore the whole mapping injective.
_ENCODED_PREFIX = "e-"

# The binary every call in this class invokes. Named once so `is_tmux_argv`
# below and `_argv` cannot disagree about what tmux is called.
BINARY = "tmux"


def is_tmux_argv(args: str) -> bool:
    """Whether a command line is an invocation of tmux itself.

    A tmux server keeps the argv of the invocation that started it, for life,
    and that invocation ends with the command the first session was asked to
    run. So a scan looking for a program by its argv tail finds the server too.
    #84, and `derive.find_detached` is where that costs something.

    Two mechanics, both checked against `ps -eww -o args` output on 2026-09-02
    rather than assumed.

    **argv[0], not a substring anywhere.** The argument after `-c` is a path we
    do not control, so a search of the whole line refuses anything running
    under a directory called tmux.

    **Its basename, because argv[0] is however the caller spelled it.** A
    leading `env -u TMUX` does not survive into the process: env execs tmux and
    is replaced by it, so argv[0] arrives as `tmux` under the private socket
    tiers exactly as it does elsewhere.

    Deliberately NOT a check for `new-session`. `-S <socket>` sits between the
    binary and the subcommand, so anything anchored on those two as one string
    stops working under the invocation our own live tiers make.
    """
    head = args.split(maxsplit=1)
    if not head:
        return False
    return _is_tmux_binary(PurePosixPath(head[0]).name)


def _is_tmux_binary(name: str) -> bool:
    """Whether a basename names tmux itself, allowing a version or build suffix.

    #96. `== BINARY` alone missed `tmux-3.4` and `tmux3`, and a server somebody
    ELSE started under such a name reopens #84 on that machine: its argv still
    ends with the agent's command line, so orphan attribution claims it and the
    row shows the server's pid, RSS and uptime, with `ram_mb` feeding the memory
    guard. Our own `_argv` invokes plain `BINARY`, so this can only ever be
    another tool's server on the same default socket, which is precisely #84's
    finding.

    **`startswith` is the obvious fix and it is wrong.** It claims `tmuxinator`,
    `tmuxp` and `tmuxifier`, which are real programs that SPAWN tmux. Claiming
    one hides a genuine agent, which is worse than the false negative it fixes.

    The rule that separates them: **a version or build suffix never begins with
    a letter, and another program's name always does.** `tmux-3.4`, `tmux3` and
    `tmux_next` are tmux; `tmuxinator` is a different program that happens to
    start with the same four characters.

    **Not `display-message -p '#{pid}'`, which the ticket suggested and which is
    exact.** It asks the server we are talking to, so it covers our own socket
    only and could not see the foreign server that is the whole case here. It
    also costs a tmux call per listing, and
    `test_list_issues_one_tmux_call_and_one_ps_call` asserts there is exactly
    one, because a call per row is a subprocess spawn per row. Exactness that
    does not cover the case, at a price a test forbids, is not the trade.
    """
    if not name.startswith(BINARY):
        return False
    suffix = name[len(BINARY) :]
    return not suffix or not suffix[0].isalpha()


def sanitize(name: str) -> str:
    """Make a project name addressable as a tmux session, ONE TO ONE.

    tmux reads '.' and ':' as window and pane separators in a target spec.
    Verified on 3.4: a session created as `hr-dotted.site` is stored as
    `hr-dotted_site`, so it exists under a name nobody looked for and
    `has-session -t =hr-dotted.site` fails while the agent is running, which
    presents as the session having vanished. Emitting neither character
    sidesteps the rewrite rather than trying to predict it.

    Injectivity is the hard requirement here, not a nicety. If two project
    names collide onto one session name, one project reads as running because
    the other is, and stopping one kills the other's agent. That is the "two
    agents in one folder" outcome #11 fixed from the discovery side, reached
    from this one.

    **A digest suffix does not deliver it, which is why this is an escape
    encoding.** An earlier version returned `a-b-<6 hex of blake2b>` for `a.b`
    and returned already safe names unchanged. A project named literally
    `a-b-28b8f5` is already safe, so it came back unchanged and collided with
    `a.b`, and the colliding name is trivially computable by anyone who can
    create a folder. Widening the digest only raises the price: 6 hex is 24
    bits, so distinct names also birthday collide by accident somewhere around
    four thousand projects. Injective by construction beats injective by hash.

    The encoding is the usual escape and escape-the-escape:

        -  ->  --      .  ->  -d      :  ->  -c

    and the whole thing gets an `e-` prefix so encoded and unencoded names
    occupy disjoint spaces. A name that already starts with `e-` is encoded for
    the same reason. Names with neither separator are returned untouched, so
    the common case still reads plainly in `tmux ls`, and readability is the
    right thing to trade away here anyway: the project already keeps the
    display name apart from the tmux name.
    """
    if not _needs_encoding(name):
        return name
    body = name.replace("-", "--").replace(".", "-d").replace(":", "-c")
    return f"{_ENCODED_PREFIX}{body}"


def _needs_encoding(name: str) -> bool:
    """A name is encoded if it holds a separator, or could be mistaken for one
    that was. The second half is what keeps the two spaces disjoint."""
    return any(sep in name for sep in _SEPARATORS) or name.startswith(_ENCODED_PREFIX)
