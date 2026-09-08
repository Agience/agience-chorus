"""Pins that the docs-library cuts are derived quantities, not typed constants.

Three numbers decide what a document is: `staleness >= superseded_at()` makes it superseded (and
therefore archived), `staleness >= stale_at()` makes it stale, and the `null_jaccard` overlap decides
whether a document joins a category or becomes an orphan.

  superseded_at()  derived from the staleness mixture — the score of a document a full year without
                    a commit that also carries a superseded marker.
  stale_at()        derived from the same mixture — a working/scratch document whose age is unreadable.
  null_jaccard()    the overlap two unrelated sets of these sizes already share, computed from the
                    corpus's own vocabulary. Beating it is break-even, not a threshold.

A derivation written as `_W_AGE * 1.0 + _W_MARKER * _MARK_SUPERSEDED` and a literal constant of the
same value produce the same number for any single input, so a test asserting only the shipped value
cannot tell them apart. Every test here instead perturbs an input and asserts the cut moved: a
derivation that returns the same number regardless of its inputs is a constant wearing a function.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

import agience_chorus.sage.docs_ops as D  # noqa: E402


def _perturb(monkeypatch, **weights):
    """Move a weight and ask the module for its cuts, via `D.superseded_at()` / `D.stale_at()`
    rather than recomputing the expression here — re-implementing the rule under test would let a
    typed constant pass unnoticed."""
    for k, v in weights.items():
        monkeypatch.setattr(D, k, v)
    return D.superseded_at(), D.stale_at()


# ── the staleness cuts ─────────────────────────────────────────────────────────────────────

def test_the_cuts_are_the_scores_they_claim_to_be():
    """superseded_at() must equal the score `staleness()` actually produces for the evidence it
    names — a fully-aged document carrying one superseded marker. If the two ever disagree, the
    cut has stopped describing the scale it cuts."""
    marker_part = D._W_MARKER * min(1.0, D._MARK_SUPERSEDED * 1)
    assert D.superseded_at() == pytest.approx(D._W_AGE * 1.0 + marker_part)

    scratch_unknown_age = D._SCRATCH_SCORE + D._W_AGE * D._AGE_UNKNOWN_SCORE
    assert D.stale_at() == pytest.approx(scratch_unknown_age)


def test_the_cuts_track_the_age_weight(monkeypatch):
    """Halve the weight the age signal carries and both cuts must fall — they are both built on it."""
    before_sup, before_stale = D.superseded_at(), D.stale_at()
    after_sup, after_stale = _perturb(monkeypatch, _W_AGE=0.25)
    assert after_sup < before_sup, "SUPERSEDED_AT ignored the age weight it is built from"
    assert after_stale < before_stale, "STALE_AT ignored the age weight it is built from"


def test_superseded_tracks_the_marker_weight_and_stale_does_not(monkeypatch):
    """The two cuts are built from different evidence, so they must respond differently. A single
    hidden constant driving both would move them together."""
    before_sup, before_stale = D.superseded_at(), D.stale_at()
    after_sup, after_stale = _perturb(monkeypatch, _MARK_SUPERSEDED=0.9)
    assert after_sup > before_sup
    assert after_stale == pytest.approx(before_stale), (
        "the marker weight moved the STALE cut — the two cuts are not built from the evidence "
        "they each name"
    )


def test_stale_tracks_the_scratch_and_unknown_age_contributions(monkeypatch):
    before = D.stale_at()
    assert _perturb(monkeypatch, _SCRATCH_SCORE=0.1)[1] < before
    assert _perturb(monkeypatch, _AGE_UNKNOWN_SCORE=0.9)[1] > before


def test_the_shipped_cuts_still_read_where_they_always_did():
    """The only value assertion in the file, and on its own it proves nothing: it pins the current
    cut values (0.7 / 0.45) so a change is visible immediately, while the tests above are what
    prove the cuts are derived rather than typed."""
    assert D.superseded_at() == pytest.approx(0.7)
    assert D.stale_at() == pytest.approx(0.45)


def test_classification_moves_with_the_cut(monkeypatch):
    """The end-to-end consequence: a document's role must follow the derived cut, not a literal."""
    stale = {"staleness": 0.6, "markers": {"superseded": 0, "draft": 0, "vision": 0, "roadmap": 0}}
    assert D.classify("body", "/x/notes.md", stale) != "superseded"
    monkeypatch.setattr(D, "_W_AGE", 0.25)   # drops the derived cut to 0.45
    assert D.classify("body", "/x/notes.md", stale) == "superseded", (
        "lowering the derived cut did not change what counts as superseded — `classify` is still "
        "comparing against a literal"
    )


