"""Co-registration — puts heterogeneous signals onto one ordered clock, so the Screen can read them together.

Persona: ophan (market algorithms, knowledge, processing) — arithmetic over bars and headlines that
have already arrived. It touches no network; astra's organons do the touching.

## What this answers

`market_frame.py` reads one homogeneous basket: `{symbol: bars}` → a `(T, F_symbols)` return
waterfall, and answers *"do these symbols move together"*. This module answers a different question —
*"does anything outside the price series move with it"* — by putting a non-price observation on the
same clock as a price one.

The Screen reads an ordered `(T, F)` matrix and reports how many independent directions it is made of;
it does not care what a column means. So mixing price with news, macro, or on-chain is a framing
problem, not a new instrument, and this module is that framing and nothing more. The read stays
`market_frame.read_market`'s, against the same correlated null.

## Three ways a co-registered frame can lie, and what is done about each

**1. Manufactured resolution.** Two planes on different cadences cannot be joined on the finer one
without inventing observations for the coarser. `join_cadence` returns the coarsest cadence present,
always — going finer would have the instrument read invented rows as real, quiet data.

**2. Absence read as zero.** This distinction is not the same answer for every plane. A bar that did
not arrive is absent — nobody observed the price and no value may be written, which is why
`market_frame.aligned_closes` inner-joins and never fills. A bucket in which the news feed returned
nothing is a real zero: the feed was observed across that bucket and carried nothing, and dropping it
would delete the quiet periods, which is most of the signal. The two are told apart by a declared
`fill` on the plane plus an `observed` extent, never guessed from the data: zero the cell for the sum,
never count it in the extent. A `FILL_ZERO_IN_EXTENT` plane zero-fills inside its observed window and
stays absent outside it.

**3. Silent re-bucketing.** Putting a fine plane onto a coarse clock is an aggregation, and the right
aggregation is a property of the quantity, not of the framer. Log returns sum over time (the one
genuinely nice property of log returns). Counts sum. A distinct-source count does not — the union is
gone once bucketed — and neither does an entropy. Every column declares its own `agg`, and a column
declaring `AGG_NONE` refuses to be re-bucketed, naming itself. The honest fix for such a column is to
rebuild it from raw observations at the target cadence, which is why `news_counts_plane` takes the
cadence as an argument instead of being resampled after the fact.

## What is deliberately not here

**No normalisation.** The planes come back in their native units, wildly incommensurate (log returns
~1e-3, article counts ~10¹, entropy ~bits). Normalisation happens on the Screen, by entroptics' own MAD
whitening, through `optics.screen_normalize` at read time via the injected slot. Scaling columns here
would be a second, weaker normaliser free to disagree with the instrument's, and per-column division is
how cosine similarity gets reinvented.

**No weights, no scores.** A sentiment score is a trained-model shape and is forbidden.
`news_counts_plane` publishes only what is directly observable in the feed's own metadata — how many
items, from how many distinct sources, how dispersed across them, how stale. Whether any of that moves
with price is a measurement (`joint_entropies`, `read_ordered`), not an assumption baked into a
coefficient. If the answer is "nothing", the frame says so.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, List, Optional, Sequence

#: A missing sample is absent — the bucket is dropped from the join. Sampled state (a price, an
#: implied vol, a funding rate): nobody observed it, so no value may be written.
FILL_NEVER = "never"

#: A missing sample inside the plane's observed extent is a real zero. Counting observations over a
#: window (articles, transactions, mentions): the window was watched and carried nothing. Outside the
#: extent it is absent, exactly like `FILL_NEVER`.
FILL_ZERO_IN_EXTENT = "zero_in_extent"

FILLS = (FILL_NEVER, FILL_ZERO_IN_EXTENT)

#: Additive over time — log returns, counts. Re-buckets by summation, exactly.
AGG_SUM = "sum"
#: The state at the end of the bucket — a level, a rate. Re-buckets by taking the last sample.
AGG_LAST = "last"
#: Cannot be re-bucketed. A distinct count, an entropy, any statistic whose inputs are gone once
#: bucketed. Rebuild it from raw observations at the target cadence instead.
AGG_NONE = "none"

AGGS = (AGG_SUM, AGG_LAST, AGG_NONE)


class PlaneError(ValueError):
    """A plane or a co-registration that cannot be built honestly. Raised rather than returning a
    degenerate frame — a read over a fabricated frame is worse than no read, because it looks like a
    measurement."""


# ── the clock ─────────────────────────────────────────────────────────────────────────────────────

def epoch_seconds(ts: str) -> float:
    """ISO-8601 → epoch seconds. Raises on an unparseable stamp rather than dropping it.

    Both producers in this stack emit something `fromisoformat` accepts on 3.12: astra's Binance rows
    carry `datetime.isoformat()` with a `+00:00` offset, GDELT's are normalised to a trailing `Z`. A
    stamp that parses to a naive datetime is refused rather than assumed UTC — the whole point of the
    join is that two planes agree about when, and a silent timezone assumption is how they stop agreeing.
    """
    try:
        parsed = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PlaneError("unparseable timestamp %r: %s" % (ts, exc))
    if parsed.tzinfo is None:
        raise PlaneError("timestamp %r has no timezone — refusing to assume UTC" % (ts,))
    return parsed.timestamp()


def bucket_start(ts: str, cadence_seconds: float) -> float:
    """The epoch second the bucket containing `ts` starts at — floor division on the cadence.

    Floor, not round: a bucket labelled by its start contains only observations at or after it, so an
    observation can never land in a bucket that began after the observation happened.
    """
    if cadence_seconds <= 0:
        raise PlaneError("cadence must be positive, got %r" % (cadence_seconds,))
    return math.floor(epoch_seconds(ts) / cadence_seconds) * cadence_seconds


def iso_utc(epoch: float) -> str:
    """Epoch seconds → ISO-8601 UTC. The bucket label, so a frame's rows are addressable by time."""
    return _dt.datetime.fromtimestamp(float(epoch), tz=_dt.timezone.utc).isoformat()


