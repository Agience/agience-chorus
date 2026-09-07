"""Deterministic reasoning — op.reason, the lumen tekton's structured-reasoning leg.

Handles structured/quantitative dynamics deterministically and knows when it cannot. Given a
numeric trajectory it asks the injected instrument whether a proper subspace resolves above the
noise null. If it does, that instrument's own propagator produces the forecast; otherwise this
returns `NON_COMPACT` with the measurement that refused (`ReasoningResult.why`).

Two things bound the answer, and neither is a quality test on the data:

  * the horizon must be derivable — with `horizon=None` the step comes off the fitted spectrum, so
    an operator whose dominant mode does not decay has no rate to read one from (`_decay_margin`);
  * the horizon may not exceed the transitions it was fitted from (`_operator_horizon`).

What this module does NOT do is decide whether resolved structure is genuine or an artefact of a
trend or a level shift. It has no measurement that separates them: a trend, a level shift and a
damped sine are all rank-one, and a level shift's dominant mode decays just as a real slow mode
does. The document that prompted this work names that separation as the valuable thing
(`agience-pharos/theory/FRACTAL-ENTROPTICS-EVAL.md` §2) and it remains unbuilt here. Do not read `DETERMINISTIC`
as "this structure is real"; read it as "a proper subspace resolved and the operator could be
rolled".

No hypothesis class and no tuned constants: every value this module uses is read off the injected
instrument rather than fit or thresholded here. There is no model leg and no fallback:
`NON_COMPACT` is a computation, not an absence — "this domain is not compact, so no exact answer
exists" — and it is never softened into a guess, a canned reply, or an empty forecast; the caller
gets an explicit flag, never a blank.

Depends only on numpy and the injected instrument's contract (`prism`). The research this
compactness test draws on names *"language / knowledge"* as the archetype non-compact case, at
`_archive/_scratch-2026-07/koopman_probe/RESEARCH.md` — so a non-compact reading on a
conversational domain is the predicted outcome, not a shortfall of this module.

Model-free, deterministic, interpretable, and orders of magnitude smaller than a network when the
domain has structure.
"""
from __future__ import annotations

import json
import re as _re
from dataclasses import dataclass
from typing import Optional

import numpy as np

# ── the instrument slots ────────────────────────────────────────────────────────────────────────
# Two slots, because this module reaches two contracts, and they are not interchangeable:
#
#   `dynamics`  ->  prism.instrument.Dynamics   decay_profile · resolution_limit · embed ·
#                                               fit_dynamics · dynamics_state
#   `read`      ->  prism.instrument.Read       read_ordered
#
# The five `Dynamics` members are all statements about lag — C(tau), a Takens delay, a
# Koopman/DMD operator over consecutive frames — over an ordered (T, F) frame. `Read`'s domain is
# a set of vectors, which has no lag. A host that fills `Read` and not `Dynamics` is therefore a
# complete embodiment of a domain that does not pose this question, not a partial one, and it must
# be able to say so per contract. (`_operator_horizon` is the one `Read` reach in this module:
# `contrast = lambda_1 / edge`, a statement about the frame that carries no lag at all.)
#
# Resolution order, most specific first — `prism.instrument`'s, not a second mechanism:
#   1. the slot handed to the call; 2. the process default the host registered; 3. `InstrumentRequired`.
# Resolved outside every `try` below: both measuring functions wrap their arithmetic in a broad
# `except Exception` that reports an unreadable frame as NON_COMPACT, so an `InstrumentRequired`
# raised inside one would be caught and published as a regime — a capacity fact rendered as a
# measurement. Hoisting the lookup is what keeps `InstrumentRequired` reaching the caller.
#
# Measuring is a host capacity, not a package one, so the instrument arrives as an argument,
# exactly as `curriculum.answers` and `crystal.Crystal` take theirs. This module carries no
# cross-package import: `prism` is the loader's own package, and what it takes from it is a
# contract, not a measurement.
def _instrument(slot, member, *, contract, at):
    """The instrument's `member`, or `InstrumentRequired` naming it. Never a silent degrade — a
    dynamics read computed some other way is not the same measurement wearing the same name."""
    from prism.instrument import get_default as _get_default, require as _require
    return _require(slot if slot is not None else _get_default(), member,
                    contract=contract, at=at)


def _dynamics(slot, member, *, at):
    return _instrument(slot, member, contract="dynamics", at=at)


def _read(slot, member, *, at):
    return _instrument(slot, member, contract="read", at=at)


# Numeric-row matcher for parse_trajectory.
_NUMROW = _re.compile(r"^[\s\[]*[-+]?\d[\d,\s.eE+\-]*[\]\s]*$")


