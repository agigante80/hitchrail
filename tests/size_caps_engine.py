"""The size caps for the engine layer's oversized modules, each argued.

`test_size_guideline.py` reads them. They are data rather than part of that
test because the arguments are most of their length: kept inline, they put the
guard's own file past the guideline it enforces (#30). The HTTP and CLI layers'
caps are `size_caps_outer.py`, split on the boundary `lint-imports` enforces.
"""

ENGINE_LAYER_CAPS: dict[str, int] = {
    # #368 split `claude_ipc.py` (1351 lines, its cap raised three times in
    # Phase 22, each honestly, which is how a file grows past its seam) into
    # a package. `screen`, `keys` and `launch` came in under the guideline.
    #
    # `plugins.py` did not, and does NOT want splitting further: the runner
    # and the update share the timeout and reap constants and the vocabulary
    # `tests/test_plugins.py` keeps out of every other module, so a second
    # file would put that vocabulary in two places for no reader's benefit.
    # Most of its length is the docstrings saying which race each of
    # `RunningChild`'s two checks closes. Measured 533 at the split, and
    # 550 after #353 gave `_shown` a tail and a backslash rule, each with
    # the reason a reviewer would otherwise undo. 570 after #363 and #384:
    # why the group is killed after a reap, with the kernel rule that
    # makes it safe, and why `kill()` clears the pid it takes. 575 for
    # #370: why scope is decided before abandonment. 578 for #401: an
    # abandoned row is seen too, so its repeat is not a second one. 639 for
    # #311: the second listing that splits `updated` from `current`, and why
    # every way it can fail leaves `updated` as it was.
    # 651 for #491: every failed second listing marks each `updated` row
    # unconfirmed, through one helper, and the constant the CLI and page read.
    "claude_ipc/plugins.py": 651,
    # screen.py crossed the guideline for #475 (394 to 441): the rule that finds
    # the live input box between its two rules, the captured reason the row
    # count alone could not be it, and the watch's counts of what it read. The
    # file is one subject, the vendor's screen, and its length is those captures.
    # 456 for the review of that change: `_input_row`, the one place that says
    # which row is the live input, shared by `queued_message` and the watch.
    "claude_ipc/screen.py": 456,
    # +_await_gone, +list(...), +#47 split, +#64, +#66, and +#89's one
    # `except` arm: the adapter can now decline to type, and the marker has
    # to come back the same way a vanished tmux takes it back.
    # 785 to 792 for #120. The name guard splits a qualified identifier
    # before validating its folder half, and the comment says why: `~` is
    # exactly the character the folder allowlist forbids, so validating the
    # whole identifier read the separator as the thing it protects against
    # and rejected every real name. That was a live defect, so its reason
    # stays in the code.
    # 792 to 826 for #102. The addition is a cleanup path plus the reason
    # it asks rather than guesses, which is the distinction the ticket drew
    # and the one a future reader would otherwise re-litigate: assuming the
    # session exists kills something that may not, assuming it does not
    # leaves the defect.
    # 826 to 833 for #113. The default `Tmux` is now built with the variable
    # names a spawned agent must not inherit, and the comment says why the
    # name is passed from here rather than known by the adapter: which
    # variable holds the token is this application's vocabulary, and tmux
    # knows nothing about it.
    # 833 to 855 for #85. Two refusals opened "has no tmux session", which
    # is the sentence #85 removed from the interface for being a claim this
    # tool cannot make: ownership is read from one server on one socket.
    # They are one builder now rather than two f-strings, because the two
    # messages had already gone out of step with the row's copy by being
    # edited separately, which is the shape of the defect itself. The
    # growth is that reason plus the branch that names the owning session
    # when there is one, which turns a dead end into an instruction.
    # 855 to 934 for #100, AFTER taking the seam rather than instead of
    # taking it. The deciding moved out to `attention.py`: which rows are
    # worth a subprocess, the cap, the wall clock budget, the TTL and the
    # argument for all four. What could not follow it is what this class
    # is: the remembered observation, the lock that guards it, and the one
    # method that actually touches a pane.
    #
    # The growth that remains is a second source for an existing overlay
    # and the reason it is combined in one place, which is that `get`,
    # `list` and the event published after an action must agree. A version
    # that flagged rows inside `list` alone would blink the flag off every
    # time an event arrived, since the interface replaces a row wholesale
    # from an event payload. That is exactly the kind of reason that
    # belongs at the code rather than in a ticket.
    # 934 to 953: the waiting set moved out of the row loop, and the
    # docstring saying why is the growth. `_stopping_guard`'s own note
    # forbids `_derive` taking that lock per row, and #100's second source
    # iterates a dict rather than testing membership, so the union is built
    # once per listing and handed down. A reader who does not know that
    # will inline it back, which is why the reason is at the parameter
    # rather than on the ticket. See #178 for the pre existing half of the
    # same note that the code still contradicts.
    # 954 to 1037 in review of #100, and all three additions are things
    # the first cut left out rather than growth. `_forget_attention`, so a
    # brand new agent does not inherit the last one's prompt, with the
    # reason there are two call sites and not four. The announce, because
    # recording a change and telling nobody is half a fix and `expire_stops`
    # already argues that in its own docstring. And the subscriber gate,
    # because an idle tick used to cost nothing and this had made it a `ps`
    # and a `tmux` call every second for the life of a user unit.
    # 1037 to 1078 for #204: `Engine.answer`, one keypress from a person
    # to a prompt they read. Mostly the argument for why this is not the
    # deferred terminal, kept at the method rather than only in the ticket,
    # because the ticket is not what the next editor is looking at.
    # 1086 to 1122: the stale refusal on `answer`, found by the security
    # audit of #204 before release. A stale session is a terminal holding a
    # shell, and relaying a person's chosen answer to a shell is the #91
    # hazard bought for something. The length is the argument for why the
    # ADAPTER cannot make that call, which is the thing a later reader would
    # otherwise "simplify" by moving the check next to the pane read.
    # 1122 to 1154 for #182: the attention epoch, and why a sweep discards
    # a whole batch of evidence gathered before a clear rather than tracking
    # which project was cleared.
    # 1154 to 1170 for #178: the membership test before the stop lock, and
    # why a note contradicted by the method twenty lines below it is a
    # defect in the record rather than a style point.
    # 1170 to 1185. #182 round 1 stopped a discarded sweep AGEING what it
    # declined to renew; round 2 found that hoisting the expiry above the
    # renewal loop popped a claim the same sweep had just written, so the
    # ordering is now spelled out where it can be read.
    # 1185 to 1198 for #218. The prune moved above `changed`, and the
    # comment says which side of the renewal it is on and why the other
    # side was round 1 of #182's regression: the two look alike in a diff
    # and are opposite in effect, so the next review needs the reason.
    # 1198 to 1224 for #243: the ceiling seam and its per pid cache, and
    # the comment carrying the measured cost that justifies the cache.
    # 1224 to 1239 for #151: `locate`, the one ladder the logs API and
    # the logs page both climb, lifted out of `logs` with its reasons.
    # 1239 to 1248 for round 1 of the Phase 13 review: the ceiling prune
    # from a snapshot, with the race it replaces written where it was.
    # 1248 to 1265 for #154 and #238: the preferences held on the engine,
    # and the sentence saying why name resolution keeps every root.
    # 1279 after the security audit of #154: an operator disabled root
    # refuses Start, with the sentence on why hiding does not.
    # 1279 to 1420 for #107: `signal_detached`, the one destructive
    # path scoped by a check, with the order that makes the check sound
    # written where it is enforced. Phase 18 carries the split.
    # And to 1441 after round 1 of its review: the label check moved here
    # from `_require_addressable`, and two guards that read the table
    # refuse when it could not be read.
    # 1468 after Phase 20 batch 1's review: the process's working
    # directory is read after the handle, the one fact argv does not carry.
    # 1479 for #189: the refusals read `held_elsewhere`, a session name
    # or a server pid, rather than the session name alone.
    # 1516 for #272: EPERM at the handle told apart from EPERM at the
    # send, with the man page's error list as the reason, and the
    # paragraph saying which of this route's ownership checks is the
    # property and which is advisory. Phase 18 carries the split.
    # 1554 for #167: a start, a stop and its ending, and the stuck scan's
    # changes, as log lines, each with the comment saying why pane output
    # is never one of them. 1569 for #167's review: the timeout line
    # worded from the row read after the timer, and why it must be.
    # 1584 for #279: the signal is bound to the pid the person confirmed,
    # with the docstring saying why a second agent for the folder is ours
    # and still not the one asked about.
    # 1734 for #242: the wrap up phase, claimed under the lock so the
    # sweep never types into the middle of the prompt, its ceiling, and
    # the sentence on why a second Stop skips to the exit.
    # 1771 for #239: `_end_anyway`, the opt in kill at expiry, and the
    # docstring saying why it is a kill and never an answer.
    # 1780 for #242's review: the look at the pane when the exit after a
    # wrap up is refused, which ends the stop as expiry does.
    # 1786 for #239's review: one look then act per name, so a later
    # row's look is never stale by the time of its kill.
    # 1566 for #274: the pidfd path, the one destructive path scoped by a
    # check rather than by the prefix, moved to `signals.py` with its seam
    # and its refusals, which is the split the #107 and #272 notes above
    # deferred. What remains is the lifecycle and the stop sequence, whose
    # notes are the footguns and are why the file is still past 400.
    # `signals.py` itself came in under the guideline and needs no entry.
    # 1585 for #406: the marker's `typing` flag, which the sweep and `stop()`
    # both set while an exit sequence goes out, and the clear in a `finally`
    # on each, so a Stop never interleaves a second sequence with the first.
    # 1622 for #407: `_give_back`, which hands a refused Exit now back to
    # the wrap up it interrupted, the arm that drops a marker on an error
    # nobody planned for, and the StopMarker note naming the three removals
    # by name and why each is safe.
    # 1628 for #410: `_flag_waiting`, so the two looks that add the waiting
    # overlay outside the sweep honour the attention epoch as it does.
    # 1635 for #419: the marker records the stop policy at `stop()`, and
    # the note saying why expiry reads it there and not the live setting.
    # 1649 for #390: the timeout line's third case, a `stale` row that is a
    # stop that worked, with why, and the unwatched exit's duration.
    # 1659 for the #387 regression: the marker's `withdrawn` flag, and the
    # StopMarker note saying why its owner writes the object and not the
    # table while a failed Kill holds it out.
    # 1667 for #408, #411 and #428: the listing carries whether a sequence
    # is being typed, the stop's age and its recorded policy, so a browser
    # that did not tap Stop can reopen the wait truthfully.
    # 1707 for #429: the second look end_anyway takes a settle after the
    # first, and the note on why one look is not evidence of a question.
    # 1712 for #453: the sweep leaves a marker whose exit is still being typed,
    # since the exit menu's look outlives the agent, and the note saying so.
    # 1712 to 1300 for #473: the sweep (`scan_for_stuck`, `advance_wrap_ups`,
    # `expire_stops` and what they call) moved to `sweep.py`, with the notes
    # above that argue its races; they stay where they were written, as the
    # history of this cap, and their text now lives in that file.
    # 1300 to 1255 for Phase 26: `StopMarker` and its note moved to
    # `stopmarker.py` unchanged, because #427 and #432 add to the rules for
    # who holds a marker and the file was at its cap. Up to 1275 for #432:
    # the table of markers a Kill holds out, and why a Stop must see them;
    # 1279 for #430, the per name clear epoch.
    # 1283 for #472: the overlay's slot and its two `cancel`s in Kill, and the
    # import. Restart's logic, its two entry points and its argument are in
    # `restart.py`, which is a mixin precisely so this file gained no methods.
    # 1291 for #290: the engine holds its `Agents` and asks the project's
    # agent to start, stop, answer and link, where it called `claude_ipc`;
    # the derive call wrapped once it passed them.
    "engine.py": 1291,
    # #473. The sweep, moved whole from `engine.py`. 465 is the move: most of
    # it is the notes on the races between a scan, a stop and a start, which
    # are the reason the code is shaped as it is. It does not want splitting
    # further, since the three entry points share the look at a pane.
    # 468 after #424: the signatures take EngineSeam, which wrapped three lines.
    # 479 for #430: why `_flag_waiting` compares a name's clear, not the counter.
    # 488 for #444: why the settle is per candidate, and the second look believed.
    # 489 for #475: the ceiling line carries what the watch read.
    # 493 for #472: an expired stop cancels a pending restart in the same
    # critical section as the removal, and the comment says why it must.
    # 494 for #290: the exception is the neutral module's, one import more.
    "sweep.py": 494,
    # signals.py: 397 when #274 moved the pidfd path here. 414 for #426: `_close`,
    # and the note on why a close that fails must not replace the outcome.
    # 426 for #425: the survivor after the wait, journalled and reported as ask.
    # 438 for the restart kill epoch: `_ends_a_restart`, called before each of the two
    # signals, and the note on why the count is what a Restart still typing reads.
    "signals.py": 438,
    # 399 to 415 for #290: the project's agent travels to each direction of
    # derivation, and the trust map is keyed by agent. The seam the file
    # already has is `Machine` and `look`, one read of the machine, against
    # the questions asked of it; splitting there is #501.
    # 438 for #290: both directions ask every configured agent, not only the
    # root's, so a changed `agent` key cannot hide one still running.
    # 460 for #294: the pane direction prefers the agent whose whole argv tail
    # a process ends with, since agy's argv carries Claude Code's marker.
    "derive.py": 460,
    # tmux.py is the module that encodes what tmux actually does
    # rather than what its manual implies, and every entry is a footgun
    # that cost real debugging: prefix matching targets, the colon
    # `list-panes` and `set-option` both need, a rewritten dot, a pane that
    # vanishes before it can be read, and now a server that keeps the argv
    # of whatever started it (#84). The length is those explanations.
    # Deleting them to reclaim lines would delete the reason the
    # workarounds look wrong, which is the one thing a reader needs.
    #
    # Raised from 425 for #84's `is_tmux_argv`, again for #89's `-e`
    # capture option, and again for #67's call bound and the note about
    # what a timeout leaves behind. All added behaviour rather than growth,
    # which the note above permits with a reason.
    #
    # The number is not repeated in this comment any more. It was written
    # as "466." while the cap said 485, which is the same decay the
    # security.py note below warns about and this file's own test forbids
    # in the documents.
    # **There IS a seam here now**, and it is #93 rather than a bump next
    # time: `sanitize`, `_needs_encoding` and their two constants are the
    # name vocabulary, pure and subprocess free, sitting beside an adapter
    # that spawns things. That is the same split #18 already made when it
    # took the host vocabulary out of config.py into hostnames.py.
    # **#93 landed and this entry loses its argument with it.** Every note
    # here defended a length caused by a module doing two jobs: the name
    # vocabulary and the adapter that spawns processes. The vocabulary is
    # `tmuxnames.py` now, and 522 became 438 without a line of explanation
    # being deleted, which is the outcome the old notes kept insisting was
    # not available. Recorded rather than silently reset, because the
    # previous entries argued in good faith from a premise that a split
    # removed.
    # 439 to 475 for #113, and the growth is the measurement rather than the
    # code. Two lines prefix `env -u VAR` to the spawn; the rest records what
    # was measured on tmux 3.4 against a pre existing server, because the two
    # options that read as correct in the manual are the ones that silently
    # do nothing: a pane inherits from the SERVER, so `env=` on the client
    # call changes nothing, and `new-session -e VAR=` leaves the variable set
    # and empty rather than absent. Deleting that table would leave a
    # workaround that looks like a longer way to write the option somebody
    # will "simplify" it back to. Same argument as every entry above it.
    # 475 to 523 for #85, and the growth is one dataclass plus the reason
    # this adapter now returns what it used to throw away. `list-panes -a`
    # has always returned every pane on the server and this module dropped
    # the ones without our prefix, so an agent alive inside another tool's
    # session was owned by a pane we had seen and discarded, and derivation
    # called it an orphan. Returning both halves costs no second call.
    #
    # Most of the added lines are two explanations a reader would otherwise
    # undo: why `rpartition` rather than `partition`, which is the parser
    # accepting a foreign session name with a space in it, and why the
    # foreign half is keyed by pid while ours is keyed by name. Behaviour
    # plus its reason, which the note above permits.
    # 524 to 539 in review of #85, and every added line is the reason for
    # one condition. `rpartition` fixed a foreign name with a space being
    # dropped and, for one input, made the outcome worse: a foreign session
    # called `hr-my project` classified as OURS, hid the agent under its
    # pane, and derived `stopped`, which offers Start. The comment says why
    # a space disqualifies a name from being ours, because the next reader
    # will see a redundant looking check beside a `startswith` and remove
    # it.
    #
    # It briefly said 554, because a `str.replace` put that same comment
    # into `kill_session`'s docstring as well, onto the illustrative guard
    # whose next paragraph explains that the condition can never be true.
    # The cap was raised for sixteen lines nobody meant to add, which is
    # how a size guideline stops meaning anything.
    # 539 to 543 for #176: four lines saying why the foreign half assigns
    # rather than `setdefault`s. The word it replaced announced a collision
    # rule that map cannot reach, and a test was written certifying that
    # hazard, so the note is what stops the word coming back.
    # 543 to 553 for #175: the empty-name guard and the note saying it
    # defends a format change rather than a defect, measured against tmux
    # 3.4, so nobody goes looking for a bug that is not there.
    # 553 to 556 for #173: the pane map asks `could_be_ours` rather than
    # "has a space", and the comment says why the question changed.
    # 595 for #175 and #189: records end at a terminator no tmux stores
    # in a name, with the note on which tmux versions store a newline,
    # and the server's pid rides in the same call so `derive` can tell
    # our own server from another one.
    # 619 after round 1 of that review: the invariant restated as it
    # holds on 3.7a, the unnamed session kept rather than dropped, and
    # the server's pid asked for on its own when there is no pane to
    # list it from (`exit-empty off`).
    # 619 to 640 for task 143, #299: `_default_runner` moves off
    # `subprocess.run`, for the same reason as `claude_ipc/plugins.py`'s
    # `plugin_runner` above: it never exposes the `Popen` it creates, so
    # it cannot kill a hung tmux invocation's own child processes as a
    # group. Duplicated rather than shared with `claude_ipc/plugins.py`, because
    # sharing it would import the tmux adapter into the vendor quarantine
    # or the vendor quarantine into the tmux adapter, either a worse
    # coupling than fifteen duplicated lines with a comment in each.
    # 640 to 678 for #299's round 1 review, the same three fixes as
    # `claude_ipc/plugins.py`'s and duplicated for the identical reason: catch
    # `BaseException` so Ctrl-C mid call still kills the group (M2), give
    # `os.killpg` `proc.pid` directly so a dropped `start_new_session`
    # raises instead of killing this process's own group (M3), and bound
    # the reap after the kill by closing the pipes rather than a second
    # unbounded `communicate()` (H1). 680 for #363's pointer to why the
    # group is killed even after the child was reaped.
    # 693 for #242: `send_text` through `send-keys -l`, with why the
    # flag is what keeps a prompt from being read as key names.
    "tmux.py": 693,
    # 413, and thirteen lines over the guideline is not a second job. #18
    # already took the host vocabulary out of this file, and what is left
    # is one dataclass and its startup refusals, which is one thing. The
    # growth is #48's `_check_self_project`, whose comment is longer than
    # its code on purpose: a filesystem read in a config constructor looks
    # wrong, and the reason it is not belongs next to it. Split only if a
    # NEW responsibility arrives, never to reclaim these lines.
    #
    # Raised from 418 for #108's `remote_reach`, which adds behaviour: the
    # token refusal now follows what can reach this server rather than what
    # it binds. Most of the addition is the argument for why a proxied
    # loopback bind is not local, which is the thing that was wrong.
    # 468 to 488 for #120. `roots` replaces `root`, and the growth is the
    # qualified `--self-project` check: it now splits an identifier, finds
    # the root that label names, and refuses if there is none. Three
    # refusals where there was one, because with several roots there are
    # three ways to name a folder that is not there.
    # 488 to 507 for #113. `TOKEN_ENV` moved here from `cli`, which was its
    # only reader until the engine gained a second one: the engine has to
    # name the variable to strip it out of what it spawns, and the import
    # contract forbids the engine layer importing `cli`. The move is the
    # whole growth, comment included, and the comment is what stops it
    # drifting back: two literals of one variable name in two layers is how a
    # scrub stops scrubbing without anything going red.
    # 518 to 520 for #154 and #238: `state_path` and `sources`, each with
    # the sentence saying why it is not a control.
    # 523: `config_path`, the file that was read, for the settings page.
    # 523 to 575 for #152: the TLS pair, loaded once at construction so
    # a certificate that cannot be read refuses BEFORE the bind, with
    # the paragraph on why that is exit 2 and not uvicorn's retried 1.
    # 575 to 594 for #207: the expected gateway MAC, normalised once.
    # 608 for #265: the ceiling, and the sentence on why a browser fires
    # a timeout above 2^31-1 ms at once.
    # And to 627 for #268: TLS on beside a plain http origin refuses.
    # 674 for #269: `cookie_is_secure`, the rule the operator decided
    # (our own TLS, or a proxy deployment whose every non loopback origin
    # is https) with the two failures it sits between written down.
    # 686 after round 1 of that batch's review: the bind is the third
    # thing the rule asks about, and the paragraph says why the origins
    # alone were not enough.
    # 690 after round 2: that paragraph claimed nothing off the machine
    # can reach a loopback bind, which `remote_reach` twenty lines above
    # calls false for the same question.
    # 735 for Phase 22 batch 1 (#302, #196, #298): `check_agent_binary`
    # moved to module level so `cli.update_plugins_command` can share it
    # instead of running its own copy that forgot to write the stripped
    # value back, and `resolved_agent_binary` plus `spawn_agent_binary`
    # arrived to carry what `cli.preflight` resolved through to every
    # spawn site without a second, less careful resolution. New
    # behaviour and a new refusal, not the growth of one job into two.
    # 738 for #167: `token` leaves the dataclass repr, which put it in any
    # log line or traceback that printed a `Config`.
    # 789 for #242: `stop_prompt` and its ceiling, with the refusals for
    # a newline or a control character and the 10s floor.
    # 803 for #239: `stop_policy` and its literal refusal.
    # 831 for #391: `plain_origins_withheld`, the one derived origin a
    # `Secure` cookie cannot return on, and the decision's argument.
    # 845 for #395: the IPv4 mapped bind refused by name, not by uvicorn.
    # 849 for #394: the origins' half of the cookie rule, for the CLI's advice.
    # 839 for #439: the five copies of the origin parse became `split_origin`
    # and `origin_parts` in hostnames.py, which took the cookie rule's reader
    # with them.
    # 846 for #437: the rule over a hosts argument, so assignment order cannot
    # matter. 848 for #436: the secure context question in the withheld rule.
    # 856 for #290: the `agents` field, checked at construction like roots.
    "config.py": 856,
    # 409, nine lines over, down from 542. #115 deleted the `?token=`
    # carrier: 135 lines once the two blocks inside `TokenMiddleware`
    # that only served it are counted.
    #
    # Nine over is not a second job, the same judgement config.py's entry
    # makes at thirteen. What is gone is the long exception this entry used
    # to carry, arguing that a boundary should not be split.
    #
    # **#80 could not have reached even this**, which is why it was closed
    # rather than done: the unit it proposed moving was 101 lines against a
    # 542 line file, landing near 435 with the exception intact. The query
    # grant was never what made this file long.
    #
    # If it grows again the seam is `TokenMiddleware`, still the largest
    # thing here. Look there before raising this number.
    # 359 to 440 for #120, and this one is on notice. The plural layer,
    # "which root does this identifier name", sits on top of the per root
    # functions rather than inside them, which is what keeps `resolve_child`
    # unchanged: proving a path is a direct child of ONE root is the
    # property the security argument rests on and it is not improved by
    # teaching it about labels. The seam is therefore real and the file is
    # two layers deep rather than two jobs wide, so it is tracked here
    # instead of split mid migration. #127 carries the split.
    "discovery.py": 440,
}
