"""Review 22, F1: the server delegation a persona sends Mantle is never taken back at the persona.

Lumen exchanges a person's narrowed delegation for its own server delegation D, signing as itself
(`act.iss` `lumen`), and sends D to Mantle on every call. A Mantle that is taken over could call
Lumen with D and have every tool, secret use included, run for the person on its choice. So Origin
addresses D to Mantle (`aud` `mantle`, `act.sub` the persona), and the persona refuses any inbound
delegation whose `act.iss` is itself. Tokens come from Origin's own issuers (`origin_issuer`).
"""
from __future__ import annotations

import asyncio

from jose import jwt as jose_jwt

from prism.trust.server_auth import ServerAuth


async def _no_exchange(*_a):
    raise AssertionError("no exchange is made for an inbound delegation the persona itself asked for")


def _inbound(auth, bearer):
    seen = {}

    async def app(scope, receive, send):
        seen["stored"] = auth.request_user_token.get()

    async def send(message):
        seen.setdefault("sent", []).append(message)

    mw = auth.make_middleware_class()(app)
    asyncio.run(mw({"type": "http", "method": "POST", "path": "/mcp",
                    "headers": [(b"authorization", f"Bearer {bearer}".encode())]}, None, send))
    return seen


def test_the_delegation_lumen_sends_mantle_is_addressed_to_mantle(origin_issuer):
    claims = jose_jwt.get_unverified_claims(origin_issuer.delegation("lumen", "person-1"))
    assert claims["aud"] == "mantle"
    assert claims["act"] == {"sub": "agience-server-lumen", "iss": "lumen"}


def test_the_delegation_lumen_sends_mantle_is_refused_inbound_at_lumen(origin_issuer):
    d = origin_issuer.delegation("lumen", "person-1")
    auth = ServerAuth("agience-server-lumen", "http://mantle.test", token_exchange=_no_exchange)
    seen = _inbound(auth, d)
    assert "stored" not in seen, "a replayed delegation ran a tool"
    assert seen["sent"][0]["status"] == 401


def test_a_delegation_lumen_asked_for_is_refused_even_addressed_to_lumen(origin_issuer):  # noqa: ARG001 (Origin's key)
    """Whatever it is addressed to, a delegation whose actor Lumen proved by its own key is one
    Lumen made to send on, never a caller's."""
    from origin.services.auth_service import issue_system_delegation_token
    d = issue_system_delegation_token("sys-1", actor="agience-server-lumen", signer="lumen",
                                      scope="platform.describe", audience="agience-server-lumen")
    auth = ServerAuth("agience-server-lumen", "http://mantle.test", token_exchange=_no_exchange)
    assert auth.verify_origin_delegation(d) is None
