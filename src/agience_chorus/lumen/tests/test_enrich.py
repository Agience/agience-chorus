"""seek — the self-directed enrichment trigger, pinned: entropy against the observer's own mean."""
import pytest

try:                                             # robust: cross-persona host vs in-persona process
    from agience_chorus.lumen.enrich import Need, SelfMean, result_entropy, seek   # (chorus/src on path)
except ImportError:
    from agience_chorus.lumen.enrich import Need, SelfMean, result_entropy, seek         # (lumen/ on path)

# The test is the host (D10). `result_entropy` takes a `conservation=` slot against
# `prism.instrument.Conservation` and raises `InstrumentRequired` when the slot cannot fill
# `entropy_bits`. A full node fills that member with `ember.optics`, so this file imports it and
# hands it over at every call. The import belongs here and not in the module under test, and every
# call below is explicit rather than leaning on the process default — a suite that only passed
# because some other module had imported the instrument first would not be green by accident.
from ember import optics as INSTRUMENT

_C = {"conservation": INSTRUMENT}


def test_peaked_result_is_low_entropy_flat_is_high():
    peaked = result_entropy([10.0, 0.2, 0.1, 0.1], **_C)   # one candidate dominates -> resolved
    flat = result_entropy([1.0, 1.0, 1.0, 1.0], **_C)      # nothing distinguishes -> undecided
    assert 0.0 <= peaked < flat <= 1.0
    assert abs(flat - 1.0) < 1e-9                      # perfectly flat is maximal


def test_single_candidate_has_no_entropy():
    assert result_entropy([5.0], **_C) == 0.0          # nothing to be undecided between
    assert result_entropy([], **_C) == 0.0


def test_bad_readings_are_dropped_not_clamped():
    # a negative or non-finite weight is not a small weight; it is not a reading at all
    assert result_entropy([1.0, 1.0, -3.0], **_C) == result_entropy([1.0, 1.0], **_C)
    assert result_entropy([1.0, 1.0, float("nan")], **_C) == result_entropy([1.0, 1.0], **_C)


# ── D10 · the injected accountant ───────────────────────────────────────────────────────────────
# An entropy accountant resolved by importing the instrument inside the function would report an
# ImportError on a node that does not carry it, at the moment a Need is being weighed. Worse than
# the ImportError is the alternative of catching it and returning 0.0: 0.0 is a real reading here
# (one candidate, or a perfectly concentrated result set), so it would make an unequipped host look
# maximally decisive, and `seek` would silently stop minting Needs while reporting nothing wrong.
# These tests exist so neither can happen quietly.

def _no_instrument_anywhere():
    """Empties the process-wide slot for the duration of a `with`, then puts back exactly what was
    there. `prism.instrument`'s default is process state — `agience-ember/src/ember/__init__.py`
    registers `ember.optics` into it at import, and this whole suite runs in one process, so a test
    that cleared it and walked away would leave every later measurement in the run with no
    instrument to measure with."""
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


def test_with_NO_accountant_the_entropy_REFUSES_at_the_point_of_measurement():
    """Never 0.0. `InstrumentRequired`, 503, naming the contract, the member and the operation.

    0.0 is the one value that must never be fabricated here, because it is a value this function
    legitimately returns: it means "one candidate" or "perfectly concentrated". A host that cannot
    measure returning it would be publishing total certainty, and `seek` would then read a maximally
    resolved result and withhold the Need — a capacity fact rendered as a verdict on the answer."""
    from prism.instrument import InstrumentRequired
    with _no_instrument_anywhere():
        for call in (lambda: result_entropy([1.0, 1.0, 1.0, 1.0]),
                     lambda: seek("murky", [1.0, 1.0, 1.0, 1.0], SelfMean())):
            try:
                call()
            except InstrumentRequired as e:
                assert e.contract == "conservation", (
                    "entropy_bits is a Conservation member, not a Read one: %r" % (e.contract,))
                assert e.member == "entropy_bits"
                assert "lumen.enrich.result_entropy" in (e.at or ""), (
                    "the refusal must name the operation, not just the member: %r" % (e.at,))
                assert e.http_status == 503
            else:
                raise AssertionError(
                    "an entropy came back with no accountant injected — nothing measured it, so "
                    "whatever it returned was fabricated")


def test_a_partial_accountant_says_WHICH_member_it_lacks():
    """The constrained host, not the unwired one — a real deployment rather than a hypothetical:
    `prism.conservation` is exactly this shape. It stands on numpy, fills `energy` and `PathLedger`,
    and cannot fill `entropy_bits`, whose floor is entroptics, which prism may never import. It must
    be told apart from an empty slot by what `InstrumentRequired` says."""
    from prism.instrument import InstrumentRequired
    from prism import conservation as NUMPY_ONLY

    with _no_instrument_anywhere():
        with pytest.raises(InstrumentRequired) as ei:
            result_entropy([1.0, 1.0, 1.0], conservation=NUMPY_ONLY)
    assert ei.value.member == "entropy_bits"
    assert "energy" in str(ei.value) and "PathLedger" in str(ei.value), (
        "a partial accountant must be told what it DOES fill, or an operator cannot tell a "
        "constrained host from an unwired one: %s" % ei.value)


def test_the_STRUCTURAL_answers_still_run_with_no_accountant_at_all():
    """The control for the two above. If `result_entropy` raised `InstrumentRequired`
    unconditionally, both no-instrument tests above would pass while the function had simply been
    broken. "Fewer than two positive weights" is a structural fact — there is nothing to be
    undecided between — and a host with no instrument answers it correctly."""
    with _no_instrument_anywhere():
        assert result_entropy([]) == 0.0
        assert result_entropy([5.0]) == 0.0
        assert result_entropy([1.0, -3.0, float("nan")]) == 0.0   # one reading survives the filter


