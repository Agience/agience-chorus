"""seek — mint a Need when a result is less resolved than this observer usually manages.

Deciding to seek is a reasoning act, and reasoning is lumen's: ember places a need on the plane
(`reach`) but does not decide that one is warranted. The threshold here is self-relative — the
observer's own running mean, never a constant — which is why it belongs with the persona that has
a point of view, not with the runner.

This is a designed, canon-aligned mechanism (GENESIS: *"interest = the steepest entropy
gradient"*) with no production consumer: nothing outside its own test imports it yet.

An observer that answers a need can notice, without being told, that it answered poorly. Of the
candidate triggers, only one has the resolving power to be useful:

    "I got a result."                     — not a signal, just an event.
    "Why don't I enrich it?"              — a wish, with no condition attached.
    "Maybe it's not very specific."       — a judgement: specific enough for what? needs an arbiter.
    "Its entropy is higher than my own mean."   — a number against a number.

The fourth is the trigger, and it is self-relative. The bar is not a configured threshold, which
would be an arbitrary cap and wrong at every other stage of development; it is the observer's own
running mean resolution, so it auto-calibrates:

  * A newborn (§13.10) has high mean entropy — everything is vague, so nothing looks anomalous and
    it does not thrash asking for help it cannot yet use.
  * A mature observer has low mean entropy and therefore notices vagueness sooner — its standard
    for "I am under-informed here" rises exactly as fast as it does.

It is §14's regression-to-the-mean used as a classifier, pointed inward: where a result's entropy
sits above the observer's own mean, the observer is measurably less resolved than usual — and
that, not a schedule and not a human's guess, is what mints a Need into the hopper.

The need then travels the ordinary path (HARNESS.md): sanitised request -> airlock -> bundle back
-> consume -> re-measure. If the entropy fell, the gap closed. If it did not, the need stands,
honestly unfilled.

The one quantity this module does not compute itself — entropy — arrives through
`prism.instrument`'s `conservation` slot as `entropy_bits`, injected rather than imported. `−Σ p
log₂ p` has no domain — the instrument and beacon cannot legitimately disagree about it, which is
what keeps it off `Instrument`/`Read`/`Dynamics` — and `Conservation` is the contract whose
membership rule is a dependency fact rather than a divergence one: `‖X‖²` is there because prism's
base install cannot hold numpy, and this is there because prism may never import entroptics.
`prism.instrument.Conservation.entropy_bits` carries the whole argument.

Resolution order is `prism.instrument`'s and not a second mechanism: the `conservation=` keyword,
then the process default a host registered, then `InstrumentRequired`, naming the member and the
operation. There is no fourth step — an unmeasured entropy never becomes 0.0, which would read as
a perfectly concentrated result set and would mint or withhold a Need on a number nothing
measured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


def result_entropy(scores: Sequence[float], *, conservation=None) -> float:
    """The normalized entropy of a result set's score distribution — how undecided the answer was.

    A peaked distribution (one candidate dominates) carries low entropy: the observer resolved the
    need. A flat distribution (many candidates, none dominant) carries high entropy: the observer
    could not distinguish, which is exactly the state that warrants enrichment.

    Normalized by `log(n)` so it is comparable across result sets of different sizes — otherwise a
    wide-but-decisive answer would look worse than a narrow-but-confused one, and the trigger would
    fire on breadth instead of confusion. Returns 0.0 for a single candidate (nothing to be
    undecided between) and ~1.0 for a perfectly flat set.

    Scores are treated as unnormalized weights; non-finite and non-positive values are dropped
    rather than clamped (a negative weight is not a small weight, it is not a reading).

    `conservation` is the `prism.instrument.Conservation` slot this module's one measurement comes
    off — see the module header. Unfilled, this raises `InstrumentRequired`; it never returns 0.0,
    because 0.0 already means something here (one candidate, or a perfectly concentrated set) and
    a host that cannot measure would be reporting total certainty."""
    from prism.instrument import get_default as _get_default, require as _require
    w = [float(s) for s in scores if isinstance(s, (int, float))
         and math.isfinite(float(s)) and float(s) > 0.0]
    n = len(w)
    if n <= 1:
        # A structural fact, answered before the slot is reached for, exactly as
        # `curriculum.answers`'s returns above its split are. There is nothing to be undecided
        # between, so a host with no instrument at all still answers this correctly — asking for
        # the instrument earlier would turn "nothing to resolve" into "this host cannot measure".
        return 0.0
    # The point of measurement. Resolution order is `prism.instrument`'s: the `conservation=`
    # keyword, then the process default a host registered, then `InstrumentRequired`, naming the
    # member and the operation. `entropy_bits` is entroptics' `shannon_bits` (bits, log base 2);
    # dividing by log2(n) normalizes to [0,1] — 0 when one weight dominates, 1 for a perfectly flat
    # set — so it is comparable across result sets of different sizes.
    entropy_bits = _require(
        conservation if conservation is not None else _get_default(), "entropy_bits",
        contract="conservation",
        at="lumen.enrich.result_entropy (the entropy of a result set's score distribution)")
    return entropy_bits(w) / math.log2(n)


@dataclass
class Resolution:
    """One observation of how well this observer resolved a need — the unit the mean is taken over."""
    need: str
    entropy: float
    gap: Optional[float] = None                 # the measured geodesic gap, when the reach knew it
    hits: int = 0


@dataclass
class SelfMean:
    """The observer's own running mean resolution — the bar the trigger measures against.

    Kept as a running mean + count (order-free, mergeable — the same (count, sum) shape
    consolidation uses) so two observers' histories can combine without replaying either.

    The bar is the standard error of the observer's own running mean, not a configured threshold:
    a result is less resolved than usual when it exceeds the mean by more than that. At count = 1
    there is no spread to measure, so the standard error is infinite and nothing clears it — "an
    observer with no history has no standard to apply", derived rather than declared — and it
    tightens as the observer accumulates history.

    The spread is the observer's own measured variance, not an imposed model: normalized entropy
    lands in [0, 1], but nothing about its distribution is Bernoulli, so a proportion's standard
    error (`sqrt(p(1-p)/k)`) would assert a distribution this observer never observed. The measured
    spread — `(count, total, total_sq)`, order-free and mergeable, the same shape consolidation
    uses, one moment further — carries no such assumption: the sample variance is undefined at
    count = 1 (no degrees of freedom, hence `inf`), and it tightens as `1/√count` for a stable
    stream. Where an observer's history genuinely carries no spread the bar is genuinely 0: a
    reading of a perfectly stable history, not a fabricated certainty, left as measured rather than
    floored — a floor here would be the arbitrary cap this whole module exists without."""
    count: int = 0
    total: float = 0.0
    total_sq: float = 0.0

    @property
    def mean(self) -> float:
        return (self.total / self.count) if self.count else 0.0

    def observe(self, entropy: float) -> None:
        """Record one resolution into the observer's own history."""
        e = float(entropy)
        if not math.isfinite(e):
            return
        self.count += 1
        self.total += e
        self.total_sq += e * e

    def variance(self) -> float:
        """The spread of this observer's own resolutions — the sample variance of what it has
        observed. `inf` below two observations: one reading has no spread to measure, and calling
        that zero would claim a stability nothing was compared against."""
        if self.count < 2:
            return float("inf")
        # Bessel-corrected, from the order-free moments. Clamped at 0 against float cancellation
        # only — a negative sample variance is an arithmetic artefact, not a reading.
        var = (self.total_sq - self.total * self.total / self.count) / (self.count - 1)
        return max(0.0, var)

    def resolution(self) -> float:
        """The smallest entropy difference this observer's own history can resolve — the standard
        error of its running mean at the spread and count it has. Infinite when new (no spread has
        been measured yet), tightening as `1/√count` as it observes."""
        var = self.variance()
        if not math.isfinite(var):
            return float("inf")
        return math.sqrt(var / self.count)

    def ready(self) -> bool:
        """Can this observer's history resolve any difference at all? False while the standard error
        spans the whole [0, 1] range the entropy lives in — there is no bar to apply yet."""
        return bool(self.count) and math.isfinite(self.resolution()) and self.resolution() < 1.0

    def above_mean(self, entropy: float) -> bool:
        """Is this result measurably less resolved than this observer usually manages?

        Measurably: by more than `resolution()` — the standard error of this observer's own running
        mean, from its own measured spread. A smaller excess is not a smaller anomaly, it is a
        difference this observer cannot see — and minting a Need for it would be asserting a reading
        the instrument does not support."""
        e = float(entropy)
        return bool(self.count) and (e - self.mean) > self.resolution()


