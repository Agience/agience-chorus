"""A question whose subject the ontology cannot place is refused, not answered from the leftovers.

## The defect

An adjective carries an information content but no hypernym parent, so it has no least common
subsumer with anything and `jc_tree` has nothing to measure. `wn_synsets_for` does not return one,
so it contributes nothing to the fired field — and the field is then seeded by whatever else the
question happened to contain. Live, on the 676,225-synset corpus:

    what does viscous mean         -> 1. Department of Energy   2. mean   3. Does
    what makes a thing beautiful   -> 1. thing                  2. brand

`does` resolves to the Department of Energy. The answers are confident, cut to a tidy 8, and about
nothing the caller asked. That is worse than no answer, because nothing downstream can tell it from
a good one.

## The test, which is comparative rather than a threshold

`I(w) = -log2(df/N)` is monotonically DECREASING in `df`, so the most informative token of a query
is simply its rarest — no logarithm, no corpus size, and `_df` is exact off `fts5vocab`. If the
rarest token is the one with no position, the question has not been understood.

`df == 0` is skipped: an unattested token is `_absent_content`'s case and it names it better, which
is why that check runs first.

## Why this is not "refuse when coverage is low"

Every question here has unplaced tokens — `what` is unplaced in all of them. What separates
`what is a glacier` from `what does viscous mean` is not how many tokens went unplaced but WHICH:
the subject, or the filler.
"""
from __future__ import annotations

import pytest

from agience_chorus.sage import content_search as CS


class _Conn:
    """A `_df` source: a token -> document-frequency table, and nothing else."""

    def __init__(self, dfs):
        self.dfs = dfs


class _Store:
    def __init__(self, dfs):
        self._conn = _Conn(dfs)
        self.artifacts = self

    class _DB:
        def __init__(self, outer):
            self._outer = outer

        def read(self):
            return self._outer._conn

    @property
    def db(self):
        return _Store._DB(self)


@pytest.fixture()
def wired(monkeypatch):
    """Bind `_df` and `wn_synsets_for` to fixtures, so the rule is tested and not the corpus."""
    def _install(dfs, placed):
        monkeypatch.setattr(CS, "_df", lambda conn, tok: conn.dfs.get(tok))
        import crystal.ontology.lookup as L
        monkeypatch.setattr(L, "wn_synsets_for", lambda w: (["%s.n.01" % w] if w in placed else []))
        return _Store(dfs)
    return _install


def test_the_rarest_token_having_no_position_is_refused(wired):
    """`viscous` is the rarest word in the question and the ontology has no position for it."""
    store = wired({"what": 90000, "does": 40000, "viscous": 300, "mean": 60000},
                  placed={"does", "mean"})
    assert CS._unplaced_subject(store, "what does viscous mean") == "viscous"


def test_a_placed_subject_is_not_refused(wired):
    """The control, and the one that must never fire: `glacier` is rarest AND placed. Filler being
    unplaced is normal — `what` has no position in any of these questions."""
    store = wired({"what": 90000, "is": 95000, "glacier": 800}, placed={"is", "glacier"})
    assert CS._unplaced_subject(store, "what is a glacier") is None


def test_a_common_unplaced_word_does_not_trigger_it(wired):
    """`what` is unplaced in every question here. Refusing on ANY unplaced token would refuse
    everything; the rule is about the rarest one."""
    store = wired({"what": 90000, "is": 95000, "planet": 700}, placed={"is", "planet"})
    assert CS._unplaced_subject(store, "what is a planet") is None


def test_an_unattested_token_is_left_to_the_absence_check(wired):
    """`df == 0` is not "infinitely informative" here — it is `_absent_content`'s case, and that
    check runs first because it names the condition better."""
    store = wired({"what": 90000, "is": 95000, "florpangle": 0}, placed={"is"})
    assert CS._unplaced_subject(store, "what is a florpangle") is None


def test_an_unmeasurable_corpus_makes_no_claim(wired):
    """No df for anything -> no most-informative token -> no refusal. A missing index must not
    become a refusal to answer anything."""
    store = wired({}, placed=set())
    assert CS._unplaced_subject(store, "what does viscous mean") is None


def test_a_store_that_cannot_be_read_makes_no_claim():
    class _Broken:
        artifacts = property(lambda self: self)

        @property
        def db(self):
            raise RuntimeError("no store")

    assert CS._unplaced_subject(_Broken(), "what does viscous mean") is None
