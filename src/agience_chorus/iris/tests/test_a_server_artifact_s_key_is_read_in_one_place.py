"""A server artifact's credential is read in one place (`_server_auth`), so it can later move to its
own secret artifact (John, 2026-11-12). Now: the access key sealed on the server artifact, else a
referenced secret, else none."""
from __future__ import annotations

import asyncio
import json

from agience_chorus.iris import server


def test_the_sealed_key_then_the_referenced_secret_then_none(monkeypatch):
    fetched = []

    async def fetch(client, secret_id, server_id, headers=None, *, endpoint):
        fetched.append((secret_id, server_id, endpoint))
        return "from-secret"
    monkeypatch.setattr(server, "_fetch_secret_material", fetch)
    run = lambda ctx: asyncio.run(server._server_auth(None, ctx, "srv-1", "https://x.example/mcp"))
    assert run({"access_key": " k-123 ", "transport": {"secret_id": "s-1"}}) == "k-123"
    assert fetched == [], "a sealed key is used before any secret is fetched"
    assert run({"transport": {"secret_id": "s-1"}}) == "from-secret"
    assert fetched == [("s-1", "srv-1", "https://x.example/mcp")]
    assert run({"transport": {"type": "http"}}) is None


def test_a_server_tool_step_sends_one_tools_call(monkeypatch):
    sent = []

    async def call(server_id, method, params=None):
        sent.append((server_id, method, params))
        return '{"result": {}}'
    monkeypatch.setattr(server, "call_mcp_server", call)
    asyncio.run(server.use_server_tool("srv-1", "echo", {"text": "hi"}))
    asyncio.run(server.use_server_tool("srv-1", "ping"))
    assert sent == [("srv-1", "tools/call", {"name": "echo", "arguments": {"text": "hi"}}),
                    ("srv-1", "tools/call", {"name": "ping", "arguments": {}})]


def test_a_server_tool_step_runs_through_op_mcp_call(monkeypatch):
    """The step's call goes through the `op.mcp.call` handler, and its answer is the server's."""
    from agience_chorus.iris.comms import mcp_tekton
    made = []
    real = mcp_tekton.mcp_handler

    def spy(call_tool=None, **kw):
        made.append(kw.get("server_id"))
        return real(call_tool, **kw)
    monkeypatch.setattr(mcp_tekton, "mcp_handler", spy)

    async def call(server_id, method, params=None):
        return '{"result": {"content": [{"type": "text", "text": "hi"}], "isError": false}}'
    monkeypatch.setattr(server, "call_mcp_server", call)
    out = asyncio.run(server.use_server_tool("srv-1", "echo", {"text": "hi"}))
    assert made == ["srv-1"]
    assert json.loads(out)["result"]["content"][0]["text"] == "hi"


def test_a_refused_server_tool_answers_the_refusal(monkeypatch):
    async def call(server_id, method, params=None):
        return '{"error": "you may read this MCP server but not run it (invoke)", "status": 403}'
    monkeypatch.setattr(server, "call_mcp_server", call)
    out = json.loads(asyncio.run(server.use_server_tool("srv-1", "echo")))
    assert out["status"] == 403


def test_no_server_named_calls_nothing(monkeypatch):
    async def call(*a, **kw):
        raise AssertionError("nothing is called")
    monkeypatch.setattr(server, "call_mcp_server", call)
    out = json.loads(asyncio.run(server.use_server_tool("", "echo")))
    assert out["status"] == 400 and "no external MCP organon" in out["error"]