# ── the category-assignment null ───────────────────────────────────────────────────────────

def test_the_chance_overlap_falls_as_the_vocabulary_grows():
    """The whole point: the same Jaccard means different things at different scales. A null that
    ignored the sizes would be 0.05 again under another name."""
    small_vocab, _ = D.null_jaccard(50, 500, 1_000)
    big_vocab, _ = D.null_jaccard(50, 500, 100_000)
    assert big_vocab < small_vocab, (
        "the chance overlap did not fall when the vocabulary grew 100x — the null is not a "
        "function of the space the sets are drawn from"
    )


def test_the_chance_overlap_rises_with_set_size():
    assert D.null_jaccard(500, 500, 5_000)[0] > D.null_jaccard(20, 500, 5_000)[0]
    assert D.null_jaccard(50, 2_000, 5_000)[0] > D.null_jaccard(50, 100, 5_000)[0]


def test_the_standard_error_tightens_as_the_draw_gets_larger():
    """The se must be a real sampling quantity, not a decoration."""
    _n1, se_small = D.null_jaccard(10, 50, 500)
    _n2, se_large = D.null_jaccard(400, 450, 500)
    assert se_large < se_small


def test_the_null_refuses_on_degenerate_inputs():
    """Nothing to draw from means no chance overlap to exceed — 0, not a fabricated level."""
    assert D.null_jaccard(0, 10, 100) == (0.0, 0.0)
    assert D.null_jaccard(10, 0, 100) == (0.0, 0.0)
    assert D.null_jaccard(10, 10, 1) == (0.0, 0.0)
    assert D.null_jaccard(200, 10, 100) == (0.0, 0.0)


def test_a_below_chance_overlap_does_not_join_a_category(monkeypatch):
    """The end-to-end consequence, with a positive control: a document whose overlap with a
    category is no more than an unrelated document's must orphan, while one that genuinely shares
    the category's vocabulary must join it. A suite asserting only the refusal would pass just as
    happily if everything orphaned."""
    shared = [f"t{i}" for i in range(40)]
    docs = [{"id": f"core{i}", "path": f"/x/core{i}.md",
             "lemmas": shared + [f"c{i}_{j}" for j in range(5)]} for i in range(5)]
    docs += [{"id": f"fill{i}", "path": f"/x/fill{i}.md",
              "lemmas": [f"f{i}_{j}" for j in range(40)]} for i in range(12)]
    # shares a quarter of the category's defining vocabulary — not enough to be union-find linked
    # into the core at the clustering threshold, so it reaches the null-compared assignment path
    docs.append({"id": "joiner", "path": "/x/joiner.md",
                 "lemmas": shared[:10] + [f"j{j}" for j in range(60)]})
    docs.append({"id": "stranger", "path": "/x/stranger.md",
                 "lemmas": [f"z{j}" for j in range(40)]})

    out = D.categorize(docs, threshold=0.18, min_size=3)
    general = [c for c in out if c["label"] == ["general"]][0]
    core = [c for c in out if c["label"] != ["general"]][0]
    assert "stranger.md" in general["docs"], (
        "a document sharing nothing with any category was absorbed into one"
    )
    assert "joiner.md" in core["docs"], (
        "a document sharing a quarter of a category's defining vocabulary was orphaned — the bar "
        "is no longer break-even against chance"
    )

    # Confirms it is the null deciding this, not the clustering: raising the chance overlap to an
    # unreachable 1.0 must orphan the same document.
    monkeypatch.setattr(D, "null_jaccard", lambda a, b, v: (1.0, 0.0))
    out2 = D.categorize(docs, threshold=0.18, min_size=3)
    general2 = [c for c in out2 if c["label"] == ["general"]][0]
    assert "joiner.md" in general2["docs"], (
        "raising the computed null did not orphan the joiner — the assignment is not reading it"
    )


