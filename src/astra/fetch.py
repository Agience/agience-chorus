# Operator code lives in chorus. Distributed to hosts as a content-addressed source bundle
# (definitions/build_bundles.py); ember executes it via ember/runner.py, sha-verified before
# exec. There are no code mirrors.
"""GET-only external resource operators — the read-only ingest primitive.

No operator may make an outbound write web call: fetching a research paper or a doc page is
fine, registering or POSTing to a site is not. This module enforces that structurally, not by
convention:
  • the HTTP method is hard-locked to GET — there is no code path that sends a body, and no
    param can change the verb;
  • only http/https schemes are allowed (no file://, ftp://, gopher:// SSRF vectors);
  • loopback / RFC-1918 / link-local / reserved hosts are blocked (so a fetched URL cannot
    trick ember into reaching an internal service);
  • responses are size-capped and time-bounded.

So `op.fetch.get` is the dual of a describe-operator on the ingest side (a coalgebra: it
unfolds an external URL into local text) while remaining incapable of mutating anything remote.
stdlib urllib only — Apache-clean, no third-party HTTP client.
"""
from __future__ import annotations

import ipaddress
import urllib.error
import urllib.request
from typing import Dict, Optional
from urllib.parse import urlparse

from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type

_MAX_BYTES = 5_000_000          # 5 MB cap — a paper/doc, not a dataset
_TIMEOUT = 20
_ALLOWED_SCHEMES = {"http", "https"}
_UA = "ember-fetch/1.0 (read-only)"


def _blocked_host(host: str) -> bool:
    """Loopback / private / link-local / reserved targets are blocked (SSRF guard). Hostnames
    that don't parse as IPs are allowed through (no DNS lookup here — this does not resolve to
    decide)."""
    h = (host or "").lower()
    if h in {"localhost", ""} or h.endswith(".local") or h.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Re-applies the scheme and host guards on every redirect hop, not just the caller's URL.

    A permitted external host can redirect to an internal or loopback address — the cloud
    metadata endpoint (`169.254.169.254`) being the worst case, since it hands out credentials —
    or to a scheme outside `_ALLOWED_SCHEMES`: `HTTPRedirectHandler.redirect_request` itself
    permits http, https, and ftp. `urllib.request.urlopen`'s default opener follows 3xx
    automatically, so without re-checking on every hop the guards would only ever see the URL the
    caller passed, never the one a redirect actually leads to.

    Raises `URLError` on a blocked hop; `_get` already catches it and renders a clean
    `{"ok": False, "reason": ...}`, so a blocked redirect ends the same way as any other blocked
    fetch, not a crash."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlparse(newurl)
        if p.scheme not in _ALLOWED_SCHEMES:
            raise urllib.error.URLError(
                "refusing redirect to scheme '%s' (http/https only): %s" % (p.scheme, newurl))
        if _blocked_host(p.hostname or ""):
            raise urllib.error.URLError(
                "refusing redirect to internal/loopback host '%s'" % (p.hostname,))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Built once. Every fetch goes through this opener — never the module-level urlopen, which
# carries the unguarded default HTTPRedirectHandler.
_OPENER = urllib.request.build_opener(_GuardedRedirect)


def _get(a: Dict) -> Dict:
    """Read-only HTTP GET of `a['url']`. Returns the decoded text (utf-8, size-capped) plus
    status/content-type. Never writes, never POSTs — the method is fixed to GET."""
    url = a["url"]
    p = urlparse(url)
    if p.scheme not in _ALLOWED_SCHEMES:
        return {"ok": False, "reason": f"scheme '{p.scheme}' not allowed (http/https only)", "url": url}
    if _blocked_host(p.hostname or ""):
        return {"ok": False, "reason": f"refusing internal/loopback host '{p.hostname}'", "url": url}
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": _UA})  # GET, hard-locked
    try:
        # _OPENER, not urlopen: the guards must re-run on every redirect hop, not just this URL.
        with _OPENER.open(req, timeout=_TIMEOUT) as r:   # noqa: S310 (scheme+host guarded per hop)
            raw = r.read(_MAX_BYTES + 1)
            ct = r.headers.get("content-type", "")
            status = getattr(r, "status", 200)
    except (urllib.error.URLError, ValueError, OSError) as e:
        return {"ok": False, "reason": str(e), "url": url}
    truncated = len(raw) > _MAX_BYTES
    body = raw[:_MAX_BYTES]
    return {"ok": True, "url": url, "status": status, "content_type": ct,
            "bytes": len(body), "truncated": truncated, "text": body.decode("utf-8", "ignore")}


_FETCH_OPS = [
    ("op.fetch.get", "fetches an external http(s) resource READ-ONLY (GET only) — a paper, a doc page"),
]
_HANDLERS = {"op.fetch.get": _get}


def register_fetch_operators(store, *, author: str = "ember-local") -> int:
    from crystal import evolution
    for name, offer in _FETCH_OPS:
        evolution.put_operator(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": f"fetch operator {name}: {offer}  [read-only / GET-only]",
            "created_by": author})
    return len(_FETCH_OPS)


def invoke(name: str, arguments: Optional[Dict] = None) -> Dict:
    h = _HANDLERS.get(name)
    if h is None:
        raise KeyError(f"no fetch operator '{name}'")
    return h(arguments or {})
