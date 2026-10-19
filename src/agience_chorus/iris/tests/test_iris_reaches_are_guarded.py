"""Iris's two outbound reaches that a caller can steer.

`fetch_url` fetches a caller-named URL. It goes through the shared egress guard, so an internal
target is refused before any connection is opened or any HTTP client is built.

`send_email` exchanges an authorizer's refresh token at the authorizer's `token_endpoint`. The
authorizer is an artifact its owner edits, so the endpoint must be an allowlisted OAuth endpoint:
a refused endpoint means no secret is read and nothing is POSTed. One send also addresses a small,
bounded number of recipients, and a line break in `To` or `Subject` (a header injection) is refused.
"""
from __future__ import annotations

import asyncio
import json
import socket

import pytest

from agience_chorus import _persona

server = _persona.load("server", __file__)


# ── fetch_url ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    attempts = []

    def _connect(address, *a, **k):
        attempts.append(address)
        raise AssertionError("a connection was opened to %r" % (address,))

    class _NoClient:
        def __init__(self, *a, **k):
            attempts.append("httpx.AsyncClient")
            raise AssertionError("an HTTP client was built")

    def _gai(host, port, *a, **k):
        if host == "intranet.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", port))]
        raise socket.gaierror(host)

    monkeypatch.setattr(socket, "create_connection", _connect)
    monkeypatch.setattr(socket, "getaddrinfo", _gai)
    monkeypatch.setattr(server.httpx, "AsyncClient", _NoClient)
    return attempts


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://127.0.0.1:8081/artifacts", "http://0x7f.1/", "http://[::1]/", "http://localhost:8086/",
    "gopher://example.com/", "http://intranet.example/admin",
])
def test_fetch_url_refuses_internal_targets_without_reaching_them(url, no_network):
    out = json.loads(asyncio.run(server.fetch_url(url)))
    assert "error" in out and "content" not in out
    assert no_network == []


# ── send_email ────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Recorder:
    """Stands in for `httpx.AsyncClient`: serves the authorizer and its two secrets, records every
    request, and answers the token exchange and the Gmail send."""

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
        return _Resp({"content": json.dumps({"value": "secret-for-" + url.rsplit("/", 1)[-1]})})

    async def post(self, url, **k):
        self.calls.append(("POST", url))
        if url.endswith("/use"):
            # Mantle releases a secret sealed to Iris's key, for the card named in `for`.
            from prism.trust import sealing
            secret = url.rsplit("/", 2)[-2]
            return _Resp({"id": secret, "sealed": sealing.seal(
                json.dumps({"value": "secret-for-" + secret}).encode(), IRIS_KEY.public_key(),
                kid="iris-1", context=f"{secret}|{(k.get('json') or {}).get('for')}")})
        if "gmail" in url:
            return _Resp({"id": "msg-1"})
        return _Resp({"access_token": "at-1"})


def _config(**over):
    cfg = {"client_id": "cid", "client_secret_artifact_id": "cs-1",
           "refresh_token_artifact_id": "rt-1", "sender_address": "noreply@agience.ai"}
    cfg.update(over)
    return cfg


from cryptography.hazmat.primitives.asymmetric import rsa as _rsa  # noqa: E402

IRIS_KEY = _rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def delegated(monkeypatch):
    from prism.trust import service_identity
    monkeypatch.setattr(server, "_require_user_headers", lambda: {"Authorization": "Bearer d"})
    monkeypatch.setattr(service_identity, "load_persona_identity", lambda name: service_identity.ServiceIdentity(
        name=name, kid=f"{name}-1", private_key=IRIS_KEY) if name == "iris" else None)


def _send(monkeypatch, config, to="person@example.com", subject="hi"):
    rec = _Recorder(config)
    monkeypatch.setattr(server.httpx, "AsyncClient", rec)
    out = json.loads(asyncio.run(server.send_email(
        to=to, subject=subject, body_html="<p>x</p>", authorizer_artifact_id="auth-1")))
    return out, rec.calls


@pytest.mark.parametrize("endpoint", [
    "http://169.254.169.254/latest/meta-data/", "https://attacker.example/token",
    "http://oauth2.googleapis.com/token", "http://127.0.0.1:8080/auth/token",
])
def test_a_token_endpoint_off_the_allowlist_is_refused_before_any_secret_is_read(
        endpoint, monkeypatch, delegated):
    out, calls = _send(monkeypatch, _config(token_endpoint=endpoint))
    assert "refused" in out.get("error", ""), out
    assert [c for c in calls if c[0] == "POST"] == []
    assert not any("cs-1" in u or "rt-1" in u for _m, u in calls), calls


def test_the_google_token_endpoint_is_allowed(monkeypatch, delegated):
    out, calls = _send(monkeypatch, _config(token_endpoint="https://oauth2.googleapis.com/token"))
    assert out.get("status") == "sent", out
    assert ("POST", "https://oauth2.googleapis.com/token") in calls


def test_an_absent_token_endpoint_uses_google(monkeypatch, delegated):
    out, calls = _send(monkeypatch, _config())
    assert out.get("status") == "sent", out
    assert ("POST", "https://oauth2.googleapis.com/token") in calls


@pytest.mark.parametrize("to", [
    "a@example.com, b@example.com, c@example.com, d@example.com",
    ",".join("p%d@example.com" % i for i in range(50)),
    "a@example.com\r\nBcc: everyone@example.com",
    "", "not-an-address",
])
def test_recipients_are_bounded_and_well_formed(to, monkeypatch, delegated):
    out, calls = _send(monkeypatch, _config(), to=to)
    assert "refused" in out.get("error", ""), out
    assert calls == []


def test_a_line_break_in_the_subject_is_refused(monkeypatch, delegated):
    out, calls = _send(monkeypatch, _config(), subject="hello\r\nBcc: everyone@example.com")
    assert "refused" in out.get("error", ""), out
    assert calls == []


def test_up_to_the_cap_is_sent(monkeypatch, delegated):
    out, _calls = _send(monkeypatch, _config(), to="a@example.com, B <b@example.com>, c@example.com")
    assert out.get("status") == "sent", out
