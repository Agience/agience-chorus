"""A persona's per-hop exchange at Origin (John, 2026-11-03, review 12).

A persona holds, for a person, only the delegation Origin narrowed to it (review 11, H3). When its
work needs another persona, it exchanges that delegation at Origin's token endpoint (RFC 8693,
`audience` = the next persona) for one narrowed to the next: the same person, five minutes, no
widening. It authenticates the exchange with its own key (an RFC 7523 client assertion). Origin lists
the hops it allows (Crystal to each persona, Lumen to Sage) and records each; this side asks only
for the hops in `HOPS`, and a refused one reaches nothing.

`KeepNarrowed` keeps the narrowed delegation the request arrived with (prism's middleware exchanges
it for the persona's server delegation and keeps only that), so a hop has its subject.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"
JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

#: The hops this side asks Origin for: from a persona to the personas its work reaches. Origin's
#: own list is the authority; this one only keeps a persona from asking for more.
HOPS = {"lumen": frozenset({"sage"})}

#: The delegation Origin narrowed to this persona that the current request arrived with, or "".
narrowed_token: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "agience_chorus_narrowed_token", default="")


class KeepNarrowed:
    """ASGI middleware: keep the request's bearer when it is Origin's delegation narrowed to this
    persona (`auth.verify_narrowed_delegation`), for a later hop. Nothing else is kept."""

    def __init__(self, app: Any, auth: Any) -> None:
        self._app = app
        self._auth = auth

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        raw = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
        tok = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
        keep = tok if tok and self._auth.verify_narrowed_delegation(tok) else ""
        held = narrowed_token.set(keep)
        try:
            await self._app(scope, receive, send)
        finally:
            narrowed_token.reset(held)


async def _post_token_exchange(origin_uri: str, form: dict) -> Optional[str]:
    """POST the exchange to Origin's token endpoint; the access token, or None (refused)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(f"{origin_uri.rstrip('/')}/auth/token", data=form)
    except Exception as exc:                                      # noqa: BLE001
        logger.warning("hop exchange to %s failed: %s", form.get("audience"), exc)
        return None
    if r.status_code != 200:
        logger.info("Origin refused the hop to %s (%s)", form.get("audience"), r.status_code)
        return None
    try:
        return str(r.json().get("access_token") or "") or None
    except ValueError:
        return None


async def exchange(auth: Any, origin_uri: str, to: str) -> Optional[str]:
    """The delegation narrowed to persona `to` for this request's person, from the one narrowed to
    this persona, or None (no such delegation here, a hop this persona does not ask for, or Origin
    refused)."""
    subject = narrowed_token.get()
    if not subject or to not in HOPS.get(getattr(auth, "persona", ""), frozenset()):
        return None
    return await _post_token_exchange(origin_uri, {
        "grant_type": TOKEN_EXCHANGE, "subject_token": subject,
        "subject_token_type": ACCESS_TOKEN, "audience": to,
        "client_id": auth.client_id, "client_assertion_type": JWT_BEARER,
        "client_assertion": auth.sign_exchange_jwt()})
