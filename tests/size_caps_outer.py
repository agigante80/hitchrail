"""The size caps for the HTTP and CLI layers' oversized modules, each argued.

`test_size_guideline.py` reads them; `size_caps_engine.py` says why they live
outside it and holds the engine layer's.
"""

OUTER_LAYER_CAPS: dict[str, int] = {
    # 460 for #123, #154 and #238: `--config`, `--session-prefix` and the
    # source tagging the settings page shows, which is one function
    # reading the flags back out of argv. Nothing here parses a value
    # twice; `settings.py` is where the file is read.
    # 461 to 490 for #152: two flags, and the uvicorn call spelling the
    # pair out as `None` rather than omitting it.
    # 490 to 527 for #207: the flag and the preflight arm that refuses
    # the wrong network, with the sentence on why the seam is resolved
    # per call. The reading itself is `gateway.py`.
    # 551 after the Phase 14 batch 3 review: the gateway verdict is its
    # own function with two exit codes, mismatch and not yet.
    # 556 after 8601915: the pinned entry's own exit code, and the words
    # for it. Bumped a commit late, which #261 notes.
    # #267 moved the certificate load here from `Config`, one read into
    # the context uvicorn serves with; `config.py` shrank by as much.
    # 616 for #258: the callback that makes OpenSSL's tty prompt
    # unreachable, and the refusal naming the key and the command that
    # decrypts it.
    # 616 to 688 for #124: `update-plugins`, a second entry point with its
    # own small parser, dispatched before the server's. A module of its own
    # was the other seam; it would have been a third web layer module for
    # forty lines of argument handling and printing, with the operation
    # itself already in `claude_ipc/plugins.py`. If a second subcommand arrives,
    # that is the moment to move both out. 693 in its review: the failure
    # code printed ahead of the words, so a script can match on it.
    # 748 for #326: `identity_banner()`, printed once before
    # `build_config()` so a refusal still names the service, and its
    # `ONE_LINE_DESCRIPTION` constant, read from the installed package's
    # metadata the same way `__init__.py` already reads `__version__`. The
    # fallback string, used only from a bare, uninstalled checkout, is
    # marked `# pragma: no cover` for that reason.
    # 804 for #141: help text and a shown default for every option that
    # lacked one, the parser factored out as `build_parser()` so both
    # `parse_args()` and the bare-invocation help path share it, two
    # worked examples in the epilog, and a `mention_update_plugins` flag
    # so that epilog's subcommand note can be left out of the concise
    # "no roots configured" refusal without a second parser. (The commit
    # that introduced this entry recorded 788, four short of the file it
    # actually landed; corrected here rather than left to re-explain the
    # gap the next time this cap is touched.)
    # 843 for Phase 22 batch 1 (#302, #196, #298): `preflight` returns a
    # `Preflight` NamedTuple carrying the absolute path it resolved
    # alongside its problems, instead of answering only `is None` and
    # discarding the value a caller needed; `main` threads that path into
    # `Config` once, before `Engine` and `create_app` exist;
    # `update_plugins_command` shares `check_agent_binary` and resolves
    # its own relative `--agent-binary` against this process's cwd before
    # spawning, so the file it checked is the file it runs.
    # 917 for #167: `--log-level` and `--verbose`, and the startup block
    # that says what this process is serving and with what, one fact a
    # line and the token only as its source. The configuration itself
    # is `logs.py`, so what grew here is the flags and the facts.
    # 949 for #341: `preflight` tells a typed path from a bare name, since
    # neither PATH message is true of a value `which` never searched for,
    # and `update_plugins_command` says why it resolves what serve refuses.
    # 956 for #283: the startup line saying an https origin in front of
    # a bind off loopback gets no `Secure` cookie, and how to get it.
    # 1005 for #242: the two flags, and the startup line naming the kind
    # of prompt Stop sends without echoing the prompt itself.
    # 1022 for #239: `--stop-policy`, resolved flag then file then default.
    # 1026 for #421: the state file's startup warnings, logged after the block.
    # 1035 for #391: the startup line naming each plain origin withheld.
    # 1037 for #394: the advice asks the cookie rule and says what #391 costs.
    # 1045 for #393: a typed path not there says where it was looked for.
    # 1061 for #391's review: the withheld line skips a host the operator
    # reaches over https, so its advice is not given on a working setup.
    # 1097 for #311 and #312: `update-plugins` prints its account at the end,
    # since a row's class is not known before the second listing, and groups
    # identical skipped rows.
    # 1107 for #311: a failed run still prints the rows it heard.
    # 1118 for Phase 24's review: so does a Ctrl-C, the likelier way a run
    # ends without its account.
    "cli.py": 1118,
    # 409 to 418 for #78: two entries in the exemption and the argument
    # beside them, which the set's own rule requires of every entry.
    # 418 to 436 for #160: the unauthenticated asset set and the argument
    # for it, which the rule beside the exemption requires of every entry.
    # 436 to 440 for #152: the cookie's `Secure` flag is `Config.tls`,
    # and the paragraph on why not behind a proxy.
    # 449 for #269: the cookie's rule and the two deployments it sits
    # between, written where the cookie is set rather than in a ticket.
    # 453 after round 2 of that batch's review: the bind clause, which
    # arrived a day after the rule, said where the rule is read.
    # 480 for #167: a line for each refusal, every request value escaped
    # through `logs.shown` and the credential only as offered or not.
    # 487 for #325: why `/favicon.ico` is a set entry, the route Starlette
    # answers HEAD on, rather than a method keyed exemption.
    "security.py": 487,
    # rather than one. A refusal handler is the shape this file is made of.
    # 513 to 517 for #120. The listing payload reports every configured
    # root as a labelled list rather than one path string, and the comment
    # says why one root is still a list.
    # 517 to 523 for #100. Six lines: the sweep now calls a second engine
    # method, and the comment says why that call is here rather than on the
    # listing route, which is the whole decision the ticket turned on.
    # 523 to 565 for #204: POST /api/sessions/{name}/answer.
    #
    # **This is past the 550 the note above names as the point to look for
    # a seam with fresh eyes.** Not split here, because doing it inside a
    # feature commit would mean moving routes and adding one in the same
    # diff, and the security review of the new route is worth more than the
    # tidiness. Tracked as its own ticket rather than left as a silent
    # overrun.
    # 574 to 615 for #180: the attention scan is started rather than
    # awaited, so an overrunning capture cannot delay a stop expiry. The
    # length is the done-callback (a task nobody awaits swallows its
    # exception) plus its teardown, and the paragraph saying which timer
    # was losing to which. Splitting this file is #205.
    # 615 to 631 for #180 round 1: the teardown comment claimed the cancel
    # stops the scan. It cancels the AWAIT; `in_thread` is run_in_executor
    # and a thread cannot be cancelled, so the worker runs to the call
    # timeout and the process waits for it at executor shutdown. Measured.
    # 631 to 669 for #147 and #148: the per server constants, read once
    # in create_app and sent on the listing, with the sentence saying why
    # not a route, and the account fallback with the sentence saying why
    # not $USER. Both are seams, so the signature grew too.
    # 669 to 687 for #151: the logs page route, whose docstring says why
    # a page route resolves a name through the API's own function. #205
    # carries the split and the seam is unchanged: this is a handler.
    # +7 for #249: the root_unavailable arm on both logs routes.
    # +137 for #154 and #238: the settings routes, the config view and
    # the editable literal beside `MAX_BODY_BYTES`. #205 is still the
    # split, and the settings routes are its first candidate.
    # 844 after round 1 of the Phase 14 review: the null refusal and the
    # one call that applies both halves of a settings body together.
    # +40 for #107: two routes and every refusal's code.
    # 894 for #263: the root_unavailable arm on three more routes.
    # 900 for #189: the `server_pid` field on the owned_elsewhere refusal.
    # 904 for #256: the listing says which hidden roots a request can
    # bring back, so the empty page stops sending somebody to a checkbox
    # that is not there.
    # 948 for #297: two plugin routes and the named event branch in the
    # stream. The run itself is `plugin_runs.py`, deliberately, so what
    # grew here is routing and the reason each answer is what it is.
    # 950 for Phase 22 batch 1 (#196, #298): the plugin update route reads
    # `config.spawn_agent_binary`, not `config.agent_binary`, so it too
    # runs the absolute path preflight resolved rather than a bare name.
    # 950 to 969 for task 157, #361: `operation_for` is built with
    # `plugin_updates.handle`, and the lifespan's `finally` kills it
    # before cancelling the sweep task, both with the comment saying why
    # a daemon thread never sees the shutdown's `KeyboardInterrupt`.
    # 983 for #167: `_error` logs every refusal it builds, with the
    # docstring saying why `extra` never enters the line.
    # 990 for #365: the lifespan's kill is wrapped in `try`, so a kill
    # that raises still cancels the sweep and the scan in its `finally`.
    # 1008 for #279: the signal route reads an optional pid, and refuses a
    # body it cannot read rather than signal as if none were sent.
    # 1009 for #370: the plugin route names all five record codes.
    # 1021 for #399 and #400: one catch for what an unparseable body
    # raises, and the signal body refuses a key it does not take.
    # 1052 for #242: the sweep starts the wrap up watch, at most one in
    # flight like the scan, and the listing says whether a prompt is set,
    # never which.
    # 1057 for #239: the policy in the listing and the settings payload.
    # 1073 for #409: the policy editable, its null refused and its change
    # a journal line.
    # 1079 for #392: teardown no longer re-raises a watch's logged error
    # over a clean shutdown or over the kill's own.
    "server.py": 1079,
}

# The web assets' caps (#68), read by `test_every_web_asset_is_under_the_size_guideline`.
# Keyed by the file name under `src/hitchrail/web/`.
WEB_CAPS: dict[str, int] = {
    # 698 at the split. One stylesheet for every page, and each further
    # stylesheet is a render blocking request on a phone before the first
    # paint, where a script module is not. Its sections (tokens, the bar,
    # the row, the dialogs, the settings page) already read as files; split
    # it along them if it passes roughly 800, or when a build step exists.
    # 760 for Phase 24's bar: the gear, the mark, the search clear control
    # and the appearance radiogroup (#320, #324, #451, #323).
    "app.css": 760,
}
