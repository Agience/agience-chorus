"""The curriculum certificate — a level advances on what it can answer, never on its byte count.

Each test names the degenerate observer it is built to catch: checking only a good observer's pass
is not evidence against a fabricating one.
"""
from __future__ import annotations

import numpy as np

try:                                             # robust: cross-persona host vs in-persona process
    from agience_chorus.lumen import curriculum as C            # (chorus/src on path)
except ImportError:
    import agience_chorus.lumen.curriculum as C                       # (lumen/ on path)

# The test supplies the instrument. `curriculum.answers` takes an `embodiment=` against
# `prism.embodiment.Embodiment` and raises `EmbodimentRequired` when the slot is empty. A full node
# fills that slot with `ember.optics`, so this file imports it and hands it over at every call. The
# import belongs here and not in the module under test — the tests at the bottom of this file prove
# the slot is real.
from ember import optics as INSTRUMENT


# A held-out set and its key. The observer is never shown `it[1]`; `key` reads it as the oracle.
ITEMS = [("dog", "canine"), ("cat", "feline"), ("oak", "tree"), ("trout", "fish"),
         ("robin", "bird"), ("rose", "flower"), ("shark", "fish"), ("pine", "tree")]
KEY = lambda it: [it[1]]                                                        # noqa: E731


def test_an_observer_that_states_the_recorded_kind_certifies():
    r = C.answers(ITEMS, lambda it: [it[1]], KEY, embodiment=INSTRUMENT)
    assert r["answers"] is True
    assert r["residual"] == 0.0            # conservation is exact, not approximately exact
    assert r["absorbed"] > 0.0
    assert r["coverage"] == 1.0


def test_a_constant_answer_is_REFUSED_though_it_scores_above_zero():
    """A pass mark cannot see this defect: an observer that answers "fish" to everything is right
    about the two fish, so it scores 0.25, and it has learned nothing. It does not certify because
    its rows do not lie in the corpus's band for those items, not because 0.25 is under some bar.

    This also pins the `(item, kind)` feature axis: flatten the coordinate to kinds alone and "fish"
    is in the span of what the corpus records somewhere, so the residual goes to zero and this
    observer certifies. The pairing has to be in the coordinate."""
    r = C.answers(ITEMS, lambda it: ["fish"], KEY, embodiment=INSTRUMENT)
    assert r["answers"] is False
    assert r["residual"] > 0.0
    assert r["rate"] > 0.0, "the point of this test is that it scores non-zero and is still refused"
    assert abs(r["rate"] - r["null"]) < 1e-12, "a constant answer is exactly its own re-paired null"


def test_a_right_answer_carrying_a_fabrication_is_REFUSED_at_rate_one():
    """A rate cannot see this at all: this observer states the correct kind for every item and one
    the corpus records for none of them. Its rate is 1.00 and any pass mark passes it. Conservation
    does not certify it, because the fabricated column is outside the band and transmits residual —
    exactly A3 ("nothing asserted that was not measured") enforced arithmetically."""
    r = C.answers(ITEMS, lambda it: [it[1], "xyzzy"], KEY, embodiment=INSTRUMENT)
    assert r["rate"] == 1.0
    assert r["answers"] is False
    assert r["residual"] > 0.0


def test_a_refusal_is_not_a_pass():
    """An observer that says nothing fabricates nothing, so its residual is trivially zero. That
    must not certify: a refusal is not a wrong answer and it is not a right one either. The absorbed
    energy is what separates them."""
    r = C.answers(ITEMS, lambda it: [], KEY, embodiment=INSTRUMENT)
    assert r["answers"] is False
    assert r["absorbed"] == 0.0
    assert r["coverage"] == 0.0


def test_a_kind_the_corpus_never_records_is_refused_not_ignored():
    """A fabricated kind must still have a column, or it is unmeasurable instead of refused —
    dropping it from the feature axis would make fabrication invisible to conservation."""
    r = C.answers(ITEMS, lambda it: ["xyzzy"], KEY, embodiment=INSTRUMENT)
    assert r["answers"] is False
    assert r["absorbed"] == 0.0 and r["residual"] > 0.0


def test_coverage_is_REPORTED_and_not_gated():
    """Conservation proves unfabricated, not complete. An observer that answers half the level
    correctly and refuses the rest has residual zero, which is true and is not mastery. The
    certificate reports both numbers rather than inventing a coverage bar; a `coverage` of 0.5 beside
    `answers: True` cannot be mistaken for one."""
    half = lambda it: [it[1]] if it[0] in ("dog", "cat", "oak", "trout") else []   # noqa: E731
    r = C.answers(ITEMS, half, KEY, embodiment=INSTRUMENT)
    assert r["answers"] is True and r["residual"] == 0.0
    assert r["coverage"] == 0.5


def test_no_oracle_is_unmeasured_never_a_verdict():
    """A missing key is a fact about the corpus, not about the observer. It must read `None`."""
    r = C.answers(ITEMS, lambda it: [it[1]], lambda it: [], embodiment=INSTRUMENT)
    assert r["answers"] is None
    assert "oracle" in r["why"] or "no band" in r["why"] or "records no kind" in r["why"]
    assert C.answers([], lambda it: [], KEY, embodiment=INSTRUMENT)["answers"] is None