@dataclass(frozen=True)
class Need:
    """A need minted because the observer measured itself under-informed. Carries the measurement,
    so the request can be audited and the outcome re-measured (did the gap actually close?)."""
    topic: str
    entropy: float
    self_mean: float
    margin: float
    gap: Optional[float] = None
    why: str = ""


def seek(need_text: str, scores: Sequence[float], mean: SelfMean, *,
         gap: Optional[float] = None, conservation=None) -> Optional[Need]:
    """seek — "seek and you will find" (the three acts, §13.11.3). Not a "consideration": the
    observer measures its own result, and where it finds itself less resolved than usual it goes
    looking. The whole loop, in one call: measure the result, record it into the observer's own
    history, and mint a Need if the result sits above the observer's own mean.

    Returns None when the observer resolved the need as well as it usually does — the common case,
    and not a failure. Recording happens either way: the mean must see every result, or the bar
    drifts toward only the bad ones and the trigger eats itself.

    `conservation` is passed straight through to `result_entropy`, never absorbed: an unmeasurable
    entropy is not a resolved need. `None` from this function means "the observer did as well as it
    usually does", so catching `InstrumentRequired` here would publish a capacity fact as a verdict
    on the result — the same substitution `_lag_for` and `curriculum.settled` avoid making."""
    h = result_entropy(scores, conservation=conservation)
    was_ready = mean.ready()
    fires = mean.above_mean(h)
    m = mean.mean
    mean.observe(h)                              # observe after judging: a result cannot raise its own bar
    if not (was_ready and fires):
        return None
    # No rounding on these fields: a rounding is itself a resolution claim, and this object's
    # whole purpose is to carry the measurement so the outcome can be re-measured against it. The
    # resolution the margin cleared is stated explicitly in `why`, as the quantity that mattered.
    return Need(topic=str(need_text), entropy=h, self_mean=m, margin=h - m, gap=gap,
                why="entropy %.4f above own mean %.4f by %.4f, which exceeds this observer's own "
                    "resolution %.4f at n=%d" % (h, m, h - m, mean.resolution(), mean.count))


__all__ = ["result_entropy", "Resolution", "SelfMean", "Need", "seek"]
