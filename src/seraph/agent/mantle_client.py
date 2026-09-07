"""MantleClient — read/write artifacts in Mantle over the wire, as an identity (bearer token).

This is the agent's access to *information* (the artifact corpus). It speaks Mantle's HTTP API and
imports no Mantle code — the Apache/AGPL boundary holds. All calls carry the agent's token, so
Mantle enforces the agent's grants: the agent can only touch what its identity is allowed to.
"""
from __future__ import annotations

import json as _json
from typing import List, Optional

from .transport import HttpxTransport, Transport


class MantleClient:
    def __init__(self, base_url: str, token: str, transport: Optional[Transport] = None) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.t = transport or HttpxTransport()

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def get_artifact(self, artifact_id: str) -> Optional[dict]:
        r = self.t.request("GET", f"{self.base}/artifacts/{artifact_id}", headers=self._h())
        return r.json() if r.ok else None

    def children(self, container_id: str, content_type: Optional[str] = None) -> List[dict]:
        """List a container/collection's child artifacts (optionally filtered by content_type)."""
        params = {"content_type": content_type} if content_type else None
        r = self.t.request("GET", f"{self.base}/artifacts/{container_id}/children",
                           headers=self._h(), params=params)
        return r.json() if r.ok else []

    def search(self, query: str, content_types: Optional[list] = None, size: int = 10) -> List[dict]:
        # WAS `/artifacts/search`, DELETED BY MANTLE — the 404 made `r.ok` false and this
        # returned [] every time, so every search came back empty and said nothing.
        #
        # `use_hybrid` and `content_types` dropped: both retired, and recall ignores
        # unknown fields, so they were inert. `content_types` mattered more
        # than the other — a caller passing it believed it was NARROWING and was not.
        # Narrowing by type is `content_type:<value>` inside `query_text`.
        body: dict = {"query_text": query, "size": size}
        if content_types:
            body["query_text"] = "%s %s" % (
                " ".join("content_type:%s" % c for c in content_types), query)
        r = self.t.request("POST", f"{self.base}/artifacts/recall", headers=self._h(), json=body)
        return (r.json() or {}).get("hits", []) if r.ok else []

    def create_artifact(self, *, container_id: str, content: str, content_type: str,
                        context: dict) -> Optional[dict]:
        """Create a new artifact in a container. Immutability lives here: consolidation/cleanup
        produces new artifacts (never edits-in-place); `context` carries the operator provenance
        (which transform/tool made it) and a derived_from edge to the sources."""
        body = {"container_id": container_id, "content": content, "content_type": content_type,
                "context": _json.dumps(context)}
        r = self.t.request("POST", f"{self.base}/artifacts", headers=self._h(), json=body)
        return r.json() if r.ok else None

    def archive_artifact(self, artifact_id: str) -> bool:
        """Archive (soft-remove): superseded/duplicate versions are archived, never destroyed —
        provenance is preserved, only head/committed answers surface."""
        r = self.t.request("PATCH", f"{self.base}/artifacts/{artifact_id}", headers=self._h(),
                           json={"state": "archived"})
        return r.ok


__all__ = ["MantleClient"]
