# Operator code lives in chorus. Distributed to hosts as a content-addressed source bundle
# (definitions/build_bundles.py); ember executes it via ember/runner.py, sha-verified before
# exec. There are no code mirrors.
"""GET-only external resource operators — the read-only ingest primitive.

No operator may make an outbound write web call: fetching a research paper or a doc page is
fine, registering or POSTing to a site is not. This module enforces that structurally, not by
convention, through the shared egress guard (`agience_chorus/_egress.py`):
  • the HTTP method is hard-locked to GET — there is no code path that sends a body, and no
    param can change the verb;
  • only http/https schemes are allowed (no file://, ftp://, gopher:// SSRF vectors);
  • the host is resolved and refused unless every address is public unicast — loopback,
    RFC-1918, link-local, CGNAT, multicast, reserved and IPv4-mapped forms are blocked, and a
    host written as a number in any form is refused outright; the connection goes to the
    address that was checked, so a fetched URL cannot trick ember into reaching an internal
    service;
  • every redirect hop is checked the same way, and the hop count is capped;
  • responses are size-capped (reading stops at the cap) and share one deadline.

So `op.fetch.get` is the dual of a describe-operator on the ingest side (a coalgebra: it
unfolds an external URL into local text) while remaining incapable of mutating anything remote.
stdlib only — Apache-clean, no third-party HTTP client.
"""
from __future__ import annotations

from typing import Dict, Optional

from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type

# Loaded two ways: as a bundle module, where the guard travels as the sibling `_egress` and is
# sha-verified with this file, and as a package module, where it is `agience_chorus._egress`.
try:
    from . import _egress
except ImportError:
    from agience_chorus import _egress

_MAX_BYTES = 5_000_000          # 5 MB cap — a paper/doc, not a dataset
_TIMEOUT = 20
_UA = "ember-fetch/1.0 (read-only)"


def _blocked_host(host: str) -> bool:
    """True when the host is refused by its spelling alone: a number in any form, `localhost`,
    or a private suffix. Names are resolved and checked by `_egress.fetch` itself."""
    return _egress.host_refused(host) is not None


def _get(a: Dict) -> Dict:
    """Read-only HTTP GET of `a['url']`. Returns the decoded text (utf-8, size-capped) plus
    status/content-type. Never writes, never POSTs — `_egress.fetch` has no other method."""
    url = a["url"]
    try:
        r = _egress.fetch(url, timeout=_TIMEOUT, max_bytes=_MAX_BYTES,
                          headers={"User-Agent": _UA})
    except _egress.EgressError as e:
        return {"ok": False, "reason": str(e), "url": url}
    return {"ok": True, "url": url, "status": r.status, "content_type": r.content_type,
            "bytes": len(r.body), "truncated": r.truncated,
            "text": r.body.decode("utf-8", "ignore")}


_FETCH_OPS = [
    ("op.fetch.get", "fetches an external http(s) resource READ-ONLY (GET only) — a paper, a doc page"),
]
_HANDLERS = {"op.fetch.get": _get}


def register_fetch_operators(store, *, author: str = "ember-local") -> int:
    from crystal import evolution
    for name, offer in _FETCH_OPS:
        evolution.put_operator(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "live",
            "context": offer, "content": f"fetch operator {name}: {offer}  [read-only / GET-only]",
            "created_by": author})
    return len(_FETCH_OPS)


def invoke(name: str, arguments: Optional[Dict] = None) -> Dict:
    h = _HANDLERS.get(name)
    if h is None:
        raise KeyError(f"no fetch operator '{name}'")
    return h(arguments or {})