def measured_cadence(timestamps: Sequence[str]) -> Optional[float]:
    """The plane's own cadence, measured as the median gap between consecutive stamps.

    Measured, never typed: a cadence declared by a caller is a number that can disagree with the
    data it describes, while the gap structure cannot. The median (not the mean) because a feed with one
    outage would otherwise report a cadence no bar in it actually has.

    Returns None for fewer than two stamps — one observation has no cadence, and answering anything
    else would be inventing one.
    """
    if timestamps is None or len(timestamps) < 2:
        return None
    secs = sorted(epoch_seconds(t) for t in timestamps)
    gaps = [b - a for a, b in zip(secs, secs[1:]) if b > a]
    if not gaps:
        return None
    gaps.sort()
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 else 0.5 * (gaps[mid - 1] + gaps[mid])


def join_cadence(planes: Sequence[Dict[str, Any]]) -> float:
    """The clock the planes can honestly share — the coarsest cadence among them.

    Joining onto anything finer requires values the coarse plane never observed, which is the
    forward-fill defect in another costume: the instrument reads the invented rows as real (perfectly
    quiet) data and every correlation touching them is biased. The coarse plane's resolution is a hard
    ceiling on what the joint frame can resolve, and pretending otherwise does not create information —
    it only hides which plane the information came from.
    """
    cadences = [p["cadence_seconds"] for p in planes if p.get("cadence_seconds")]
    if not cadences:
        raise PlaneError("no plane carries a cadence — cannot derive a join clock")
    return max(float(c) for c in cadences)


# ── the plane ─────────────────────────────────────────────────────────────────────────────────────