# ── the two regimes ─────────────────────────────────────────────────────────────────────────────
# Named constants so neither is a bare string at a call site. `NON_COMPACT` means the resolved-rank
# curve did not plateau, so no compact law governs the series — not "fall through to a model";
# there is no model leg.
DETERMINISTIC = "deterministic"
NON_COMPACT = "non_compact"


# ── what is not a reading ───────────────────────────────────────────────────────────────────────
# Every measuring function below ends in a broad `except Exception` that reports the frame as
# unreadable. That is right for the failures a degenerate frame actually produces — a singular
# matrix, a zero-width axis, a non-finite entry — because "this frame carries no read" IS the
# measurement in those cases.
#
# It is wrong for a failure of the machine. A `MemoryError` says the process could not get the
# pages it asked for; it says nothing whatever about the trajectory, and returning `NON_COMPACT`
# from one publishes "no compact law governs this series" on the strength of an allocator refusing.
# That was live: before the horizon was bounded, `rho` from the shard telemetry produced a horizon
# of 12,143,019 steps, whose rollout asks numpy for a (12143019, 380) complex array — 68.8 GiB. The
# allocation failed after 14.5 seconds and the caller was told the data was not compact.
#
# So these re-raise. It is the same rule the module already applies to `InstrumentRequired` by
# resolving instrument members outside every `try`: a capacity fact must never be rendered as a
# measurement. `KeyboardInterrupt` and `SystemExit` derive from `BaseException` and were never
# caught by `except Exception`; they are named here only so the list reads as the whole intent.
_NOT_A_READING = (MemoryError, RecursionError, SystemError, KeyboardInterrupt, SystemExit)


def _lag_for(X, *, dynamics=None) -> Optional[int]:
    """The signal's own correlation length, as the delay lag. `None` when it cannot be measured.

      decay_profile(X)      -> C(tau), the ordered-axis autocorrelation (the OTF, by Wiener-Khinchin)
      resolution_limit(C)   -> xi, the integral correlation length: sum_tau C(tau)/C(0) over the
                               positive lobe — how many lags the signal stays correlated with
                               itself. That is the delay lag; embedding further adds samples the
                               signal has already forgotten, embedding less throws away structure.

    Threshold-free by construction: no exp(-a t) grid, no fitted rate, no peak search.

    Bounds on the lag are the instrument's, not this function's: `embed` treats `d <= 1` as no
    embedding and raises when `A.shape[0] <= d`; `decay_profile` returns `None` below its own
    minimum row count. This returns what the instrument measured, unmodified.

    Both instrument members are resolved before the `try`, never inside it, so an
    `InstrumentRequired` reaches the caller rather than being read here as "this frame carries no
    lag"."""
    at = "lumen.reasoning._lag_for (read the trajectory's own correlation length as the delay lag)"
    decay_profile = _dynamics(dynamics, "decay_profile", at=at)
    resolution_limit = _dynamics(dynamics, "resolution_limit", at=at)
    try:
        Xa = np.atleast_2d(np.asarray(X, dtype=float))
        if not np.all(np.isfinite(Xa)):
            return None
        prof = decay_profile(Xa)
        if prof is None:
            return None                     # the instrument will not read this frame — no lag exists
        xi = float(resolution_limit(prof).xi)
        if not np.isfinite(xi) or xi <= 0:
            return None
        return int(round(xi))
    except _NOT_A_READING:
        raise                           # a failure of the machine, not a reading
    except Exception:
        return None


def complexity_regime(X, *, null=None, dynamics=None):
    """Return (regime, K_signal, curve). The regime is read from the injected instrument, not
    thresholded.

    Compact iff the instrument resolves a proper subspace of modes above the noise null:
    ``0 < K_signal < F``.

      K_signal == 0   nothing rose above the noise floor — not "maximally compact", nothing
                      resolved.
      K_signal == F   every mode is significant: full rank, no compression, no governing law.

    `dynamics` is the `prism.instrument.Dynamics` slot, passed straight through to `_lag_for` and
    used here for `embed` and `dynamics_state`. Unfilled, this raises rather than returning
    `NON_COMPACT`: "no compact law governs this series" and "this host cannot look" are different
    statements, and only one of them is about the series.

    The embedding depth is the measured correlation length from `_lag_for` — the same question
    answered once rather than twice: an unmeasurable lag means the instrument will not read a
    decay profile from this frame, so it cannot certify a regime on it either, and this returns
    NON_COMPACT.

    `null` is the caller's noise provider — the only external input besides the instrument slots.
    `far` is not passed at all: the instrument applies its own."""
    at = "lumen.reasoning.complexity_regime (embed the trajectory and resolve its modes)"
    embed = _dynamics(dynamics, "embed", at=at)
    dynamics_state = _dynamics(dynamics, "dynamics_state", at=at)
    lag = _lag_for(X, dynamics=dynamics)
    if lag is None:
        return NON_COMPACT, 0, []       # unreadable frame -> no regime measured -> no assertion
    Xe = embed(X, lag)
    F = int(Xe.shape[1])
    try:
        dyn = dynamics_state(Xe.shape[1])
        dyn.update_block(Xe)
        K = int(dyn.resolved(null=null))
    except _NOT_A_READING:
        raise                           # a failure of the machine, not a reading
    except Exception:
        return NON_COMPACT, 0, []
    return (DETERMINISTIC if 0 < K < F else NON_COMPACT), K, [K]


