"""Transport — the over-the-wire seam.

Ember is Apache-2.0 and must never *import* the AGPL platform services (Mantle, Lumen, Chorus).
It reaches them only over HTTP. The transport is injected so (a) the license boundary is
structural — the agent core has no dependency on any platform package — and (b) the agent is
unit-testable without a network (pass a fake transport).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass
class HttpResponse:
    status_code: int
    _json: Any = None
    text: str = ""

    def json(self) -> Any:
        return self._json

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: Optional[dict] = None,
                json: Optional[dict] = None, params: Optional[dict] = None,
                timeout: float = 30.0) -> HttpResponse: ...


class HttpxTransport:
    """Default real transport. httpx is permissively licensed — no AGPL import crosses here."""

    def request(self, method: str, url: str, *, headers=None, json=None, params=None,
                timeout: float = 30.0) -> HttpResponse:
        import httpx

        r = httpx.request(method, url, headers=headers, json=json, params=params, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = None
        return HttpResponse(status_code=r.status_code, _json=body, text=r.text)


__all__ = ["HttpResponse", "Transport", "HttpxTransport"]