# ── the settled half ──────────────────────────────────────────────────────────────────────────────
def _planted_planes(rng, n_planes, T, F, k, noise=0.1):
    """`n_planes` observations of one k-dimensional structure.

    The basis `B` is drawn once, outside the loop, so every plane shares the same k-dimensional
    subspace. `accumulator` pools planes of one structure — `F` constant across planes is what a
    fixed coordinate basis is for — and a fresh basis per plane would pool observations of different
    structures instead of repeated observations of the same one."""
    B = rng.standard_normal((k, F))
    return [(rng.standard_normal((T, k)) @ B) + noise * rng.standard_normal((T, F))
            for _ in range(n_planes)]


def test_a_planted_rank_settles_at_that_rank_with_the_interval_collapsed():
    rng = np.random.default_rng(0)
    F, K = 24, 3
    s = C.settled(_planted_planes(rng, 20, 40, F, K), F, read=INSTRUMENT)
    assert s["settled"] is True
    assert s["rank"] == K
    assert s["interval"] == (K, K), "settled means the Weyl interval COLLAPSED onto the count"


def test_noise_is_UNMEASURABLE_not_settled_and_not_failed():
    """"I cannot resolve this" and "this has not settled" are different claims (§21: ontology
    coordinates are sparse and a sparse frame reads as noise). A frame that resolves no modes has no
    rank to have stopped moving, so `settled` is None, not False — a promotion gate reading False
    would treat unmeasurable as a verdict about the level."""
    rng = np.random.default_rng(1)
    s = C.settled([rng.standard_normal((40, 24)) for _ in range(20)], 24, read=INSTRUMENT)
    assert s["settled"] is None
    assert s["rank"] == 0
    assert "K_signal = 0" in s["why"]


def test_no_frames_is_unmeasured():
    assert C.settled([], 24, read=INSTRUMENT)["settled"] is None


# ── the certificate ───────────────────────────────────────────────────────────────────────────────
def test_an_unmeasured_half_certifies_NOTHING():
    """`certified` is True only when both halves are measured and true; where a half could not be
    measured at all, `certified` is None rather than False, because "we did not find out" and "we
    found out it is not so" are different readings."""
    perfect = dict(items=ITEMS, stated=lambda it: [it[1]], key=KEY)
    c = C.certify(0, **perfect, embodiment=INSTRUMENT, read=INSTRUMENT)  # answers only — no frames supplied
    assert c.answers is True and c.settled is None
    assert c.certified is None, "an unmeasured half must not certify"
    assert any("settled" in w for w in c.why)

    rng = np.random.default_rng(0)
    both = C.certify(0, frames=_planted_planes(rng, 20, 40, 24, 3), n_features=24, **perfect,
                     embodiment=INSTRUMENT, read=INSTRUMENT)
    assert both.settled is True and both.answers is True
    assert both.certified is True

    bad = C.certify(0, frames=_planted_planes(rng, 20, 40, 24, 3), n_features=24,
                    items=ITEMS, stated=lambda it: ["fish"], key=KEY,
                    embodiment=INSTRUMENT, read=INSTRUMENT)
    assert bad.certified is False, "a measured failure is False, not None"


def test_the_level_assertion_is_carried_and_no_word_count_is():
    """`CURRICULUM-DATA-PLAN` §1: the receptive-vocabulary targets "are never an input to any
    algorithm: nothing in the code may read them." So they are not in the module at all — what a
    checker needs is the assertion, which carries no number."""
    assert C.LEVELS[0] == "name a thing and give its kind"
    assert set(C.LEVELS) == set(range(8))
    src = open(C.__file__, encoding="utf-8").read()
    for target in ("5,000", "25,000", "50,000", "80,000", "120,000", "150,000"):
        assert target not in src, "a level word-count target reached the code: %r" % target


# ── the injected instrument ───────────────────────────────────────────────────────────────────────
# `answers()` takes its instrument as an argument rather than importing it, so a host with no
# instrument registered gets a named error at the point of measurement. Catching that error and
# returning `answers: None` would read identically to "no probe was supplied" and would let a host
# that cannot measure report a level as uncertified rather than unmeasurable. These three tests
# confirm that does not happen.

def _no_instrument_anywhere():
    """Empty the process-wide slot for the duration of a `with`, then put back exactly what was
    there. `prism.instrument`'s default is process state — `agience-ember/src/ember/__init__.py`
    registers `ember.optics` into it at import, and this whole suite runs in one process, so a test
    that cleared it and walked away would make every later measurement in the run find no
    instrument."""
    import contextlib
    from prism import instrument as _inst

    @contextlib.contextmanager
    def _cm():
        saved = _inst.get_default()
        _inst.clear_default()
        try:
            yield
        finally:
            _inst.set_default(saved) if saved is not None else _inst.clear_default()
    return _cm()