def _decay_margin(dyn) -> Optional[float]:
    """`m = |μ|` of the operator's dominant mode — does anything here actually decay?

    `None` when the spectrum carries no readable mode, and `None` when `m` is outside `(0, 1)`:
    `m >= 1` is growth or a standing offset and `m = 0` is nothing, so there is no rate to read a
    horizon off.

    **This is a horizon input, not a quality test.** `reason()` gates on it only where the horizon
    must be derived (`horizon=None`); a caller who states a horizon is not refused for it.

    That distinction is load-bearing, and it was got wrong here once. A non-decaying mode does NOT
    mean the forecast is bad. Scored out-of-sample at h=10 on the real telemetry in
    the node's own `metrics.jsonl`, the rollout of these very operators lands within
    0.002%–0.056% median absolute percentage error, and on `ts` — the wall-clock timestamp, a pure
    ramp — it is exact. Gating both paths on `m` threw those away for nothing. The document's §2
    concern is that a long-memory estimator MISATTRIBUTES structure on a trended series and reports
    a spurious exponent; that is a different claim from "a trend cannot be forecast", and conflating
    them costs real forecasts.

    What `m` reads on the calibrated series of `agience-pharos/theory/FRACTAL-ENTROPTICS-EVAL.md` §2 (embedded at
    the measured lag, six seeds) — calibration, not a cut:

        genuine fGn H=0.8   m = 0.898       AR(1) φ=0.95   m = 0.943
        damped sine         m = 0.978       white + shift  m = 0.9969
        white + trend       m = 1.0004      (no derivable horizon)

    Note what is NOT available here: rank does not separate artefact from law either. A trend and a
    level shift are rank-one (`K_signal = 1`) — but so is a damped sine, so a rule on
    `K_signal == 1` would refuse the real system along with the artefact. Neither `m` nor the rank
    is a genuine-versus-artefact discriminator and none is claimed. `m` is reported on the result so
    a caller can see 0.90 and 0.9969 for the different things they are.
    """
    try:
        mu = np.abs(np.asarray(dyn.rates().mu))
        mu = mu[np.isfinite(mu)]
        if not mu.size:
            return None
        m = float(np.max(mu))
        return m if 0.0 < m < 1.0 else None
    except _NOT_A_READING:
        raise                           # a failure of the machine, not a reading
    except Exception:
        return None


