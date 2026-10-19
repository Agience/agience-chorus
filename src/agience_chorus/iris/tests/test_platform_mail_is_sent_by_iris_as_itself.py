"""Platform mail is Iris's own operation: a platform service asks, and Iris sends as the platform's
system principal under a delegation it obtained as itself, with the authorizer's secrets released
sealed to its own key.

2026-10-19: platform mail ran as an operator invoked through Crystal on a token addressed to
Mantle; Iris refused that token, the token's scope reached no route Mantle serves, and the system
principal held `read` on the mail secrets. No receipt or usage warning was ever sent.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agience_chorus import _persona

server = _persona.load("server", __file__)

IRIS_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
NS = uuid.UUID("11111111-1111-4111-8111-111111111111")
AUTHZ = str(uuid.uuid5(NS, "platform/platform-email-authorizer"))


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(str(self.status_code), request=None, response=self)


class _World:
    """Origin, Mantle, Google and Gmail, as far as platform mail reaches them."""

    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, **k):
        self.calls.append(("GET", url, headers, None))
        assert url.endswith(f"/artifacts/{AUTHZ}"), url
        return _Resp({"content": json.dumps({"client_id": "cid", "client_secret_artifact_id": "cs-1",
                                             "refresh_token_artifact_id": "rt-1",
                                             "sender_address": "connect@agience.ai"})})

    async def post(self, url, headers=None, json=None, data=None, **k):
        self.calls.append(("POST", url, headers, json))
        if url.endswith("/internal/system-delegation"):
            return _Resp({"token": "sys-delegation-for-iris", "scope": "platform.email.send"})
        if url.endswith("/use"):
            from prism.trust import sealing
            secret = url.rsplit("/", 2)[-2]
            return _Resp({"id": secret, "sealed": sealing.seal(
                f"value-of-{secret}".encode(), IRIS_KEY.public_key(), kid="iris-1",
                context=f"{secret}|{(json or {}).get('for')}")})
        if "gmail" in url:
            return _Resp({"id": "msg-1"})
        return _Resp({"access_token": "at-1"})


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
def world(monkeypatch):
    from prism.trust import service_identity
    w = _World()
    monkeypatch.setattr(server.httpx, "AsyncClient", w)
    monkeypatch.setattr(service_identity, "get_instance_namespace", lambda: NS)
    monkeypatch.setattr(service_identity, "load_persona_identity", lambda name: service_identity.ServiceIdentity(
        name=name, kid=f"{name}-1", private_key=IRIS_KEY) if name == "iris" else None)
    monkeypatch.setattr(server._auth, "sign_exchange_jwt", lambda: "iris-signed")
    return w


def _call(caller, body):
    async def run():
        tok = server._auth.request_service_caller.set(caller)
        try:
            return await server.platform_mail(_Request(body))
        finally:
            server._auth.request_service_caller.reset(tok)
    return asyncio.run(run())


def test_a_platform_service_has_iris_send_as_itself_with_secrets_sealed_to_it(world):
    resp = _call("chorus", {"to": "jane@example.com", "subject": "Your plan is active", "body_html": "<p>x</p>"})
    assert resp.status_code == 200, resp.body
    assert json.loads(resp.body)["status"] == "sent"

    asked = next(c for c in world.calls if c[1].endswith("/internal/system-delegation"))
    assert asked[2]["Authorization"] == "Bearer iris-signed" and asked[3] == {"purpose": "platform-mail"}
    mantle = [c for c in world.calls if "/artifacts/" in c[1]]
    assert {c[2]["Authorization"] for c in mantle} == {"Bearer sys-delegation-for-iris"}
    uses = [c for c in mantle if c[1].endswith("/use")]
    assert sorted(c[1].rsplit("/", 2)[-2] for c in uses) == ["cs-1", "rt-1"]
    assert all(c[3] == {"for": AUTHZ} for c in uses), "released for the platform authorizer only"


@pytest.mark.parametrize("caller", ["", "mantle", "crystal"])
def test_anyone_but_the_chorus_platform_service_is_refused(world, caller):
    resp = _call(caller, {"to": "jane@example.com", "subject": "x", "body_html": "x"})
    assert resp.status_code == 403
    assert world.calls == [], "nothing is asked of Origin or Mantle"
