"""Unit tests for the DERIVED answer-size logic (`content_search._knee`).

These are pure — no corpus, no store — so they verify the principle the live serve path rests on:
the number of grounded spans is derived from the BM25 score distribution, never a fixed count.
(The corpus-integration side of `answer()` must still be verified live on the box holding corpus.db.)
"""
from agience_chorus.sage.content_search import _knee


def test_single_or_empty():
    assert _knee([]) == 0
    assert _knee([-3.0]) == 1


def test_one_dominant_answer_returns_one():
    # An exact-title hit that dwarfs the rest ("who was Ada Lovelace"): relevance 12 vs 4 = a halving+.
    assert _knee([-12.0, -4.0, -3.8, -3.5]) == 1


def test_multi_facet_cluster_kept_then_cut():
    # A tight cluster (8, 7.5, 7) then a real drop to noise (2): keep the three-strong cluster.
    assert _knee([-8.0, -7.5, -7.0, -2.0, -1.9]) == 3


def test_flat_distribution_keeps_all():
    # No break anywhere (a broad, evenly-relevant query): the whole set is relevant; ceiling bounds it.
    assert _knee([-5.1, -5.0, -4.9, -4.8]) == 4


def test_equal_scores_keep_all():
    assert _knee([-5.0, -5.0]) == 2


def test_relevance_floor_is_noise_boundary():
    # Once relevance reaches 0, everything after is noise → cut there.
    assert _knee([-5.0, 0.0, 0.0]) == 1


def test_sharpest_break_wins_not_the_first_minor_dip():
    # A minor 1.3x dip early, a real 3x break later: the real break is the knee.
    assert _knee([-10.0, -7.7, -7.0, -2.3, -2.2]) == 3


# ── the rank and the cut must read one measurement (§13.14) ──────────────────────────────────────
# `_reach_rank` re-orders by measured reach. If it hands back the BM25 scores in that new order, the
# downstream cut reads a sequence that is monotone in neither signal — measured on the live corpus:
# a cut of 184 for "what is a dog" and 193 for "what is a star", i.e. no cut at all, with `_CEILING`
# silently becoming the answer length. These pin the contract that prevents that mis-pairing.
class _FakeArtifacts:
    def __init__(self, ids):
        self._ids = set(ids)

    def get_artifact(self, aid):
        return {"id": aid} if aid in self._ids else None


class _FakeStore:
    def __init__(self, ids=()):
        self.artifacts = _FakeArtifacts(ids)


def test_reach_rank_returns_the_reach_it_ranked_by_not_the_bm25_it_replaced(monkeypatch):
    import agience_chorus.sage.content_search as cs
    from ember.ontology import match as _match
    monkeypatch.setattr(_match, "fired_field", lambda q, s=None: {"need": 1.0})
    # `b` reaches further than `a` despite a much worse BM25 score — the case reach exists to fix.
    energies = {"wn-a": (1.0, 0.9), "wn-b": (9.0, 0.0)}
    monkeypatch.setattr(_match, "propagate", lambda f, t: energies.get("wn-" + t[0], (0.0, float("inf"))))
    ranked, acct, reached = cs._reach_rank([("wn-a", "t", -20.0), ("wn-b", "t", -1.0)],
                                           "need", _FakeStore())
    assert [c[0] for c in ranked] == ["wn-b", "wn-a"]        # ranked by reach
    # The score carried out is the reach that DID the ranking, standardised against this query's own
    # null — not the BM25 it replaced, and not the raw energy either. Both candidates stand on one
    # position, so the pool's per-position reaches are {1.0, 9.0}: mean 5.0, spread 4.0, and
    # `z = (energy - 1*5.0) / (sqrt(1)*4.0)` gives -1.0 and +1.0. Negated on the way out, keeping
    # BM25's sign convention so the cut reads the same direction it always has.
    assert [c[2] for c in ranked] == [-1.0, 1.0]
    assert [c[2] for c in ranked] != [-20.0, -1.0], "the BM25 scores were passed through"
    # Two readings cannot separate, and the cut says so rather than pretending: any two-point
    # series splits perfectly, so "two groups" and "a ramp" are the same observation at n=2 — the
    # explained variance equals its own no-structure baseline exactly. The property under test is
    # that the cut reads the reach; with enough points to separate, it does:
    assert cs._knee([c[2] for c in ranked]) == 2             # n=2: honest "cannot tell"
    assert cs._knee([-9.0, -8.8, -8.6, -1.0, -0.9]) == 3     # a real break, read off the reach
    assert reached == {"wn-a", "wn-b"} and acct["reach"] == "measured"


def test_degraded_reach_passes_bm25_through_untouched():
    """No coordinate, nothing reachable, or `match` absent: the teleport order and its own scores
    stand. The re-rank refines a teleport; it never manufactures one."""
    import agience_chorus.sage.content_search as cs
    cand = [("x", "t", -5.0), ("y", "t", -1.0)]
    ranked, acct, reached = cs._reach_rank(cand, "", _FakeStore())   # no terms fire → no coordinate
    assert ranked == cand and reached == set() and acct["reach"] in ("no-coordinate", "unreached")


def test_an_unreached_candidate_still_faces_the_lexical_test():
    """The fallback survives exactly where the geometry could not place the candidate — otherwise a
    doc sharing only a common word ("Who Was…?" on "who was") would be admitted on BM25 alone."""
    import agience_chorus.sage.content_search as cs
    assert "y" not in cs._reach_rank([("y", "t", -1.0)], "", _FakeStore())[2]
