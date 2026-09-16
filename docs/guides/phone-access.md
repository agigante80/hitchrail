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
hitchrail --root main=~/projects \
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
hitchrail --root main=~/projects --host 192.168.1.10
```

This works, it needs nothing installed, and it is what the README shows. State
the exposure plainly before choosing it:

- Hitchrail is now listening on that interface **for anyone who can reach it**.
  On a home network that is every device on the wifi, including the ones you do
  not administer. On a cafe or hotel network it is everybody.
- **The token is the only control.** There is no second factor and no source
  address restriction. Someone who obtains the token has a shell as you.
- **It is HTTP, unless you give it a certificate.** The grant fragment stays
  in the browser and reaches no server log, which is real and is not the
  whole story: the cookie it becomes crosses your network in cleartext on
  every subsequent request. Anyone positioned to read that traffic can replay
  it. `--tls-cert` and `--tls-key` end that from the server itself, and the
  section below says where a certificate for a private address comes from;
  a TLS terminating proxy is the other way, and if you are installing one,
  route 1 is less work.
- **It is a decision with an expiry date you will not be told about.** This
  choice is correct while you are on a network you trust. Nothing warns you
  when the machine joins one you do not, and a laptop's whole job is joining
  other networks. `--expect-gateway-mac` is the one thing that will: it names
  the default gateway of the network you meant, and a start anywhere else,
  or anywhere the gateway cannot be identified, refuses with exit 2 and the
  unit stays stopped until you look (`ip neigh show default` or the router's
  label gives you the address). It catches the cafe, the hotel and the
  replaced router, and not an attacker on the LAN, who can present any MAC.
  Checked once, when the unit starts: a machine that joins another network
  while it is running is not noticed until the next start. `ip route show
  default` names the gateway's address, and `ip neigh show` the MAC beside
  it; the password manager entry for `/grant` is keyed by origin, so a new
  scheme or port means a new entry there too.

That last point is why this is second rather than first. It is not less secure
in the moment. It is a decision that silently stops being the one you made.

### 2a. HTTPS on that address, without a second daemon

uvicorn terminates TLS itself, so the two flags are the whole of the server
side:

```sh
hitchrail --host 192.168.1.10 \
  --tls-cert ~/.config/hitchrail/box.pem \
  --tls-key  ~/.config/hitchrail/box-key.pem
```

Both or neither: one without the other refuses at startup naming the missing
one, and a certificate that cannot be loaded refuses at startup too, before
anything is bound, so the failure is never plain HTTP on the port you believed
was TLS. With TLS on, the banner prints `https://` links, the cookie is
`Secure`, and the origin check expects `https://192.168.1.10:8787`, all
derived from the flags; `--allow-origin` stays for a proxy in front, whose
scheme and port are its own.

**Where the certificate comes from is the real work, and it is on the phone.**
A public CA cannot issue for `192.168.1.10` or for a `.local` name, because
there is no way to prove control of a private address to a public issuer. A
bare self signed certificate produces a browser warning you would learn to
click through, which trains exactly the wrong reflex on the one tool where a
warning matters. The practical answer is a local certificate authority, and
[mkcert](https://github.com/FiloSottile/mkcert) is the tool for it:

```sh
mkcert -install                       # a local CA, trusted on THIS machine
mkcert -cert-file box.pem -key-file box-key.pem 192.168.1.10 box.lan
```

Then the CA has to be trusted on the phone as well, or the phone gets the
warning the whole exercise exists to avoid: `mkcert -CAROOT` prints where
`rootCA.pem` is, and that file goes onto the phone and into its trust store
(Android: Settings, Security, Encryption and credentials, Install a
certificate, CA certificate; iOS: open the file, install the profile, then
enable it under Certificate Trust Settings). The CA's private key stays on the
machine that made it, and anything that trusts the CA trusts every
certificate it signs, which is why route 1 stays first: `tailscale serve`
hands you a genuinely trusted certificate for the tailnet name with no CA to
install anywhere.

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
| That, and the cookie encrypted, with a CA to install on the phone | 2a, a certificate |
| To reach it from one interface | 2, name that interface |
| To reach it from every interface | Nothing on this page. Reconsider. |

## Enrolling a device

Getting a new phone in means moving the token onto it, once. The link the
banner prints carries it in the fragment, `/grant#token=...`, and a saved link
works for as long as the token does. The other door is the form at `/grant`,
which takes the token typed or pasted, and that is the one a password manager
fills: **put the token in your password manager as the password for the
address Hitchrail serves on**, and enrolling the next device is opening
`/grant` and letting the manager fill the field. The credential is never
retyped, never in a message, and lives where your other credentials live.

That is the whole of it, and it was a decision (#171). A QR code printed by
the server would cost a fourth runtime dependency or a hand rolled encoder
for a once per device event; a short pairing code would be the first
endpoint here that genuinely needs rate limiting, because a short code is
guessable by construction; and a QR drawn inside the authenticated page would
hand the raw token to script, which the `HttpOnly` cookie exists to prevent.
The paragraph above costs nothing and addresses a moment that is rare,
recoverable and already survivable.

## Running it unattended

`packaging/hitchrail.service` is a systemd user unit template. It is a template
to copy and edit rather than a file to install, and it carries its own
instructions in comments at the top.

Two things about it belong here rather than in the file:

**The token has to come from the environment.** A generated token changes on
every start, so a service that restarts invalidates the link saved on your
phone. Put `HITCHRAIL_TOKEN` in the unit's `EnvironmentFile` and `chmod 600`
it, because anyone who can read that file can run code as you.

**A refusal stays stopped, and a bind failure retries.** The unit prevents a
restart on exit 2, which is every deliberate refusal: a blank `HITCHRAIL_TOKEN`,
a root that is not a directory, a typo in the `ExecStart`. Without that it
retried them every five seconds forever, and the journal filled with copies of
the message telling you what was wrong. A port already in use is exit 3 and is
still retried, because that is usually a previous instance still shutting down.

**The unit sets `PYTHONUNBUFFERED=1`, and the banner below is why.** Python
block buffers stdout when it is not a terminal, and under a unit stdout is the
journal. Hitchrail flushes the banner itself since #145, so the template's line
is for everything else the process prints. Before that fix the entire log was
uvicorn's four lines, which appear only because uvicorn logs to stderr, and a
missing message reads as a clean start rather than as a missing message.

**The banner withholds the token when it is talking to the journal.** Under a
unit, standard output is journald: persistent, and readable by root and by
members of the `systemd-journal` group. A token printed to a terminal scrolls
past while you watch it; the same token printed to the journal is kept. So when
Hitchrail sees it is writing to the journal it prints the address without the
fragment, and tells you to append the value you already put in the
`EnvironmentFile`. If you have not set one, it says that instead, because a
generated token under a service is wrong twice over.
