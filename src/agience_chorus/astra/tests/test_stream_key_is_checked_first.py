"""astra's stream webhooks check the stream key before anything runs on astra's platform authority.

SRS calls `POST /stream/publish` with the stream name `{source_artifact_id}:{key}`. The key must
read the source artifact at Mantle as itself before astra looks the source up with its platform
token, and every failure — wrong key, missing artifact, incomplete artifact — answers the same 401,
so the route is not an oracle for which artifact ids exist.

`GET /stream/sessions` needs a Bearer token that reads the source whose sessions it lists.

Mantle is a recorder standing in for `httpx.AsyncClient`: the key `agc_good` and the user token
`user-token` read `src-1` and `src-incomplete`; the platform token (what `_sign_platform_token`
returns here) is identifiable by value, so a platform call made before the key check is visible.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from agience_chorus.astra import stream_routes as sr

_PLATFORM = "platform-token"
_ARTIFACTS = {
    "src-1": {"id": "src-1", "workspace_id": "ws-1", "owner_id": "u-1", "context": "{}"},
    "src-incomplete": {"id": "src-incomplete", "context": "{}"},
}
_READERS = {"agc_good", "user-token"}


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class _Mantle:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _bearer(self, headers):
        return (headers.get("Authorization") or "").removeprefix("Bearer ")

    async def get(self, url, headers=None, **k):
        bearer = self._bearer(headers)
        self.calls.append(("GET", url, bearer))
        aid = url.rstrip("/").rsplit("/", 1)[-1]
        if bearer in _READERS and aid in _ARTIFACTS:
            return _Resp(200, _ARTIFACTS[aid])
        return _Resp(404 if bearer == _PLATFORM else 401)

    async def post(self, url, headers=None, json=None, **k):
        bearer = self._bearer(headers)
        self.calls.append(("POST", url, bearer))
        if url.endswith("/artifacts/batch"):
            ids = (json or {}).get("artifact_ids") or []
            return _Resp(200, [_ARTIFACTS[i] for i in ids if i in _ARTIFACTS])
        return _Resp(201, {"id": "session-1"})

    async def patch(self, url, headers=None, **k):
        self.calls.append(("PATCH", url, self._bearer(headers)))
        return _Resp(200, {})


@pytest.fixture
def mantle(monkeypatch):
    m = _Mantle()
    monkeypatch.setattr(sr.httpx, "AsyncClient", m)
    monkeypatch.setattr(sr, "_sign_platform_token", lambda: _PLATFORM)
    monkeypatch.setattr(sr, "_ACTIVE_SESSIONS", {})
    app = FastAPI()
    app.include_router(sr.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, m


def _publish(client, source, key):
    return client.post("/stream/publish", json={"stream": "live/%s:%s" % (source, key)})


@pytest.mark.parametrize("source,key", [
    ("src-1", "agc_wrong"),            # an artifact that exists, a key that does not open it
    ("src-missing", "agc_wrong"),      # an artifact that does not exist
    ("src-missing", "agc_good"),       # a working key, an artifact that does not exist
    ("src-incomplete", "agc_good"),    # a working key, an artifact missing its workspace/owner
    ("src-1", "not-an-api-key"),
])
def test_every_failure_answers_the_same(mantle, source, key):
    client, _m = mantle
    r = _publish(client, source, key)
    assert (r.status_code, r.json()) == (401, {"detail": "Invalid stream key"})


@pytest.mark.parametrize("source", ["src-1", "src-missing"])
def test_no_platform_call_is_made_for_a_key_that_fails(mantle, source):
    client, m = mantle
    _publish(client, source, "agc_wrong")
    assert [c for c in m.calls if c[2] == _PLATFORM] == []


def test_a_working_key_publishes_and_is_checked_first(mantle):
    client, m = mantle
    r = _publish(client, "src-1", "agc_good")
    assert r.status_code == 200, r.text
    assert r.json()["artifact_id"] == "session-1"
    assert m.calls[0] == ("GET", sr.artifact_url(sr.MANTLE_URI, "src-1"), "agc_good")
    assert any(c[0] == "POST" and c[2] == _PLATFORM for c in m.calls[1:])


# ── GET /stream/sessions ──────────────────────────────────────────────────────────────────────────

def _live(client):
    assert _publish(client, "src-1", "agc_good").status_code == 200


def test_sessions_needs_a_token(mantle):
    client, _m = mantle
    _live(client)
    r = client.get("/stream/sessions", params={"source_artifact_id": "src-1"})
    assert r.status_code == 401
    assert "ws-1" not in r.text and "session-1" not in r.text


def test_there_is_no_unfiltered_listing(mantle):
    client, _m = mantle
    _live(client)
    r = client.get("/stream/sessions", headers={"Authorization": "Bearer user-token"})
    assert r.status_code == 400
    assert "session-1" not in r.text


def test_a_source_the_token_cannot_read_lists_nothing(mantle):
    client, _m = mantle
    _live(client)
    r = client.get("/stream/sessions", params={"source_artifact_id": "src-1"},
                   headers={"Authorization": "Bearer someone-else"})
    assert r.status_code == 404
    assert "session-1" not in r.text


def test_a_reader_sees_its_sources_sessions(mantle):
    client, _m = mantle
    _live(client)
    r = client.get("/stream/sessions", params={"source_artifact_id": "src-1"},
                   headers={"Authorization": "Bearer user-token"})
    assert r.status_code == 200
    assert [s["artifact_id"] for s in r.json()["sessions"]] == ["session-1"]
