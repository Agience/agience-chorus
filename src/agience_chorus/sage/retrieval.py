# Operator code lives in chorus/crystal. This is sage's op.retrieve (grounding) operator
# implementation; lumen, the wisdom/inference tekton, is its primary caller (hence the
# LUMEN_-prefixed env vars below). It consumes mantle search over the wire; the serialization
# boundary on the mantle side is the `/artifacts/recall` response, whose hits mantle builds from
# `mantle.search.types.SearchHit` over its encrypted SSE index. Nothing here reads a lattice
# directly, which is why this path keeps mantle's property and `sage/content_search.py` — the
# in-process BM25 arm over `corpus_fts` — is a different arm, not a second client. stdlib + lazy
# httpx only.
"""Retrieval — op.retrieve, grounding the lumen tekton's answers in the Agience corpus.

A bare model answers from its parametric memory, which for a small local model is shallow and
repetitive. The Agience thesis is that knowledge lives in artifacts: before generating, we
search Mantle for artifacts relevant to the user's question and hand them to the model as
evidence to reason over — so answers are grounded in specific, current source material instead
of generic priors, and the model can say "I don't have that" instead of confabulating.

Retrieval is an enhancement, not a dependency: it is fail-soft. If Mantle search is unavailable
(503) or errors, we return no evidence and the model answers as before — chat never breaks on a
retrieval failure. Coverage grows with the corpus (docs + code + the mint-back loop); the wiring
here is what lets that growth show up in answers.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

log = logging.getLogger("lumen.retrieval")

RETRIEVAL_ON = os.getenv("LUMEN_RETRIEVAL", "1") != "0"
RETRIEVAL_K = int(os.getenv("LUMEN_RETRIEVAL_K", "6"))
# The finite-context budget. The model is the observer; its context window is the hard ceiling,
# so grounding gets only a bounded slice of it (the rest stays for the query + the answer). We
# rank by relevance and fill until this budget is spent — a working set, never the whole corpus.
# ~4 chars/token, so 7000 chars ≈ 1750 tokens of grounding out of an 8192-token window.
GROUNDING_CHAR_BUDGET = int(os.getenv("LUMEN_GROUNDING_CHARS", "7000"))
PER_DOC_CHAR_CAP = int(os.getenv("LUMEN_GROUNDING_PER_DOC_CHARS", "1400"))


def _bearer(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    t = token.strip()
    return t if t.lower().startswith("bearer ") else f"Bearer {t}"


def _recall(client, mantle_url: str, token: str, body: dict):
    r = client.post(f"{mantle_url.rstrip('/')}/artifacts/recall",
                    headers={"Authorization": _bearer(token), "Content-Type": "application/json"},
                    json=body, timeout=12)
    r.raise_for_status()
    return r.json()


def _searched(client, query: str, token: str, mantle_url: str, search_id: str) -> List[dict]:
    """The Search `search_id` run for `query`: Mantle reads what the caller may read and
    `crystal.search` orders it by the Search's rank keys."""
    from crystal import search
    r = client.get(f"{mantle_url.rstrip('/')}/artifacts/{search_id}",
                   headers={"Authorization": _bearer(token)}, timeout=12)
    r.raise_for_status()
    artifact = r.json()
    s = search.settings(artifact, {"query_text": query})
    hits: list = []
    total = 0
    while len(hits) < search.WINDOW:
        page = _recall(client, mantle_url, token,
                       search.recall_body(query, s["scope"], len(hits))) or {}
        batch = page.get("hits") or []
        total = int(page.get("total") or 0)
        hits.extend(batch)
        if not batch or len(hits) >= total:
            break
    return search.answer(artifact, s, hits, total, token)["hits"]


def retrieve(query: str, auth_token: Optional[str], mantle_url: str,
             k: int = RETRIEVAL_K, search_id: Optional[str] = None) -> List[dict]:
    """Return relevant artifacts for `query` as evidence dicts {title, content, score}.

    `search_id` names a Search artifact: its rank, size and scope decide the hits, run as Crystal
    runs it (`crystal.search`). Without one, up to `k` hits come back in recall's own order.

    Uses the caller's own token, so retrieval respects the user's grants — Lumen only ever grounds
    on knowledge the user is authorized to see. Fail-soft: any error (incl. 503 when encrypted
    search isn't provisioned) yields an empty list; a Search the caller cannot run falls back to
    the plain recall.
    """
    if not RETRIEVAL_ON or not query or not auth_token:
        return []
    import httpx

    hits: Optional[list] = None
    try:
        with httpx.Client() as client:
            if search_id:
                try:
                    hits = _searched(client, query, auth_token, mantle_url, search_id)
                except Exception as exc:
                    log.info("retrieval: search %s failed (%s); plain recall", search_id,
                             type(exc).__name__)
            if hits is None:
                # No `state`: recall's default is the live set, which is what grounding reads.
                hits = _recall(client, mantle_url, auth_token,
                               {"query_text": query, "size": k, "highlight": True}).get("hits") or []
    except Exception as exc:  # pragma: no cover - network/search failures degrade to no-grounding
        log.info("retrieval: search failed (%s); grounding skipped", type(exc).__name__)
        return []

    out: List[dict] = []
    for h in hits:
        content = (h.get("content") or "").strip()
        title = (h.get("title") or h.get("description") or "").strip()
        if not content and not title:
            continue
        out.append({"id": h.get("version_id") or h.get("id") or "",
                    "title": title, "content": content, "score": h.get("score", 0.0)})
    return out


# `retrieve()` above is the deterministic evidence lookup that op.retrieve serves; this module
# has no language-model consumer and no provider import.


# ── registration — the lumen tekton's op.retrieve ────────────────────────────
_RETRIEVAL_OPS = [
    ("op.retrieve", "grounds a query in the corpus: mantle FTS search under the caller's "
     "own grants, budgeted evidence assembly (top-k, per-doc + total char caps), "
     "fail-soft — retrieval is an enhancement, never a break"),
]


#: the capabilities each operator needs to run, by operator id.
_NEEDS = {
    "op.retrieve": ["store.read"],
}


def register_retrieval_operators(store, *, author: str = "ember-local") -> int:
    """Register the lumen-tekton retrieval operator(s). Mirrors the impl register_* pattern."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _RETRIEVAL_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "live",
            "context": offer, "offer": offer, "needs": list(_NEEDS[name]),
            "content": f"lumen tekton operator {name}: {offer}",
            "created_by": author}))
    return len(_RETRIEVAL_OPS)


__all__ = ["retrieve", "RETRIEVAL_ON", "register_retrieval_operators"]