def plane(name: str, *, timestamps: Sequence[str], rows: Sequence[Sequence[float]],
          columns: Sequence[str], fill: str, aggs: Optional[Sequence[str]] = None,
          observed: Optional[Sequence[str]] = None,
          cadence_seconds: Optional[float] = None) -> Dict[str, Any]:
    """One co-registerable observation set: an ordered `(T, F)` block plus how it may be joined.

    `fill` and `aggs` are declarations, not inferences. Nothing here inspects the numbers to decide
    whether a gap means zero or means absent — that is a fact about what the column measures, known to
    whoever built it and unknowable from the values (a column of zeros and a column with holes look
    identical once written down).

    `observed` is `(from, to)`, the window over which this feed was actually being watched. It is what
    makes `FILL_ZERO_IN_EXTENT` honest: inside it a gap is a measured zero, outside it a gap is absence.
    Omitted, it defaults to the span the timestamps themselves cover — the narrowest defensible claim,
    never wider than the evidence.

    `aggs` defaults to `AGG_NONE` for every column, which is the safe default: a column that has not
    said how it aggregates refuses to be re-bucketed instead of being summed on a guess.
    """
    if fill not in FILLS:
        raise PlaneError("plane %r: fill must be one of %s, got %r" % (name, (FILLS,), fill))
    cols = list(columns)
    if not cols:
        raise PlaneError("plane %r: a plane with no column carries nothing" % name)
    stamps = list(timestamps)
    body = [list(r) for r in rows]
    if len(stamps) != len(body):
        raise PlaneError("plane %r: %d timestamps but %d rows — a row must be addressable by time"
                         % (name, len(stamps), len(body)))
    for i, r in enumerate(body):
        if len(r) != len(cols):
            raise PlaneError("plane %r: row %d has %d values for %d columns"
                             % (name, i, len(r), len(cols)))
    use_aggs = list(aggs) if aggs is not None else [AGG_NONE] * len(cols)
    if len(use_aggs) != len(cols):
        raise PlaneError("plane %r: %d aggs for %d columns" % (name, len(use_aggs), len(cols)))
    for a in use_aggs:
        if a not in AGGS:
            raise PlaneError("plane %r: unknown agg %r; known: %s" % (name, a, (AGGS,)))

    if observed is not None:
        obs = (epoch_seconds(observed[0]), epoch_seconds(observed[1]))
    elif stamps:
        secs = [epoch_seconds(t) for t in stamps]
        obs = (min(secs), max(secs))
    else:
        obs = None

    return {
        "name": name,
        "timestamps": stamps,
        "rows": body,
        "columns": cols,
        "fill": fill,
        "aggs": use_aggs,
        "observed": obs,
        "cadence_seconds": (float(cadence_seconds) if cadence_seconds
                            else measured_cadence(stamps)),
    }


def rebucket(p: Dict[str, Any], cadence_seconds: float) -> Dict[str, Any]:
    """Put a plane onto a coarser clock, by each column's own declared aggregation.

    Refuses on any `AGG_NONE` column, naming it. A distinct-source count or an entropy genuinely
    cannot be recovered from its bucketed values, and a framer that summed them anyway would publish a
    number with no referent. Rebuild such a column from raw observations at the target cadence
    (`news_counts_plane` takes the cadence for exactly this).

    Refuses to go finer, for the reason `join_cadence` exists.
    """
    native = p.get("cadence_seconds")
    if native and cadence_seconds < native - 1e-9:
        raise PlaneError(
            "plane %r is %gs and cannot be resampled to %gs — that would manufacture resolution it "
            "never observed" % (p["name"], native, cadence_seconds))
    if native and abs(cadence_seconds - native) <= 1e-9:
        return p

    blocked = [c for c, a in zip(p["columns"], p["aggs"]) if a == AGG_NONE]
    if blocked:
        raise PlaneError(
            "plane %r cannot be re-bucketed to %gs: column(s) %s declare agg=%r. Rebuild them from "
            "raw observations at the target cadence — a distinct count or an entropy is not "
            "recoverable from its bucketed values."
            % (p["name"], cadence_seconds, ", ".join(repr(b) for b in blocked), AGG_NONE))

    grouped: Dict[float, List[List[float]]] = {}
    for ts, row in zip(p["timestamps"], p["rows"]):
        grouped.setdefault(bucket_start(ts, cadence_seconds), []).append(row)

    out_stamps: List[str] = []
    out_rows: List[List[float]] = []
    for start in sorted(grouped):                      # order is meaning, not convenience
        block = grouped[start]
        row: List[float] = []
        for j, agg in enumerate(p["aggs"]):
            col = [r[j] for r in block]
            row.append(float(sum(col)) if agg == AGG_SUM else float(col[-1]))
        out_stamps.append(iso_utc(start))
        out_rows.append(row)

    return dict(p, timestamps=out_stamps, rows=out_rows, cadence_seconds=float(cadence_seconds))


# ── the join ──────────────────────────────────────────────────────────────────────────────────────

