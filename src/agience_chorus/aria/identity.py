"""`op.identity.verify` — the organon through which chorus reaches origin for identity decisions.

Chorus never imports origin. `src/tests/test_chorus_does_not_import_origin.py` walks the AST and
rejects any import of origin from chorus, at any scope, including a lazy import inside a function.
Origin is a peer, reached over the wire, which is what lets each deployment point at its own
authority (`ORIGIN_URI` at a node's own ground plane, or a shared one). This module holds no origin
import, so the invariant the test enforces holds.

The module follows one division of labor: the surface is flow, the decision is authority. Rendering
a challenge, collecting a credential, and landing a redirect are conduit work — a facet's job, and
routes like `/auth/providers` and `/setup/status` answer any caller. Verifying a credential,
resolving claims, and minting anything is origin's job; `/auth/nonce`, which issues a challenge,
answers 401 because issuing state is something only the issuer may hold. This organon is how a
facet asks origin to make that decision. It never mints a credential itself — it carries a bearer to
the authority and returns what the authority says, or a refusal.

Transport is injected. The default reaches the network with `httpx` (aria's existing idiom), but a
caller may pass any `(method, url, headers, json) -> (status, payload)` callable. This makes the
module testable with no socket, and makes the network reach a declared, swappable seam rather than a
hidden one.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Tuple

#: The capability name. A need addressed here asks "who is this?" — never "give me a token".
IDENTITY_VERIFY_CAP = "op.identity.verify"

#: The authority's own claim-resolution route. `/auth/userinfo` reads claims from a bearer, which is
#: the authority reading its own grant — the decision a facet may not make for itself.
_USERINFO = "/auth/userinfo"

Transport = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]]], Tuple[int, Any]]


def origin_uri(fallback: str = "") -> str:
    """Where the authority lives. Env-driven so a node can point at its own ground plane."""
    return os.getenv("ORIGIN_URI") or fallback or "http://127.0.0.1:8080"


def _httpx_transport(timeout: float = 8.0) -> Transport:
    """The default reach. `httpx` is imported lazily so this module stays importable — and testable —
    on a host that has no HTTP stack at all."""
    def send(method: str, url: str, headers: Dict[str, str],
             payload: Optional[Dict[str, Any]]) -> Tuple[int, Any]:
        import httpx
        with httpx.Client(timeout=timeout) as c:
            r = c.request(method, url, headers=headers, json=payload)
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, None
    return send


def verify_handler(*, origin: Optional[str] = None,
                   transport: Optional[Transport] = None) -> Callable[[Any], Dict[str, Any]]:
    """Organon handler. The need is `{"token": "<bearer>"}`; the answer is what the authority says.

        {"verified": True,  "principal": {...}}          the authority resolved it
        {"verified": False, "reason": "...", "status": n} it did not

    The handler never mints a credential: there is no path here that returns one. A facet that could
    mint would be a second issuer, and deriving authority server-side rather than taking the
    caller's word is the property `[[provenance-needs-authority]]` names.

    The handler fails closed. A missing token, an unreachable authority, or an unparseable answer
    all return `verified: False` with the reason stated, rather than assume an answer it could not
    obtain.
    """
    base = (origin or origin_uri()).rstrip("/")
    send = transport or _httpx_transport()

    def handler(need: Any) -> Dict[str, Any]:
        need = need or {}
        token = str(need.get("token") or "").strip()
        if not token:
            return {"verified": False, "reason": "no token in the need", "status": 0}
        try:
            status, payload = send("GET", base + _USERINFO,
                                   {"Authorization": "Bearer " + token}, None)
        except Exception as exc:                       # the authority is unreachable
            return {"verified": False, "reason": "authority unreachable: %s" % type(exc).__name__,
                    "status": 0}
        if status == 200 and isinstance(payload, dict):
            return {"verified": True, "principal": payload, "status": status}
        return {"verified": False,
                "reason": "authority refused" if status in (401, 403) else "unexpected answer",
                "status": status}

    return handler


#: Registered like every other capability — an offer, so a need can find it.
_IDENTITY_OPS = [
    (IDENTITY_VERIFY_CAP,
     "ORGANON: asks the AUTHORITY who a bearer belongs to, over the wire (origin is a peer, never "
     "imported). Returns the principal or a refusal with the status. Never mints a credential — the "
     "surface is flow, the decision is authority"),
]


def register_identity_operators(store, *, author: str = "aria-identity") -> int:
    """Register aria's identity organon. Mirrors the impl register_* pattern."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _IDENTITY_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": "aria identity organon %s: %s" % (name, offer),
            "created_by": author}))
    return len(_IDENTITY_OPS)