def test_the_injected_accountant_MEASURES_and_the_value_did_not_move():
    """The control that keeps the no-instrument tests from being satisfied by code that never
    measures anything.

    With the accountant injected the same calls measure, and they measure the same numbers to the
    full float64 repr: `ember.optics.entropy_bits(w) / log2(n)`. A conversion that changed the value
    would change which results mint a Need, which is the whole behaviour of this module."""
    assert result_entropy([10.0, 0.2, 0.1, 0.1], **_C) == 0.14644284475577451
    assert result_entropy([1.0, 1.0, 1.0, 1.0], **_C) == 1.0
    assert result_entropy([3.0, 1.0, 1.0], **_C) == 0.8649735207179273
    assert result_entropy([10.0, 0.1, 0.1], **_C) == 0.10021741342150445


def test_a_newborn_has_no_resolvable_bar_so_it_does_not_thrash():
    """There is no typed `warmup` constant: the bar is the standard error of the observer's own
    measured spread. A newborn does not mint a Need on its first flat result, because the excess
    cannot clear its own standard error, not because a count says so.

    Negative control: the results are still observed (the mean must see everything, or the bar
    drifts toward only the bad ones), and `resolution()` tightens as history accumulates — otherwise
    "no bar" would be permanent and the trigger could never fire at all."""
    m = SelfMean()
    assert not hasattr(m, "warmup"), "warmup came back"
    fired = [seek("q%d" % i, [1.0, 1.0, 1.0], m, **_C) for i in range(4)]
    assert all(f is None for f in fired)               # no resolvable bar -> no needs minted
    assert m.count == 4                                # but every result is observed


def test_one_observation_is_not_a_resolvable_bar_whatever_its_value():
    """A single observation must not resolve any difference, at any value. The sample variance is
    undefined at count = 1 (no degrees of freedom), so `resolution()` reads `inf` regardless of
    what was observed — not the standard error of a proportion (`sqrt(p(1-p)/k)`), which would read
    zero at the entropy boundary (1.0) and claim infinite resolving power from a single sample."""
    for value in (1.0, 0.0, 0.5):
        m = SelfMean()
        m.observe(value)
        assert m.resolution() == float("inf"), "one sample claimed a resolution at %r" % (value,)
        assert not m.ready()


def test_the_bar_tightens_with_history_on_one_distribution():
    """The negative control for `resolution()` being a measurement at all: more of the same kind of
    result must narrow it, or "no bar" is permanent and the trigger can never fire.

    Measured on one distribution deliberately, so what moves is the count, not the mean: mixing
    distributions would let the mean drift do the narrowing instead of the sample size, and the
    assertion would pass without the count doing any work."""
    m = SelfMean()
    stream = [0.4, 0.6] * 32                            # a stable spread, so only `count` varies
    for e in stream[:8]:
        m.observe(e)
    wide = m.resolution()
    assert 0.0 < wide < float("inf")                    # a real reading, not a degenerate one
    for e in stream[8:]:
        m.observe(e)
    assert m.resolution() < wide, "the bar never tightened — it is not a measurement"


def test_fires_only_when_above_the_observers_OWN_mean():
    m = SelfMean()
    for _ in range(6):                                  # a history of well-resolved answers
        seek("routine", [10.0, 0.1, 0.1], m, **_C)
    assert m.ready() and m.mean < 0.5
    # a resolved answer does not fire
    assert seek("resolved", [10.0, 0.1, 0.1], m, **_C) is None
    # an undecided one does
    n = seek("murky topic", [1.0, 1.0, 1.0, 1.0], m, **_C)
    assert isinstance(n, Need)
    assert n.topic == "murky topic" and n.margin > 0.0
    assert "above own mean" in n.why and "resolution" in n.why


def test_the_bar_auto_calibrates_with_development():
    """A newborn (high mean entropy) tolerates vagueness a mature observer flags."""
    newborn = SelfMean()
    for _ in range(6):
        seek("vague", [1.0, 1.0, 1.0, 1.0], newborn, **_C)   # everything is vague early on
    mature = SelfMean()
    for _ in range(6):
        seek("sharp", [10.0, 0.1, 0.1], mature, **_C)        # this one usually resolves cleanly
    middling = [3.0, 1.0, 1.0]
    assert seek("x", list(middling), newborn, **_C) is None   # below the newborn's mean: unremarkable
    assert seek("x", list(middling), mature, **_C) is not None  # above the mature mean: enrich
    assert newborn.mean > mature.mean


def test_every_result_is_observed_so_the_bar_cannot_eat_itself():
    m = SelfMean()                                  # no `warmup` constant — the bar is the measured resolution
    for _ in range(3):
        seek("a", [10.0, 0.1], m, **_C)
    before = m.count
    seek("b", [1.0, 1.0, 1.0], m, **_C)                   # fires, and is still recorded
    assert m.count == before + 1


def test_need_carries_the_measurement_for_audit_and_re_measure():
    m = SelfMean()                                  # no `warmup` constant — the bar is the measured resolution
    for _ in range(4):
        seek("routine", [10.0, 0.1, 0.1], m, **_C)
    n = seek("quantum error correction", [1.0, 1.0, 1.0], m, gap=0.83, **_C)
    assert n is not None
    assert n.entropy > n.self_mean and abs(n.margin - (n.entropy - n.self_mean)) < 1e-6
    assert n.gap == 0.83                               # the measured gap rides along for re-measure
