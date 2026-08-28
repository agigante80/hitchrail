from __future__ import annotations
import pathlib, contextlib, json
import httpx, pytest
from conftest import FakeClock, FakeTmux, procs_from
from hitchrail import server
from hitchrail.config import Config
from hitchrail.engine import Engine
from hitchrail.events import EventBus

pytestmark = pytest.mark.integration

H = {"host": "localhost", "origin": "http://localhost:8787"}

def make(tmp_path):
    (tmp_path / "vessel").mkdir()
    config = Config(root=tmp_path, sessions_dir=tmp_path / ".s", token="s3cret")
    clock = FakeClock()
    engine = Engine(config=config, tmux=FakeTmux(), procs_fn=procs_from(""),
                    meminfo_fn=lambda: "MemTotal: 33554432 kB\nMemAvailable: 25198592 kB\n",
                    clock=clock, sleep=clock.sleep)
    return server.create_app(engine=engine, config=config, bus=EventBus())

@contextlib.asynccontextmanager
async def cl(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        yield c

async def test_surrogate(tmp_path):
    app = make(tmp_path)
    async with cl(app) as c:
        r = await c.post("/api/grant", content=b'{"token": "\\ud800"}',
                         headers={**H, "content-type": "application/json"})
        print("SURROGATE ->", r.status_code, r.text[:200])

async def test_percent_encoded_path(tmp_path):
    app = make(tmp_path)
    async with cl(app) as c:
        for p in ("/%67rant", "/gr%61nt", "/grant/", "/GRANT", "/./grant", "/api/grant/../../"):
            try:
                r = await c.get(p, headers=H)
                print(f"PATH {p!r} -> {r.status_code} {r.text[:80]!r}")
            except Exception as e:
                print(f"PATH {p!r} -> EXC {e}")

async def test_methods_on_exempt(tmp_path):
    app = make(tmp_path)
    async with cl(app) as c:
        for m, p in [("POST","/grant"),("DELETE","/grant"),("GET","/api/grant"),
                     ("DELETE","/api/grant"),("HEAD","/grant"),("OPTIONS","/api/grant")]:
            r = await c.request(m, p, headers=H)
            print(f"{m} {p} -> {r.status_code}")

async def test_no_origin_on_grant(tmp_path):
    app = make(tmp_path)
    async with cl(app) as c:
        r = await c.post("/api/grant", json={"token":"s3cret"}, headers={"host":"localhost"})
        print("NO ORIGIN ->", r.status_code, r.text[:120], dict(r.headers).get("set-cookie"))

async def test_error_shapes(tmp_path):
    app = make(tmp_path)
    async with cl(app) as c:
        wrong = await c.post("/api/grant", json={"token":"nope"}, headers=H)
        missing = await c.get("/api/projects", headers={"host":"localhost"})
        print("WRONG:", wrong.status_code, repr(wrong.content), dict(wrong.headers))
        print("MISSING:", missing.status_code, repr(missing.content), dict(missing.headers))

async def test_grant_query_still(tmp_path):
    app = make(tmp_path)
    async with cl(app) as c:
        r = await c.get("/grant?token=s3cret", headers={"host":"localhost"})
        print("GRANT PAGE w/ query token ->", r.status_code, dict(r.headers).get("set-cookie"))

async def test_root_path(tmp_path):
    """Simulate a proxy-mounted root_path."""
    app = make(tmp_path)
    scopes = []
    async def call(path, root, method="GET"):
        from starlette.testclient import TestClient
        recv_done = False
        body = b""
        result = {}
        async def receive():
            return {"type":"http.request","body":b"","more_body":False}
        async def send(msg):
            if msg["type"]=="http.response.start":
                result["status"]=msg["status"]
            elif msg["type"]=="http.response.body":
                result.setdefault("body",b"")
                result["body"]+=msg.get("body",b"")
        scope = {"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":method,
                 "scheme":"http","path":path,"raw_path":path.encode(),"root_path":root,
                 "query_string":b"","headers":[(b"host",b"localhost")],"client":("127.0.0.1",1),
                 "server":("127.0.0.1",8787)}
        await app(scope, receive, send)
        return result
    for path, root in [("/api/grant","/api"), ("/grant","/gr"), ("/api/grant","")]:
        r = await call(path, root)
        print(f"ROOTPATH path={path!r} root={root!r} -> {r.get('status')} {r.get('body',b'')[:80]!r}")