def _operator_horizon(m: float, rows, read_ordered) -> Optional[int]:
    """How far this operator's own spectrum can still say anything. `None` when it cannot be read.

        ℓ(m) = ⌈ ln(1/ε) / (−ln m) ⌉        m = |μ| of the dominant mode, from `_decay_margin`

    the step at which the strongest surviving mode has decayed to ε, the frame's own noise floor
    expressed as a fraction of the dominant mode's amplitude — not machine epsilon; a
    representability limit is not a resolution limit. Past that step the operator is predicting
    from an amplitude it no longer has.

    `Read.read_ordered` publishes `contrast = λ₁ / edge` — the noise floor relative to the
    dominant mode, from the same spectrum as `m`, so no external scale enters:

        ε = 1 / contrast        ⟹      ℓ = ⌈ ln(contrast) / (−ln m) ⌉

    `contrast > 1` is the instrument's own statement that structure exists, so it doubles as the
    guard rather than adding a second one: where nothing resolves, ε >= 1, and a mode already at
    the floor has no distance left to decay through.

    `read_ordered` is taken off the `Read` slot and not the `Dynamics` one: `contrast` is a
    statement about the frame's correlation spectrum, so a corpus-domain embodiment can answer it
    while filling no `Dynamics` member at all. `m` arrives already measured and already bounded to
    `(0, 1)`, so this function reaches only the `Read` slot and a `Dynamics`-only host is never sent
    here.

    Returns `None` — never 0, never a step count — when no structure was resolved to decay from,
    and when the step the formula produces is longer than the evidence behind it. The caller then
    reports NON_COMPACT rather than rolling out a chosen number of times regardless.

    **The horizon may not exceed the transitions it was fitted from.** `m` is a strict inequality on
    a float, so a mode at `1 - 1.7e-7` passes `_decay_margin` and `-ln(m)` is then ~1.7e-7: the
    formula returns 8,294,607 steps. Measured, not hypothesised — that is `keyed_coverage` from
    the node's own `metrics.jsonl`, a bounded ratio that sits at 1.0 between shifts, read
    over its real 2,298 rows. An operator asked to speak 3,609x further than it has ever been
    observed is extrapolating, and a decay rate that slow is not distinguishable from no decay at
    this sample size — the strict inequality cannot see the difference but the span can.

    `T` is the frame's own row count, so this is the extent of the evidence rather than a chosen
    ceiling, and it is a refusal rather than a clip: a horizon silently truncated to `T` hands back
    a forecast that looks well-formed while hiding the reason it was suspect. No genuine case here
    comes near the bound — a damped sine reads 321 of 512, a slow rotation 51 of 64, `dark_matter`
    on the same real file 115 of 2,298.

    Resolved by the caller before its own `try`, not inside this function: `reason()` wraps this
    call in `except Exception: return NON_COMPACT`, so an `InstrumentRequired` raised here would be
    caught and published as a regime rather than reaching the caller."""
    try:
        W = np.asarray(rows, dtype=float)
        rd = read_ordered(W)
        contrast = float(rd.contrast)       # λ₁ / edge — the floor as a relative amplitude, inverted
        if not np.isfinite(contrast) or contrast <= 1.0:
            return None                     # nothing resolved above the floor -> nothing to decay from
        h = int(np.ceil(np.log(contrast) / (-np.log(m))))
        return h if 1 <= h <= int(W.shape[0]) else None
    except _NOT_A_READING:
        raise                           # a failure of the machine, not a reading
    except Exception:
        return None


@dataclass
class ReasoningResult:
    regime: str
    method: Optional[str] = None
    forecast: Optional[np.ndarray] = None
    equations: Optional[list] = None
    complexity: int = 0
    fit_error: float = float("nan")
    curve: Optional[list] = None
    #: `m = |μ|` of the dominant mode, from `_decay_margin` — how fast the strongest surviving mode
    #: decays. Reported rather than only tested against, because `m` near 1 is what a level shift
    #: looks like and a caller that sees only the regime cannot tell 0.90 from 0.9969.
    margin: Optional[float] = None
    #: The step count actually rolled, and where it came from: the operator's own spectrum when the
    #: caller stated no horizon, the caller's number when it did. A horizon far beyond the series'
    #: correlation length is the visible shape of a drift fitted as a law.
    horizon: Optional[int] = None
    #: Why this regime, when the regime is a refusal. `None` on an answer. Never inferred from the
    #: absence of a forecast — each refusal below names its own measurement.
    #:
    #: ASCII, every one of them. This string travels to the turn artifact's JSON, to logs, and to
    #: `conversation._quantitative`'s caller, and those run under consoles whose encoding cannot
    #: represent arbitrary glyphs. Same rule as `query_neighbourhood`'s one reporting line: a message
    #: about a refusal must not itself be able to fail to print. The maths keeps its symbols in the
    #: docstrings, which are read in a file and not through a pipe.
    why: Optional[str] = None

    @property
    def deferred(self):
        return self.regime == NON_COMPACT


