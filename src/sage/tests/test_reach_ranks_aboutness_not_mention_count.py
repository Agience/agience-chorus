"""Reach is standardised against the query's own null, so size neither wins nor loses by itself.

## The defect

`match.propagate` sums over the positions it is handed, so raw energy is EXTENSIVE: a candidate that
names more things scores higher for naming more things. A synset names exactly one — itself — and a
document names every term the corpus keyed it on, so the two are not comparable. Measured on the
live 676,225-synset corpus, "what is a glacier" under the raw sum:

    Highline Trail (Glacier National Park)   10.31   rank 1
    glacier.n.01                              8.56   rank 31

A hiking-trail article out-reached the concept because it also named trail, park and mountain.

## Why the obvious corrections are not it

Every fixed correction is a guess at how reach should scale with size, and each buys precision by
discarding documents. Measured over 18 questions — target at rank 1, and how many documents survive
into the top ten:

    raw sum            1/18     156 documents
    energy / n        17/18      24
    max per position   7/18     140
    energy / sqrt(n)  15/18     117
    standardised      17/18      52

`energy / n` shipped first and made the answers lexicon-only: a concept always has exactly one
position, the smallest denominator available, so dividing by count hands it a structural win no
measurement gave it. It also came with a tiebreak ("the concept beats a mention of it") and a
position-dedup, both of which existed to settle ties between a stub article and the concept it
named. Positioning a document on the terms the corpus keyed it on removed those ties — 0 of 18
queries tie at the top — and reach alone then reached the same 17/18, so both rules were deleted
rather than kept as scaffolding.

## What replaced them

Under a null where a candidate's positions say nothing about the need, its total reach is the sum of
`n` draws from the reach this pool actually exhibits — mean `mu`, spread `sigma`, both measured from
the positions THIS query reached. A sum of `n` such draws has expectation `n*mu` and spread
`sqrt(n)*sigma`, so

    z = (energy - n*mu) / (sqrt(n)*sigma)

is how far a candidate stands above what its own size predicts. Size leaves the comparison because
it appears in both terms, not because it was divided out. No exponent is chosen and no constant
appears.

## What is asserted

The properties, against fixtures, so these state the rule rather than re-measure the corpus.
"""
from __future__ import annotations

import pytest

from sage import content_search as CS


class _Match:
    """A `match` seam with a stated geometry: `fired` maps position -> the energy it contributes."""

    def __init__(self, fired):
        self._fired = fired

    def fired_field(self, query, store):
        return dict(self._fired)

    def offer_synsets(self, text):
        return [w for w in str(text).split() if w in self._fired]

    def propagate(self, fired, targets):
        hit = [fired[t] for t in targets if t in fired]
        return (float(sum(hit)), 0.0 if hit else float("inf"))

    def expand_associative(self, store, fired):
        return fired


class _Store:
    """Just enough store for `_reach_rank`: a doc lookup keyed on `lemmas`, and no injection."""

    def __init__(self, docs):
        self._docs = docs
        self.artifacts = self

    class _DB:
        def __init__(self, outer):
            self._outer = outer

        def read(self):
            return self._outer

    @property
    def db(self):
        return _Store._DB(self)

    def _doc(self, cid):
        """The `doc` blob as the lattice stores it, or `None` for an id it does not hold."""
        d = self._docs.get(cid)
        if d is None:
            return None
        return '{"lemmas": [%s]}' % ", ".join('"%s"' % w for w in d.split())

    def execute(self, sql, args=()):
        """Both doc reads the ranking makes.

        The batched `id IN (...)` form is the one that runs — a pool of 200 was 200 point lookups
        into a 9.7 GB file before it was batched — and it yields `(id, doc)` pairs. The single-id
        form is kept because a fake that answers only the shape currently called cannot catch the
        next caller getting it wrong.
        """
        if " IN (" in sql:
            return _Rows([(cid, self._doc(cid)) for cid in args if self._doc(cid) is not None])
        cid = args[0] if args else None
        doc = self._doc(cid)
        return _Rows([] if doc is None else [(doc,)])

    def get_artifact(self, vid):
        return None                       # nothing injected; the pool is the whole candidate set


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


@pytest.fixture()
def seam(monkeypatch):
    """Bind the ontology into the ranking module, which is where it is read.

    The ranking lives in `mantle.search.ranking` so the store that produces candidates can reach it
    without a persona. That module resolves its own bound seam, so patching
    `content_search._resolve_seam` does not affect it: the fixture sets the bound seam directly and
    `monkeypatch` restores it.
    """
    from mantle.search import ranking as _ranking

    def _install(fired):
        m = _Match(fired)
        monkeypatch.setattr(_ranking, "_MATCH_SEAM", m)
        monkeypatch.setattr(_ranking, "_PROJECTION_SEAM", m)
        return m
    return _install


