"""Review 12, John's decision 2: Lumen reaches Sage for a person by a per-hop exchange at Origin.

Lumen holds, for a person, only the delegation Origin narrowed to Lumen. To retrieve on Sage for that
person, Lumen exchanges that delegation at Origin's token endpoint (RFC 8693, `audience` = `sage`)
for one narrowed to Sage: the same person, five minutes, no widening. It authenticates the exchange
with its own key. Origin lists Lumen to Sage among the hops it allows and records each. Lumen asks
for no other hop, and a person's request still reaches no other persona; a grant key reaches as
before.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from agience_chorus import _hop

_spec = importlib.util.spec_from_file_location("chorus_lumen_server_hop",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


@pytest.fixture
def origin(monkeypatch):
    asked = []

    async def post(origin_uri, form):
        asked.append((origin_uri, form))
        return f"hop:{form['audience']}"

    monkeypatch.setattr(_hop, "_post_token_exchange", post)
    monkeypatch.setattr(L._auth, "sign_exchange_jwt", lambda: "lumen-assertion")
    return asked


@pytest.fixture
def narrowed_to_lumen():
    tok = _hop.narrowed_token.set("lumen-narrowed")
    try:
        yield
    finally:
        _hop.narrowed_token.reset(tok)


def test_lumen_hops_to_sage_on_its_own_narrowed_delegation(origin, narrowed_to_lumen):
    headers = asyncio.run(L._caller_headers_to("sage"))
    assert headers == {"Authorization": "Bearer hop:sage"}
    _uri, form = origin[0]
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert form["subject_token"] == "lumen-narrowed" and form["audience"] == "sage"
    assert form["client_id"] == L.LUMEN_CLIENT_ID
    assert form["client_assertion"] == "lumen-assertion"


def test_lumen_asks_for_no_other_hop(origin, narrowed_to_lumen):
    with pytest.raises(L.MissingDelegationError):
        asyncio.run(L._caller_headers_to("iris"))
    assert origin == []


def test_without_a_narrowed_delegation_there_is_no_hop(origin):
    with pytest.raises(L.MissingDelegationError):
        asyncio.run(L._caller_headers_to("sage"))
    assert origin == []


def test_a_grant_key_still_reaches_any_persona(origin):
    ctok = L._auth.request_caller_token.set("agc_key")
    try:
        assert asyncio.run(L._caller_headers_to("iris")) == {"Authorization": "Bearer agc_key"}
    finally:
        L._auth.request_caller_token.reset(ctok)
    assert origin == []


def test_the_middleware_keeps_only_a_delegation_narrowed_to_this_persona():
    seen = []

    async def inner(scope, receive, send):
        seen.append(_hop.narrowed_token.get())

    class Auth:
        def verify_narrowed_delegation(self, tok):
            return {"aud": "lumen"} if tok == "lumen-narrowed" else None

    app = _hop.KeepNarrowed(inner, Auth())
    for raw in ("lumen-narrowed", "a-person-token"):
        scope = {"type": "http", "headers": [(b"authorization", f"Bearer {raw}".encode())]}
        asyncio.run(app(scope, None, None))
    assert seen == ["lumen-narrowed", ""]
