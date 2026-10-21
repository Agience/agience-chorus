"""`call_mcp_server`: Iris reaches an MCP server a person added, and only safely.

2026-10-18: a person's MCP server (a `vnd.agience.mcp-server+json` card) could be created and never
reached — Crystal knew only the personas. Iris now relays one request to it. The server is chosen by
whoever writes the card, so every reach goes through the egress guard: only HTTP, no private or
local address, no redirect followed with a request body, and the caller's own credential never
sent.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agience_chorus import _egress
from agience_chorus.iris import server


def test_a_method_outside_the_relayed_set_is_refused_before_anything_is_read():
    out = json.loads(asyncio.run(server.call_mcp_server("x", "notifications/cancelled")))
    assert "not relayed" in out["error"]


@pytest.mark.parametrize("context,why", [
    ({"transport": {"type": "stdio", "command": "/bin/sh"}}, "HTTP servers only"),
    ({"transport": {"type": "http"}}, "no endpoint"),
    ({}, "HTTP servers only"),
])
def test_only_an_http_endpoint_is_reached(context, why):
    with pytest.raises(_egress.EgressRefused) as e:
        server._server_endpoint(context)
    assert why in str(e.value)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8184/mcp", "http://localhost/mcp",
                                 "http://10.0.0.5/mcp", "http://169.254.169.254/latest",
                                 "http://mantle.internal/mcp", "file:///etc/passwd"])
def test_a_post_to_a_private_or_local_address_is_refused(url):
    """The box's own services — Mantle on loopback, the cloud metadata address — are exactly what
    a card naming an arbitrary URL would otherwise reach."""
    with pytest.raises(_egress.EgressRefused):
        _egress.post(url, b"{}")


def test_an_event_stream_answer_is_read_and_an_error_is_raised():
    ok = _egress.Response("u", 200, "text/event-stream",
                          b'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n\n', False)
    assert server._mcp_rpc_result(ok) == {"tools": []}
    bad = _egress.Response("u", 200, "application/json",
                           b'{"jsonrpc":"2.0","id":2,"error":{"code":-32601,"message":"no"}}', False)
    with pytest.raises(_egress.EgressError):
        server._mcp_rpc_result(bad)


def test_the_callers_credential_is_not_sent_and_a_named_secret_is(monkeypatch):
    sent = []

    def fake_post(url, body, *, headers=None, **kw):
        sent.append(dict(headers or {}))
        payload = json.loads(body)
        result = {"protocolVersion": "2025-06-18"} if payload.get("method") == "initialize" else {"ok": 1}
        return _egress.Response(url, 200, "application/json",
                                json.dumps({"jsonrpc": "2.0", "id": payload.get("id"), "result": result}).encode(),
                                False, {"mcp-session-id": "s1"})

    monkeypatch.setattr(_egress, "post", fake_post)
    assert server._mcp_exchange("https://mcp.example.com/mcp", "tools/list", {}, None) == {"ok": 1}
    assert all("Authorization" not in h for h in sent), "no credential is invented"
    assert sent[-1]["mcp-session-id"] == "s1", "the session the server opened is kept"

    sent.clear()
    server._mcp_exchange("https://mcp.example.com/mcp", "tools/list", {}, "server-secret")
    assert all(h["Authorization"] == "Bearer server-secret" for h in sent)


# ── reading a server is not running it ────────────────────────────────────────────────────────
# 2026-10-21: a server card shared to be seen also let its reader call every tool on the server.

class _Resp:
    def __init__(self, body, status=200):
        self._b, self.status_code = body, status

    def json(self):
        return self._b

    def raise_for_status(self):
        pass


def _world(monkeypatch, may_invoke):
    asked, reached = [], []

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None, **k):
            asked.append(url)
            if url.endswith("/grants/my-access"):
                assert params == {"resource_id": "srv-1", "action": "invoke"}
                return _Resp({"allowed": may_invoke})
            return _Resp({"id": "srv-1", "content_type": "application/vnd.agience.mcp-server+json",
                          "context": json.dumps({"url": "https://tools.example.com/mcp", "transport": {"type": "http"}})})

    monkeypatch.setattr(server.httpx, "AsyncClient", _C)
    monkeypatch.setattr(server, "_require_user_headers", lambda: {"Authorization": "Bearer d"})
    monkeypatch.setattr(server, "_mcp_exchange", lambda endpoint, method, params, auth: reached.append(method) or {"ok": 1})
    return asked, reached


@pytest.mark.parametrize("method", ["tools/call", "prompts/get"])
def test_running_a_persons_server_needs_invoke_on_its_card(monkeypatch, method):
    _, reached = _world(monkeypatch, may_invoke=False)
    out = json.loads(asyncio.run(server.call_mcp_server("srv-1", method, {"name": "x"})))
    assert out["status"] == 403 and "invoke" in out["error"] and reached == []


def test_seeing_what_a_server_offers_needs_only_read(monkeypatch):
    asked, reached = _world(monkeypatch, may_invoke=False)
    out = json.loads(asyncio.run(server.call_mcp_server("srv-1", "tools/list")))
    assert out == {"result": {"ok": 1}} and reached == ["tools/list"]
    assert not any(u.endswith("/grants/my-access") for u in asked)


def test_a_caller_who_may_invoke_runs_it(monkeypatch):
    _, reached = _world(monkeypatch, may_invoke=True)
    out = json.loads(asyncio.run(server.call_mcp_server("srv-1", "tools/call", {"name": "x"})))
    assert out == {"result": {"ok": 1}} and reached == ["tools/call"]