def test_naming_more_things_is_not_reaching_further(seam):
    """The measured defect, as a rule.

    `broad` names the subject and two others the need touches only faintly, so its RAW energy is
    the larger and the sum ranked it first. Standardised, its size is what it has to beat, and two
    faint positions do not pay for themselves.

    The energies are uneven on purpose. Where every position reaches alike the spread is zero, both
    candidates land exactly on what their size predicts, and the standardisation correctly reports
    no difference between them — there is none to report. The live geometry is not flat: measured,
    `glacier` reached 8.56 where `trail` and `park` reached a fraction of that, and it is that
    unevenness the comparison reads.
    """
    seam({"glacier.n.01": 8.5, "trail.n.01": 0.5, "park.n.01": 0.5})
    store = _Store({"doc-broad": "glacier.n.01 trail.n.01 park.n.01"})
    cand = [("doc-broad", "text/html", -10.0), ("wn-glacier.n.01", "text/x-wordnet", -8.0)]

    ranked, account, _reached = CS._reach_rank(cand, "what is a glacier", store)

    assert account["reach"] == "measured"
    assert ranked[0][0] == "wn-glacier.n.01", (
        "a document that names three touched concepts outranked the one that IS the subject; reach "
        "is being summed rather than standardised. Order: %s" % [r[0] for r in ranked])


def test_a_document_can_still_outrank_a_concept(seam):
    """The control that the previous rule must not become "concepts always win" — the failure the
    `energy / n` correction had, which made every answer lexicon-only.

    `doc-strong` stands on two positions the need reaches hard; the concept stands on one it barely
    reaches. The document is further above what its size predicts, and it wins.
    """
    seam({"ice.n.01": 10.0, "snow.n.01": 10.0, "thin.n.01": 0.01})
    store = _Store({"doc-strong": "ice.n.01 snow.n.01"})
    cand = [("wn-thin.n.01", "text/x-wordnet", -9.0), ("doc-strong", "text/html", -1.0)]

    ranked, _account, _reached = CS._reach_rank(cand, "ice and snow", store)

    assert ranked[0][0] == "doc-strong", (
        "a document reaching two strong positions lost to a concept reaching one weak one — size "
        "is being divided out rather than standardised against. Order: %s" % [r[0] for r in ranked])


def test_a_candidate_that_reaches_nothing_ranks_below_one_that_does(seam):
    seam({"ice.n.01": 1.0})
    store = _Store({"doc-ice": "ice.n.01", "doc-other": "unrelated.n.01"})
    cand = [("doc-other", "text/html", -9.0), ("doc-ice", "text/html", -1.0)]

    ranked, _a, reached = CS._reach_rank(cand, "ice", store)

    assert ranked[0][0] == "doc-ice", [r[0] for r in ranked]
    assert "doc-other" not in reached, "a candidate with no position was reported as reached"


def test_everything_unreached_keeps_the_lexical_order_and_says_so(seam):
    """`unreached` counts candidates that reached NOTHING, and that is the test — not the sign of
    the standardised score. A negative `z` is a real reading of a real candidate."""
    seam({"ice.n.01": 1.0})
    store = _Store({"a": "unrelated.n.01", "b": "elsewhere.n.01"})
    cand = [("a", "text/html", -3.0), ("b", "text/html", -1.0)]

    ranked, account, reached = CS._reach_rank(cand, "ice", store)

    assert ranked == cand and account["reach"] == "unreached" and reached == set()


def test_a_negative_score_is_a_reading_and_not_an_absence(seam):
    """A candidate below its own size's expectation scores negative and must still be ranked and
    reported as reached. Treating `z < 0` as unreached would report a measurement as an absence."""
    seam({"a.n.01": 10.0, "b.n.01": 0.001, "c.n.01": 0.001})
    store = _Store({"doc-weak": "b.n.01 c.n.01"})
    cand = [("wn-a.n.01", "text/x-wordnet", -9.0), ("doc-weak", "text/html", -1.0)]

    ranked, account, reached = CS._reach_rank(cand, "a", store)

    assert account["reach"] == "measured"
    assert "doc-weak" in reached, "a candidate that reached two positions was reported unreached"
    assert [r[0] for r in ranked][0] == "wn-a.n.01", [r[0] for r in ranked]


def test_an_empty_fired_field_leaves_the_order_alone(seam):
    """No coordinate, no re-rank — the lexical order passes through and says so."""
    seam({})
    store = _Store({})
    cand = [("a", "text/html", -3.0), ("b", "text/html", -1.0)]
    ranked, account, reached = CS._reach_rank(cand, "???", store)
    assert ranked == cand and account["reach"] == "no-coordinate" and reached == set()
