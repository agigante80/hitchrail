"""TLS from the server itself (#152): the two flags, and the part that is not
the two flags.

Premortem 1 of the Phase 14 plan: TLS ships with origins still derived as
`http`, every mutating request is refused with a 403 blaming our own origin
check, and the hermetic tier cannot see it because only a socket carries a
scheme. So the derivation is tested here in BOTH directions, the cookie flag
in both, and `tests/test_live_socket.py` carries the socket half: a grant
and a mutating request through a real certificate.
"""

from __future__ import annotations

import pathlib

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from conftest import FakeTmux, procs_from
from hitchrail.cli import banner, build_config, main, parse_args
from hitchrail.config import Config, ConfigError
from hitchrail.events import EventBus
from hitchrail.roots import Root
from hitchrail.security import middleware_stack
from hitchrail.server import create_app
from support import make_certificate, make_config
from test_api import NO_AGENT_CONFIG, PLENTY, make_engine


@pytest.fixture
def certificate(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    return make_certificate(tmp_path)


def _roots(tmp_path: pathlib.Path) -> tuple[Root, ...]:
    (tmp_path / "root").mkdir(exist_ok=True)
    return (Root(label="main", path=(tmp_path / "root").resolve()),)


# -- the refusals, before the bind ------------------------------------------


@pytest.mark.parametrize(
    ("given", "missing"),
    [("--tls-cert", "--tls-key"), ("--tls-key", "--tls-cert")],
)
def test_one_flag_without_the_other_refuses_naming_the_missing_one(
    tmp_path: pathlib.Path,
    certificate: tuple[pathlib.Path, pathlib.Path],
    given: str,
    missing: str,
) -> None:
    cert, key = certificate
    path = cert if given == "--tls-cert" else key
    _roots(tmp_path)
    with pytest.raises(ConfigError, match=f"{given} needs {missing}"):
        build_config(parse_args(["--root", f"main={tmp_path / 'root'}", given, str(path)]))


@pytest.mark.parametrize("what", ["missing", "directory"])
def test_a_path_that_is_not_a_file_refuses_naming_the_flag(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path], what: str
) -> None:
    cert, key = certificate
    bad = tmp_path / "nope.pem" if what == "missing" else tmp_path
    with pytest.raises(ConfigError, match=r"--tls-key .*: not a readable file"):
        Config(roots=_roots(tmp_path), tls_cert=cert, tls_key=bad)
    with pytest.raises(ConfigError, match=r"--tls-cert .*: not a readable file"):
        Config(roots=_roots(tmp_path), tls_cert=bad, tls_key=key)


def test_a_certificate_that_cannot_be_loaded_refuses_at_startup(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path]
) -> None:
    """The failure that must never happen is plain HTTP on the port the
    operator believed was TLS. A garbage certificate is loaded ONCE at
    construction and refused with the file named, before any bind; the cli
    tier proves the port then holds nothing."""
    _, key = certificate
    garbage = tmp_path / "garbage.pem"
    garbage.write_text(
        "-----BEGIN CERTIFICATE-----\nnot a certificate\n-----END CERTIFICATE-----\n"
    )
    with pytest.raises(ConfigError, match=r"cannot be loaded, so nothing will be served"):
        Config(roots=_roots(tmp_path), tls_cert=garbage, tls_key=key)
    # And from the command line: exit 2, the deliberate stop the unit never
    # restarts, not uvicorn's exit 1 that it retries.
    argv = [
        "--root",
        f"main={tmp_path / 'root'}",
        "--tls-cert",
        str(garbage),
        "--tls-key",
        str(key),
    ]
    assert main(argv) == 2


def test_a_key_that_does_not_match_the_certificate_refuses(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path]
) -> None:
    cert, _ = certificate
    (tmp_path / "other").mkdir()
    _, other_key = make_certificate(tmp_path / "other")
    with pytest.raises(ConfigError, match="cannot be loaded"):
        Config(roots=_roots(tmp_path), tls_cert=cert, tls_key=other_key)


# -- the part that is not the two flags -------------------------------------


