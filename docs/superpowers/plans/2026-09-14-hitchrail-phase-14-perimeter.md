# Phase 14: The perimeter, chosen rather than assumed

**Objective: the operator chooses how this is reached and how it is proved,
instead of being handed one answer.**

## Goal

A LAN deployment can be HTTPS without a second daemon, a person holding a
token can get in without a saved link, and adding a folder does not mean
editing a systemd unit. That is the roadmap's done-when, unchanged. Every
ticket here touches a security control, so each was a decision before it was
work, and every decision was taken before this plan was written.

## What this phase is actually about

Configuration the operator can reach, and the perimeter drawn where it was
always meant to be. Today every setting is a command line flag in a systemd
unit, read once at startup and invisible afterwards; the token crosses a LAN
in cleartext unless somebody installs a reverse proxy; a detached agent can
be seen and not ended; and the unit that binds a named address will serve on
whatever network later hands the machine that address, and nothing says so.

The tickets are together because they interact: TLS changes what a cookie
and an origin are, the config file is where a settings page writes, and the
README's stated limitations change with all three.

**Every ticket was checked against the tree on 2026-09-14 before it was given
a task**, body and comments. Every premise held but one: #173 named a parser
that split a session name on its first space, and that parser now splits on
the last, so the cost of widening the name pattern is smaller than the ticket
said, which is part of why the decision went the way it did. #107's comments
had reversed its body twice; the body is rewritten from them.

**Five decisions were taken by the operator on 2026-09-14**, so no task below
still has a question in it:

- #107 is built, with the honest confirmation sentence in place of a
  predicate that claimed to know ownership, on the confirmed assumption that
  a SIGTERM to an on screen agent is the class of loss the existing kill
  already carries.
- #171 is documentation: a paragraph on enrolling a device from a password
  manager. The QR and the pairing code are declined with their costs.
- #173 widens `NAME_PATTERN` to admit a space.
- #154 is the ticket's own answer: a config file the interface can only
  toggle within, and no route that takes a path, ever.
- #207 keys on the default gateway's MAC and says it guards against accident.

## What this phase is NOT about

**A route that takes a path.** #154 says why in one line: it turns a shell
equivalent API into a shell equivalent API with no directory restriction.
The config file is edited on the machine and the phone chooses among what
is in it. A test asserts no route accepts a path, so the next feature cannot
add one by accident.

**Authentication beyond one shared token.** Deferred in the roadmap. #171
adds a way to move the existing credential, not a second kind.

