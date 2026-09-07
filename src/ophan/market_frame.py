"""The market frame — bars -> a return waterfall the instrument can read.

Licence: chorus AGPL.

This module lives on ophan, not astra: it holds no fetcher and touches no network — it is
arithmetic over bars that have already arrived, which is an algorithm and not an ingest. What stays
on astra is the world-touching half (`market_sources.py`'s fetchers, `market_ingest.py`'s writers).
The content types this module writes against (`market-series`, `market-bars`, `market-news`,
`market-snapshot`) already live on ophan.

ember/optics.py already carries the whole measurement vocabulary this module needs, in generic
energy-flow terms: `OpticsRead.k_signal` (with the evidence behind it) for how many drivers clear a
permutation null, `read_ordered(..., null=correlated_null())` for the z-score against it,
`entropy_bits(weights)` for SVD entropy, `OpticsRead.top_share` for leading-mode share, and
`scales(rows)` / `correlation_length(rows)` / `decay_profile(W)` for the natural scales. The market
port is only the market-specific part: turning bars into the matrix that feeds these.

A basket's structure lives on the feature axis, not the ordered axis, which is why this module reads
`OpticsRead.top_share` rather than `optics.coherence()`. `coherence()` is strehl over
`axis_spectrum(W, 0)` — the ordered axis — so it asks "are the rows all the same thing?" For a return
waterfall the answer is no even when the basket is tightly driven: the driver changes sign and
magnitude every bar, so each row is a different scalar multiple of the common mode, and strehl cannot
distinguish a tightly driven basket from pure noise. `top_share` measures the dominant feature-mode
power fraction instead, which does distinguish them, and `k_signal` says how many drivers clear the
null.

`ember/optics.py` is the one door onto entroptics — nothing else may import it directly
([[one-instrument-enforced]]) — so market code stays out of ember: ember is the instrument and its
nomenclature is generic energy-flow (absorb/transmit, propagate_residual, coherence, decay_profile).
A `MarketFrame` in ember would drag a domain into the instrument; it belongs to the persona that owns
the bars.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple


class FrameError(ValueError):
    """The frame cannot be built. Raised rather than returning a degenerate matrix — a read over a
    fabricated frame is worse than no read, because it looks like a measurement."""


def aligned_closes(series: Dict[str, Sequence[Dict[str, Any]]]) -> Tuple[List[str], List[str], List[List[float]]]:
    """Align several symbols' bars onto the timestamps they all share.

    Returns `(timestamps, symbols, closes)` where `closes[t][i]` is symbol `i`'s close at `timestamps[t]`.

    Inner join on timestamp, never forward-filled: a missing bar is missing, and carrying the last
    close forward would invent a zero return, which reads to the instrument as real (perfectly quiet)
    data and biases every correlation that touches it. Dropping the timestamp is honest and costs
    only samples.

    Time order is preserved: the entroptics Screen is ordered — shuffling destroys coherence
    ([[entroptics-screen-is-ordered]]) — so the rows are sorted by timestamp, not by dict iteration.
    """
    if not series:
        raise FrameError("no series given — nothing to frame")
    symbols = sorted(series)
    per_symbol: Dict[str, Dict[str, float]] = {}
    for sym in symbols:
        rows = series[sym] or []
        by_ts: Dict[str, float] = {}
        for r in rows:
            ts, close = r.get("ts"), r.get("close")
            if ts is None or close is None:
                continue
            by_ts[str(ts)] = float(close)
        if not by_ts:
            raise FrameError("series %r has no usable (ts, close) bars" % sym)
        per_symbol[sym] = by_ts

    common = set(per_symbol[symbols[0]])
    for sym in symbols[1:]:
        common &= set(per_symbol[sym])
    if not common:
        raise FrameError("the series share no common timestamps — cannot align without inventing bars")

    timestamps = sorted(common)                       # order is meaning, not convenience
    closes = [[per_symbol[sym][ts] for sym in symbols] for ts in timestamps]
    return timestamps, symbols, closes


def log_returns(closes: Sequence[Sequence[float]]) -> List[List[float]]:
    """Per-column log returns — the waterfall the instrument reads.

    Log returns, not price levels: levels are non-stationary and their correlation matrix is dominated
    by trend, so a read over levels measures drift rather than structure. A non-positive close is
    refused rather than clamped — it is either bad data or a different instrument, and clamping would
    fabricate a return.
    """
    if len(closes) < 2:
        raise FrameError("need at least 2 bars to form one return")
    out: List[List[float]] = []
    for prev, cur in zip(closes, closes[1:]):
        row: List[float] = []
        for a, b in zip(prev, cur):
            if a <= 0.0 or b <= 0.0:
                raise FrameError("non-positive close (%r -> %r) — refusing to fabricate a return"
                                 % (a, b))
            row.append(math.log(b / a))
        out.append(row)
    return out


def market_frame(series: Dict[str, Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Bars per symbol → the ordered return waterfall, plus what it was built from.

    The provenance travels with the matrix: which symbols, which timestamps, how many were dropped by
    the inner join. A read whose frame you cannot reconstruct is not a measurement.
    """
    timestamps, symbols, closes = aligned_closes(series)
    rows = log_returns(closes)
    offered = {sym: len(series[sym] or []) for sym in symbols}
    return {
        "symbols": symbols,
        "timestamps": timestamps[1:],                 # one fewer row than closes, by construction
        "rows": rows,
        "bars_offered": offered,
        "bars_aligned": len(timestamps),
        "returns": len(rows),
        "dropped_by_alignment": {s: offered[s] - len(timestamps) for s in symbols},
    }