def _rollout(dyn, z, horizon: int):
    """Roll the fitted operator forward `horizon` steps, by whichever forecast this series supports.

    `Dynamics` offers two and NEITHER dominates.

    `rollout` evolves the REDUCED DMD spectrum — `x_h = sum_k phi_k mu_k^h b_k`, exact eigenvalue
    powers, one eigensolve for the whole horizon. It cannot represent a defective operator: a
    ramp's propagator is a Jordan block, eigenvalue 1 repeated with one eigenvector, the reduction
    resolves rank 1, and a straight line comes back as geometric growth.

    `propagator_full` is `A = Pyx Pxx^+`, iterated one matmul per step. It reproduces the Jordan
    case exactly and loses precision where the spectral path does not — at large magnitude, each
    matmul carries the whole state's error forward.

    Measured on this node's own telemetry, median absolute percentage error at horizon 10:

        series            magnitude    spectral   full-iter
        bytes              8.81e+08     0.0573%     0.0161%
        operators                48     0.0397%     0.0067%
        total_artifacts    2.19e+06     0.0763%     0.0509%
        ts                 1.79e+09     0.0001%     0.0023%
        rho                       1     0.0001%     0.0004%

    against synthetic series where the ordering is the other way round — a ramp `3 + t/4` is
    2.05e-02 spectral against 2.91e-10 iterated. A rule picking one would be right about half of a
    real corpus.

    So the series picks. The last `horizon` steps of the trajectory are held out, both forecasts
    are run from the point before them, and whichever reproduced the held-out tail more closely
    forecasts the future. That is model selection on evidence the caller already holds — no
    constant, no threshold, and no claim about which method is better in general, because the
    measurement says there is no such claim to make.

    A trajectory too short to hold anything out keeps the spectral forecast, which is `Dynamics`'
    own default.
    """
    full = getattr(dyn, "propagator_full", None)
    if full is None:
        return dyn.rollout(z, horizon)

    A = np.asarray(full())

    def _iterate(state, steps):
        state = np.asarray(state, dtype=A.dtype if np.iscomplexobj(A) else float)
        out = []
        for _ in range(int(steps)):
            state = A @ state
            out.append(state)
        return np.asarray(out) if out else np.zeros((0, np.asarray(state).size))

    # ── which forecast this series supports, measured on its own held-out tail ────────────────
    # `dyn` was fitted on the whole trajectory, so both candidates see the same operator; what is
    # being compared is how each PROPAGATES it, which is the only thing that differs.
    try:
        frames = np.asarray(getattr(dyn, "tensors")()[0] if callable(getattr(dyn, "tensors", None))
                            else None)
    except Exception:
        frames = None
    if frames is None or frames.ndim != 2 or frames.shape[0] < 2 * int(horizon) + 1:
        return _iterate(z, horizon)

    h = int(horizon)
    origin, actual = frames[-h - 1], frames[-h:]
    try:
        spectral = np.asarray(dyn.rollout(origin, h))
        iterated = _iterate(origin, h)
        scale = np.maximum(np.abs(actual), 1e-12)
        e_spectral = float(np.median(np.abs(np.asarray(spectral) - actual) / scale))
        e_iterated = float(np.median(np.abs(iterated - actual) / scale))
    except Exception:
        return _iterate(z, horizon)

    return dyn.rollout(z, horizon) if e_spectral <= e_iterated else _iterate(z, horizon)



