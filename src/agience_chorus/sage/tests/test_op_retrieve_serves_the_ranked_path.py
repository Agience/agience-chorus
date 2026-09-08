"""`op.retrieve` publishes the measured path, not the lexical teleport that feeds it.

## Why this needed a test

`store_retrieve` backs `op.retrieve` — the capability the MCP bridge dispatches, and the surface a
peer or an editor integration actually calls. It returned `content_search.search` directly: BM25
alone, which over 18 natural questions on the live corpus put the target at rank 1 **zero** times
and 13 times did not carry it in the top 200 at all.

Everything the ranking learned — reach, the standardisation against the pool's own null, the
instrument's cut, the modifier projection — lived in `answer()`, which this capability never
called. The improvements were real and unreachable.

## What is asserted

That the published surface runs the ranked path, and that its size comes from the cut. Against
fixtures rather than the corpus: the point is which code path serves the capability, not what the
corpus happens to hold.
"""
from __future__ import annotations

import pytest

from agience_chorus.sage import reach_provider as RP


class _Artifacts:
    def __init__(self, titles):
        self._titles = titles

    def get_artifact(self, aid):
        if aid not in self._titles:
            return None
        return {"id": aid, "title": self._titles[aid], "content": "body of " + aid}


class _Store:
    def __init__(self, titles):
        self.artifacts = _Artifacts(titles)


@pytest.fixture()
def wired(monkeypatch):
    """Bind the content_search seam so the capability's own path is what runs.

    The CUT is patched on `mantle.search.ranking`, not on `content_search`. `store_retrieve` asks
    `ranking.cut_for` for one number — the frame and the cut are one answer, and assembling them at
    each call site is what let mantle's recall ask for the cut without the frame — so the cut is
    read there now, and `cs._relevance_cut` is only a name pointing at the same module.
    """
    def _install(pool, ranked, cut):
        import agience_chorus.sage.content_search as cs
        from mantle.search import ranking
        monkeypatch.setattr(cs, "search", lambda store, q, k=None: list(pool))
        monkeypatch.setattr(cs, "_reach_rank", lambda c, q, s: (list(ranked), {}, set()))
        monkeypatch.setattr(ranking, "cut_for",
                            lambda ranked, query=None, store=None, frame=None: cut)
        monkeypatch.setattr(RP, "resolve_text", lambda s, a: a.get("content", ""), raising=False)
        return cs
    return _install


def test_the_capability_returns_the_reach_order_not_the_bm25_order(wired):
    """The pool arrives worst-first by reach; the capability must publish the RANKED order."""
    pool = [("wn-b", "t", -20.0), ("wn-a", "t", -1.0)]
    ranked = [("wn-a", "t", -9.0), ("wn-b", "t", -1.0)]
    wired(pool, ranked, cut=2)
    store = _Store({"wn-a": "the answer", "wn-b": "a mention"})

    hits = RP.store_retrieve(store, "a question", k=6)

    assert [h["id"] for h in hits] == ["wn-a", "wn-b"], (
        "the capability published the lexical order — it is calling `search` and not the ranked "
        "path: %s" % [h["id"] for h in hits])
    assert hits[0]["score"] > hits[1]["score"], "score is not higher-is-better as op.retrieve states"


def test_the_cut_decides_the_size_and_k_is_only_a_ceiling(wired):
    """How many results a question HAS is derived. `k` bounds it; it does not set it."""
    pool = ranked = [("wn-%d" % i, "t", -float(9 - i)) for i in range(6)]
    wired(pool, ranked, cut=2)
    store = _Store({"wn-%d" % i: "t%d" % i for i in range(6)})

    assert len(RP.store_retrieve(store, "q", k=6)) == 2, "the cut did not decide the size"
    assert len(RP.store_retrieve(store, "q", k=1)) == 1, "k did not bound the answer"


def test_an_unreadable_frame_does_not_take_the_capability_down(wired, monkeypatch):
    """The cut is a refinement. If the projection or the cut raises, the capability still answers —
    a diagnostic failure must not become a retrieval failure."""
    pool = ranked = [("wn-a", "t", -9.0), ("wn-b", "t", -1.0)]
    cs = wired(pool, ranked, cut=2)

    def _boom(*a, **k):
        raise RuntimeError("no frame")

    monkeypatch.setattr(cs, "_relevance_cut", _boom)
    store = _Store({"wn-a": "a", "wn-b": "b"})

    hits = RP.store_retrieve(store, "q", k=6)
    assert [h["id"] for h in hits] == ["wn-a", "wn-b"], "a cut failure emptied the answer"


def test_a_blank_query_still_answers_nothing(wired):
    """Fail-soft, unchanged: the capability's contract for an empty need."""
    wired([], [], cut=0)
    assert RP.store_retrieve(_Store({}), "   ", k=6) == []
