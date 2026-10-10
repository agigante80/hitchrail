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
    # 1114 for #439: the CLI asks `Config.https_origin_hosts` instead of
    # parsing the origins a second time.
    # 1120 for #436: the withheld line gives a loopback name different advice,
    # since the flag it used to give cannot turn Secure off for it. Two over the
    # 1118 the phase began at, since #439's saving was spent first.
    # 1127 for #464: the interrupt and failure output of update-plugins says its
    # rows are provisional and that the plugin after the last `...` was in
    # flight, which costs a constant and a longer print.
    # 1130 for #464's round 1 review: neither line is said when no row was
    # heard, and the comment saying why a refresh and the last listing cannot
    # be told apart from here.
    # 1132 for #460: the group's count is rows, and why "listed" was one short.
    # 1142 for #491: an `updated` row's detail no longer hides the approved
    # command, and a stderr note says the version check never happened.
    # 1187 for #290: every `[agents]` binary goes through the same lookup as
    # --agent-binary, now one function told which setting to name.
    "cli.py": 1187,
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
    # and the appearance radiogroup (#320, #324, #451, #323). 770 for the
    # color-scheme each explicit theme sets (#470).
    "app.css": 770,
}