def co_register(planes: Sequence[Dict[str, Any]],
                cadence_seconds: Optional[float] = None) -> Dict[str, Any]:
    """N heterogeneous planes → one ordered `(T, F_total)` frame the Screen can read, plus provenance.

    The columns are concatenated on the feature axis in the order the planes are given, and the rows
    are the buckets the planes can honestly share. Which buckets those are depends on each plane's
    declared `fill`:

      * `FILL_NEVER` planes intersect — a bucket survives only if every one of them observed it.
      * `FILL_ZERO_IN_EXTENT` planes do not narrow the join; inside their observed extent a missing
        bucket becomes a row of zeros, and a surviving bucket outside their extent drops (it is
        absence, not zero, and no plane may contribute a value it did not observe).

    A frame with no `FILL_NEVER` plane has nothing to intersect, so the join runs over the union of
    the count planes' buckets within their common extent.

    The provenance travels with the matrix — which planes, which cadence, how many buckets each plane
    offered and how many the join kept. A read whose frame you cannot reconstruct is not a measurement.
    """
    if not planes:
        raise PlaneError("no planes given — nothing to co-register")
    cadence = float(cadence_seconds) if cadence_seconds else join_cadence(planes)
    aligned = [rebucket(p, cadence) for p in planes]

    indexed: List[Dict[float, List[float]]] = []
    for p in aligned:
        by_bucket: Dict[float, List[float]] = {}
        for ts, row in zip(p["timestamps"], p["rows"]):
            by_bucket[bucket_start(ts, cadence)] = row
        if not by_bucket:
            raise PlaneError("plane %r contributed no buckets" % p["name"])
        indexed.append(by_bucket)

    strict = [i for i, p in enumerate(aligned) if p["fill"] == FILL_NEVER]
    if strict:
        keep = set(indexed[strict[0]])
        for i in strict[1:]:
            keep &= set(indexed[i])
    else:
        keep = set()
        for by_bucket in indexed:
            keep |= set(by_bucket)

    # A zero-fill plane may only speak inside the window it was actually watching.
    for p, by_bucket in zip(aligned, indexed):
        if p["fill"] != FILL_ZERO_IN_EXTENT or not p["observed"]:
            continue
        lo, hi = p["observed"]
        keep = {b for b in keep if lo - 1e-9 <= b <= hi + 1e-9}

    if not keep:
        raise PlaneError(
            "the planes share no bucket at %gs — cannot align without inventing observations "
            "(offered: %s)" % (cadence, ", ".join("%s=%d" % (p["name"], len(ix))
                                                  for p, ix in zip(aligned, indexed))))

    buckets = sorted(keep)                             # order is meaning: the Screen is ordered
    rows: List[List[float]] = []
    for b in buckets:
        row: List[float] = []
        for p, by_bucket in zip(aligned, indexed):
            got = by_bucket.get(b)
            if got is None:
                # Only reachable for a zero-fill plane inside its extent — the strict planes defined
                # `keep` by intersection, so they cannot be missing here.
                got = [0.0] * len(p["columns"])
            row.extend(float(v) for v in got)
        rows.append(row)

    columns: List[str] = []
    spans: Dict[str, List[int]] = {}
    for p in aligned:
        start = len(columns)
        columns.extend("%s.%s" % (p["name"], c) for c in p["columns"])
        spans[p["name"]] = [start, len(columns)]

    return {
        "rows": rows,
        "columns": columns,
        "timestamps": [iso_utc(b) for b in buckets],
        "cadence_seconds": cadence,
        # where each plane's columns sit in the joint frame — what `joint_entropies` needs to ask
        # "does this block reduce uncertainty about that one", and what a mode read needs to say
        # which plane a driver came from.
        "plane_spans": spans,
        "planes": [p["name"] for p in aligned],
        "buckets_offered": {p["name"]: len(ix) for p, ix in zip(aligned, indexed)},
        "buckets_joined": len(buckets),
        "dropped_by_alignment": {p["name"]: len(ix) - len(buckets)
                                 for p, ix in zip(aligned, indexed)},
    }


def split_planes(frame: Dict[str, Any], *names: str) -> List[List[List[float]]]:
    """Cut a co-registered frame back into its per-plane blocks, still row-aligned.

    This is what makes a directed read possible: `joint_entropies(X, Y)` needs two frames on the same
    ordered axis, and the only way to get them honestly is to cut them out of one join rather than
    build them separately (two independently-built frames are on private axes, and superposing those
    reads the misalignment rather than the signal — which is why `joint_entropies` raises on a length
    mismatch instead of truncating).
    """
    out: List[List[List[float]]] = []
    for name in names:
        span = frame["plane_spans"].get(name)
        if span is None:
            raise PlaneError("frame carries no plane %r; it has %s" % (name, frame["planes"]))
        lo, hi = span
        out.append([row[lo:hi] for row in frame["rows"]])
    return out


# ── the news counts plane ─────────────────────────────────────────────────────────────────────────

#: Column order is part of the contract — a reader must rebuild the frame identically on any host.
NEWS_COLUMNS = ("n_articles", "n_sources", "h_source", "age_median_s")

#: Only `n_articles` is additive. `n_sources` is a distinct count and `h_source` an entropy — both
#: lose their inputs at bucketing — and a median does not sum either. So this plane refuses to be
#: re-bucketed, which is why it is built at the target cadence in the first place.
NEWS_AGGS = (AGG_SUM, AGG_NONE, AGG_NONE, AGG_NONE)


