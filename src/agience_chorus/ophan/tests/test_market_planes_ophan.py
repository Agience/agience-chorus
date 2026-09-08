"""Co-registration — heterogeneous planes onto one clock, and the ways that can silently lie.

What is pinned here is the set of frames the instrument would happily read and report a confident number
over, every one of which is a fabrication: a coarse plane resampled onto a fine clock, a distinct-count
column summed as if it were additive, a quiet news bucket deleted as if it were a hole, a bucket filled
outside the window anyone was watching, and rows in dict order rather than time order.

The filename is deliberately unique across chorus: duplicate test basenames substitute silently under
pytest, and the file would be dropped with no error at all.
"""
import math

import pytest

from agience_chorus.ophan import market_planes as mp

# The test is the host. `news_counts_plane` takes a `conservation=` slot against
# `prism.instrument.Conservation` and has no reading to give when it is empty — so this file imports
# the instrument and hands it over, exactly as the market-frame suite does for the `read` slot. The
# import belongs here and not in the module under test: a persona reaching into ember directly is the
# edge `test_chorus_does_not_import_the_archived_beam.py` holds at zero for product code.
from ember import optics as INSTRUMENT

MIN = 60.0
HOUR = 3600.0
#: A fixed epoch second — nothing here may depend on the wall clock. Divisible by 3600 (and so by
#: 900), deliberately: `bucket_start` floors onto the cadence, so an unaligned base would make every
#: bucket's label differ from the stamp that fell in it. That is the flooring working correctly, and a
#: fixture that ignored it would be testing its own arithmetic rather than the join.
BASE = 1_759_996_800


def _ts(offset_seconds):
    return mp.iso_utc(BASE + offset_seconds)


def _news(*offsets_and_sources):
    return [{"title": "h", "source": src, "published_at": _ts(off), "url": "", "lang": "en"}
            for off, src in offsets_and_sources]


# ── the clock: coarsest wins, and finer raises ────────────────────────────────────────────────────

def test_cadence_is_measured_from_the_gaps_not_declared():
    """A caller's declared cadence can disagree with the data; the gap structure cannot. Fails if
    `measured_cadence` ever trusts an argument over the stamps."""
    stamps = [_ts(i * 900) for i in range(10)]
    assert mp.measured_cadence(stamps) == 900.0


def test_cadence_median_survives_one_outage():
    """One gap of an hour in a 15m series must not move the reported cadence. Fails if the mean is
    used — the mean here reads 1215s, a cadence no bar in the series has."""
    stamps = [_ts(0), _ts(900), _ts(1800), _ts(1800 + 3600), _ts(1800 + 4500)]
    assert mp.measured_cadence(stamps) == 900.0