@dataclass
class ReasoningRouter:
    """`null` is the only consumer-set value: everything else about the answer is decided by the
    injected instrument instead.

    `dynamics` and `read` decide which instrument takes the measurement, not what the measurement
    says; the host sets them at assembly. Left `None`, each resolves the process default the host
    registered; with no default registered, the call raises rather than returning a regime or a
    forecast.

    Default `null=None` uses the instrument's closed-form bulk provider, which knows nothing about
    this substrate's measurement precision. A region with real structured noise should pass its
    own (`reference_null`, `self_calibrating_null`)."""
    null: object = None
    #: The host's two instrument slots — see the module header. `None` means "resolve the process
    #: default", never "measure some other way".
    dynamics: object = None
    read: object = None

    def reason(self, train_trajs, context, horizon=None, dt=None) -> ReasoningResult:
        """Read the regime, and if it is compact let the instrument's own propagator forecast it.

        There is one path and no hypothesis class: no polynomial library, no sparsity cut, no
        acceptance gate fit against the instrument's own output. `complexity_regime` resolves the
        modes above the noise null; if a proper subspace is resolved, the dynamics are compact and
        `Dynamics.fit_dynamics` — the same instrument that judged the spectrum — generates the
        forecast. Otherwise this returns `NON_COMPACT`.

        `complexity_regime` asks whether a proper subspace resolved. The rest of the refusals here
        are about whether a horizon exists and how far it may reach, not about whether the resolved
        structure deserves belief — see the module header for what this module cannot tell you.

        The resolved rank gates; it does not shape the forecast. The instrument's propagator is the
        unregularised least-squares operator `A = P_yx · P_xx⁺`, so for a scalar series this is
        AR(lag) OLS and for a panel VAR(lag) OLS, regardless of what `K_signal` resolved
        (`agience-pharos/theory/FRACTAL-ENTROPTICS-EVAL.md` §4 measures the two identical to four decimals at
        every horizon, and shows the propagator unchanged for every `rank=` passed). That is worth
        knowing at the call site: OLS overfits where regularisation matters, so a short training
        frame with many features is exactly where this forecast is weakest.

        The cost: no human-readable `equations`. A recovered polynomial that might be the wrong
        basis is worse than an honest operator, but the loss is real."""
        at = "lumen.reasoning.reason (fit the trajectory's propagator and roll it out)"
        embed = _dynamics(self.dynamics, "embed", at=at)
        fit_dynamics = _dynamics(self.dynamics, "fit_dynamics", at=at)
        # Resolved outside the `try` below, so an `InstrumentRequired` reaches the caller rather
        # than being reported as NON_COMPACT, and only when it will be used: a caller that states
        # a horizon never reads the spectrum's contrast, so raising on a member the run does not
        # need would make a `Dynamics`-only host look unequipped for work it can do. The decay
        # margin below is a `Dynamics` read (`rates()`), so making it unconditional does not widen
        # what a `Read`-less host must fill.
        read_ordered = (_read(self.read, "read_ordered",
                              at="lumen.reasoning._operator_horizon (read the spectrum's contrast "
                                 "as the relative noise floor the forecast decays to)")
                        if horizon is None else None)
        F = train_trajs[0].shape[1]
        regime, K, curve = complexity_regime(np.vstack(train_trajs), null=self.null,
                                             dynamics=self.dynamics)
        if regime == NON_COMPACT:
            return ReasoningResult(NON_COMPACT, complexity=K, curve=curve,
                                   why=("no proper subspace resolved above the noise null "
                                        "(K_signal=%d) -- nothing here is compact" % K))

        # Compact: the propagator is the answer, and it is the injected instrument's.
        try:
            stacked = np.vstack(train_trajs)
            lag = _lag_for(stacked, dynamics=self.dynamics)
            if lag is None:
                return ReasoningResult(NON_COMPACT, complexity=K, curve=curve,
                                       why=("the instrument reads no correlation length from this "
                                            "frame, so there is no depth to embed at"))
            dyn = fit_dynamics(embed(train_trajs[0], lag))
            for W in train_trajs[1:]:
                dyn = dyn.merge(fit_dynamics(embed(W, lag)))
            z = embed(context, lag)[-1]
            # `m` is read on every path, but it GATES only the path that needs it.
            #
            # The decay margin is what the horizon is derived from — `ℓ = ⌈ln(contrast)/(−ln m)⌉`
            # has no value when nothing decays — so a caller who states no horizon and hands over a
            # non-decaying operator gets a refusal, because there is no step to compute. A caller
            # who states a horizon has already answered that question and the margin is not in
            # their way.
            #
            # This was briefly a gate on both paths, on the theory that a non-decaying mode means a
            # drift rather than a law. Measured against the data, that theory is false. Scored
            # out-of-sample at h=10 on the node's own `metrics.jsonl`, the rollout of exactly
            # these non-decaying operators lands within 0.002%–0.056% median absolute percentage
            # error — `ts`, the wall-clock timestamp, is exact. A ramp is the easiest series there
            # is and the propagator recovers it; refusing it destroys a correct answer and protects
            # no one. The document's §2 concern is that a long-memory estimator MISATTRIBUTES
            # structure on a trended series and reports a spurious exponent, which is a different
            # claim from "a trend cannot be forecast". Conflating the two costs real forecasts.
            #
            # What a non-decaying mode does cost is the horizon, and that is bounded separately —
            # see `_operator_horizon`, where a step longer than the evidence is refused.
            m = _decay_margin(dyn)
            if m is None and horizon is None:
                return ReasoningResult(NON_COMPACT, complexity=K, curve=curve,
                                       why=("the dominant mode does not decay (|mu| >= 1 is growth "
                                            "or a standing offset, |mu| = 0 is nothing), so there "
                                            "is no rate to read a horizon off -- state a horizon "
                                            "and this frame can still be rolled"))
            # The horizon is the operator's, not the caller's: `horizon=None` reads it off the
            # fitted spectrum; see `_operator_horizon`.
            h = (_operator_horizon(m, embed(stacked, lag), read_ordered)
                 if horizon is None else int(horizon))
            if h is None or h < 1:
                return ReasoningResult(NON_COMPACT, complexity=K, curve=curve, margin=m,
                                       why=("no horizon this frame supports: either nothing "
                                            "resolved above its own noise floor (contrast <= 1), "
                                            "so there is no amplitude to decay through, or the "
                                            "dominant mode decays so slowly that the step it buys "
                                            "runs past every transition the operator was fitted "
                                            "from -- see _operator_horizon"))
            roll = np.asarray(_rollout(dyn, z, h))[:, -F:]
        except _NOT_A_READING:
            raise                           # a failure of the machine, not a reading
        except Exception:
            return ReasoningResult(NON_COMPACT, complexity=K, curve=curve,
                                   why="the propagator could not be fitted or rolled on this frame")

        # Not a threshold: a rollout that left the finite reals is not a forecast. Whether the
        # dynamics are learnable was already decided by the significance read above.
        if not np.all(np.isfinite(roll)):
            return ReasoningResult(NON_COMPACT, complexity=K, curve=curve, margin=m, horizon=h,
                                   why="the rollout left the finite reals -- that is not a forecast")
        # Read off the member actually called: this is recorded on the turn artifact and quoted
        # in the certificate below as "the instrument that decided", so the record names whichever
        # instrument the host filled the slot with.
        return ReasoningResult(DETERMINISTIC, getattr(fit_dynamics, "__module__", None) or
                               type(self.dynamics).__module__,
                               roll, None, K, float("nan"), curve, margin=m, horizon=int(h))


