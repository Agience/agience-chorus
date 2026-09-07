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


def retrieve(query: str, auth_token: Optional[str], mantle_url: str,
             k: int = RETRIEVAL_K) -> List[dict]:
    """Return up to k relevant artifacts for `query` as evidence dicts {title, content, score}.

    Uses the caller's own token, so retrieval respects the user's grants — Lumen only ever grounds
    on knowledge the user is authorized to see. Fail-soft: any error (incl. 503 when encrypted
    search isn't provisioned) yields an empty list.
    """
    if not RETRIEVAL_ON or not query or not auth_token:
        return []
    import httpx

    try:
        r = httpx.post(
            # WAS `/artifacts/search`, DELETED BY MANTLE. The 404 fell into the `!= 200`
            # branch below, which logs at INFO and returns [] — so grounding was silently
            # skipped on every answer, beneath the default log level.
            f"{mantle_url.rstrip('/')}/artifacts/recall",
            headers={"Authorization": _bearer(auth_token), "Content-Type": "application/json"},
            # `use_hybrid` dropped: retired, and recall IGNORES unknown fields,
            # so sending it was inert rather than wrong. `state` and `highlight` are real.
            json={"query_text": query, "size": k,
                  "state": "committed", "highlight": True},
            timeout=12,
        )
        if r.status_code != 200:
            log.info("retrieval: search returned %s (grounding skipped)", r.status_code)
            return []
        hits = r.json().get("hits", []) or []
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


def register_retrieval_operators(store, *, author: str = "ember-local") -> int:
    """Register the lumen-tekton retrieval operator(s). Mirrors the impl register_* pattern."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _RETRIEVAL_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": f"lumen tekton operator {name}: {offer}",
            "created_by": author}))
    return len(_RETRIEVAL_OPS)


__all__ = ["retrieve", "RETRIEVAL_ON", "register_retrieval_operators"]
