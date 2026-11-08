"""Seraph reads no credential on a grant key (review 21, F1).

A grant key is Mantle's own bearer secret: a Mantle that is taken over can present one to Seraph
and answer every read it makes on it. A credential Seraph acts with comes only from a read on a
delegation Origin issued; on a grant key, Seraph reads none and Mantle is not asked.
"""
from __future__ import annotations

import asyncio

from agience_chorus import _persona

_server = _persona.load("server", __file__)


def test_a_grant_key_reads_no_credential(monkeypatch):
    asked = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, **k):
            asked.append(url)
            raise AssertionError("Mantle was asked for a credential on a grant key")

    monkeypatch.setattr(_server.httpx, "AsyncClient", _Client)
    tok = _server._auth.request_user_token.set("agk_planted")
    try:
        got = asyncio.run(_server._fetch_and_decrypt_secret(secret_id="cred-1"))
    finally:
        _server._auth.request_user_token.reset(tok)
    assert got is None and asked == []