@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
def test_derived_origins_carry_the_servers_own_scheme(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path], tls: bool
) -> None:
    """Both directions, because a one way test passes on the default and
    ships the broken case (premortem 1)."""
    cert, key = certificate
    config = Config(
        roots=_roots(tmp_path),
        host="127.0.0.1",
        port=8787,
        token="t",
        tls_cert=cert if tls else None,
        tls_key=key if tls else None,
    )
    assert config.scheme == ("https" if tls else "http")
    ours = "https://127.0.0.1:8787" if tls else "http://127.0.0.1:8787"
    other = "http://127.0.0.1:8787" if tls else "https://127.0.0.1:8787"
    assert ours in config.allowed_origins
    assert other not in config.allowed_origins


def test_an_allow_origin_keeps_its_own_scheme_whatever_ours_is(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path]
) -> None:
    """A proxy in front of a TLS server is still configured, not derived."""
    cert, key = certificate
    config = Config(
        roots=_roots(tmp_path),
        token="t",
        tls_cert=cert,
        tls_key=key,
        extra_origins=("http://box.lan:8080",),
    )
    assert "http://box.lan:8080" in config.allowed_origins


def _mutating_app(config: Config) -> Starlette:
    async def ok(request: httpx.Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[Route("/x", ok, methods=["POST"])], middleware=middleware_stack(config)
    )


@pytest.mark.integration
@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
async def test_the_origin_check_accepts_our_scheme_and_refuses_the_other(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path], tls: bool
) -> None:
    cert, key = certificate
    config = Config(
        roots=_roots(tmp_path),
        port=8787,
        tls_cert=cert if tls else None,
        tls_key=key if tls else None,
    )
    app = _mutating_app(config)
    ours, other = ("https", "http") if tls else ("http", "https")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
        accepted = await c.post(
            "/x", headers={"host": "localhost", "origin": f"{ours}://localhost:8787"}
        )
        refused = await c.post(
            "/x", headers={"host": "localhost", "origin": f"{other}://localhost:8787"}
        )
    assert accepted.status_code == 200
    assert refused.status_code == 403
    assert refused.json()["code"] == "origin_rejected"


@pytest.mark.integration
@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
async def test_the_cookie_is_secure_exactly_when_we_terminate_tls(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path], tls: bool
) -> None:
    """Both directions: `Secure` over plain HTTP is a cookie that is set and
    never sent back, and its absence over our own HTTPS offers the credential
    to a plain request on the same host."""
    cert, key = certificate
    (tmp_path / "root").mkdir(exist_ok=True)
    config = make_config(
        tmp_path / "root",
        token="s3cret",
        sessions_dir=tmp_path / ".s",
        agent_config_path=NO_AGENT_CONFIG,
        tls_cert=cert if tls else None,
        tls_key=key if tls else None,
    )
    engine = make_engine(config, FakeTmux(), procs_from(""), PLENTY)
    app = create_app(engine=engine, config=config, bus=EventBus())
    scheme = config.scheme
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as c:
        r = await c.post(
            "/api/grant",
            json={"token": "s3cret"},
            headers={"host": "localhost", "origin": f"{scheme}://localhost:8787"},
        )
    assert r.status_code == 200
    header = r.headers["set-cookie"].lower()
    assert ("secure" in header.split("; ")) is tls, header


def test_the_banner_prints_links_in_the_servers_scheme(
    tmp_path: pathlib.Path, certificate: tuple[pathlib.Path, pathlib.Path]
) -> None:
    cert, key = certificate
    config = Config(
        roots=_roots(tmp_path),
        host="127.0.0.1",
        extra_hosts=("box.lan",),
        token="t",
        tls_cert=cert,
        tls_key=key,
    )
    text = banner(config)
    assert "https://box.lan:8787/grant" in text
    assert "http://" not in text


def test_the_flags_reach_uvicorn_as_the_certificate_pair(
    tmp_path: pathlib.Path,
    certificate: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cert, key = certificate
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/x")
    (tmp_path / "root").mkdir(exist_ok=True)
    argv = [
        "--root",
        f"main={tmp_path / 'root'}",
        "--tls-cert",
        str(cert),
        "--tls-key",
        str(key),
    ]
    assert main(argv) == 0
    assert captured["ssl_certfile"] == str(cert)
    assert captured["ssl_keyfile"] == str(key)
    # And nothing without the flags: `None` is how uvicorn spells "no TLS".
    captured.clear()
    code = main(["--root", f"main={tmp_path / 'root'}"])
    assert code == 0
    assert (captured.get("ssl_certfile"), captured.get("ssl_keyfile")) == (None, None)