def test_join_clock_is_the_coarsest_plane():
    """The central rule: joining onto anything finer needs values the coarse plane never observed."""
    fine = mp.plane("fine", timestamps=[_ts(i * 900) for i in range(8)],
                    rows=[[float(i)] for i in range(8)], columns=["x"],
                    fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    coarse = mp.plane("coarse", timestamps=[_ts(i * 3600) for i in range(3)],
                      rows=[[float(i)] for i in range(3)], columns=["y"],
                      fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    assert mp.join_cadence([fine, coarse]) == 3600.0
    assert mp.join_cadence([coarse, fine]) == 3600.0     # order of argument must not decide


def test_resampling_finer_is_refused_by_name():
    """The fabrication this module exists to prevent. Fails (silently, in production) if `rebucket`
    ever interpolates — the instrument reads invented rows as real, perfectly quiet data."""
    coarse = mp.plane("coarse", timestamps=[_ts(i * 3600) for i in range(3)],
                      rows=[[float(i)] for i in range(3)], columns=["y"],
                      fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    with pytest.raises(mp.PlaneError) as e:
        mp.rebucket(coarse, 900.0)
    assert "manufacture resolution" in str(e.value)


# ── re-bucketing: the aggregation is a property of the quantity ─────────────────────────────────────

def test_log_returns_sum_exactly_across_buckets():
    """The identity that makes cross-scale reads honest: a log return over an hour is the sum of the
    four 15m log returns inside it — exactly, not approximately. This is why a 1m series can be read
    against a daily one without either being resampled dishonestly."""
    steps = [0.01, -0.004, 0.007, -0.002, 0.003, 0.001, -0.005, 0.002]
    p = mp.plane("r", timestamps=[_ts(i * 900) for i in range(8)],
                 rows=[[s] for s in steps], columns=["SYM"],
                 fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    hourly = mp.rebucket(p, 3600.0)
    assert len(hourly["rows"]) == 2
    assert hourly["rows"][0][0] == pytest.approx(sum(steps[:4]), abs=1e-12)
    assert hourly["rows"][1][0] == pytest.approx(sum(steps[4:]), abs=1e-12)


def test_agg_last_takes_the_state_at_bucket_close():
    """A level is not additive — resampling it must take the closing state, not the sum."""
    p = mp.plane("lvl", timestamps=[_ts(i * 900) for i in range(4)],
                 rows=[[10.0], [11.0], [12.0], [13.0]], columns=["iv"],
                 fill=mp.FILL_NEVER, aggs=[mp.AGG_LAST])
    assert mp.rebucket(p, 3600.0)["rows"] == [[13.0]]


def test_distinct_count_refuses_to_be_rebucketed_and_names_itself():
    """A distinct count and an entropy lose their inputs at bucketing. Summing them would publish a
    number with no referent. Fails if `AGG_NONE` is ever treated as a default-to-sum."""
    p = mp.plane("news", timestamps=[_ts(i * 900) for i in range(4)],
                 rows=[[3.0, 2.0]] * 4, columns=["n_articles", "n_sources"],
                 fill=mp.FILL_ZERO_IN_EXTENT, aggs=[mp.AGG_SUM, mp.AGG_NONE])
    with pytest.raises(mp.PlaneError) as e:
        mp.rebucket(p, 3600.0)
    assert "n_sources" in str(e.value)


def test_columns_default_to_refusing_rebucket():
    """The safe default: a column that has not declared how it aggregates must not be guessed at."""
    p = mp.plane("x", timestamps=[_ts(i * 900) for i in range(4)],
                 rows=[[1.0]] * 4, columns=["c"], fill=mp.FILL_NEVER)
    assert p["aggs"] == [mp.AGG_NONE]


# ── absence vs zero: the distinction the module turns on ──────────────────────────────────────────

def test_missing_sample_in_a_strict_plane_drops_the_bucket():
    """A price nobody observed may not be written. The bucket leaves the join entirely."""
    a = mp.plane("a", timestamps=[_ts(0), _ts(900), _ts(1800)],
                 rows=[[1.0], [2.0], [3.0]], columns=["x"],
                 fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    b = mp.plane("b", timestamps=[_ts(0), _ts(1800)],
                 rows=[[9.0], [8.0]], columns=["y"],
                 fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM], cadence_seconds=900.0)
    frame = mp.co_register([a, b])
    assert frame["buckets_joined"] == 2                       # the 900s bucket is gone, not filled
    assert frame["timestamps"] == [_ts(0), _ts(1800)]
    assert frame["rows"] == [[1.0, 9.0], [3.0, 8.0]]


def test_quiet_news_bucket_is_a_measured_zero_not_a_hole():
    """The other half, and the one that is easy to get backwards. The feed was polled across the
    window and carried nothing. Dropping these buckets deletes the quiet periods — most of the series,
    and the contrast against which a burst means anything. Fails if the news plane is intersected."""
    price = mp.plane("px", timestamps=[_ts(i * 900) for i in range(4)],
                     rows=[[float(i)] for i in range(4)], columns=["SYM"],
                     fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    news = mp.plane("news", timestamps=[_ts(900)], rows=[[5.0]], columns=["n_articles"],
                    fill=mp.FILL_ZERO_IN_EXTENT, aggs=[mp.AGG_SUM],
                    observed=(_ts(0), _ts(2700)), cadence_seconds=900.0)
    frame = mp.co_register([price, news])
    assert frame["buckets_joined"] == 4                       # every price bucket survives
    assert [r[1] for r in frame["rows"]] == [0.0, 5.0, 0.0, 0.0]


def test_zero_fill_stops_at_the_observed_extent():
    """Outside the window nobody was watching, a gap is absence and no zero may be written. Fails if
    the extent is ignored — the frame then claims quiet over a period it never observed at all."""
    price = mp.plane("px", timestamps=[_ts(i * 900) for i in range(6)],
                     rows=[[float(i)] for i in range(6)], columns=["SYM"],
                     fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    news = mp.plane("news", timestamps=[_ts(900)], rows=[[5.0]], columns=["n_articles"],
                    fill=mp.FILL_ZERO_IN_EXTENT, aggs=[mp.AGG_SUM],
                    observed=(_ts(0), _ts(1800)), cadence_seconds=900.0)
    frame = mp.co_register([price, news])
    assert frame["buckets_joined"] == 3                       # buckets 3,4,5 are outside the extent
    assert frame["timestamps"] == [_ts(0), _ts(900), _ts(1800)]


def test_observed_extent_defaults_to_the_evidence_not_wider():
    """An omitted extent must be the narrowest defensible claim — the span the stamps themselves
    cover. Fails if it ever defaults to unbounded, which would zero-fill unwatched time."""
    p = mp.plane("news", timestamps=[_ts(900), _ts(1800)], rows=[[1.0], [2.0]],
                 columns=["n"], fill=mp.FILL_ZERO_IN_EXTENT, aggs=[mp.AGG_SUM])
    assert p["observed"] == (float(BASE + 900), float(BASE + 1800))


# ── order, and invalid input ─────────────────────────────────────────────────────────────────────

def test_rows_are_time_ordered_regardless_of_input_order():
    """The entroptics Screen is ordered — shuffling destroys coherence. Fails if the join ever
    iterates a dict rather than sorting on the bucket."""
    a = mp.plane("a", timestamps=[_ts(1800), _ts(0), _ts(900)],
                 rows=[[3.0], [1.0], [2.0]], columns=["x"],
                 fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    frame = mp.co_register([a])
    assert frame["rows"] == [[1.0], [2.0], [3.0]]
    assert frame["timestamps"] == [_ts(0), _ts(900), _ts(1800)]


def test_naive_timestamp_is_refused_not_assumed_utc():
    """Two planes agree about when, or the join is meaningless. A silent timezone assumption is how
    they stop agreeing while both still look correct."""
    with pytest.raises(mp.PlaneError) as e:
        mp.epoch_seconds("2026-08-07T12:00:00")
    assert "refusing to assume UTC" in str(e.value)


def test_disjoint_planes_refuse_rather_than_return_an_empty_frame():
    a = mp.plane("a", timestamps=[_ts(0), _ts(900)], rows=[[1.0], [2.0]], columns=["x"],
                 fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    b = mp.plane("b", timestamps=[_ts(100_000), _ts(100_900)], rows=[[1.0], [2.0]], columns=["y"],
                 fill=mp.FILL_NEVER, aggs=[mp.AGG_SUM])
    with pytest.raises(mp.PlaneError) as e:
        mp.co_register([a, b])
    assert "share no bucket" in str(e.value)


# ── the news plane: observable, never scored ──────────────────────────────────────────────────────

def test_news_plane_counts_volume_breadth_and_dispersion():
    items = _news((60, "reuters.com"), (120, "reuters.com"), (180, "ft.com"),
                  (3700, "wsj.com"))
    p = mp.news_counts_plane(items, cadence_seconds=HOUR, conservation=INSTRUMENT)
    assert p["columns"] == list(mp.NEWS_COLUMNS)
    assert [r[0] for r in p["rows"]] == [3.0, 1.0]            # n_articles
    assert [r[1] for r in p["rows"]] == [2.0, 1.0]            # n_sources: reuters+ft, then wsj
    # h_source: 2-from-one-source + 1-from-another is not flat, so strictly between 0 and log2(2).
    assert 0.0 < p["rows"][0][2] < 1.0
    assert p["rows"][1][2] == 0.0                            # a single source disperses nothing


def test_news_dispersion_is_the_instruments_entropy_not_a_local_copy():
    """The column must be `entropy_bits` itself, not a local re-implementation, so a caller's entropy
    and the instrument's own cannot drift into two definitions. Fails if the arithmetic is restated
    locally."""
    items = _news((60, "a.com"), (120, "b.com"), (180, "c.com"), (240, "d.com"))
    p = mp.news_counts_plane(items, cadence_seconds=HOUR, conservation=INSTRUMENT)
    assert p["rows"][0][2] == pytest.approx(INSTRUMENT.entropy_bits([1, 1, 1, 1]))
    assert p["rows"][0][2] == pytest.approx(2.0)             # four flat sources = log2(4)


def test_news_plane_refuses_without_the_conservation_slot():
    """Without the conservation slot, `news_counts_plane` raises rather than substituting a zero
    dispersion or a narrower plane under the same name: a frame whose width depends on which host
    filled it is not a frame anything can join against."""
    from prism.instrument import InstrumentRequired
    items = _news((60, "a.com"))
    with pytest.raises(InstrumentRequired) as e:
        mp.news_counts_plane(items, cadence_seconds=HOUR, conservation=object())
    assert e.value.member == "entropy_bits"


def test_news_plane_refuses_an_all_undated_batch():
    """An item with no publish time cannot be placed in time, and a plane built from none of them is
    an observation of nothing — which must not be reported as an observation of quiet."""
    items = [{"title": "h", "source": "a.com", "published_at": ""}]
    with pytest.raises(mp.PlaneError) as e:
        mp.news_counts_plane(items, cadence_seconds=HOUR, conservation=INSTRUMENT)
    assert "observation of nothing" in str(e.value)


def test_news_plane_cannot_be_silently_resampled():
    """The plane declares itself unresamplable, so a caller who joins it against a coarser price
    series is told to rebuild it rather than handed a summed distinct-count."""
    items = _news((60, "a.com"), (900, "b.com"), (3700, "c.com"))
    p = mp.news_counts_plane(items, cadence_seconds=900.0, conservation=INSTRUMENT)
    with pytest.raises(mp.PlaneError) as e:
        mp.rebucket(p, HOUR)
    assert "n_sources" in str(e.value) and "raw observations" in str(e.value)


# ── the returns plane, and the round trip through the frame ───────────────────────────────────────

def _bars(n, step=900, start=100.0, drift=0.001):
    return [{"ts": _ts(i * step), "close": start * math.exp(drift * i)} for i in range(n)]


def test_returns_plane_delegates_to_market_frame():
    """An adapter, not a second implementation — two definitions of "the return waterfall" is how a
    joint read and a price-only read start disagreeing while both look correct."""
    p = mp.returns_plane({"A": _bars(6), "B": _bars(6, drift=0.002)})
    assert p["columns"] == ["A", "B"]
    assert p["fill"] == mp.FILL_NEVER
    assert p["aggs"] == [mp.AGG_SUM, mp.AGG_SUM]
    assert len(p["rows"]) == 5                               # one fewer than the bars, by construction
    assert p["rows"][0][0] == pytest.approx(0.001, abs=1e-9)


def test_split_planes_returns_row_aligned_blocks():
    """`joint_entropies` needs two frames on the same ordered axis and raises on a mismatch. The only
    honest way to get them is to cut them out of one join."""
    price = mp.returns_plane({"A": _bars(9)})
    news = mp.news_counts_plane(_news((900, "a.com"), (1800, "b.com"), (1800, "c.com")),
                                cadence_seconds=900.0, observed=(_ts(0), _ts(7200)),
                                conservation=INSTRUMENT)
    frame = mp.co_register([price, news])
    x, y = mp.split_planes(frame, "returns", "news")
    assert len(x) == len(y) == len(frame["rows"])
    assert len(x[0]) == 1 and len(y[0]) == 4
    assert frame["columns"][0] == "returns.A"
    assert frame["columns"][1] == "news.n_articles"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# The matched pair — these two only mean something together.
#
# "co_register returned a matrix and joint_entropies returned a number" is not evidence of anything:
# a frame of pure noise produces both. What has to be shown is that a news plane genuinely coupled to
# the price moves reads higher than one that is independent of them — measured through the same call,
# on the same shapes, changing only whether the coupling exists.
# ══════════════════════════════════════════════════════════════════════════════════════════════════

def _coupled_basket(n=240, coupled=True, seed=7):
    """Returns driven by a common factor, plus a news feed that either reacts to it or does not.

    The coupling is the one a market actually shows: attention spikes when the move is large, in
    either direction. So `n_articles` tracks |f| — which is deliberately not a linear relationship
    with the signed return, because a read that only survives on a linear coupling would be a weaker
    claim than the one being made.
    """
    import random
    rng = random.Random(seed)
    factor = [rng.gauss(0.0, 0.01) for _ in range(n)]
    closes = {"A": [100.0], "B": [50.0], "C": [25.0]}
    for f in factor:
        for sym, beta in (("A", 1.0), ("B", 0.8), ("C", 1.2)):
            closes[sym].append(closes[sym][-1] * math.exp(beta * f + rng.gauss(0.0, 0.001)))
    series = {sym: [{"ts": _ts(i * 900), "close": c} for i, c in enumerate(vals)]
              for sym, vals in closes.items()}

    items = []
    for i, f in enumerate(factor):
        burst = int(abs(f) * 400) if coupled else int(abs(rng.gauss(0.0, 0.01)) * 400)
        for j in range(burst):
            items.append({"title": "h", "source": "src%d" % (j % 5),
                          "published_at": _ts((i + 1) * 900 + 1), "url": "", "lang": "en"})
    return series, items


def _joint_read(coupled, price_plane=mp.magnitude_plane, plane_name="magnitude"):
    series, items = _coupled_basket(coupled=coupled)
    price = price_plane(series)
    news = mp.news_counts_plane(items, cadence_seconds=900.0,
                                observed=(_ts(0), _ts(241 * 900)), conservation=INSTRUMENT)
    frame = mp.co_register([price, news])
    assert frame["plane_spans"][plane_name] == [0, 3]         # the join did not silently reshape
    assert frame["plane_spans"]["news"] == [3, 7]
    return mp.read_co_registered(frame, draws=200, read=INSTRUMENT), frame


def test_coupled_news_and_price_magnitude_read_as_ONE_driver():
    """The point of the whole module, executed: a feed that bursts when the market moves is not a
    second signal — it is the same signal observed through a different instrument, and a Screen that
    is framing them honestly must resolve exactly one driver spanning both blocks.

    Measured: k_signal 1, top_share 0.867, contrast 4.58."""
    r, frame = _joint_read(coupled=True)
    assert frame["buckets_joined"] == 240                     # the join did not collapse
    assert r["k_signal"] == 1                                 # one driver, spanning both planes
    assert r["top_share"] > 0.8                               # and it owns the joint frame


def test_independent_news_reads_as_a_SECOND_driver_not_a_shared_one():
    """The negative control, and the only reason to believe the test above. Same shapes, same call,
    same 240 buckets — the only difference is whether the feed reacts to the factor. Without it,
    "the read returned a number" is satisfied by any two frames at all.

    Measured: k_signal 2 (the two blocks are separate things), top_share 0.500 against the coupled
    0.867 — a wide separation, not a hair."""
    coupled, f_c = _joint_read(coupled=True)
    alone, f_a = _joint_read(coupled=False)
    assert f_c["buckets_joined"] == f_a["buckets_joined"], "shapes must match or this compares nothing"
    assert alone["k_signal"] == 2                             # magnitude and news are two drivers
    assert alone["top_share"] < 0.6
    assert coupled["top_share"] > alone["top_share"] + 0.3    # wide, not a hair


def test_signed_returns_are_BLIND_to_volatility_coupled_news():
    """The finding this suite exists to pin: the Screen reads a covariance spectrum, which is linear,
    and news volume couples to |move|, not to move. `|f|` and `f` are linearly uncorrelated by
    symmetry — exactly, at every sample size — so a signed frame cannot see this coupling however
    strong it is. Measured on the identical fixture: top_share 0.4880 coupled vs 0.4860 independent,
    k_signal 2 in both. Indistinguishable.

    This is the guard against someone simplifying `magnitude_plane` away as a duplicate of
    `returns_plane`: they answer different questions, and the wrong one here reads as a working
    measurement that is measuring nothing at all.
    ([[pick-the-read-by-which-axis]] — column structure is not row structure, and three different
    things in this stack are named "coherence" for the same reason.)"""
    coupled, _ = _joint_read(coupled=True, price_plane=mp.returns_plane, plane_name="returns")
    alone, _ = _joint_read(coupled=False, price_plane=mp.returns_plane, plane_name="returns")
    assert abs(coupled["top_share"] - alone["top_share"]) < 0.05, (
        "signed returns separated the arms — if this now WORKS, the fixture's coupling has become "
        "directional and no longer models the phenomenon magnitude_plane exists for")


def test_the_read_refuses_an_unnormalisable_screen_rather_than_reading_it_raw():
    """Raw, the news block's covariance is ~1e7x the return block's — the leading mode would be
    news at any coupling, and the read would report a confident number about a unit mismatch.

    `_NoNormalise` is not beacon's shape — beacon fills `screen_normalize` too (its `engine.whiten`
    is the same estimator, measured identical). It is a constrained host: one that fills the reading
    members and not the normalising one. Such a host raises by name rather than reading raw."""
    from prism.instrument import InstrumentRequired

    class _NoNormalise:
        correlated_null = staticmethod(INSTRUMENT.correlated_null)
        read_ordered = staticmethod(INSTRUMENT.read_ordered)
        scales = staticmethod(INSTRUMENT.scales)

    _, frame = _joint_read(coupled=True)
    with pytest.raises(InstrumentRequired) as e:
        mp.read_co_registered(frame, draws=20, read=_NoNormalise())
    assert e.value.member == "screen_normalize"
    assert e.value.contract == "read"


def test_joint_entropies_answers_a_DIFFERENT_question_and_is_kept_separate():
    """Not the co-movement read, and recorded here so nobody reaches for it as one.

    `joint_power` is `J = P1ᵀP2` over feature channels: it asks "does knowing which channel is bright
    in X tell you which is bright in Y". That is a routing question. Two frames can move together
    perfectly while every row spreads its power the same way across channels — which is this fixture,
    and why I_XY reads ~0 in both arms. Pinned so the zero is understood as the right answer to the
    question actually asked, rather than rediscovered as a bug."""
    series, items = _coupled_basket(coupled=True)
    frame = mp.co_register([
        mp.magnitude_plane(series),
        mp.news_counts_plane(items, cadence_seconds=900.0,
                             observed=(_ts(0), _ts(241 * 900)), conservation=INSTRUMENT)])
    x, y = mp.split_planes(frame, "magnitude", "news")
    j = INSTRUMENT.joint_entropies(x, y)
    assert set(j) == {"H_X", "H_Y", "H_XY", "I_XY", "H_X_given_Y", "H_Y_given_X"}
    assert j["I_XY"] == pytest.approx(j["H_X"] + j["H_Y"] - j["H_XY"], abs=1e-12)  # exact, one table


def test_magnitude_plane_discards_sign_and_stays_additive():
    """|r| is a path length: additive across buckets, and not the same number as the net move."""
    series = {"A": _bars(5)}
    signed = mp.returns_plane(series)
    mag = mp.magnitude_plane(series)
    assert mag["aggs"] == [mp.AGG_SUM]
    assert all(v >= 0.0 for row in mag["rows"] for v in row)
    assert mag["rows"] == [[abs(v) for v in row] for row in signed["rows"]]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# The living Screen — pooling, and the silent ways a pooled spectrum stops meaning anything
# ══════════════════════════════════════════════════════════════════════════════════════════════════

def _window(coupled=True, n=60, seed=0):
    """One window of the same coupled/independent fixture, as a co-registered frame."""
    import random
    rng = random.Random(seed)
    factor = [rng.gauss(0.0, 0.01) for _ in range(n)]
    closes = {"A": [100.0], "B": [50.0], "C": [25.0]}
    for f in factor:
        for sym, beta in (("A", 1.0), ("B", 0.8), ("C", 1.2)):
            closes[sym].append(closes[sym][-1] * math.exp(beta * f + rng.gauss(0.0, 0.001)))
    series = {sym: [{"ts": _ts(i * 900), "close": c} for i, c in enumerate(vals)]
              for sym, vals in closes.items()}
    items = []
    for i, f in enumerate(factor):
        burst = int(abs(f) * 400) if coupled else int(abs(rng.gauss(0.0, 0.01)) * 400)
        for j in range(burst):
            items.append({"title": "h", "source": "src%d" % (j % 5),
                          "published_at": _ts((i + 1) * 900 + 1), "url": "", "lang": "en"})
    news = mp.news_counts_plane(items, cadence_seconds=900.0,
                                observed=(_ts(0), _ts((n + 1) * 900)), conservation=INSTRUMENT)
    return mp.co_register([mp.magnitude_plane(series), news])


def test_pooling_certifies_what_one_window_cannot():
    """The point of the living Screen, shown on the independent arm because that is where one
    window is genuinely undecided: it estimates k=2 but reports the interval (1,2) — "it could be one,
    I cannot yet tell". A second window collapses the interval onto the count and it certifies. The
    one-shot read cannot express that uncertainty at all; it returns a bare number.

    Fails if `certified` is ever computed from anything but the interval collapsing — the only
    honest route to certification is more evidence, never a loosened tolerance."""
    h = mp.market_accumulator(_window(coupled=False, seed=1), read=INSTRUMENT)
    mp.accumulate(h, _window(coupled=False, seed=1))
    one = mp.accumulated_market_read(h, read=INSTRUMENT)
    assert one["k_signal"] == 2
    assert one["certified"] is False and one["interval"] == (1, 2)

    for s in range(2, 6):
        mp.accumulate(h, _window(coupled=False, seed=s))
    many = mp.accumulated_market_read(h, read=INSTRUMENT)
    assert many["certified"] is True
    assert many["interval"] == (2, 2) and many["k_signal"] == 2
    assert many["band"] < one["band"], "the band must SHRINK as evidence pools"
    assert many["T"] > one["T"] and many["planes_pooled"] == 5


def test_the_band_shrinks_monotonically_and_is_the_progress_reading():
    """`band` is the monotone quantity — the one a caller can watch to know it is getting closer.
    `certified` is not (see the next test), so anything that wants "am I nearly there" must read this."""
    h = mp.market_accumulator(_window(seed=1), read=INSTRUMENT)
    bands = []
    for s in range(1, 6):
        mp.accumulate(h, _window(seed=s))
        bands.append(mp.accumulated_market_read(h, read=INSTRUMENT)["band"])
    assert bands == sorted(bands, reverse=True), "the band must fall with every pooled plane: %s" % bands
    assert bands[-1] < bands[0] / 2


def test_certification_is_NOT_a_latch_and_more_evidence_can_UNcertify():
    """A screen can certify and then stop being certified as more evidence arrives: the band shrinks
    monotonically but the estimate moves too, so a tightening interval can straddle again. On 6-row
    windows (thin enough to see it): planes=2 certifies (1,1); planes=4 reads (1,2) and does not.

    That is the instrument being honest, not flapping. `certified` describes the evidence pooled right
    now. A caller that caches "this basket certified" and stops re-reading has cached an expired fact.

    Fails if `certified` is ever made sticky to look more stable — which would be a tolerance
    loosening wearing a cache's clothes."""
    h = mp.market_accumulator(_window(n=6, seed=1), read=INSTRUMENT)
    seen = []
    for s in range(1, 6):
        mp.accumulate(h, _window(n=6, seed=s))
        seen.append(mp.accumulated_market_read(h, read=INSTRUMENT)["certified"])
    assert True in seen and seen[-1] is False, (
        "expected certification to be reached and then LOST as the estimate moved; got %s" % seen)


def test_pooling_separates_coupled_from_independent_and_CERTIFIES_both():
    """The negative control, and here it is stronger than the one-shot version: both arms certify,
    so the difference is not "one read was noisier" — it is two settled, incompatible answers.
    Coupled resolves one driver spanning both planes; independent resolves two."""
    def pooled(coupled):
        h = mp.market_accumulator(_window(coupled=coupled, seed=1), read=INSTRUMENT)
        for s in range(1, 6):
            mp.accumulate(h, _window(coupled=coupled, seed=s))
        return mp.accumulated_market_read(h, read=INSTRUMENT)

    c, a = pooled(True), pooled(False)
    assert c["certified"] and a["certified"], "both arms must settle or this compares nothing"
    assert c["k_signal"] == 1, "a reacting feed and price magnitude are ONE driver"
    assert a["k_signal"] == 2, "an unrelated feed is a SECOND driver"


def test_a_changed_basis_refuses_and_names_what_moved():
    """The guard the whole pooling path stands on, and the failure it prevents is silent.

    entroptics and beacon both check only that `F` is constant. So a basket that loses ETHUSDT and
    gains SOLUSDT between windows pools cleanly: same width, well-formed covariance, a confident
    certified count — of nothing. Nothing downstream can detect it, because the arithmetic never
    breaks. `F` is not the identity of a basis; the names are.

    Fails the moment someone "relaxes" this to a width check to make a live feed keep running."""
    h = mp.market_accumulator(_window(seed=1), read=INSTRUMENT)
    mp.accumulate(h, _window(seed=1))

    swapped = dict(_window(seed=2))
    swapped["columns"] = ["magnitude.A", "magnitude.B", "magnitude.SOL"] + swapped["columns"][3:]
    with pytest.raises(mp.PlaneError) as e:
        mp.accumulate(h, swapped)
    assert "magnitude.SOL" in str(e.value) and "magnitude.C" in str(e.value)
    assert "not a spectrum" in str(e.value)


def test_same_width_different_ORDER_is_also_refused():
    """The subtler half: reordered columns are the same set and the same width, so every width or
    set-based check passes — and the pooled covariance is then summed across two different bases,
    silently. Order is part of the basis identity."""
    h = mp.market_accumulator(_window(seed=1), read=INSTRUMENT)
    mp.accumulate(h, _window(seed=1))
    reordered = dict(_window(seed=2))
    cols = list(reordered["columns"])
    reordered["columns"] = [cols[1], cols[0]] + cols[2:]
    with pytest.raises(mp.PlaneError):
        mp.accumulate(h, reordered)


def test_mixing_cadences_is_refused():
    """Two clocks in one covariance produce a count belonging to neither."""
    h = mp.market_accumulator(_window(seed=1), read=INSTRUMENT)
    hourly = dict(_window(seed=2), cadence_seconds=3600.0)
    with pytest.raises(mp.PlaneError) as e:
        mp.accumulate(h, hourly)
    assert "belongs to neither" in str(e.value)


def test_an_empty_screen_reads_None_not_zero():
    """An empty screen has not measured zero: "nothing pooled" and "pooled and resolved nothing" are
    different statements, and must not share a value — a `k_signal` of 0 from an empty screen would
    read as a measurement."""
    assert mp.accumulated_market_read(mp.market_accumulator(_window(seed=1), read=INSTRUMENT),
                                      read=INSTRUMENT) is None


def test_the_pooled_read_names_its_null_because_it_is_not_the_permutation_one():
    """A pooled screen keeps the covariance, not the samples, so nothing remains to permute. That is
    a real divergence from `read_co_registered`, which uses the correlated permutation null — so the
    read must say which null answered it rather than letting a caller assume they match."""
    h = mp.market_accumulator(_window(seed=1), read=INSTRUMENT)
    mp.accumulate(h, _window(seed=1))
    r = mp.accumulated_market_read(h, read=INSTRUMENT)
    assert "permute" in r["null"]
    assert r["columns"][:3] == ["magnitude.A", "magnitude.B", "magnitude.C"]


def test_opening_a_screen_refuses_without_the_instrument():
    """The accumulator is a `read` member; a host without one raises rather than pooling locally."""
    from prism.instrument import InstrumentRequired
    with pytest.raises(InstrumentRequired) as e:
        mp.market_accumulator(_window(seed=1), read=object())
    assert e.value.member == "accumulator"
