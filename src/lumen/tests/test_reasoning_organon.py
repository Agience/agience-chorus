"""lumen's own reasoning organon (op.reason).
The module imports cleanly (numpy plus the injected instrument's contract only),
`register_reasoning_operators` registers `op.reason` through the fitness substrate, and the
`_NUMROW` matcher parses a pasted numeric series. The retrieval half is sage's (its tests live in
`sage/tests`).

The test is the host (D10). `reasoning` does not open `from ember import optics`; it resolves
`prism.instrument.Dynamics` and `prism.instrument.Read`, and with neither slot filled it raises
`InstrumentRequired` rather than reporting `NON_COMPACT`. That distinction matters: an unfilled slot
folded into a regime reports a capacity fact as a measurement about the data.

Both spellings of "a host" are exercised, because both are live:

  * `import ember` registers `ember.optics` as the process default — how `lumen/conversation.py`
    and `lumen/server.py` reach the instrument today, since neither passes a slot. The import lives
    here and not in the module under test, so the process default is exercised rather than assumed.
  * `ReasoningRouter(dynamics=…, read=…)` is the explicit keyword, pinned at the bottom.

This is also what makes the file pass on its own: the organon has no module-level import of its own
that would register a host as a side effect of merely importing it.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import ember  # noqa: F401  — the host: registers `ember.optics` as the process default at import

# the persona dir on sys.path so its local organon imports by bare name (the persona load pattern)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reasoning  # noqa: E402


class _Capture:
    """A store that records what registration would write. Nothing persists."""

    def __init__(self):
        self.docs = {}

    def get_artifact(self, aid):
        return self.docs.get(aid)

    def put_artifact(self, doc):
        self.docs[doc["id"]] = dict(doc)
        return doc


def test_reasoning_registers_op_reason():
    store = _Capture()
    n = reasoning.register_reasoning_operators(store)
    assert n == 1
    doc = store.docs["op.reason"]
    assert doc["content_type"] == "application/vnd.agience.operator+json"
    assert "lumen tekton" in doc["content"]


def test_reasoning_parse_trajectory_numrow_restored():
    # _NUMROW / _re must be defined at module scope for this to succeed — a latent NameError
    # otherwise; pinned here.
    X = reasoning.parse_trajectory("1.0 2.0\n2.0 4.0\n3.0 6.0\n4.0 8.0\n5.0 10.0\n6.0 12.0")
    assert X is not None and X.shape == (6, 2)


def _planted_rotation(r: float, theta: float = 0.4, T: int = 64, t0: int = 0):
    """A scaled rotation — the paper §7 exact-recovery shape. The generator is written out here,
    independently of anything the router does, so it can serve as the oracle: the true continuation
    is computable in closed form and is not produced by the mechanism under test (§38)."""
    import numpy as np
    t = np.arange(t0, t0 + T)
    return np.stack([r ** t * np.cos(theta * t), r ** t * np.sin(theta * t)], axis=1)


def test_reasoning_router_refuses_or_answers_without_raising():
    """Asserts only that the router returns one of its two regimes without raising. A check against
    the complete set of regimes cannot fail regardless of correctness
    ([[verification-that-cannot-fail]]), so this alone is L0 evidence, not a correctness check — the
    two tests below assert against a planted compact case and a planted non-compact case, so a
    router that always answered one regime would fail there."""
    import numpy as np
    t = np.linspace(0, 6.0, 64)
    X = np.stack([np.sin(t), np.cos(t)], axis=1)
    res = reasoning.ReasoningRouter().reason([X], X, horizon=4, dt=1.0)
    assert res.regime in (reasoning.DETERMINISTIC, reasoning.NON_COMPACT)
    if res.regime == reasoning.NON_COMPACT:
        assert res.forecast is None          # NON_COMPACT never pairs with a fabricated forecast


def test_a_planted_compact_system_is_answered_and_the_forecast_is_EXACT():
    """The oracle: a scaled rotation is a linear system whose continuation is known in closed form,
    so the forecast can be scored against an answer computed without the router (§38: expected
    results computed independently of the mechanism under test).

    This guards against the router reporting `NON_COMPACT` for a system it has already resolved and
    whose operator it has already recovered exactly — which reads at the call site as a measurement
    about the data, not a capacity fact about the router.

    `1e-9` is not a tuned tolerance: paper §7 puts the recovery at machine epsilon (measured 1.4e-15
    here) and §5 rolls out by exact eigenvalue powers, so this is six orders of margin over the
    measured value and would still fail on any fit that was merely approximate."""
    import numpy as np
    r, theta, T = 0.90, 0.4, 64
    X = _planted_rotation(r, theta, T)
    res = reasoning.ReasoningRouter().reason([X], X, dt=1.0)

    assert res.regime == reasoning.DETERMINISTIC, (
        "a planted linear system must resolve compact, not refuse (K_signal=%s)" % res.complexity)
    assert res.forecast is not None
    assert 0 < res.complexity, "DETERMINISTIC means 0 < K < F — K=0 is 'nothing resolved'"

    fc = np.asarray(res.forecast)
    truth = _planted_rotation(r, theta, T=fc.shape[0], t0=T)      # the ORACLE, not the router
    assert fc.shape == truth.shape
    rel = np.abs(fc - truth).max() / np.abs(truth).max()
    assert rel < 1e-9, "forecast is not the planted continuation (rel err %.3g)" % rel


def test_the_horizon_is_read_off_the_operator_and_shortens_as_the_mode_decays_faster():
    """The horizon is `ℓ(m) = ⌈ln(1/ε)/(−ln m)⌉` (Def 9.4): a function of the measured decay rate, so
    a faster-decaying mode predicts for fewer steps. A constant would pass every other assertion in
    this file; this is the one it cannot pass.

    Negative control, both directions: an undamped system (`|μ| = 1`, nothing ever decays to the
    floor) and pure noise (nothing rises above the floor to decay from) both carry no forecast — so
    "answers everything" fails here just as "answers nothing" would fail above."""
    import numpy as np
    slow = reasoning.ReasoningRouter().reason([_planted_rotation(0.99)], _planted_rotation(0.99), dt=1.0)
    fast = reasoning.ReasoningRouter().reason([_planted_rotation(0.90)], _planted_rotation(0.90), dt=1.0)
    assert slow.regime == fast.regime == reasoning.DETERMINISTIC
    assert len(np.asarray(slow.forecast)) > len(np.asarray(fast.forecast)), (
        "a slower-decaying mode must support a LONGER horizon — the horizon is not being read off "
        "the operator (slow=%d, fast=%d)"
        % (len(np.asarray(slow.forecast)), len(np.asarray(fast.forecast))))

    t = np.arange(64)
    undamped = np.stack([np.cos(0.4 * t), np.sin(0.4 * t)], axis=1)     # |μ| = 1 exactly
    res = reasoning.ReasoningRouter().reason([undamped], undamped, dt=1.0)
    assert res.regime == reasoning.NON_COMPACT and res.forecast is None

    noise = np.random.default_rng(0).standard_normal((64, 2))
    res = reasoning.ReasoningRouter().reason([noise], noise, dt=1.0)
    assert res.regime == reasoning.NON_COMPACT and res.forecast is None
    assert res.complexity == 0, "noise must resolve NOTHING, not 'one thing'"


# ── D10 · the two instrument slots ────────────────────────────────────────────────────────────────

def _no_instrument_anywhere():
    """Empties both resolution steps for the duration of a block, then puts back exactly what was
    there.

    Clearing the process default is what makes a no-instrument test real: this file imports `ember`
    at module scope and the whole suite runs in one process, so a test that only omitted the keyword
    would resolve the default, measure perfectly, and pass without ever exercising the
    no-instrument path."""
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


def test_with_NO_instrument_reason_REFUSES_it_does_not_report_NON_COMPACT():
    """Pins that an unfilled instrument slot raises rather than reports a regime. `_lag_for` and
    `complexity_regime` both end in a broad `except Exception` that returns "no lag" / `NON_COMPACT`.
    A slot resolved inside either of those would have its `InstrumentRequired` caught there and
    published as a regime — the router would answer
    "this domain is not compact" on a host that never looked at the domain at all, and the
    certificate below would then record `mass = 0.0, unverified` as a measured verdict.

    So the members are resolved outside every `try`, and `InstrumentRequired` reaches the caller
    naming the contract, the member, and the operation — never `NON_COMPACT`, never at import."""
    import numpy as np
    from prism.instrument import InstrumentRequired
    X = _planted_rotation(0.90)

    with _no_instrument_anywhere():
        try:
            reasoning.ReasoningRouter().reason([X], X, dt=1.0)
        except InstrumentRequired as e:
            assert e.contract == "dynamics", (
                "the propagator fit is a DYNAMICS member — a set of vectors has no lag, so a "
                "corpus-domain embodiment fills none of it and must be able to say so per contract")
            assert e.member in reasoning_dynamics_members()
            assert "lumen.reasoning" in (e.at or "")
            assert e.http_status == 503
        else:
            raise AssertionError(
                "reason() returned a regime with no instrument injected — nothing measured the "
                "trajectory, so whatever it reported about the DATA was fabricated")

        # …and the structural half of the module still works with no instrument at all: parsing a
        # pasted table and registering the operator are not measurements.
        assert reasoning.parse_trajectory("1 2\n2 4\n3 6\n4 8\n5 10\n6 12") is not None
        assert reasoning.register_reasoning_operators(_Capture()) == 1

    # the control: injected explicitly (resolution step 1, not the process default), the same call
    # measures — so this passing is not explained by a router that reports NON_COMPACT for every
    # input.
    import ember.optics as _ap
    res = reasoning.ReasoningRouter(dynamics=_ap, read=_ap).reason([X], X, dt=1.0)
    assert res.regime == reasoning.DETERMINISTIC and res.forecast is not None
    fc = np.asarray(res.forecast)
    truth = _planted_rotation(0.90, T=fc.shape[0], t0=64)
    assert np.abs(fc - truth).max() / np.abs(truth).max() < 1e-9


def reasoning_dynamics_members():
    from prism.instrument import DYNAMICS_MEMBERS
    return DYNAMICS_MEMBERS


def test_the_READ_slot_is_separate_from_the_DYNAMICS_slot():
    """Two contracts, and this is the one file in chorus that reaches both. `_operator_horizon`
    reads `contrast` = λ₁/edge, a statement about the frame with no lag in it — a `Read` member. A
    host that fills `Dynamics` and not `Read` is a real, partial deployment, and it raises
    `InstrumentRequired` naming `read_ordered` rather than anything in the dynamics family.

    Folding `read_ordered` into the dynamics slot would pass every other test here and would
    silently make `Read` un-fillable on its own."""
    from prism.instrument import InstrumentRequired
    import ember.optics as _ap
    X = _planted_rotation(0.90)

    class _DynamicsOnly:                       # fills all five Dynamics members and no Read member
        decay_profile = staticmethod(_ap.decay_profile)
        resolution_limit = staticmethod(_ap.resolution_limit)
        embed = staticmethod(_ap.embed)
        fit_dynamics = staticmethod(_ap.fit_dynamics)
        dynamics_state = staticmethod(_ap.dynamics_state)

    with _no_instrument_anywhere():
        try:
            reasoning.ReasoningRouter(dynamics=_DynamicsOnly()).reason([X], X, dt=1.0)
        except InstrumentRequired as e:
            assert e.contract == "read" and e.member == "read_ordered"
            assert "_operator_horizon" in (e.at or "")
        else:
            raise AssertionError(
                "the horizon was read with no `Read` filled — either the two slots have been "
                "collapsed into one, or the refusal was swallowed into NON_COMPACT")

        # …and the mirror: `Read` alone cannot fit a propagator.
        class _ReadOnly:
            read_ordered = staticmethod(_ap.read_ordered)

        try:
            reasoning.ReasoningRouter(read=_ReadOnly()).reason([X], X, dt=1.0)
        except InstrumentRequired as e:
            assert e.contract == "dynamics"
        else:
            raise AssertionError("a read-only instrument fitted a propagator")


def test_the_recorded_METHOD_names_the_instrument_that_actually_answered():
    """`method` is written onto the turn artifact and quoted in the certificate as "the instrument
    that decided", so a hardcoded name there would go on naming one module on a host running
    something else. Read off the member actually called.

    `method` is read off `__module__`, so it follows whichever module actually answered rather than
    naming a fixed one."""
    import ember.optics as _ap
    X = _planted_rotation(0.90)

    class _Wrapped:                            # a distinct module identity, same arithmetic
        decay_profile = staticmethod(_ap.decay_profile)
        resolution_limit = staticmethod(_ap.resolution_limit)
        embed = staticmethod(_ap.embed)
        fit_dynamics = staticmethod(_ap.fit_dynamics)
        dynamics_state = staticmethod(_ap.dynamics_state)

    direct = reasoning.ReasoningRouter(dynamics=_ap, read=_ap).reason([X], X, dt=1.0)
    assert direct.method == "ember.optics"     # the instrument, named because it is what answered

    # the control: `fit_dynamics` here is `ember.optics`'s own function object, so its `__module__`
    # is still `ember.optics` — the honest answer, since that is the code that ran. `method` must
    # track the slot rather than staying fixed, so the discriminating case is an instrument whose
    # members are its own, below.
    class _Own:
        @staticmethod
        def decay_profile(W):
            return _ap.decay_profile(W)

        @staticmethod
        def resolution_limit(p):
            return _ap.resolution_limit(p)

        @staticmethod
        def embed(X_, d):
            return _ap.embed(X_, d)

        @staticmethod
        def fit_dynamics(X_, **kw):
            return _ap.fit_dynamics(X_, **kw)

        @staticmethod
        def dynamics_state(n, **kw):
            return _ap.dynamics_state(n, **kw)

    own = reasoning.ReasoningRouter(dynamics=_Own(), read=_ap).reason([X], X, dt=1.0)
    assert own.regime == reasoning.DETERMINISTIC
    assert own.method != "ember.optics", (
        "`method` is a constant again — it names ember.optics for an instrument that is not it")
    assert own.method == _Own.fit_dynamics.__module__


def test_the_horizon_may_not_RUN_PAST_the_evidence_it_was_fitted_from():
    """Found on real data, not on synthesis, which is why it is pinned here.

    `_decay_margin` is a strict inequality on a float, so a dominant mode at `1 - 1.7e-7` passes it.
    `-ln(m)` is then ~1.7e-7 and the horizon formula returns 8,294,607 steps. That is a measurement,
    not a hypothetical: it is `keyed_coverage` from the node's own `metrics.jsonl` — a
    bounded ratio that sits at 1.0 between shifts — read over its real 2,298 rows, so the operator
    claimed to see 3,609x further than it had ever been observed. The document's §7.3 asks exactly
    for this ("validate the rank test on real series … the synthetic separation is perfect, which
    usually means the test is too clean"), and the synthetic level shift does NOT exhibit it: its
    horizon is 642 steps from 4,038 rows, comfortably inside the evidence.

    The fixture is a near-unit-root random walk, which reaches the same state at test size — raw
    horizon 845 from 433 fitted transitions — so the suite does not depend on a path outside the
    repo. `T` is read off the frame, so the bound is the extent of the evidence rather than a
    ceiling anyone chose."""
    import numpy as np
    r = np.random.default_rng(0)
    T = 512
    x = np.zeros(T)
    for i in range(1, T):
        x[i] = 0.99999 * x[i - 1] + 0.01 * r.standard_normal()      # a random walk, near unit root
    X = x.reshape(-1, 1)

    res = reasoning.ReasoningRouter().reason([X], X, dt=1.0)
    assert res.regime == reasoning.NON_COMPACT, (
        "a near-unit-root walk was answered with a horizon longer than its own history "
        "(|mu|=%s, horizon=%s)" % (res.margin, res.horizon))
    assert res.forecast is None
    assert res.why and "fitted from" in res.why, (
        "refused, but not by the horizon bound (why=%r)" % res.why)
    assert res.margin is not None and 0.0 < res.margin < 1.0, (
        "this fixture must PASS the decay gate — otherwise the horizon bound is never consulted "
        "and the assertion above passes for free (|mu|=%s)" % res.margin)


def test_a_NON_DECAYING_operator_is_still_rolled_when_the_caller_STATES_a_horizon():
    """The counter-test, and it exists because the opposite was briefly implemented here.

    `_decay_margin` was made a gate on both paths, on the theory that a non-decaying dominant mode
    means a drift rather than a law and so should never be forecast. That theory is false, and real
    data said so: scored out-of-sample at h=10 on the node's own `metrics.jsonl`, the
    rollouts of exactly those non-decaying operators land within 0.002%–0.056% median absolute
    percentage error, and on `ts` — the wall-clock timestamp — the forecast is exact. Gating on `m`
    threw away correct answers to protect against nothing.

    So the rule is: `m` decides whether a horizon can be DERIVED, not whether the frame may be
    rolled. A ramp has no derivable horizon (nothing decays, so `ℓ` has no value) and is refused
    with `horizon=None`; hand it a horizon and it must be answered, and answered well.

    The oracle is arithmetic, not the router: a ramp's continuation is `a + b·t`, computed here."""
    import numpy as np
    T, a, b = 256, 3.0, 0.25
    t = np.arange(T)
    X = (a + b * t).reshape(-1, 1)                     # a pure ramp: |mu| >= 1, nothing decays

    # with no horizon stated there is no rate to read one off — a refusal about the HORIZON
    none_h = reasoning.ReasoningRouter().reason([X], X, dt=1.0)
    assert none_h.regime == reasoning.NON_COMPACT
    assert none_h.why and "horizon" in none_h.why, (
        "the refusal must be about the horizon, not about the data being an artefact (why=%r)"
        % none_h.why)

    # with a horizon stated it must be answered, and the answer must be the ramp
    H = 10
    res = reasoning.ReasoningRouter().reason([X], X, horizon=H, dt=1.0)
    assert res.regime == reasoning.DETERMINISTIC, (
        "a stated horizon on a perfectly forecastable ramp was refused (why=%r) — the decay margin "
        "is gating a path it must not gate" % res.why)
    fc = np.asarray(res.forecast).ravel()[:H]
    truth = a + b * np.arange(T, T + H)                # the ORACLE, computed independently
    rel = float(np.max(np.abs(fc - truth) / np.abs(truth)))
    assert rel < 1e-6, "the ramp continuation is wrong (max rel err %.3g)" % rel


def test_a_MEMORY_ERROR_is_raised_not_reported_as_a_regime():
    """A failure of the machine must never be published as a measurement about the data.

    Every measuring function here ends in a broad `except Exception` that reports the frame as
    unreadable, which is right for a singular matrix or a zero-width axis — there, "this frame
    carries no read" IS the finding. It is wrong for `MemoryError`, which says the allocator refused
    and says nothing whatever about the trajectory.

    This was live rather than theoretical. Before the horizon was bounded, `rho` from the shard
    telemetry produced a horizon of 12,143,019 steps, whose rollout asks numpy for a
    (12143019, 380) complex array — 68.8 GiB. The allocation failed after 14.5 seconds and the
    caller was told the series was not compact. Same defect class as certifying a residual nobody
    measured: a fact about the host wearing the clothes of a fact about the data.

    The fixture raises from `rollout`, which is inside `reason()`'s widest `try`, so a regression
    that drops the re-raise is caught exactly where it would do the damage."""
    import ember.optics as ap
    X = _planted_rotation(0.90)

    class _OOM:
        """The instrument, except that rolling the operator runs the machine out of memory."""
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def fit_dynamics(self, *a, **k):
            dyn = self._inner.fit_dynamics(*a, **k)

            class _Dyn:
                """Both forecast surfaces run out of memory.

                `reasoning._rollout` iterates `propagator_full`, and falls back to `rollout` on a
                `Dynamics` that predates it. The allocation can fail in either, and the contract is
                about neither in particular: a failure of the machine must reach the caller as a
                failure of the machine. Injecting at only one leaves the other silently untested.
                """

                def __getattr__(_s, n):
                    return getattr(dyn, n)

                def propagator_full(_s, *_a, **_k):
                    raise MemoryError("Unable to allocate 68.8 GiB for an array with shape "
                                      "(12143019, 380) and data type complex128")

                def rollout(_s, *_a, **_k):
                    raise MemoryError("Unable to allocate 68.8 GiB for an array with shape "
                                      "(12143019, 380) and data type complex128")
            return _Dyn()

    try:
        reasoning.ReasoningRouter(dynamics=_OOM(ap), read=ap).reason([X], X, horizon=4, dt=1.0)
    except MemoryError:
        pass                                  # the only correct outcome
    else:
        raise AssertionError(
            "a MemoryError inside the rollout was swallowed and returned as a regime — the caller "
            "was told something about the DATA on the strength of an allocation failure")
