# Reaching Hitchrail from your phone

**Running Hitchrail as a service converts a session shaped exposure into a
standing one.** Until now the window in which this API was reachable was the
window in which you were sitting at the machine watching it. A unit removes
that coupling permanently: it is reachable while you sleep, while the laptop is
in a bag on a train, and on whatever network it joined when it woke up. Nothing
below makes that untrue. What the routes differ on is who else is in the window
with you.

Hitchrail already gets the default right. `--host` defaults to `127.0.0.1`, so
**the safe thing is what happens when you pass nothing**, and every route on
this page is a decision to move away from it. Read them in order: they are
ordered best first, and the ordering is the argument rather than a menu.

A note that applies to all three. A token is generated and required as soon as
anything outside this machine can reach Hitchrail, and the server refuses to
start without one. That token is the only thing between a stranger and a shell
running as you.

## 1. An overlay network

**The recommended route, and the only one that stays correct when the machine
changes networks.**

Hitchrail stays on its loopback default and never opens an inbound port.
Something on an overlay network fronts it, reaching it over an encrypted link
with its own identity check. Tailscale Serve is the version of this most people
have to hand:

```sh
hitchrail --root ~/projects \
  --allow-host  laptop.tailnet-name.ts.net \
  --allow-origin https://laptop.tailnet-name.ts.net

tailscale serve --bg 8787
```

**Both flags, and neither is optional here.** They answer different questions
and Hitchrail refuses on each separately:

- `--allow-host` is what the server will answer to. The proxy forwards a
  request whose `Host` is your tailnet name, and an unlisted host is refused
  before anything else runs.
- `--allow-origin` is the exact origin a browser may claim, written
  `scheme://host[:port]`. The scheme and port here are the proxy's, `https` and
  443, and they cannot be derived from our own loopback bind. This is what its
  own help text means by "needed behind a TLS terminating proxy".

What this buys, and it is worth being precise because it is the reason for the
ordering. No inbound port is open, so there is nothing to find by scanning. The
link is encrypted end to end, so the cookie does not cross anything in clear.
Access is gated by the tailnet's own identity check before Hitchrail's token is
reached at all. And critically: **none of that changes when the laptop joins a
different network**, because none of it depended on which network it was on.

## 2. A named LAN address

Bind to one specific address on your local network:

```sh
hitchrail --root ~/projects --host 192.168.1.10
```

This works, it needs nothing installed, and it is what the README shows. State
the exposure plainly before choosing it:

- Hitchrail is now listening on that interface **for anyone who can reach it**.
  On a home network that is every device on the wifi, including the ones you do
  not administer. On a cafe or hotel network it is everybody.
- **The token is the only control.** There is no second factor and no source
  address restriction. Someone who obtains the token has a shell as you.
- **It is HTTP.** The grant fragment stays in the browser and reaches no server
  log, which is real and is not the whole story: the cookie it becomes crosses
  your network in cleartext on every subsequent request. Anyone positioned to
  read that traffic can replay it. Put a TLS terminating proxy in front of it
  if that matters, and if you are doing that, route 1 is less work.
- **It is a decision with an expiry date you will not be told about.** This
  choice is correct while you are on a network you trust. Nothing warns you
  when the machine joins one you do not, and a laptop's whole job is joining
  other networks.

That last point is why this is second rather than first. It is not less secure
in the moment. It is a decision that silently stops being the one you made.

## 3. Never the wildcard

Do not bind the wildcard address `0.0.0.0`. It is not a shortcut for route 2
and Hitchrail treats it differently on purpose: a wildcard is never offered as
a link in the startup banner, because it is not an address anybody can open.

The reasoning, rather than only the prohibition:

- `0.0.0.0` does not mean "my LAN address". It means **every interface this
  machine has, including the ones you forgot about**: a second NIC, a VPN
  tunnel, a container bridge, a tethered phone. You are not choosing an
  audience, you are declining to choose one.
- It is the finding, not the fix. OWASP's Docker Security Cheat Sheet treats
  binding every interface as the vulnerability and a loopback bind as the
  remediation, and NVD carries the CVE class for getting it wrong
  (CVE-2023-37895).
- The tools that got this right say the same thing. Ollama binds loopback by
  default and explains why, its API ships without authentication, and its
  hardening guidance is that to reach one interface you **name that address**,
  because the wildcard is wrong on any host with more than one NIC.

If you want one interface, name it. That is route 2, and naming it is the whole
difference.

## Which one

| You want | Route |
|---|---|
| It to keep working when the laptop moves | 1, overlay |
| No inbound port open anywhere | 1, overlay |
| Nothing installed, one trusted network, you accept the exposure above | 2, named address |
| To reach it from one interface | 2, name that interface |
| To reach it from every interface | Nothing on this page. Reconsider. |

## Running it unattended

`packaging/hitchrail.service` is a systemd user unit template. It is a template
to copy and edit rather than a file to install, and it carries its own
instructions in comments at the top.

Two things about it belong here rather than in the file:

**The token has to come from the environment.** A generated token changes on
every start, so a service that restarts invalidates the link saved on your
phone. Put `HITCHRAIL_TOKEN` in the unit's `EnvironmentFile` and `chmod 600`
it, because anyone who can read that file can run code as you.

**The banner withholds the token when it is talking to the journal.** Under a
unit, standard output is journald: persistent, and readable by root and by
members of the `systemd-journal` group. A token printed to a terminal scrolls
past while you watch it; the same token printed to the journal is kept. So when
Hitchrail sees it is writing to the journal it prints the address without the
fragment, and tells you to append the value you already put in the
`EnvironmentFile`. If you have not set one, it says that instead, because a
generated token under a service is wrong twice over.
