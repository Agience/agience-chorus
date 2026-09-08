"""Sage as a provider of `op.retrieve` over the ground-plane reach — a cross-persona reach.

Sage owns `op.retrieve` (its sole capability). Today lumen/ember call it over HTTP
(`sage.retrieval.retrieve` is a thin client to mantle FTS). This module is the signal-native face of
that same capability: sage builds its own `Reactor` over the shared ground plane and
`.serve("op.retrieve", handler)`, so an Apache runner (ember) can reach it by placing a need on the
plane — no import of sage, no carried return address, evidence returns through the ground correlated
by provenance (see `prism/reach.py`).

The provider is wired with the plane adapters `mantle.db.plane.LatticeKeyring`/
`LatticeLightcone`, so sage's entitlement to open a need addressed to `op.retrieve` is the same grant
light-cone that keys its content at rest, and the ground key is the same fleet `collection_key`
derivation the runner derives — the circuit completes because both sides derive identical keys from
the shared root, gated by their real light-cones. The adapters live in mantle, which both the runner
and the personas already depend on; their only imports are `mantle.db.access` and
`…content_cache`.

`store_retrieve` backs the reach with sage's real `content_search` BM25 tekton over the lattice
store, projected into `op.retrieve`'s shape. `local_retrieve` is the loopback fallback: a minimal
real keyed lookup (token-overlap over an in-memory doc set) in the same authoritative shape —
`[{id, title, content, score}]`, matching `sage.retrieval.retrieve` — for callers with no corpus
store to hand. Cross-process carrier wiring (a real WebRTC/QUIC/RF fabric plus a durable ground
carrier) is a separate gated deploy step — this module stays loopback/same-process.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from prism.reach import GROUND, Reactor

# `mantle.db.plane.LatticeLightcone`/`LatticeKeyring` are imported lazily inside
# `serve_retrieve`, not at module level: the adapters reach `mantle.db.access` lazily
# themselves, so importing sage must not drag the lattice package onto the path for callers that
# never stand up a provider. Keeping it lazy preserves that.

RETRIEVE_CAP = "op.retrieve"

__all__ = ["RETRIEVE_CAP", "local_retrieve", "store_retrieve", "retrieve_handler",
           "serve_retrieve", "serve_retrieve_if_configured"]


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def local_retrieve(query: str, docs: List[Dict[str, Any]], k: int = 6) -> List[Dict[str, Any]]:
    """A minimal real retrieval over an in-memory doc set, in sage's `op.retrieve` shape.

    Scores each doc by normalized query-token overlap (matched query tokens / distinct doc tokens),
    keeps the non-zero hits, and returns the top-`k` as `[{id, title, content, score}]` — the same
    evidence contract `sage.retrieval.retrieve` returns over HTTP. Deterministic and query-dependent
    (a real ranker, not a canned stub): different queries yield different rankings. This is the
    loopback fallback; `store_retrieve` is the real corpus search behind the same signature.
    """
    q = set(_tokens(query))
    hits: List[Dict[str, Any]] = []
    for d in docs:
        toks = _tokens("%s %s" % (d.get("title", ""), d.get("content", "")))
        if not toks:
            continue
        overlap = sum(1 for t in toks if t in q)
        if overlap == 0:
            continue
        score = round(overlap / len(set(toks)), 6)          # normalized: dense match > diffuse match
        hits.append({"id": d.get("id", ""), "title": d.get("title", ""),
                     "content": d.get("content", ""), "score": score})
    hits.sort(key=lambda h: (-h["score"], h["id"]))         # score desc, id for a stable tie-break
    return hits[:k]


def store_retrieve(corpus: Any, query: str, k: int = 6) -> List[Dict[str, Any]]:
    """The real corpus search behind `op.retrieve` — sage's moved `content_search` BM25 over the lattice
    store, projected into op.retrieve's `[{id,title,content,score}]` shape. `corpus` is an ember
    LocalStore bundle (`.artifacts.db` + `.get_artifact`, `.content*` for text). This is the capability
    `local_retrieve` was a stand-in for: the full retrieval tekton now backs the reach in-process.

    `content_search.search` returns `(id, content_type, bm25)` best-first (bm25 is negative, most-negative
    best); each hit's title/content is resolved from the store and the score is negated so `higher = better`
    (matching `local_retrieve`'s convention). Empty/blank query → no hits (fail-soft)."""
    if not (query or "").strip():
        return []
    try:                                             # robust: cross-persona host vs in-persona process
        from agience_chorus.sage import content_search as _cs       # (chorus/src on path) — the moved retrieval tekton
    except ImportError:
        import agience_chorus.sage.content_search as _cs                 # (sage/ on path)
    from mantle.shard.content import resolve_text           # ember grounding (persona→ember allowed)
    # Imported AFTER `content_search`, which is what binds the ontology into it. Importing the
    # ranking first would work too — `bind` is not import-order sensitive — but reading it in this
    # order says which module fills the seam the next line depends on.
    from mantle.search import ranking as _ranking

    # ── the ranked path, not the teleport ────────────────────────────────────────────────────────
    # `search` is BM25 alone, and BM25 alone does not answer these questions: measured over 18
    # natural questions on the live corpus it put the target at rank 1 **zero** times, and 13 times
    # the answer was not in its top 200 at all. Reach re-ranks what it proposes and injects the
    # need's own fired position regardless of pool depth, which takes the same 18 to 17/18.
    #
    # This is the surface `op.retrieve` publishes and the MCP bridge dispatches, so a caller that
    # asks this capability a question gets the measured path — the same one `answer()` uses — rather
    # than the lexical teleport that feeds it.
    #
    # `k` becomes a CEILING rather than the answer size. How many results a question has is
    # `_relevance_cut`'s to derive (the instrument's `k_signal` over the candidates' own
    # coordinates); a caller that wants fewer still gets fewer, and one that wants more does not get
    # padding it did not earn.
    pool = _cs.search(corpus, query, k=_cs._POOL) or []
    ranked, _account, _reached = _cs._reach_rank(pool, query, corpus)
    # One call, because the frame and the cut are one answer: `cut_for` reads the ranking's own
    # synset coordinates, builds the frame the adaptive instrument needs, and falls back to `_knee`
    # when there is none. Assembling that here — as this did — is how mantle's recall came to ask
    # for the cut without the frame and get the thin tier without noticing.
    cut = _ranking.cut_for(ranked, query=query, store=corpus)
    hits: List[Dict[str, Any]] = []
    for aid, _ct, score in ranked[:min(cut, k) if k else cut]:
        art = corpus.artifacts.get_artifact(aid)
        if not art:
            continue
        try:
            content = resolve_text(corpus, art)
        except Exception:
            content = art.get("content") or ""
        hits.append({"id": aid, "title": str(art.get("title") or ""),
                     "content": content or "", "score": round(-float(score), 6)})
    return hits


def retrieve_handler(docs: Optional[List[Dict[str, Any]]] = None, *, corpus: Any = None,
                     k: int = 6) -> Callable[[Any], List[Dict[str, Any]]]:
    """Build the injected `need -> evidence` handler for `op.retrieve`. The need is `{query, k?}`; the
    evidence is sage's retrieval shape. When `corpus` (a real store bundle) is given the handler is the
    moved `content_search` BM25 tekton (the full move); otherwise it falls back to the in-memory
    `local_retrieve` over `docs` (the loopback proof shape). Missing/empty query → no hits (fail-soft,
    like the HTTP path). This is the one seam the full content_search move swapped behind."""
    def handler(need: Any):
        need = need or {}
        # ── frame-native (§A.2): the need's payload is a signal, not just a query string ──────────────
        # If it carries a (T,F) beam frame, absorb this tekton's coupled band (its offer's subspace) and
        # return the residual to propagate onward — the absorb-and-propagate-the-remaining mechanism, live at
        # the provider. Additive: a query-only need is unchanged (returns the hits list as before).
        from prism import frames as _frames
        try:                                                  # this tekton's coupling = op.retrieve's offer span
            # `tekton_basis_for` is a measurement the host performs (offer coords → subspace), reached
            # through the declared `match` seam via `_host_seams`, rather than importing ember directly
            # (the last `chorus → ember` edge §2 forbids). `HostSeamUnfilled` is an `ImportError`, so a
            # host that binds nothing lands in the same `except` on the same input and `_basis` stays
            # None: there is nothing more specific to report.
            from agience_chorus._host_seams import resolve as _seam
            _basis = (_seam("match").tekton_basis_for(corpus, RETRIEVE_CAP)
                      if corpus is not None else None)
        except Exception:
            _basis = None
        _fr = _frames.absorb_need(need, basis=_basis)
        if _fr is not None:                                   # a signal frame → absorb the band, return residual
            _fr["hits"] = (store_retrieve(corpus, need.get("query", ""), k=int(need.get("k", k)))
                           if corpus is not None else [])
            return _fr
        # ── query path (unchanged) ───────────────────────────────────────────────────────────────────
        query = need.get("query", "")
        kk = int(need.get("k", k))
        if corpus is not None:
            return store_retrieve(corpus, query, k=kk)
        return local_retrieve(query, docs or [], k=kk)
    return handler


def serve_retrieve(store: Any, *, root_secret: bytes, fabric: Any,
                   docs: Optional[List[Dict[str, Any]]] = None, corpus: Any = None,
                   principal: str = "sage", k: int = 6, ground: str = GROUND,
                   reach: Optional[Callable[[Any, str], Any]] = None) -> Reactor:
    """Stand sage up as the provider of `op.retrieve` over `fabric`, grounded on `ground`.

    Builds `Reactor(principal, keyring=LatticeKeyring(root_secret), lightcone=LatticeLightcone(store), ...)`
    and serves the retrieval handler. The reactor's light-cone (sage's real grants, via `mantle.db.access`)
    must reach `op.retrieve` for sage to open needs addressed to it; the ground key both sides derive
    from `root_secret` is what carries the evidence back. `corpus` (a real store bundle) selects the moved
    `content_search` BM25 tekton; `docs` selects the in-memory `local_retrieve` (loopback proof). Returns
    the reactor (hold it to keep serving). `reach` injects a light-cone fn for tests without a grant store."""
    from mantle.db.plane import LatticeKeyring, LatticeLightcone   # lazy: only a wired host binds these
    rc = Reactor(principal, keyring=LatticeKeyring(root_secret),
                 lightcone=LatticeLightcone(store, reach=reach), fabric=fabric, ground=ground)
    rc.serve(RETRIEVE_CAP, retrieve_handler(docs, corpus=corpus, k=k))
    return rc


def _default_wiring() -> Optional[Dict[str, Any]]:
    """No carrier by default — the gated follow-up wires this. Returns None so the provider stays dark."""
    return None


def serve_retrieve_if_configured(
        *, wiring: Optional[Callable[[], Optional[Dict[str, Any]]]] = None) -> Optional[Reactor]:
    """Host-lifespan hook: stand sage up as the `op.retrieve` provider when — and only when — a live
    carrier is wired. Returns the serving Reactor, or None when nothing is configured (the default on a
    plain boot). Guarded end-to-end: any missing piece or error resolves to None, so sage boots whether
    or not the ground-plane carrier exists and `server_startup` never breaks.

    The carrier (a real WebRTC/QUIC/RF fabric + the fleet `root_secret` + the lattice `corpus` store, and
    the grant `store` for the light-cone) is a separate gated deploy step; `wiring` is the injection point
    — a callable returning `{store, root_secret, fabric, corpus?/docs?, principal?, ground?}`. Until it is
    provided, this is a no-op: the reach provider stays dark and the HTTP `op.retrieve` (`retrieval.py`)
    remains sage's live grounding path."""
    try:
        cfg = (wiring or _default_wiring)()
    except Exception:
        return None
    if not cfg or cfg.get("fabric") is None or cfg.get("root_secret") is None or cfg.get("store") is None:
        return None
    try:
        return serve_retrieve(cfg["store"], root_secret=cfg["root_secret"], fabric=cfg["fabric"],
                              docs=cfg.get("docs"), corpus=cfg.get("corpus"),
                              principal=cfg.get("principal", "sage"), ground=cfg.get("ground", GROUND))
    except Exception:
        return None
