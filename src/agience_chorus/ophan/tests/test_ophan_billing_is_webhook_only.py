"""Plan limits are written by the Stripe webhook and by nothing an MCP caller can reach.

`activate_subscription` and `update_subscription` set a person's plan limits on ophan's platform
identity for the `person_id` they are handed. They are not registered tools: registered, any caller
could grant any person any plan. The webhook is their only caller.

The webhook itself is unauthenticated until the signature verifies, so it reads a bounded body and
answers without exception text — a refusal says what was refused, never ophan's configuration or a
traceback message.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from agience_chorus import _persona

_server = _persona.load("server", __file__)


def test_the_subscription_writers_are_not_registered_tools():
    tools = {t.name for t in _server.mcp._tool_manager.list_tools()}
    assert "activate_subscription" not in tools
    assert "update_subscription" not in tools
    assert "issue_license" in tools                      # control: the listing is the real one


def test_the_webhook_still_reaches_them(monkeypatch):
    seen = []

    async def _activate(**kw):
        seen.append(("activate", kw["person_id"], kw["plan"]))
        return json.dumps({"status": "activated"})

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(_server, "activate_subscription", _activate)
    monkeypatch.setattr(_server, "_send_account_email", _noop)
    out = asyncio.run(_server._dispatch_stripe_event(
        "checkout.session.completed",
        json.dumps({"metadata": {"person_id": "p-1", "plan_key": "pro"}, "mode": "subscription"})))
    assert json.loads(out)["status"] == "activated"
    assert seen == [("activate", "p-1", "pro")]


# ── the webhook endpoint ──────────────────────────────────────────────────────────────────────────

def _call(headers, chunks):
    """Drive the ASGI handler; return (status, body, how many receive() calls were made)."""
    sent, reads = [], [0]
    queue = list(chunks)

    async def receive():
        reads[0] += 1
        body = queue.pop(0) if queue else b""
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/webhooks/stripe", "headers": headers}
    asyncio.run(_server._handle_stripe_webhook_http(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body.decode(), reads[0]


def test_a_declared_oversize_body_is_refused_unread():
    status, _body, reads = _call([(b"content-length", b"50000000"),
                                  (b"stripe-signature", b"t=1,v1=x")], [b"x" * 10])
    assert status == 413
    assert reads == 0


def test_an_undeclared_oversize_body_stops_being_read_at_the_cap():
    chunk = b"x" * 65536
    status, _body, reads = _call([(b"stripe-signature", b"t=1,v1=x")], [chunk] * 100)
    assert status == 413
    assert reads < 100


@pytest.fixture
def fake_stripe(monkeypatch):
    mod = types.ModuleType("stripe")
    behaviour = {}

    class Webhook:
        @staticmethod
        def construct_event(body, sig, secret):
            if "raise" in behaviour:
                raise behaviour["raise"]
            return behaviour["event"]

    mod.Webhook = Webhook
    monkeypatch.setitem(sys.modules, "stripe", mod)
    return behaviour


def _signed():
    return _call([(b"stripe-signature", b"t=1,v1=x"), (b"content-length", b"2")], [b"{}"])


def test_an_unresolvable_secret_is_not_described(monkeypatch):
    async def _raise():
        raise RuntimeError("secret artifact 7f3a at /private/path-DETAIL-1 is unreadable")
    monkeypatch.setattr(_server, "_resolve_stripe_webhook_secret", _raise)
    status, body, _ = _signed()
    assert status == 503
    assert "DETAIL-1" not in body and "7f3a" not in body


def test_a_failed_signature_is_not_described(monkeypatch, fake_stripe):
    async def _secret():
        return "whsec_test"
    monkeypatch.setattr(_server, "_resolve_stripe_webhook_secret", _secret)
    fake_stripe["raise"] = ValueError("expected signature for secret whsec_DETAIL-2")
    status, body, _ = _signed()
    assert status == 400
    assert "DETAIL-2" not in body


def test_a_dispatch_error_is_not_described(monkeypatch, fake_stripe):
    async def _secret():
        return "whsec_test"

    async def _boom(**kw):
        raise RuntimeError("mantle at http://10.0.0.7:8081 said DETAIL-3")
    monkeypatch.setattr(_server, "_resolve_stripe_webhook_secret", _secret)
    monkeypatch.setattr(_server, "_dispatch_stripe_event", _boom)
    fake_stripe["event"] = {"id": "evt_detail_test", "type": "x", "data": {"object": {}}}
    status, body, _ = _signed()
    assert "DETAIL-3" not in body and "10.0.0.7" not in body