def news_counts_plane(items: Sequence[Dict[str, str]], *, cadence_seconds: float,
                      observed: Optional[Sequence[str]] = None, name: str = "news",
                      conservation: Any = None) -> Dict[str, Any]:
    """News metadata → an observable `(T, 4)` plane. No score, no weights, no model.

    Every column is a direct count or a dispersion over the feed's own metadata — nothing here reads
    what a headline says, let alone how it feels about it. A sentiment score is a trained-model shape
    and is forbidden ([[no-trained-weights]]), and a hand-written lexicon would be the same thing with
    the coefficients typed in by hand ([[never-impose-knowledge-derive-it]]). What can be observed
    without a model is how much the world is talking and how broadly:

        n_articles     how many items landed in the bucket — attention volume
        n_sources      across how many distinct domains — attention breadth
        h_source       entropy over the per-source distribution, in bits — is this one outlet
                       repeating itself (low) or the whole press moving at once (high)?
        age_median_s   median staleness of the items at bucket close — is the feed reacting or recalling?

    Whether any of that moves with price is then something the instrument measures
    (`joint_entropies`, `read_ordered`), not something a coefficient asserts. If the honest answer is
    "these columns carry nothing", the read says so — which a sentiment score never can.

    `h_source` requires the conservation slot, and the refusal is the point. `entropy_bits` is a
    `prism.instrument.Conservation` member so that a caller's entropy and the instrument's own cannot
    drift into being two different definitions ([[never-handroll-probes]]). Summing `-p log2 p` here
    would be a fourth copy of the arithmetic, and the one property worth having — that it is the same
    callable — is exactly what a local restatement forfeits. A host with no instrument cannot compute
    this column, which is a capacity fact, so it refuses rather than shipping a narrower plane under
    the same name (a frame whose width depends on the host is not a frame anyone can join against).
    """
    from prism.instrument import get_default as _get_default, require as _require
    _slot = conservation if conservation is not None else _get_default()
    entropy_bits = _require(
        _slot, "entropy_bits", contract="conservation",
        at="ophan.market_planes.news_counts_plane (source dispersion over the news feed)")

    if cadence_seconds <= 0:
        raise PlaneError("cadence must be positive, got %r" % (cadence_seconds,))

    buckets: Dict[float, List[Dict[str, str]]] = {}
    for it in items or []:
        published = (it.get("published_at") or "").strip()
        if not published:
            continue                                   # an unknown publish time cannot be placed in time
        buckets.setdefault(bucket_start(published, cadence_seconds), []).append(it)

    if not buckets:
        raise PlaneError(
            "no news item carries a usable `published_at` — refusing to report an empty plane as an "
            "observation of quiet (it is an observation of nothing)")

    stamps: List[str] = []
    rows: List[List[float]] = []
    for start in sorted(buckets):                      # order is meaning, not convenience
        block = buckets[start]
        per_source: Dict[str, int] = {}
        for it in block:
            src = (it.get("source") or "").strip() or "(unattributed)"
            per_source[src] = per_source.get(src, 0) + 1
        close = start + cadence_seconds
        ages = sorted(max(0.0, close - epoch_seconds(it["published_at"])) for it in block)
        mid = len(ages) // 2
        age_median = ages[mid] if len(ages) % 2 else 0.5 * (ages[mid - 1] + ages[mid])
        rows.append([
            float(len(block)),
            float(len(per_source)),
            float(entropy_bits(list(per_source.values()))),
            float(age_median),
        ])
        stamps.append(iso_utc(start))

    return plane(
        name,
        timestamps=stamps, rows=rows, columns=list(NEWS_COLUMNS),
        # A quiet bucket is a zero here, and that is the whole reason this fill mode exists. The
        # feed was polled across the window; a bucket with no article is a measured zero, not a hole.
        # Dropping those buckets would delete the quiet periods — which are most of the series, and
        # exactly the contrast against which a burst means anything.
        fill=FILL_ZERO_IN_EXTENT, aggs=list(NEWS_AGGS),
        observed=observed, cadence_seconds=float(cadence_seconds),
    )