def parse_trajectory(text: str):
    """Extract the longest run of consecutive numeric rows (whitespace/comma-separated, consistent
    column count) from free text — a pasted time series / table. Returns (T, F) or None."""
    best, run = None, []

    def _flush(rows):
        # Whether a run is long enough to reason about is the instrument's question: `decay_profile`
        # returns None below its own `MIN_ROWS` and `fit_dynamics` below two rows. This extracts
        # what is present and lets the instrument decide.
        nonlocal best
        if rows and (best is None or len(rows) > len(best)):
            best = rows
    for line in text.splitlines():
        s = line.strip()
        if s and _NUMROW.match(s):
            vals = [float(v) for v in _re.split(r"[,\s]+", s.strip("[] ")) if v not in ("", "[", "]")]
            if vals and (not run or len(vals) == len(run[0])):
                run.append(vals); continue
        _flush(run); run = []
    _flush(run)
    if not best:
        return None
    return np.asarray(best, dtype=float)


_RTYPE = "application/vnd.agience.reasoning+json"


def _bearer(token):
    if not token:
        return None
    t = token.strip()
    return t if t.lower().startswith("bearer ") else f"Bearer {t}"


# `op.reason` is reached from the conversation act itself (`conversation._quantitative`), and what
# it produces goes to the asker as text, not to a model as an instruction — there is nothing here
# to prompt.
#
# `persist_turn` below writes a triple, a store act rather than model scaffolding. It has no
# caller: reachable only behind `LUMEN_LEARN=1`, and the chat path is read-only by standing rule.
# Kept because the write-back design is live in the docs and this is its implementation.

