"""The market frame — bars → the ordered return waterfall the instrument reads.

What is pinned here is the set of ways a frame can silently lie: forward-filling a missing bar,
shuffling time order, reading price levels instead of returns, or clamping bad data. Each of those
produces a matrix the instrument will happily read and report a confident number over.
"""
import contextlib
import math
import random

import pytest

from agience_chorus.ophan import market_frame as mf

# The test is the host: `read_market` does not import the instrument itself, but takes a `read=`
# against `prism.instrument.Read` and refuses when the slot is empty. A full node fills that slot
# with `ember.optics`, so this file imports it and hands it over at every call. The import belongs
# here rather than in the module under test, so that a test which resolves cleanly does so because
# the module's own dependency is genuinely satisfied, not because an import elsewhere in the process
# quietly filled the slot.
from ember import optics as INSTRUMENT


def _bars(*pairs):
    return [{"ts": ts, "close": c} for ts, c in pairs]


A = _bars(("t1", 100.0), ("t2", 101.0), ("t3", 102.0))
B = _bars(("t1", 50.0), ("t2", 50.5), ("t3", 51.0))


# ── alignment: the inner join, and why it must not fill ───────────────────────────────────────────

def test_aligned_on_shared_timestamps_only():
    ts, syms, closes = mf.aligned_closes({"A": A, "B": B})
    assert ts == ["t1", "t2", "t3"]
    assert syms == ["A", "B"]
    assert closes[0] == [100.0, 50.0]


def test_a_missing_bar_DROPS_the_timestamp_it_is_never_filled_forward():
    """Forward-filling invents a zero return, which reads to the instrument as real, perfectly quiet
    data and biases every correlation touching it. Dropping the sample is honest."""
    short = _bars(("t1", 50.0), ("t3", 51.0))          # t2 absent
    ts, _, closes = mf.aligned_closes({"A": A, "B": short})
    assert ts == ["t1", "t3"]                          # t2 gone, not carried
    assert len(closes) == 2


def test_disjoint_series_are_REFUSED_not_padded():
    with pytest.raises(mf.FrameError, match="no common timestamps"):
        mf.aligned_closes({"A": A, "B": _bars(("x1", 1.0), ("x2", 2.0))})


def test_time_order_is_preserved_regardless_of_input_order():
    """The entroptics Screen is ordered — a shuffle destroys coherence — so rows must come out sorted
    by timestamp, not in whatever order the bars arrived."""
    scrambled = _bars(("t3", 102.0), ("t1", 100.0), ("t2", 101.0))
    ts, _, closes = mf.aligned_closes({"A": scrambled, "B": B})
    assert ts == ["t1", "t2", "t3"]
    assert closes[0][0] == 100.0 and closes[-1][0] == 102.0


def test_symbol_order_is_deterministic():
    """Column order must not depend on dict iteration, or two hosts read different matrices."""
    _, syms, _ = mf.aligned_closes({"Z": A, "A": B})
    assert syms == ["A", "Z"]


def test_empty_and_unusable_series_are_refused():
    with pytest.raises(mf.FrameError, match="nothing to frame"):
        mf.aligned_closes({})
    with pytest.raises(mf.FrameError, match="no usable"):
        mf.aligned_closes({"A": [{"ts": "t1"}]})       # no close


# ── returns, not levels ───────────────────────────────────────────────────────────────────────────

def test_log_returns_are_taken_not_price_levels():
    """Levels are non-stationary and their correlation is dominated by trend, so a read over levels
    measures drift rather than structure."""
    rows = mf.log_returns([[100.0, 50.0], [101.0, 50.5]])
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(0.00995, abs=1e-4)
    assert rows[0][1] == pytest.approx(0.00995, abs=1e-4)   # same 1% move


def test_one_bar_cannot_form_a_return():
    with pytest.raises(mf.FrameError, match="at least 2 bars"):
        mf.log_returns([[100.0]])


@pytest.mark.parametrize("bad", [[[100.0], [0.0]], [[0.0], [100.0]], [[100.0], [-1.0]]])
def test_non_positive_close_is_REFUSED_not_clamped(bad):
    """Clamping would fabricate a return. A non-positive close is bad data or a different
    instrument — either way the frame must not paper over it."""
    with pytest.raises(mf.FrameError, match="non-positive close"):
        mf.log_returns(bad)


# ── provenance travels with the matrix ────────────────────────────────────────────────────────────

