"""A server artifact's credential is read in one place (`_server_auth`), so it can later move to its
own secret artifact (John, 2026-11-12). Now: the access key sealed on the server artifact, else a
referenced secret, else none."""
from __future__ import annotations

import asyncio

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