def persist_turn(input_text, res, token, mantle_url, container_id=None):
    """Write the turn back into the ontology as a `(context = input, content = output,
    operator = tool)` triple edge — the live-learning loop. The operator provenance is
    `lumen:reason:<method>` when reasoned deterministically, `lumen:router:model` when deferred, so
    the corpus records which operator applied to which context (the router becomes learnable).
    Fail-soft: never raises, never blocks the turn."""
    try:
        import httpx
        deferred = res.regime == NON_COMPACT
        operator = "lumen:router:model" if deferred else f"lumen:reason:{res.method}"
        fit = res.fit_error if res.fit_error == res.fit_error else None
        # Verification mass is derived server-side, never client-asserted. Verification is not a
        # one-shot label but an accumulating mass (inertia): a triple's initial mass comes from its
        # self-certificate, and mass accrues post-hoc from independent sources recorded as
        # append-only confirmation events — user sentiment (the human oracle: good sentiment adds
        # mass, a correction subtracts it), oracle agreement, consistency with existing verified
        # triples, downstream success. The dark-matter surfacing filter gates on effective mass
        # (initial + confirmations) >= floor: only then does a triple ground future turns. A
        # deferred turn starts at ~0 (dark matter) and can only rise by external confirmation, so
        # an off-topic or incorrect answer never becomes fact on its own.
        #
        # A result reaches this point only if the router already accepted it, so the certificate
        # below is the router's verdict rather than a second opinion with its own threshold. A
        # certified result carries mass 1.0; an uncertified one carries 0.0, to be raised only by
        # external confirmation.
        forecast_ok = res.forecast is not None and np.all(np.isfinite(np.asarray(res.forecast)))
        certified = (not deferred) and forecast_ok and res.method is not None
        if certified:
            # The certificate names what was actually measured, and nothing else.
            #
            # It used to read `certificate:residual-is-noise`, which asserted the one thing on the
            # path that is never computed: `res.fit_error` is `float("nan")` on every result this
            # module produces, so the `fit=` clause below was always dropped and the claim went out
            # bare. A residual read would need a one-step in-sample error, and the `Propagator`
            # contract declares `update` / `update_block` / `resolved` / `rates` / `rollout` /
            # `merge` — no member that predicts a frame it was fitted on. Widening the contract is
            # the doc's §7.2 work (build the regularised propagator from the truncated spectrum),
            # not something to do as a side effect of fixing a string.
            #
            # So the three measurements that did happen are what the certificate carries: a proper
            # subspace resolved above the noise null, the dominant mode decays, and the rollout
            # stayed finite. `read=` names the instrument that decided, read off the result rather
            # than typed as a literal — the instrument is injected, so a literal here would certify
            # whichever instrument this module was written against rather than the one the host
            # filled the slot with.
            ev = ("certificate:resolved-and-decaying,read=%s,K_signal=%d"
                  % (res.method, res.complexity))
            if res.margin is not None:
                ev += ",mu=%.4f" % res.margin
            if res.horizon is not None:
                ev += ",horizon=%d" % res.horizon
            if fit is not None:
                ev += f",fit={fit:.2g}"     # still absent by construction — see above
            mass, verification, sources = 1.0, "verified", [ev]
        else:
            # Names the measurement that refused, not merely that something did. `res.why` is set by
            # every refusal in `reason()`; the fallback covers a result built by hand.
            mass, verification, sources = 0.0, "unverified", [
                "non-compact:" + (res.why or "no-deterministic-answer")]
        out = {"regime": res.regime, "method": res.method, "equations": res.equations,
               "complexity": res.complexity, "fit_error": fit,
               # The two numbers behind the regime, so a stored turn can be re-judged without the
               # frame: `margin` near 1 is what a level shift looks like, and a `horizon` far past
               # the series' own correlation length is a drift fitted as a law. A record that kept
               # only the regime could not tell either from a genuine slow mode.
               "margin": res.margin, "horizon": res.horizon, "why": res.why,
               "forecast": (np.asarray(res.forecast).tolist() if res.forecast is not None else None)}
        context = {"content_type": _RTYPE, "title": f"reasoning turn ({operator})",
                   "operator": operator, "regime": res.regime, "source": "lumen:reason",
                   "verification": verification,   # derived label for the current mass
                   "mass": mass,                   # accruable inertia; surfacing gates on effective mass
                   "sources": sources,             # what contributed mass (append confirmations here)
                   # The provenance record of what was reasoned over, kept whole: a truncated
                   # provenance says "this is the input" about something that is not.
                   "input": (input_text or "")}
        payload = {"content": json.dumps(out), "content_type": _RTYPE,
                   "context": json.dumps(context)}
        if container_id:
            payload["container_id"] = container_id
        httpx.post(f"{mantle_url.rstrip('/')}/artifacts",
                   headers={"Authorization": _bearer(token), "Content-Type": "application/json"},
                   json=payload, timeout=10)
    except Exception:
        pass


# ── registration — the lumen tekton's op.reason ──────────────────────────────
_REASONING_OPS = [
    ("op.reason", "deterministic dynamics-reasoning: reads the regime (the resolved-rank "
     "K_signal), forecasts exactly where the domain is compact, refuses with a "
     "measured NON_COMPACT otherwise"),
]


# ADDED 2026-08-26. Operators were registered with NO `collection_id`, and the content seal keys
# on a collection origin root — so they could never be sealed and
# `data_integrity_check.artifacts_holding_inline_plaintext` climbed off zero on every boot. The
# repair that first drove that count to zero gave collectionless platform vocabulary `stage.system`
# "rather than an exemption"; the writers were never changed. This is that fix reaching the writer.
# `collection_id` alone suffices — `vertex._place` writes the origin containment edge from it, in
# the same savepoint as the row. Inlined, not shared: `_persona.load()` loads these modules
# individually and cross-importing between them is the hazard that module exists to prevent.
_SYSTEM_COLLECTION = "stage.system"


def _now_iso() -> str:
    """This observer's clock reading, claimed. The store never invents one (`vertex._attribute`
    returns untouched when `created_time` is None) and it is first-write-wins."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


#: Read ONCE per process, not per call. `manifest.OPERATORS = operators()` is computed at import
#: while `operators()` recomputes on demand, and `test_the_lumen_manifest_surface_is_unchanged_for_
#: the_host` asserts the two are equal — a fresh timestamp per call makes that impossible, and it
#: also makes the registered dict non-deterministic for anything that compares payloads. Reading
#: the clock at import gives one claim per process, which is what an idempotent upsert wants:
#: first-write-wins means only the first one is ever kept anyway.
_REGISTERED_AT = _now_iso()


def register_reasoning_operators(store, *, author: str = "ember-local") -> int:
    """Register the lumen-tekton reasoning operator(s). Mirrors the impl register_* pattern."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _REASONING_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": f"lumen tekton operator {name}: {offer}",
            "created_by": author,
            "collection_id": _SYSTEM_COLLECTION, "created_time": _REGISTERED_AT}))
    return len(_REASONING_OPS)