def test_frame_reports_what_it_was_built_from_including_what_it_dropped():
    """A read whose frame cannot be reconstructed is not a measurement."""
    short = _bars(("t1", 50.0), ("t3", 51.0))
    frame = mf.market_frame({"A": A, "B": short})
    assert frame["symbols"] == ["A", "B"]
    assert frame["bars_offered"] == {"A": 3, "B": 2}
    assert frame["bars_aligned"] == 2
    assert frame["returns"] == 1
    assert frame["dropped_by_alignment"] == {"A": 1, "B": 0}


def test_timestamps_line_up_with_returns_not_with_closes():
    """N closes give N-1 returns; the timestamp list must be the return index or every downstream
    join is off by one."""
    frame = mf.market_frame({"A": A, "B": B})
    assert len(frame["rows"]) == len(frame["timestamps"]) == 2


# ── the read itself, through the one instrument ─────────────────────────────────────────────────────
#
# These two are a matched pair and only mean something together. "read_market returned a number" is a
# check that cannot fail. What must hold is that the number discriminates: a basket built with a shared
# driver must read as structured, and a basket built without one must not. The second test is the load-
# bearing one — without it, an instrument hard-wired to answer "1" would pass the first.

def _walk(rets, p0=100.0):
    px, out = p0, []
    for i, r in enumerate(rets):
        px *= math.exp(r)
        out.append({"ts": "t%04d" % i, "close": px})
    return out


def _basket(*, shared, n=240, seed=7):
    """`shared=True` puts one common driver behind every symbol (σ 5× the idiosyncratic noise);
    `shared=False` gives each symbol independent noise only."""
    rnd = random.Random(seed)
    drv = [rnd.gauss(0, 0.01) for _ in range(n)]
    out = {}
    for j, (sym, p0) in enumerate([("AAA", 100.0), ("BBB", 50.0), ("CCC", 12.5)]):
        idio = [rnd.gauss(0, 0.002) for _ in range(n)]
        rets = [(drv[i] if shared else rnd.gauss(0, 0.01)) + idio[i] for i in range(n)]
        out[sym] = _walk(rets, p0)
    return out


@pytest.fixture(autouse=True, scope="module")
def _needs_numpy():
    pytest.importorskip("numpy", reason="the instrument reads through numpy")


def test_a_shared_driver_is_SEEN_as_one_mode_holding_most_of_the_energy():
    r = mf.read_market(_basket(shared=True), draws=200, read=INSTRUMENT)
    assert r["k_signal"] >= 1                      # the driver clears the null
    assert r["top_share"] > 0.9                    # and it owns the basket's energy
    assert r["contrast"] > 1.0                     # lambda_1 stands above the noise floor
    assert r["frame"]["returns"] == 239            # provenance rode along


def test_independent_symbols_do_NOT_read_as_a_shared_mode():
    """The negative control. Three unrelated walks have no common driver, so no mode may own the
    basket. `optics.coherence()` is not the right read for this discrimination, since it is a
    function of feature count rather than of structure; keep this test adversarial — if it ever
    passes at the same value as the test above, the read has stopped measuring structure and every
    number downstream of it is decoration."""
    driven = mf.read_market(_basket(shared=True), draws=200, read=INSTRUMENT)
    alone = mf.read_market(_basket(shared=False), draws=200, read=INSTRUMENT)
    assert alone["top_share"] < driven["top_share"] - 0.4   # a wide separation, not a hair
    assert alone["top_share"] < 0.6                         # no mode owns the basket
    assert alone["k_signal"] < driven["k_signal"] or alone["k_signal"] == 0


def test_the_concentration_read_is_on_the_FEATURE_axis_not_the_ORDERED_axis():
    """Pins why `top_share` is the read here and `optics.coherence` (strehl) is not.

    strehl asks "are the rows all the same thing" — on the ordered axis. A driven basket's rows are
    each a different scalar multiple of the common mode (the driver flips sign every bar), so strehl
    correctly sees no row coherence while `top_share` correctly sees the shared driver. If this ever
    starts agreeing, someone has changed which axis a read is taken on.

    Stated without a hardcoded floor, because strehl's disordered floor depends on min(T, F) — for
    this 3-symbol basket it sits near 0.52, not near 0. The invariant is the comparison against its
    own floor at the same shape: adding a driver moves strehl barely at all and `top_share` enormously.
    """
    driven, noise = _basket(shared=True), _basket(shared=False)

    s_driven = INSTRUMENT.coherence(mf.market_frame(driven)["rows"])  # "are the rows the same thing"
    s_noise = INSTRUMENT.coherence(mf.market_frame(noise)["rows"])
    assert abs(s_driven - s_noise) < 0.1        # ordered axis: the driver is invisible here

    t_driven = mf.read_market(driven, draws=200, read=INSTRUMENT)["top_share"]       # "do the columns share a mode"
    t_noise = mf.read_market(noise, draws=200, read=INSTRUMENT)["top_share"]
    assert t_driven > 0.9 and t_noise < 0.6     # feature axis: the driver is obvious here
    assert t_driven - t_noise > 10 * abs(s_driven - s_noise)        # which axis carries it, quantified

    assert "coherence" not in mf.read_market(driven, draws=200, read=INSTRUMENT)     # ambiguous name off the surface