**Rate limiting.** Nothing in this phase introduces an endpoint that needs
it, and that is a constraint the tickets were shaped by (#171 option B,
#153 before it), not an accident.

**A settings page that edits the perimeter.** #238's read only group is the
perimeter: roots and their paths, the bind, the allowlists, the token,
`agent_binary`, `session_prefix`, `self_project`, and `stop_prompt` when
Phase 19 adds it. The editable subset is a literal, asserted member by
member.

**Rescanning roots on a signal or a timer.** Restart is the honest boundary;
the config file makes restarting cheap.

## The exit criteria, and which task answers each

| Criterion | Tasks |
|---|---|
| 1. A LAN deployment can be HTTPS without a second daemon | 82 |
| 2. A person holding a token can get in without a saved link | 85, and it is documentation: the form exists since 6eda342 |
| 3. Adding a folder does not mean editing a systemd unit | 79, with 80 and 81 on the same file |

Tasks 83, 84 and 86 serve the objective's "how it is proved" clause and the
delivers line: a name pattern that no longer invites the alias workaround, a
unit that notices the wrong network, and the one destructive path that was
visible and unreachable.

## Expected work

Eight tasks in four batches, one ticket each. Work the batches in order and
the tickets within a batch in the order given; the ordering is dependency,
not taste. **Round 1 of the review loop runs at the end of every batch**, with
the security lens on any batch that touches `security.py`, `headers.py`,
`cli.py`'s bind, a route table, or a spawn path, which here is all four.

### Batch 1: configuration the operator can reach, tasks 79 to 81

One file, `~/.config/hitchrail/config.toml`, read once at startup, with the
flags still winning. The refusals are the same objects the flags use, not a
second validator: premortem 2 below is the failure this batch is most likely
to have, and the rule is that the file feeds `Config` and nothing validates
before `Config` does.

- [x] **Task 79, #154.** Roots from the config file, `--root` still winning
      with no deprecation. Every refusal that applies to `--root` applies
      identically to the file, because both build the same `Root` objects and
      `Config` refuses them the same way: nested roots, a path that is not a
      directory, a duplicate label, an invalid label. A malformed file refuses
      at startup naming the file and the line and never starts with a partial
      set. The interface toggles `enabled` on a root already in the file, the
      choice persists to the file, a disabled root's projects are absent from
      the listing and its sessions are not killed by being hidden. **A test
      asserts no route accepts a path**, read from the real route table and
      the request bodies the routes parse, so the next route cannot.

- [x] **Task 80, #123.** `--session-prefix`, and `session_prefix` in the
      config file, two lines each once task 79 exists. The refusals
      `_check_session_prefix` already makes become reachable from the command
      line and are tested there. Two instances with different prefixes cannot
      see or kill each other's work, proved in the live tmux tier with two
      prefixes on one private socket.

- [x] **Task 81, #238.** The settings page. `GET /api/config` returns the
      effective configuration with the token omitted and every value tagged
      with its source (flag, file, default); `PATCH /api/config` accepts the
      editable subset only, a literal asserted member by member, refusing any
      other key with a stable code. Read only fields render as text, never as
      disabled inputs. The browser takes `stop_timeout` from the server and
      retires its hardcoded thirty seconds; #147 already put per server
      constants on the listing payload, and `stop_timeout` rides there too, on
      the same argument, so the wait is right before the settings page has
      ever been opened. Persistence is task 79's file.

### Batch 2: the scheme, task 82

- [x] **Task 82, #152.** `--tls-cert` and `--tls-key`, both or neither,
      refusing at startup before the bind, an unreadable or malformed
      certificate refused at startup rather than at the first request. **The
      part that is not the two flags:** derived origins become `https` when
      TLS is on, so Start is not refused by our own origin check; the banner
      prints `https://` links; the cookie carries `Secure` when TLS is on and
      not when it is off, or it is set and never sent back. **Proved on a
      live socket with a real certificate**, because only a socket carries a
      scheme: the hermetic tier cannot see premortem 1. `mkcert` documented
      in `docs/guides/phone-access.md` as route 2, the CA trusted on the phone
      included, with Tailscale kept first.

### Batch 3: the edges of the perimeter, tasks 83 to 85

- [x] **Task 83, #173.** `NAME_PATTERN` admits a space. `sanitize` re-proven
      injective over the wider input, by property test rather than by
      enumeration, since that is how the first version of the pattern was
      caught failing open. A live tmux test of what tmux actually stores for
      a session name with a space, because a fake encodes our own belief. The
      unsupported message for the characters still refused says to rename,
      not something a symlink answers.

- [ ] **Task 84, #207.** An `ExecStartPre` in the unit template that reads
      the default gateway's MAC and exits 2 when it is not the expected one,
      so `RestartPreventExitStatus=2` makes the unit dead until a human acts.
      The code says it guards against joining the wrong network by accident
      and not against an attacker on the LAN, and "cannot tell" refuses. The
      expected value is a line the operator fills in; unset means the check
      is off and the header says so.

- [ ] **Task 85, #171.** The paragraph in `docs/guides/phone-access.md`: put
      the token in a password manager and it fills the existing form. Closes
      as documentation, with the declined options and their costs left on the
      ticket for the next time it is asked.

### Batch 4: the destructive path, task 86

- [ ] **Task 86, #107.** `POST /api/sessions/{name}/signal`. Acquire the
      pidfd, then re-derive and refuse unless the row is still `detached` for
      that project and that pid with no seen owner; SIGTERM, SIGKILL only on a
      second explicit request; the protected project and this server's own
      ancestry refused before any handle is opened; a qualified identifier
      whose label names no configured root refused before any pid is looked
      up. New codes with statuses in `docs/api.md`, the full refusal set the
      gate listed, the seam as a callable alias with its fake in
      `tests/conftest.py`. The row gains one control, styled danger, confirmed
      with the sentence: "Hitchrail can see no session that owns this agent.
      If it is open on a screen somewhere, this will end it there too." **One
      refusal on a real process in the live tier**: a child the test started
      and ended between the listing and the call yields `gone` with nothing
      signalled, which is premortem 4's rule.

## Done looks like

- [ ] Every task above is ticked, or is marked MOVED OUT with the issue that
      carries it.
- [ ] The premortem's four rules each have the assertion named below, in the
      suite, and two of them run on a live socket or a real process.
- [ ] `docs/api.md` documents every route, field and code this phase added,
      held to the server both ways.
- [ ] `README.md` and `docs/guides/phone-access.md` state the limitations as
      they are after this phase: HTTPS from the server itself as route 2, the
      config file as where roots live, the signal route as what a detached
      row can do.
- [ ] Design section 5.2b no longer says pid signalling does not exist and
      states what constrains it; section 5's control count and the two
      documents that count it agree (#174 is Phase 17 and must not be made
      worse here).
- [ ] The roadmap's Phase 14 block says `state: done`, the milestone is closed,
      `scripts/check-phases.sh` is clean, and this plan has no unticked box
      without a marker.

## Fails if

Written as a premortem on 2026-09-14, by asking the operator: it is the end of
this phase and it failed badly; what happened? Four answers, confirmed as the
list, each with the evidence that makes it believable and the rule that stops
it.

1. **TLS shipped with origins still derived as `http`**, so every mutating
   request was refused with a 403 from our own origin check, and the hermetic
   tier could not see it because only a socket carries a scheme. The origin
   check is the control that found `--allow-origin https://box.lan:443`
   accepted and never matched in Phase 2. Rule: task 82 is proved on a live
   socket with a real certificate, a Start through it included, and the
   hermetic tier's origin derivation test is parametrised over both schemes.

2. **The config file grew a second validator** and refused differently from
   `--root`: a nested root the flag refuses accepted from the file, or a
   label the file refuses accepted from the flag. Two validators is how the
   allowlist held two spellings of one host in Phase 2. Rule: the file
   produces `Root` objects and `Config` refuses them; a test feeds the same
   bad input through both doors and asserts the same refusal, for every
   refusal `--root` has.

3. **The settings PATCH route's editable subset gained a perimeter key** in
   a later edit, and a request could then change what a spawned process is.
   Rule: the subset is a literal, asserted member by member like
   `ANSWER_KEYS`, and a second test asserts every perimeter field named in
   #238 is NOT in it, so adding one fails in the suite and not in review.

4. **The pidfd route was proved on fakes** and never against a process that
   exited or was reused between the listing and the call, which is the whole
   of what the pidfd buys. Rule: task 86 carries a live tier test on a real
   child process for the `gone` refusal, and the recorder test asserts the
   handle is opened before the verification, both named in the task.

## Out of scope

- A route that takes a path: refused by #154 and asserted against.
- Authentication beyond one token: deferred in the roadmap; #171 moves the
  existing credential.
- Rate limiting: no endpoint here needs it, by design.
- Editing the perimeter from the settings page: #238's read only group.
- Rescanning roots without a restart.
- Section 5's control count across the three documents: #174, Phase 17.
