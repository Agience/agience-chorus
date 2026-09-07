"""op.reason on REAL series, not synthesised ones.

`agience-pharos/theory/FRACTAL-ENTROPTICS-EVAL.md` §7.3: *"Validate the rank test on real series with known
artefacts — the synthetic separation is perfect, which usually means the test is too clean."* Real
data earned its place here twice, and the second time it settled what a counter can be asked for.

**What it caught.** `keyed_coverage` read `|mu| = 0.99999983` — a mode that decays, barely — and the
horizon formula returned 8,294,607 steps from 2,298 rows. `rho` returned 12,143,019, whose rollout
asks numpy for a `(12143019, 380)` complex array: **68.8 GiB**. That raised `MemoryError`, which the
broad `except Exception` in `reason()` swallowed and reported as `NON_COMPACT` — an allocation
failure rendered as a conclusion about the data, after 14.5 seconds of trying. No synthetic series
in the suite reaches that state; the synthetic level shift tops out at 642 steps from 4,038 rows.

**What it settled.** A cumulative counter can be answered. Scored out-of-sample at h=10, the
rollout of those non-decaying operators lands within 0.002%–0.056% median absolute percentage error,
and `ts` — the wall-clock timestamp — is exact; a ramp is the easiest series there is. What a
counter lacks is not a law but a *derivable horizon*: `ℓ = ⌈ln(contrast)/(−ln m)⌉` has no value when
nothing decays. So the statement asserted below is that a counter is refused when the caller states
no horizon and forecast accurately when they do.

Data: the node's own `metrics.jsonl` — the node's own operational telemetry, 2305 samples
over 15.2 days at ~6-minute cadence, with real gaps (to 2.5 days), reshards, and bursty ingest. Set
`LUMEN_REAL_SERIES` to point elsewhere. The whole module skips when the file is absent, so a
checkout without the shard runs the rest of the suite unaffected — this is evidence when the data is
there, never a failure when it is not.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

import ember  # noqa: F401  — the host: registers `ember.optics` as the process default at import

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reasoning  # noqa: E402

# genesis writes the node's telemetry beside the shard (`<EMBER_SQLITE_DIR>/metrics.jsonl` —
# see `ember.genesis._node_dir`), so the default is DERIVED from the store the host already
# names rather than naming a box. LUMEN_REAL_SERIES still points it anywhere.
_shard = (os.environ.get("EMBER_SQLITE_DIR") or "").strip()
_DEFAULT = os.path.join(_shard, "metrics.jsonl") if _shard else ""
SRC = (os.environ.get("LUMEN_REAL_SERIES") or "").strip() or _DEFAULT

pytestmark = pytest.mark.skipif(
    not SRC or not os.path.exists(SRC),
    reason="no real series (set LUMEN_REAL_SERIES, or EMBER_SQLITE_DIR to the shard holding "
           "metrics.jsonl)")

#: Minimum samples before a channel is read at all. Below this the instrument declines the frame
#: anyway, and the skip would happen inside `reason()` where the test could not see it.
_MIN_SAMPLES = 256

#: Forecast length for the accuracy assertions. Short enough that a held-out tail exists on every
#: channel, long enough that a wrong operator diverges visibly.
_H = 10


def _rows():
    out = []
    with open(SRC, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _channel(rows, name):
    import numpy as np
    v = [r.get(name) for r in rows]
    v = [float(x) for x in v if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return np.asarray(v, dtype=float)


def _numeric_channels(rows):
    """Every scalar channel long enough to read — discovered, not listed."""
    keys = set()
    for r in rows:
        keys |= {k for k, v in r.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return sorted(k for k in keys if _channel(rows, k).size >= _MIN_SAMPLES)


def _counters(rows):
    """The channels that are non-decreasing over the whole record.

    Derived from the data, because the obvious guesses are wrong on this file: `total_artifacts`,
    `bytes` and `content_docs` all fall at reshards and retirements, so they are not counters here.
    What survives is `operators`, `symbols`, `wordnet`, `ts` and `retired_this_cycle`."""
    import numpy as np
    return [n for n in _numeric_channels(rows)
            if bool(np.all(np.diff(_channel(rows, n)) >= -1e-12))]


def test_real_series_are_actually_present_and_long_enough():
    """The fixture check. Without it every assertion below could pass on an empty file."""
    rows = _rows()
    assert len(rows) >= _MIN_SAMPLES, "only %d usable rows at %s" % (len(rows), SRC)
    assert _counters(rows), "no non-decreasing channel in %s — no counter fixture here" % SRC


def test_NO_channel_is_forecast_FURTHER_than_it_has_been_observed():
    """The invariant real data bought, held across every channel rather than the one that broke it.

    `rho`'s pre-fix horizon of 12,143,019 steps makes the rollout ask for 68.8 GiB. An operator may
    not claim to see further than it has ever looked, so `_operator_horizon` bounds the step by the
    transitions it was fitted from. This is where a regression would surface first, and it is a
    statement about the horizon only — nothing here judges whether the structure is genuine."""
    rows = _rows()
    checked = 0
    for name in _numeric_channels(rows):
        x = _channel(rows, name)
        X = x.reshape(-1, 1)
        res = reasoning.ReasoningRouter().reason([X], X, dt=1.0)
        if res.regime != reasoning.DETERMINISTIC:
            continue
        checked += 1
        assert res.horizon is not None and res.horizon <= X.shape[0], (
            "%r was forecast %s steps from %d samples — the horizon ran past its own evidence"
            % (name, res.horizon, X.shape[0]))
        assert res.forecast is not None and len(res.forecast) == res.horizon
    assert checked, (
        "no channel was answered at all, so the bound was never exercised — this test would pass "
        "on a router that refused everything")


def test_a_COUNTER_has_no_DERIVABLE_horizon_but_is_forecast_ACCURATELY_when_given_one():
    """A counter has a law and no derivable horizon.

    A cumulative counter has a perfectly good law — `x[t+1] = x[t] + c` — and the propagator
    recovers it. What it does not have is a decay rate, so `ℓ` cannot be derived and `horizon=None`
    is refused. Both halves are asserted together: the refusal alone reads as a gate working when
    it is a horizon missing.

    Accuracy is scored against the channel's own held-out tail, so the oracle is the data and not
    the router. The bar is 1% median absolute percentage error — the measured values are 0.002% to
    0.056%, so this is more than an order of magnitude of margin and would still fail on any fit
    that had genuinely lost the series."""
    import numpy as np
    rows = _rows()
    names = _counters(rows)
    scored = 0
    for name in names:
        x = _channel(rows, name)
        X = x.reshape(-1, 1)

        no_h = reasoning.ReasoningRouter().reason([X], X, dt=1.0)
        if no_h.regime == reasoning.DETERMINISTIC:
            # A counter whose spectrum happens to carry a decaying mode is not the fixture this
            # test is about; it is not a failure, it just does not exercise the claim.
            continue
        if no_h.complexity == 0:
            # Refused at the rank gate, before any horizon question arises. `retired_this_cycle` is
            # flat at zero on the reference file and reads this way. A different refusal, and not
            # the one under test — asserting the horizon wording here would be asserting against a
            # measurement that never happened.
            continue
        assert no_h.why and "horizon" in no_h.why, (
            "%r was refused, but not for want of a horizon (why=%r) — if the refusal is about the "
            "data being an artefact, this module has grown a judgement it cannot justify"
            % (name, no_h.why))

        split = x.size - _H
        tr = x[:split].reshape(-1, 1)
        truth = x[split:split + _H]
        res = reasoning.ReasoningRouter().reason([tr], tr, horizon=_H, dt=1.0)
        if res.regime != reasoning.DETERMINISTIC:
            continue
        scored += 1
        fc = np.asarray(res.forecast).ravel()[:_H]
        denom = np.where(np.abs(truth) > 0, np.abs(truth), 1.0)
        mape = float(np.median(np.abs(fc - truth) / denom) * 100.0)
        assert mape < 1.0, (
            "%r forecast at a stated horizon is off by %.3f%% median — the rollout has lost a "
            "series it used to reproduce to 0.05%%" % (name, mape))
    assert scored, (
        "no counter was both refused without a horizon and answered with one, so neither half of "
        "the claim was exercised")


def test_the_gate_does_not_refuse_EVERY_real_channel():
    """The control that keeps the file honest. "Refuse everything" satisfies every assertion above.

    Measured on the reference file: `dark_matter` answers with |mu| = 0.9811 and a horizon of 115
    steps against 2,293 rows — comfortably inside its own evidence."""
    rows = _rows()
    answered = [n for n in _numeric_channels(rows)
                if reasoning.ReasoningRouter().reason(
                    [_channel(rows, n).reshape(-1, 1)],
                    _channel(rows, n).reshape(-1, 1), dt=1.0).regime == reasoning.DETERMINISTIC]
    assert answered, (
        "every real channel was refused with no horizon stated — a gate that never answers is an "
        "off switch, and it would satisfy every other assertion in this file")


def test_a_real_PANEL_is_read_without_raising_and_respects_the_same_bound():
    """The multivariate path, which the single-channel tests never reach: `reason()` fits a VAR here
    rather than an AR. The panel is per-content-type artifact counts — 12 real channels.

    No claim is made about which regime is correct for a panel of counters; the assertion is that
    the read completes and that any answer it gives stays inside its own evidence."""
    import collections
    import numpy as np
    rows = _rows()
    present = collections.Counter()
    for r in rows:
        for k in (r.get("by_content_type") or {}):
            present[k] += 1
    types = [k for k, v in present.most_common() if v >= len(rows) - 3][:12]
    if len(types) < 2:
        pytest.skip("no multi-channel content-type panel in this file")

    M = np.zeros((len(rows), len(types)))
    for i, r in enumerate(rows):
        b = r.get("by_content_type") or {}
        for j, k in enumerate(types):
            M[i, j] = float(b.get(k, 0.0))

    res = reasoning.ReasoningRouter().reason([M], M, dt=1.0)
    assert res.regime in (reasoning.DETERMINISTIC, reasoning.NON_COMPACT)
    if res.regime == reasoning.DETERMINISTIC:
        assert res.horizon is not None and res.horizon <= M.shape[0], (
            "the panel was forecast %s steps from %d samples" % (res.horizon, M.shape[0]))
    else:
        assert res.forecast is None and res.why