def test_the_null_is_a_computed_null_not_a_threshold():
    """`k_certain` must be able to come back False. A read that is always certain has no null behind
    it — it is an argmax wearing a null's clothes ([[one-resolution-not-thresholds]])."""
    r = mf.read_market(_basket(shared=True), draws=200, read=INSTRUMENT)
    assert r["null"] == "permutation(draws=200)"
    assert isinstance(r["k_certain"], bool)
    assert r["k_margin_last"] is not None and r["k_margin_next"] is not None


# ── the instrument slot (plan item D10) ───────────────────────────────────────────────────────────

def _no_instrument_anywhere():
    """Empty both resolution steps for the duration of a block — the injected keyword is simply not
    passed, and the process default is cleared and restored.

    Clearing the process default is required for the refusal tests below to mean anything:
    `ember/__init__.py` registers `ember.optics` as the process default at import, and this file
    imports it above in the same process, so omitting only the keyword would resolve the default and
    report a passing refusal test that never actually saw a refusal."""
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


def test_with_NO_instrument_the_read_REFUSES_at_the_point_of_measurement():
    """With no instrument, the read must raise `InstrumentRequired` (503, naming the member and the
    operation that wanted it) rather than return a `k_signal` of 0, `None`, or an empty read. The
    refusal happens at the point of measurement, never at import: this module is importable, and its
    frame half usable, on a host that cannot measure at all."""
    from prism.instrument import InstrumentRequired
    with _no_instrument_anywhere():
        try:
            mf.read_market(_basket(shared=True), draws=200)
        except InstrumentRequired as e:
            assert e.contract == "read"
            assert e.member == "correlated_null"      # the first member the read reaches for
            assert "read_market" in (e.at or ""), (
                "the refusal must name the operation, not just the member: %r" % (e.at,))
            assert e.http_status == 503
        else:
            raise AssertionError(
                "read_market returned a read with no instrument injected — nothing measured it, so "
                "whatever it returned was fabricated")


def test_a_partial_instrument_says_WHICH_member_it_lacks():
    """Pins the constrained-host case, not the unwired one. `prism.instrument` checks per member at
    the point of use, so a store that can draw a null and take a read but cannot answer `scales` must
    be told apart from an empty slot by what the refusal says."""
    from prism.instrument import InstrumentRequired

    class _NoScales:
        correlated_null = staticmethod(INSTRUMENT.correlated_null)
        read_ordered = staticmethod(INSTRUMENT.read_ordered)

    with _no_instrument_anywhere():
        try:
            mf.read_market(_basket(shared=True), draws=200, read=_NoScales())
        except InstrumentRequired as e:
            assert e.member == "scales"
            assert "read_ordered" in str(e), (
                "a partial instrument must be told what it DOES fill, or an operator cannot tell a "
                "constrained host from an unwired one: %s" % e)
        else:
            raise AssertionError("a partial instrument measured something it cannot measure")


def test_the_FRAME_still_builds_with_no_instrument_at_all():
    """The control for the two tests above. If `read_market` refused unconditionally, or if
    `market_frame` were dragged behind the instrument slot, both refusal tests would pass while the
    module had simply been broken. Aligning bars, dropping unshared timestamps, and differencing to
    returns are structural facts about the bars, and a host with no instrument answers all of them."""
    with _no_instrument_anywhere():
        frame = mf.market_frame(_basket(shared=True))
        assert frame["returns"] == 239 and frame["symbols"] == ["AAA", "BBB", "CCC"]

    # …and the injected read still works, which is what stops "it refuses" being satisfied by code
    # that refuses everything. Same basket, same draws, a real discriminating number.
    r = mf.read_market(_basket(shared=True), draws=200, read=INSTRUMENT)
    assert r["top_share"] > 0.9 and r["k_signal"] >= 1
