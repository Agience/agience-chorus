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