def test_the_common_lemma_share_is_DERIVED_not_a_typed_default():
    """`categorize`'s default common-lemma share is derived per corpus (`derived_common_frac`)
    rather than a typed constant — a fixed share cannot ask "does dropping at f leave the union-find
    with more than one cluster on this corpus?", which is the measurement that settles it. The share
    must come from the corpus in hand, not a restored typed default.
    """
    assert D.categorize.__kwdefaults__["drop_common_frac"] is None, (
        "categorize is back to a typed vocabulary share instead of measuring it")
    # `everywhere` sits in 4 of 10 documents: dropped at the shipped 0.35 share, kept at 0.99.
    docs = [{"id": f"d{i}", "path": f"/x/d{i}.md",
             "lemmas": (["everywhere"] if i < 4 else []) + [f"own{i}", f"own{i}b"]}
            for i in range(10)]

    def _general_size(frac):
        out = D.categorize(docs, threshold=0.2, min_size=2, drop_common_frac=frac)
        return sum(c["size"] for c in out if c["label"] == ["general"])

    assert _general_size(0.99) < _general_size(D.COMMON_LEMMA_FRAC), (
        "keeping the corpus-common lemma did not link any documents that dropping it separates — "
        "`categorize` is ignoring the parameter and still using a literal"
    )


def test_the_derived_share_MOVES_WITH_THE_CORPUS():
    """The point of deriving it: two corpora with different boilerplate shares must not get the
    same number. A derivation that returns the same value regardless of input is a constant,
    not a derivation.
    """
    def corpus(n_share):
        n = 10
        k = int(n_share * n)
        return [{"id": f"d{i}", "path": f"/x/d{i}.md",
                 "lemmas": (["boiler", "plate"] if i < k else []) + [f"g{i//3}", f"own{i}"]}
                for i in range(n)]
    a = D.derived_common_frac(corpus(0.3))
    b = D.derived_common_frac(corpus(0.9))
    assert a is not None and b is not None, (a, b)
    assert a != b, "the derived share is the same for two very different corpora: %r" % a


def test_the_derived_share_REFUSES_on_a_corpus_with_no_structure():
    """[[absence-is-not-an-affirmative-claim]] — a corpus whose documents share nothing has no share
    to find. `derived_common_frac` returns None rather than falling back to `COMMON_LEMMA_FRAC` or
    any other number, which would report a grouping the corpus does not support.
    """
    singletons = [{"id": f"d{i}", "path": f"/x/d{i}.md", "lemmas": [f"only{i}"]} for i in range(8)]
    assert D.derived_common_frac(singletons) is None
    assert D.derived_common_frac([]) is None


def test_NO_CUT_FUNCTION_CARRIES_A_TYPED_DEFAULT_SCALE():
    """No cut function (`topics`, `categorize`, `build_library`, `library_plan`) carries a typed
    numeric default: the query picks the scale, per §9.6, not a shipped literal.

    Checked by signature, so it catches a new cut function too, and it names the offender.
    """
    import inspect
    offenders = []
    for name, param in (("topics", "threshold"), ("categorize", "threshold"),
                        ("build_library", "consolidate_threshold"),
                        ("library_plan", "resolution")):
        sig = inspect.signature(getattr(D, name))
        default = sig.parameters[param].default
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            offenders.append("%s(%s=%r)" % (name, param, default))
    assert not offenders, (
        "a typed scale is back: %s. The NEED carries the resolution; `resolutions()` reports the "
        "levels this corpus actually has." % offenders)


def test_a_caller_with_NO_resolution_gets_the_CHOICES_not_a_grouping():
    """The positive half — refusing to pick must still be useful, or callers fall back to
    hard-coding a number to get past it. `resolutions()` must offer real levels to choose from: an
    empty list here would be indistinguishable from an empty corpus and give the caller nothing to
    choose from.
    """
    docs = [{"id": f"d{i}", "path": f"/x/d{i}.md",
             "lemmas": [f"g{i//3}", "shared", f"own{i}"]} for i in range(9)]
    offered = D.resolutions(docs)
    assert offered, "no levels were offered for a corpus that plainly has structure"
    assert offered == sorted(offered, reverse=True), "levels must descend"
    assert all(0.0 < v <= 1.0 for v in offered), offered
    # and they are real: cutting at a level yields the grouping, cutting between two adjacent
    # levels yields the same one — which is what makes them the distinguishable zooms.
    assert len(set(offered)) == len(offered), "duplicate levels: these are not distinct zooms"

