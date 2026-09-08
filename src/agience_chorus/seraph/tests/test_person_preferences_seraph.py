"""Person preferences are read and written through seraph's `get_person_preferences` and
`set_person_preferences` tektons, which reach Origin's `/auth/me/preferences` over the wire at
`ORIGIN_URI` rather than through an import — `chorus -> origin` stays at 0, and
`src/tests/test_chorus_does_not_import_origin.py` is the guard; this file is that guard's
caller-side companion.

A management tekton without a verified delegation must not proceed to the wire. `_headers()` exists
in this module and resolves unconditionally to seraph's own platform JWT, and Origin's `/auth/me/*`
routes resolve the person from the token — so a tool that called `_headers()` instead of
`_require_user_headers()` would not fail on a missing delegation, it would succeed against the wrong
person and return a plausible-looking dict, with no error to notice. That is why the property needs
a test with a positive control beside it rather than a code review alone.

`test_no_delegation_refuses_*` therefore asserts two things, and the second is the one that matters:
the call raises, and no HTTP request was made at all — proving the raise happens before the wire
rather than being a rejection at Origin. A tool that fell through to the platform JWT would still
"fail" in a test whose Origin stub returns 401, and the assertion would pass while the defect stood.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent


# 2026-08-26: an inline copy of `src/_persona.py`'s loader lived here. That module is its one
# home and does strictly more — it pops the half-built module from `sys.modules` when
# `exec_module` raises, and names the persona in the error when the file is absent.
from agience_chorus import _persona  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


_server = _persona.load("server", __file__)


# ── a recording stand-in for the wire ────────────────────────────────────────
class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _RecordingClient:
    """Records every request instead of making one. `calls` is shared across instances so a test
    can assert zero calls happened — an instance-local list would be unobservable if the tool
    never constructed a client, which is precisely the case under test."""

    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, headers, None))
        return _Resp(200, {"theme": "dark", "locale": "en"})

    async def patch(self, url, headers=None, json=None):
        self.calls.append(("PATCH", url, headers, json))
        return _Resp(200, {"theme": "dark", "locale": "en", **(json or {})})


@pytest.fixture
def wire(monkeypatch):
    _RecordingClient.calls = []
    monkeypatch.setattr(_server.httpx, "AsyncClient", _RecordingClient)
    return _RecordingClient


@pytest.fixture
def no_delegation():
    """Clear the delegation ContextVar — the unauthenticated case."""
    tok = _server._auth.request_user_token.set("")
    yield
    _server._auth.request_user_token.reset(tok)


@pytest.fixture
def delegated():
    """A delegation in context, as the ASGI middleware would leave it on a verified request."""
    tok = _server._auth.request_user_token.set("delegation-jwt-for-seraph")
    yield "delegation-jwt-for-seraph"
    _server._auth.request_user_token.reset(tok)


# ── no delegation, no request ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_delegation_refuses_the_read(wire, no_delegation):
    with pytest.raises(Exception) as exc:
        await _server.get_person_preferences()
    assert "delegation" in str(exc.value).lower(), \
        f"refused, but not for the delegation reason: {exc.value!r}"
    assert wire.calls == [], \
        ("get_person_preferences reached the wire with no verified delegation — it fell through to "
         "the platform JWT instead of refusing, and Origin would have answered for the WRONG person")


@pytest.mark.asyncio
async def test_no_delegation_refuses_the_write(wire, no_delegation):
    """The write matters more than the read: a fall-through here mutates another person's settings."""
    with pytest.raises(Exception) as exc:
        await _server.set_person_preferences(json.dumps({"theme": "light"}))
    assert "delegation" in str(exc.value).lower(), \
        f"refused, but not for the delegation reason: {exc.value!r}"
    assert wire.calls == [], \
        "set_person_preferences WROTE to Origin with no verified delegation"


# ── the positive control — without it the raises above prove nothing ─────────
@pytest.mark.asyncio
async def test_a_delegated_read_reaches_origin_as_the_caller(wire, delegated):
    """The positive control, plus the no-escalation assertion in one.

    Both raise tests above would pass just as happily if these tools were broken for everyone. This
    proves the working path works, and pins the header to the caller's delegation, so the tool
    cannot silently start using `_headers()` (seraph's platform JWT) later.
    """
    out = json.loads(await _server.get_person_preferences())
    assert out == {"theme": "dark", "locale": "en"}

    assert len(wire.calls) == 1
    method, url, headers, _ = wire.calls[0]
    assert method == "GET"
    assert url == f"{_server.ORIGIN_URI}/auth/me/preferences", \
        "the tekton must reach ORIGIN_URI — Origin is a service, not an import"
    assert headers["Authorization"] == f"Bearer {delegated}", \
        "the call did not carry the CALLER's delegation — service identity was used instead"


@pytest.mark.asyncio
async def test_a_delegated_write_forwards_the_object_unchanged(wire, delegated):
    """The merge is Origin's. This tool forwards the patch verbatim and returns what Origin
    returns — it must not read-modify-write, which would lose a concurrent update, nor re-implement
    `person_service.update_preferences`'s shallow merge in a second repo."""
    out = json.loads(await _server.set_person_preferences(json.dumps({"locale": "fr"})))
    assert out["locale"] == "fr" and out["theme"] == "dark", \
        "the merged result from Origin was not returned intact"

    method, url, headers, body = wire.calls[0]
    assert method == "PATCH"
    assert url == f"{_server.ORIGIN_URI}/auth/me/preferences"
    assert body == {"locale": "fr"}, f"the patch body was rewritten client-side: {body!r}"
    assert headers["Authorization"] == f"Bearer {delegated}"


@pytest.mark.asyncio
async def test_a_non_object_patch_is_refused_before_the_wire(wire, delegated):
    """`preferences` is a JSON object. A list or a bare string would be forwarded to Origin and
    stored into a JSON column that the rest of the platform reads as a mapping."""
    for bad in ("not json at all", json.dumps(["a", "b"]), json.dumps("scalar")):
        out = json.loads(await _server.set_person_preferences(bad))
        assert "error" in out, f"{bad!r} was accepted as preferences"
    assert wire.calls == [], "a malformed preferences payload was sent to Origin"


@pytest.mark.asyncio
async def test_an_origin_refusal_is_reported_not_swallowed(monkeypatch, delegated):
    """Origin's own refusal (401/404) must surface as an error, never as an empty-but-successful
    dict — `{}` is a valid preferences value, so a swallowed 401 is indistinguishable from a
    person who has set nothing."""
    class _Refusing(_RecordingClient):
        async def get(self, url, headers=None, params=None):
            return _Resp(401, {"detail": "Missing Bearer token"})

    monkeypatch.setattr(_server.httpx, "AsyncClient", _Refusing)
    out = json.loads(await _server.get_person_preferences())
    assert out.get("status") == 401 and "error" in out, \
        f"Origin's refusal was not reported: {out!r}"


def test_the_tektons_are_registered_tools():
    """A tool that is not registered is not a tekton — it is a function nobody can call."""
    names = {t.name for t in _server.mcp._tool_manager.list_tools()}
    assert {"get_person_preferences", "set_person_preferences"} <= names, \
        f"the preference tektons are not registered: {sorted(names)}"


def test_this_module_does_not_import_origin():
    """The caller-side companion to `src/tests/test_chorus_does_not_import_origin.py`: seraph holds
    Origin's identity now, so it is where the deleted edge would most plausibly come back."""
    import ast
    tree = ast.parse((_HERE.parent / "server.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
    assert "origin" not in found, "seraph/server.py imports origin — it must use ORIGIN_URI"
