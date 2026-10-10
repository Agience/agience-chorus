"""Seraph's two token surfaces a caller reaches directly.

`verify_token` answers "is this an access token, and of which class" — nothing more. It returns no
claims, and a token carrying `token_type` (Origin's refresh, email_verify and pwd_reset tokens) is
not an access token and does not verify, whichever verifier's signature check it passes.

`complete_authorizer_bearer` reads the Authorizer's config from the stored artifact under the
caller's delegation — the tool takes no config argument — and exchanges the code only at an
allowlisted OAuth token endpoint. A refused endpoint means no secret is read and nothing is POSTed.
"""
from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from agience_chorus import _persona

server = _persona.load("server", __file__)


# ── verify_token ──────────────────────────────────────────────────────────────────────────────────

_CLAIMS = {"sub": "person-1", "aud": "client-1", "email": "p@example.com", "exp": 9999999999,
           "scope": "platform.all"}


@pytest.fixture
def verifiers(monkeypatch):
    """Every verifier refuses unless the test sets what `user` returns."""
    answer = {}
    monkeypatch.setattr(server._auth, "verify_delegation_jwt", lambda t: None)
    monkeypatch.setattr(server._auth, "verify_origin_delegation", lambda t: None)
    monkeypatch.setattr(server._auth, "verify_user_jwt", lambda t: answer.get("user"))
    monkeypatch.setattr(server._auth, "verify_core_jwt", lambda t: answer.get("user"))
    return answer


def _verify(token="t"):
    return json.loads(asyncio.run(server.verify_token(token)))


def test_an_access_token_verifies_with_its_class_and_no_claims(verifiers):
    verifiers["user"] = dict(_CLAIMS)
    out = _verify()
    assert out == {"valid": True, "token_class": "user"}


@pytest.mark.parametrize("token_type", ["refresh", "email_verify", "pwd_reset", "anything"])
def test_a_special_purpose_token_is_not_an_access_token(verifiers, token_type):
    verifiers["user"] = dict(_CLAIMS, token_type=token_type)
    out = _verify()
    assert out["valid"] is False and out["token_class"] is None
    assert "claims" not in out and "person-1" not in json.dumps(out)


def test_an_unverifiable_token_reports_no_detail_of_why(verifiers):
    out = _verify()
    assert out["valid"] is False and "claims" not in out


# ── complete_authorizer_bearer ────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _Recorder:
    def __init__(self, config):
        self.config, self.calls = config, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **k):
        self.calls.append(("GET", url))
        if url.endswith("/auth-1"):
            return _Resp({"content": json.dumps(self.config)})
        return _Resp({"content": json.dumps({"value": "client-secret"})})

    async def post(self, url, **k):
        self.calls.append(("POST", url))
        return _Resp({"access_token": "at-1", "expires_in": 3600})


@pytest.fixture
def harness(monkeypatch):
    stored = []
    monkeypatch.setattr(server, "_require_user_headers", lambda: {"Authorization": "Bearer d"})

    async def _store(**kw):
        stored.append(kw)
    monkeypatch.setattr(server, "_store_or_rotate_bearer_token", _store)

    def _run(config):
        rec = _Recorder(config)
        monkeypatch.setattr(server.httpx, "AsyncClient", rec)
        out = json.loads(asyncio.run(server.complete_authorizer_bearer(
            authorizer_artifact_id="auth-1", authorization_code="code-1",
            redirect_uri="https://my.agience.ai/cb")))
        return out, rec.calls, stored
    return _run


def test_the_tool_takes_no_caller_supplied_config():
    params = inspect.signature(server.complete_authorizer_bearer).parameters
    assert "authorizer_config" not in params
    assert "authorizer_artifact_id" in params


@pytest.mark.parametrize("endpoint", [
    "http://169.254.169.254/latest/meta-data/", "https://attacker.example/token",
    "http://127.0.0.1:8080/auth/token", None,
])
def test_a_stored_endpoint_off_the_allowlist_is_refused(harness, endpoint):
    cfg = {"client_id": "cid", "client_secret_id": "cs-1", "provider": "p"}
    if endpoint is not None:
        cfg["token_endpoint"] = endpoint
    out, calls, stored = harness(cfg)
    assert "error" in out, out
    assert [c for c in calls if c[0] == "POST"] == []
    assert not any(u.endswith("/cs-1") for _m, u in calls), calls
    assert stored == []


def test_the_stored_config_is_what_the_exchange_uses(harness):
    cfg = {"client_id": "cid", "client_secret_id": "cs-1", "provider": "google",
           "token_endpoint": "https://oauth2.googleapis.com/token"}
    out, calls, stored = harness(cfg)
    assert out == {"status": "connected", "authorizer_artifact_id": "auth-1"}
    assert calls[0][0] == "GET" and calls[0][1].endswith("/auth-1")
    assert ("POST", "https://oauth2.googleapis.com/token") in calls
    assert stored and stored[0]["access_token"] == "at-1"