def magnitude_plane(series: Dict[str, Sequence[Dict[str, Any]]], *, name: str = "magnitude",
                    cadence_seconds: Optional[float] = None) -> Dict[str, Any]:
    """`{symbol: bars}` → |log return| per symbol — how much the market moved, sign discarded.

    The Screen reads a covariance spectrum, which is a linear read, and attention couples to |move|
    rather than to move: `|f|` and `f` are linearly uncorrelated by symmetry, exactly and at every
    sample size, so a signed frame is blind to volatility-coupled news no matter how much of it there
    is. A burst of coverage does not say which way the market went — it says that it went somewhere.
    Anything that couples to activity rather than to direction (news volume, search interest,
    liquidations, funding stress) is read against this plane. Anything directional (order-flow
    imbalance, a rates differential) belongs against `returns_plane`; framing a directional signal here
    would throw away the sign that is its content.

    `AGG_SUM`, and the quantity it makes is a path length, not a variance. Σ|r| over sub-buckets is
    the total distance travelled inside the bucket and is genuinely additive; `|Σr|` — the net move —
    is not the same number and is smaller whenever the path doubles back. The additive one is chosen
    because it survives re-bucketing exactly, and because activity, not displacement, is what this
    plane is for. It is deliberately not called realised volatility: that name is taken by
    `sqrt(Σr²)`, which does not sum, and using it here would invite a reader to substitute one for the
    other.
    """
    from ophan import market_frame as _mf
    frame = _mf.market_frame(series)
    return plane(
        name,
        timestamps=frame["timestamps"],
        rows=[[abs(v) for v in row] for row in frame["rows"]],
        columns=list(frame["symbols"]),
        fill=FILL_NEVER, aggs=[AGG_SUM] * len(frame["symbols"]),
        cadence_seconds=cadence_seconds,
    )


def read_co_registered(frame: Dict[str, Any], *, draws: int = 200,
                       read: Any = None) -> Dict[str, Any]:
    """Measure a co-registered frame — do the planes share a mode? — through the one instrument.

    This is `market_frame.read_market`'s question asked over a wider frame: `k_signal` is how many
    drivers clear the correlated permutation null, `top_share` how much of the joint frame the leading
    one owns. What is new is only that the columns now come from different worlds, so a driver that
    spans two plane blocks is a signal moving across them rather than within one.

    The screen is normalised first, and here that is load-bearing rather than hygienic. `read_market`
    needs no normalisation because every one of its columns is a log return — the frame is
    commensurate by construction. This frame is not: measured on the suite's own fixture, `n_articles`
    runs 0–40 while a 15m log return runs ~0.01, so the raw covariance is ~10⁷ times larger on the news
    block. Read unnormalised, the leading mode is always news, at any coupling, and the read would
    report a confident number about arithmetic rather than about the market. MAD whitening on the
    screen is the fix, applied through `optics.screen_normalize` — never a per-column rescale here,
    which is how cosine similarity gets reinvented and which would discard the magnitudes the
    conservation certificate is stated over.

    Both a full node and a beacon-backed store fill this contract: `mantle/search/beacon/engine.py::whiten`
    implements the identical MAD estimator entroptics uses, and beacon's own `noise_floor` already
    depends on it, so a multi-plane read runs on either and `isinstance(beacon, Read)` stays True.

    `whitening_amplification` is reported straight through when the instrument supplies it. MAD
    whitening can rescale a frame with heterogeneous channel occupancy by up to ~1e12, and a caller
    that cares reads that rather than assuming the frame came back comparable.
    """
    rows = frame.get("rows")
    if not rows:
        raise PlaneError("frame carries no rows — nothing to read")

    from prism.instrument import get_default as _get_default, require as _require
    _slot = read if read is not None else _get_default()
    _at = "ophan.market_planes.read_co_registered (screen the joint frame against the correlated null)"
    screen_normalize = _require(_slot, "screen_normalize", contract="read", at=_at)
    correlated_null = _require(_slot, "correlated_null", contract="read", at=_at)
    read_ordered = _require(_slot, "read_ordered", contract="read", at=_at)
    scales = _require(_slot, "scales", contract="read", at=_at)

    screen = screen_normalize(rows)
    if screen is None:
        raise PlaneError(
            "the screen could not be normalised — refusing to read incommensurate planes raw, which "
            "would report the unit mismatch as the leading mode")

    rd = read_ordered(screen, null=correlated_null(draws=draws))
    return {
        "frame": {k: frame[k] for k in
                  ("planes", "columns", "cadence_seconds", "buckets_joined",
                   "buckets_offered", "dropped_by_alignment")},
        "k_signal": rd.k_signal,
        "k_margin_last": getattr(rd, "k_margin_last", None),
        "k_margin_next": getattr(rd, "k_margin_next", None),
        "k_certain": getattr(rd, "k_certain", None),
        "top_share": rd.top_share,
        "contrast": rd.contrast,
        "scales": scales(screen),
        "whitening_amplification": getattr(rd, "whitening_amplification", None),
        "null": "permutation(draws=%d)" % draws,
    }