def read_market(series: Dict[str, Sequence[Dict[str, Any]]], *, draws: int = 200,
                read: Any = None) -> Dict[str, Any]:
    """Measure a basket through the one instrument — no fitted parameters, no configured rate.

    This is the whole point of the market port: canon says **"the screen is the market — rates are
    measured, never configured"**, and this is that sentence executed. It returns the instrument's
    read (`k_signal` and the evidence behind it, coherence, scales) against the **correlated
    permutation null** — the right null here because retrieved rows are correlated by construction,
    which is exactly what `Read.correlated_null` exists for.

    `read` is the structure-read instrument — `prism.instrument.Read`, whose `correlated_null`,
    `read_ordered` and `scales` this function is the one caller of. Keyword-only and defaulting to
    `None`, which is not "no measurement": with nothing injected and no process default registered,
    the read refuses with `InstrumentRequired` at the moment it is asked. A full node fills it with
    `ember.optics`; a beacon-backed store fills it with its own.

    The instrument is injected rather than imported, because an import — even a lazy one — would be
    an L3->L3 edge from chorus to the layer that owns the instrument. Every member reached here is a
    `Read` member and not an `Instrument` one: this function reads and never splits, which is why
    `prism.instrument` declares the two separately.
    """
    frame = market_frame(series)
    # The refusal belongs after the frame is built, not before: aligning bars, dropping unshared
    # timestamps and differencing to returns are structural facts about the bars, and `market_frame`
    # still answers them on a host with no instrument at all. Only the read needs one.
    #
    # Resolution order is `prism.instrument`'s, most specific first: the `read=` keyword, then the
    # process default a host registered, then a refusal naming the member and the operation. There
    # is no fourth step. (`prism.instrument.resolve` is the same two steps hard-wired to the
    # `"embodiment"` slot; `Read` consumers pass their own, which is what its docstring says to do.)
    from prism.instrument import get_default as _get_default, require as _require
    _slot = read if read is not None else _get_default()
    _at = "ophan.market_frame.read_market (screen the aligned basket against the correlated null)"
    correlated_null = _require(_slot, "correlated_null", contract="read", at=_at)
    read_ordered = _require(_slot, "read_ordered", contract="read", at=_at)
    scales = _require(_slot, "scales", contract="read", at=_at)

    rd = read_ordered(frame["rows"], null=correlated_null(draws=draws))
    return {
        "frame": {k: frame[k] for k in
                  ("symbols", "bars_offered", "bars_aligned", "returns", "dropped_by_alignment")},
        # How many drivers clear the null, and the evidence either side of the cut.
        "k_signal": rd.k_signal,
        "k_margin_last": getattr(rd, "k_margin_last", None),
        "k_margin_next": getattr(rd, "k_margin_next", None),
        "k_certain": getattr(rd, "k_certain", None),
        # How much of the basket the leading driver owns — `top_share`, the dominant-mode power
        # fraction. Not `optics.coherence()`: that is strehl, which does not distinguish a tightly
        # driven basket from pure noise (see the module docstring).
        "top_share": rd.top_share,
        "contrast": rd.contrast,            # lambda_1 / noise floor: >1 means structure
        # The ordered-axis lag-1 coherence z-score — a different quantity that shares the name
        # `coherence` in this module. Order-sensitive, which is why the frame is time-sorted.
        "lag1_coherence_z": rd.coherence,
        "scales": scales(frame["rows"]),
        "null": "permutation(draws=%d)" % draws,
    }