def test_with_NO_instrument_the_split_REFUSES_at_the_point_of_measurement():
    """With no instrument, the split does not return `None`, does not return a zero split, and does
    not fabricate a reading — it raises `EmbodimentRequired` (503), naming the member and the
    operation that wanted it."""
    from prism.embodiment import EmbodimentRequired
    with _no_instrument_anywhere():
        try:
            C.answers(ITEMS, lambda it: [it[1]], KEY)
        except EmbodimentRequired as e:
            assert e.member == "absorb_transmit"
            assert e.contract == "embodiment"
            assert "curriculum.answers" in (e.at or ""), (
                "the refusal must name the operation, not just the member: %r" % (e.at,))
            assert e.http_status == 503
        else:
            raise AssertionError(
                "answers() returned a verdict with no instrument injected — the split cannot have "
                "been measured, so whatever it returned was fabricated")


def test_a_partial_embodiment_says_WHICH_member_it_lacks():
    """A constrained host, not an unwired one. An embodiment that fills `membrane_screen` and not
    `absorb_transmit` is a real, partial deployment (`prism/instrument.py`'s `Instrument`: a partial
    fill is "a constrained host reporting its constraint, not an optional member"). It is told apart
    from an empty slot by what the error says, not by the exception type."""
    from prism.embodiment import EmbodimentRequired

    class _ScreenOnly:                       # fills one member of the contract, and only one
        def membrane_screen(self):
            raise AssertionError("not reached")

    with _no_instrument_anywhere():
        try:
            C.answers(ITEMS, lambda it: [it[1]], KEY, embodiment=_ScreenOnly())
        except EmbodimentRequired as e:
            assert e.member == "absorb_transmit"
            assert "membrane_screen" in str(e), (
                "a partial embodiment must be told what it DOES fill, or the operator cannot tell "
                "a constrained host from an unwired one: %s" % e)
        else:
            raise AssertionError("a partial embodiment measured something it cannot measure")


def test_the_STRUCTURAL_answers_still_run_with_no_instrument_at_all():
    """The control for the two tests above: if `answers()` raised unconditionally, both would pass
    while the function had simply been broken. Every return above the split is a structural fact —
    nothing was asked, nothing was said, the corpus records nothing — and a host with no instrument
    answers all three correctly. That is the line between "not equipped" and "the observer said
    nothing", visible from outside."""
    with _no_instrument_anywhere():
        r = C.answers([], lambda it: [], KEY)                       # nothing was asked
        assert r["answers"] is None and r["n"] == 0

        r = C.answers(ITEMS, lambda it: [], lambda it: [])          # nobody said anything at all
        assert r["answers"] is None and "nothing to conserve" in r["why"]

        r = C.answers(ITEMS, lambda it: [it[1]], lambda it: [])     # the corpus has no oracle
        assert r["answers"] is None and "no band to absorb against" in r["why"]

        # …and the whole certificate still builds its unmeasured-half report without an instrument.
        c = C.certify(0)
        assert c.certified is None and c.answers is None

        # …and `settled` still answers the one fact that is structural rather than measured.
        assert C.settled([], 24)["settled"] is None


def test_the_SETTLED_half_takes_a_READ_and_refuses_without_one():
    """Two slots because they are two contracts. `settled` pools planes and reports what the pooled
    spectrum resolves — a statement about the signal, never a split of one — so it resolves
    `prism.instrument.Read`, not the `embodiment` slot `answers` uses. A host that fills only one of
    the two gets one measured half and a named error on the other.

    Without this, `settled` on an unequipped host could report `settled: None` with a "no frames
    were accumulated" reason — a capacity fact read as a statement about the level, which is what
    the two slots keep apart."""
    from prism.instrument import InstrumentRequired
    rng = np.random.default_rng(0)
    planes = _planted_planes(rng, 20, 40, 24, 3)

    with _no_instrument_anywhere():
        try:
            C.settled(planes, 24)
        except InstrumentRequired as e:
            assert e.contract == "read", "the settled half is a READ, not an embodiment"
            assert e.member == "accumulator"
            assert "curriculum.settled" in (e.at or "")
            assert e.http_status == 503
        else:
            raise AssertionError(
                "settled() returned a verdict with no instrument injected — nothing pooled the "
                "planes, so whatever it returned was fabricated")

        # The embodiment slot does not satisfy this: handing the split instrument to the read must
        # not measure. A slot that fills `absorb_transmit` and nothing else is a real host.
        class _SplitOnly:
            absorb_transmit = staticmethod(INSTRUMENT.absorb_transmit)

        try:
            C.settled(planes, 24, read=_SplitOnly())
        except InstrumentRequired as e:
            assert e.member == "accumulator" and e.contract == "read"
        else:
            raise AssertionError("a split-only instrument took a structure read")

    # The control: with the read injected, the same call measures, so the errors above are not
    # simply a function that always raises.
    s = C.settled(planes, 24, read=INSTRUMENT)
    assert s["settled"] is True and s["rank"] == 3