def returns_plane(series: Dict[str, Sequence[Dict[str, Any]]], *, name: str = "returns",
                  cadence_seconds: Optional[float] = None) -> Dict[str, Any]:
    """`{symbol: bars}` → the return waterfall as a plane, joinable against anything else.

    An adapter over `market_frame`, not a second implementation: the alignment rule (inner join, never
    forward-filled) and the differencing rule (log returns, non-positive closes refused) live there and
    are not restated here. Two definitions of "the return waterfall" is precisely how a joint read and
    a price-only read start disagreeing while both look correct.

    `fill=FILL_NEVER` and `agg=AGG_SUM`: a bar that did not arrive is absent and may not be filled,
    but a log return over a coarser bucket IS the sum of the log returns inside it — exactly, not
    approximately. That identity is what lets a 1m series be read honestly against a daily one.
    """
    from ophan import market_frame as _mf
    frame = _mf.market_frame(series)
    return plane(
        name,
        timestamps=frame["timestamps"], rows=frame["rows"],
        columns=list(frame["symbols"]),
        fill=FILL_NEVER, aggs=[AGG_SUM] * len(frame["symbols"]),
        cadence_seconds=cadence_seconds,
    )


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the living screen — a market read that accumulates, so the count can certify
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Everything above this line is one-shot: `read_co_registered` builds a frame, reads it, and throws
# the screen away, so every read starts from zero samples and the resolved count is a point estimate
# that cannot say how sure it is. entroptics measures the identical effect in `ember/optics.py`:
#
#     one turn        T=34, F=195   band=16.26   interval [2,195]   never certifies
#     pooled 20 turns T=466         band= 2.13   interval [10,59]   band falls as sqrt(F/T)
#
# What accumulation buys here, measured on the suite's own `_window` fixture (7 columns: 3
# magnitude + 4 news, 60-row windows). `interval` is the resolved-dimension confidence interval;
# `certified` means it has collapsed onto the count:
#
#     coupled      planes=1  T= 60  band=0.916  k=1  interval=(1,1)  certified=True
#                  planes=5  T=300  band=0.352  k=1  interval=(1,1)  certified=True
#     independent  planes=1  T= 60  band=0.916  k=2  interval=(1,2)  certified=False   <- cannot yet tell
#                  planes=2  T=120  band=0.600  k=2  interval=(2,2)  certified=True
#
# The independent arm is the informative one: at one window it estimates k=2 but reports `(1,2)` — it
# could be one, not yet settled — and a second window settles it. A one-shot read cannot express that
# at all; it returns a bare number with no way to state its own uncertainty. And k=1 vs k=2 is the
# market question: when news genuinely reacts, news and price magnitude are one driver observed
# twice; when it does not, they are two unrelated ones.
#
# `certified` is not a latch. More evidence can un-certify a screen: the band shrinks monotonically,
# but the estimate moves too, so a tightening interval can straddle again. Measured on 6-row windows,
# where the frame is thin enough to see it happen:
#
#     planes=1  T= 6  band=4.494  k=1  interval=(0,1)  certified=False
#     planes=2  T=12  band=2.694  k=1  interval=(1,1)  certified=True
#     planes=4  T=24  band=1.663  k=1  interval=(1,2)  certified=False   <- more evidence, less settled
#
# That is the instrument being honest, not flapping. `certified` is a statement about the evidence
# pooled right now; the monotone quantity is `band`, and it is the one to watch for progress. A caller
# that caches "this basket certified" and stops re-reading has cached a fact that has since expired.


def market_accumulator(frame: Dict[str, Any], *, read: Any = None) -> Dict[str, Any]:
    """Open a live screen sized to a co-registered frame's columns — the pooling read's front door.

    Returns a handle `{"acc", "columns", "cadence_seconds", "planes"}` rather than the bare
    accumulator, because `F` alone cannot say whether the next frame belongs. Pooling two frames
    that merely happen to be the same width is how a spectrum over two coordinate systems gets built
    and then read as one. The column names travel so `accumulate` can refuse a mismatch.

    `whiten=True` is the normalisation, not a second one: entroptics applies its own `normalize` to
    each plane before summing the covariance — the same callable `screen_normalize` exposes — so the
    pooled and one-shot paths share one definition of whitening.

    It is applied per plane, which decides what question this read answers. Per-window whitening
    makes each window contribute its correlation structure rather than its amplitude, so one loud
    window cannot dominate the pooled spectrum. The cost is that cross-window amplitude is not read:
    this answers *"do they move together"*, never *"did they move more this week"*.
    """
    cols = list(frame.get("columns") or [])
    if not cols:
        raise PlaneError("frame carries no columns — nothing to size an accumulator to")

    from prism.instrument import get_default as _get_default, require as _require
    _slot = read if read is not None else _get_default()
    accumulator = _require(
        _slot, "accumulator", contract="read",
        at="ophan.market_planes.market_accumulator (open a pooled screen over the joint frame)")
    return {
        "acc": accumulator(len(cols), whiten=True),
        "columns": cols,
        "cadence_seconds": frame.get("cadence_seconds"),
        "planes": 0,
    }


def accumulate(handle: Dict[str, Any], frame: Dict[str, Any]) -> Dict[str, Any]:
    """Pool one more co-registered frame into the living screen. Mutates and returns the handle.

    The columns must match exactly — same names, same order — and a mismatch refuses. This is the
    guard the whole pooling path stands on: entroptics and beacon both check only that `F` is
    constant, so a basket that lost `ETHUSDT` and gained `SOLUSDT` between windows would otherwise
    pool cleanly — the covariance well-formed, the read returning a confident certified count that is
    a count of nothing, undetectable downstream. `F` is not the identity of a basis; the names are.

    The cadence must match too. Windows at different bar widths carry different natural scales, so
    pooling them mixes two clocks into one covariance and the resulting `k` belongs to neither.
    """
    cols = list(frame.get("columns") or [])
    if cols != handle["columns"]:
        added = [c for c in cols if c not in handle["columns"]]
        gone = [c for c in handle["columns"] if c not in cols]
        raise PlaneError(
            "this screen pools the basis %s and was handed %s%s%s. A pooled spectrum over two "
            "coordinate systems is not a spectrum — re-open the accumulator, or co-register the new "
            "frame onto the original columns."
            % (handle["columns"], cols,
               "; gained %s" % added if added else "",
               "; lost %s" % gone if gone else ""))

    have, want = frame.get("cadence_seconds"), handle["cadence_seconds"]
    if have and want and abs(float(have) - float(want)) > 1e-9:
        raise PlaneError(
            "this screen pools %gs windows and was handed a %gs one — two clocks in one covariance "
            "produce a count that belongs to neither" % (want, have))

    rows = frame.get("rows")
    if not rows:
        raise PlaneError("frame carries no rows — refusing to pool an empty plane as an observation")
    handle["acc"].add(rows)
    handle["planes"] += 1
    return handle


def accumulated_market_read(handle: Dict[str, Any], *, read: Any = None) -> Optional[Dict[str, Any]]:
    """What the living screen currently resolves — the certified *whether*, not just a count.

    Returns the pooled read plus the basis it is over, or `None` when nothing has been pooled — which
    is a different statement from a pooled screen that resolved nothing, and the two must not share a
    value.

    Read `certified` before `k_signal`. `certified` is True only once the resolved-dimension
    interval has collapsed onto the count. Until then `k_signal` is the best estimate and `interval`
    says how far from settled it is, and the only way to close that gap is more evidence, never a
    loosened tolerance. That is why `band` and `interval` come back beside the count instead of being
    summarised away: a caller who can see only "not certified" has no move left except to relax
    something.

    The null is not the permutation null used by `read_co_registered`. A pooled accumulator retains
    the covariance, not the samples, so a resampling provider has nothing left to permute and the
    certification uses the closed-form bulk edge instead. `read_market` chose the correlated
    permutation null deliberately, because retrieved rows are correlated by construction, so the two
    paths are asked against different nulls and may legitimately disagree. Use this one for *"has the
    count settled"*; use the one-shot read for *"does this clear a correlated null"*. Neither
    substitutes for the other, and the returned `null` says which was used.
    """
    if handle.get("planes", 0) < 1:
        return None

    from prism.instrument import get_default as _get_default, require as _require
    _slot = read if read is not None else _get_default()
    accumulated_read = _require(
        _slot, "accumulated_read", contract="read",
        at="ophan.market_planes.accumulated_market_read (certify the pooled joint screen)")

    got = accumulated_read(handle["acc"])
    if got is None:
        return None
    out = dict(got)
    out["columns"] = list(handle["columns"])
    out["planes_pooled"] = handle["planes"]
    out["cadence_seconds"] = handle["cadence_seconds"]
    out["null"] = "closed-form bulk edge (a pooled screen retains no samples to permute)"
    return out
