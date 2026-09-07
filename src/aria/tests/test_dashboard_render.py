"""aria's dashboard renderer — the invariants that test it, held alongside it in `aria/facets/`.

These tests exercise the renderer directly: whether a converged mesh reads as healthy, whether a dead
ingest is drawn as busy, whether a stale backlog invents an ETA. Testing the renderer here, in the
persona that owns it, keeps the test from reaching across the boundary ember is not allowed to cross.

Each of these is a "does the view lie" test, which is why they matter more than their size suggests.
A renderer that draws a dead process as busy, or an empty mesh as converged, produces a page an
operator will believe.
"""
from __future__ import annotations

import time

import pytest

from aria.facets import dashboard_render as DR


def test_drain_done_is_not_true_merely_because_the_cursor_is_empty():
    """`last_id == ""` means both "finished and wrapped" and "a fresh sweep has not advanced", and
    `swept_at` is sticky. A box that swept, then ingested a large batch of artifacts, must not
    render green "safe to retire" for content that was never promoted. This is the retirement gate."""

    # swept long ago, backlog since measured as non-zero -> must not read as done
    assert DR._draincls({"drain_done": False, "drain_cursor": "x"}) != "good"
    assert "safe to retire" not in DR._drainsub({"drain_done": False, "drain_backlog": 500_000,
                                                 "drain_backlog_at": time.time()})
    # genuinely done
    assert DR._draincls({"drain_done": True}) == "good"


def test_a_stale_backlog_does_not_produce_an_eta():
    """`backlog` is measured on the 900s pass and retained when that pass fails; `rate` is a 30s
    difference. Dividing a stale backlog by a fresh rate would produce an ETA that refreshes every
    30s and reads as live even though the backlog itself could be hours old."""

    now = time.time()
    fresh = DR._drainsub({"drain_per_min": 13800, "drain_backlog": 2_190_315,
                          "drain_backlog_at": now - 120, "drain_cursor": "x"})
    stale = DR._drainsub({"drain_per_min": 13800, "drain_backlog": 4_300_000,
                          "drain_backlog_at": now - 7200, "drain_cursor": "x"})
    # Note the assertion shape: the stale string says "no ETA", so a bare `"ETA" not in stale`
    # matches that substring and fails. Check for the refusal explicitly.
    assert "ETA" in fresh and "no ETA" not in fresh
    assert "no ETA" in stale and "old" in stale


def test_a_converged_mesh_can_be_healthy():
    """The success state — every box converged and drained, with nothing left ingesting — must
    render as healthy, not amber `watch`."""

    now = time.time()
    converged = [{"node": "a", "artifacts": 100, "ts": now, "role": "full",
                  "ingest": {"range": "0-4", "assigned": 5, "done": 5, "converged": True},
                  "queue": {"pending": 0, "running": 0}}]
    assert ">healthy<" in DR.render_dashboard(converged, "a") or "healthy" in DR.render_dashboard(converged, "a")


def test_a_dead_ingest_process_is_not_rendered_as_busy():
    """A `working_on` timestamp hours old must not still render as bold "ingesting <shard>" — the
    snapshot can stay fresh while its contents are dead, so staleness has to be read from the
    activity timestamp itself."""

    now = time.time()
    dead = [{"node": "b", "artifacts": 10, "ts": now,
             "working_on": {"state": "claimed", "shard": "train-00021.parquet", "ts": now - 25_200},
             "content_at": {"at": "wiki-en-5", "ts": now - 25_200}}]
    html = DR.render_dashboard(dead, "b")
    assert "stalled" in html, "a 7-hour-dead process rendered without any staleness marker"


def test_overlapping_shard_ranges_are_detected():
    """Overlapping shard ranges must be flagged: left undetected, they let `whole_art =
    max(nodes)` silently under-count the true union size."""

    assert DR._detect_shard_overlap([{"ingest": {"range": "0-99"}}, {"ingest": {"range": "50-149"}}])
    assert not DR._detect_shard_overlap([{"ingest": {"range": "0-4"}}, {"ingest": {"range": "5-22"}}])


# ── the staleness bounds are derived from the publisher's period ───────────────────────────
#
# The staleness bounds are integer multiples of `_SNAPSHOT_PERIOD_S` and `_SLOW_PASS_PERIOD_S`,
# which are declared properties of `ember/surface/stats.py` rather than judgements about health.
#
# The failure mode these tests catch: a bound written as `2 * PERIOD` where the call site still
# compares against a literal is the constant wearing an expression, and a test that only asserts
# "120 is stale" cannot tell the two apart. So every test below moves the declared period and
# asserts the rendered verdict moves with it.


def _box(node="a", *, age_s=0.0, ts=None, **kw):
    b = {"node": node, "artifacts": 100, "ts": time.time() if ts is None else ts,
         "age_s": age_s, "role": "full", "queue": {"pending": 0, "running": 0}}
    b.update(kw)
    return b


def test_staleness_tracks_the_declared_snapshot_period(monkeypatch):
    """A snapshot 150s old is stale at a 60s period and fresh at a 120s one. If the verdict does
    not move when the period does, the bound is not derived from it."""
    box = [_box(age_s=150.0, ingest={"converged": True})]

    assert "watch" in DR.render_dashboard(box, "a") or "degraded" in DR.render_dashboard(box, "a")

    # Only the declared period is moved. Everything else must follow from it — that is the claim.
    monkeypatch.setattr(DR, "_SNAPSHOT_PERIOD_S", 120.0)
    html = DR.render_dashboard(box, "a")
    assert "healthy" in html, (
        "doubling the declared publish period left a 150s-old snapshot stale — the staleness "
        "bound is a constant, not a multiple of the period"
    )


def test_the_headline_panel_and_the_card_use_the_same_staleness_bound():
    """A box the page draws red on its own card must not be the box the whole-universe totals are
    taken from — the card's staleness bound and the totals' must be the same bound."""
    assert DR._snapshot_missed_s() == 2.0 * DR._SNAPSHOT_PERIOD_S
    now = time.time()
    stale_box = _box(ts=now - (DR._snapshot_missed_s() + 1), age_s=DR._snapshot_missed_s() + 1)
    fresh_box = _box("b", ts=now, age_s=0.0, artifacts=7)
    stale_box["artifacts"] = 999_999
    html = DR.render_dashboard([stale_box, fresh_box], "b")
    assert "999,999" not in html.split("<div class=cards>")[0], (
        "a box past the missed-publish bound still set the universe totals"
    )


def test_the_eta_refusal_tracks_the_declared_slow_pass(monkeypatch):
    """The backlog ETA is refused once the backlog has survived a slow pass. Lengthen the pass and
    the same backlog becomes usable again."""
    now = time.time()
    b = {"drain_per_min": 1000, "drain_backlog": 50_000,
         "drain_backlog_at": now - 2000, "drain_cursor": "x"}
    assert "no ETA" in DR._drainsub(b)

    # Only the declared slow-pass period is moved; the refusal must follow it.
    monkeypatch.setattr(DR, "_SLOW_PASS_PERIOD_S", 3600.0)
    out = DR._drainsub(b)
    assert "no ETA" not in out and "ETA" in out, (
        "lengthening the declared slow pass did not make a 2000s-old backlog usable — the "
        "refusal is a constant, not two slow passes"
    )


def test_the_stalled_marker_tracks_the_declared_activity_silence(monkeypatch):
    """`_fresh` and `_stale_age` must read the same bound, or a line can be drawn live and stalled
    at once. Moving the bound must move both."""
    now = time.time()
    dead = [_box("b", working_on={"state": "claimed", "shard": "s.parquet", "ts": now - 400})]
    assert "stalled" in DR.render_dashboard(dead, "b")

    # Only the periods-of-silence count is moved; the marker must follow it.
    monkeypatch.setattr(DR, "_ACTIVITY_SILENCE_PERIODS", 60.0)
    html = DR.render_dashboard(dead, "b")
    assert "stalled" not in html, (
        "raising the activity-silence bound left a 400s-old log line marked stalled"
    )
    assert "ingesting" in html, "the same line must now read as live, not merely lose its marker"


# ── publish backlog and share have no typed-threshold colour ───────────────────────────────

def test_a_large_publish_backlog_is_not_rendered_as_bad():
    """A large publish backlog is not, on its own, evidence of anything about health — a fleet can
    run a multi-day backfill with an enormous backlog throughout. Green stays on the measured
    converged signal; above it the tile carries no colour, because nothing measures it."""
    assert DR._backlogcls({"publish_backlog": 0}) == "good"
    assert DR._backlogcls({"publish_backlog": 5_674_711}) == ""
    assert DR._backlogcls({"publish_backlog": 250_001}) == ""
    assert DR._backlogcls({"publish_backlog": 1}) == ""
    assert DR._backlogcls({}) == "", "an unmeasured backlog must render as nothing, never as 0"


def test_share_colour_comes_from_the_measured_converged_flag_not_a_typed_share():
    """The share colour must come from the measured `converged` flag, not a typed share threshold:
    a shard node holding a large share of the union but not yet converged must not read as good,
    and one that is converged must, regardless of what share it holds."""
    now = time.time()
    big_but_not_converged = [_box("a", ts=now, artifacts=100,
                                  ingest={"range": "0-4", "converged": False})]
    html = DR.render_dashboard(big_but_not_converged, "a")
    assert 'class="sharepct good"' not in html, (
        "a node at 100% of the union but NOT converged was coloured good — the colour is still "
        "reading the share instead of the measured flag"
    )

    converged = [_box("a", ts=now, artifacts=100,
                      ingest={"range": "0-4", "converged": True})]
    assert 'class="sharepct good"' in DR.render_dashboard(converged, "a")

    partial = [_box("a", ts=now, artifacts=50, ingest={"range": "0-2", "converged": False}),
               _box("b", ts=now, artifacts=100, ingest={"range": "0-4", "converged": True})]
    html = DR.render_dashboard(partial, "a")
    assert "warn" not in html.split("sharepct")[1][:20], (
        "a healthy shard node holding half the union is still drawn amber"
    )


def test_the_disk_band_is_presentation_only_and_never_reaches_health():
    """60 and 85 are a declared operator alarm level, not a health measurement. They decide a
    tile's colour and nothing else — a full disk must not silently become the page's overall
    verdict without a measurement saying so."""
    now = time.time()
    full = [_box("a", ts=now, disk_pct=99.0, ingest={"converged": True})]
    html = DR.render_dashboard(full, "a")
    assert 'class="v bad"' in html, "the disk band stopped colouring at all"
    assert ">healthy<" in html, (
        "a 99% disk changed the page's overall health verdict — a typed presentation band is "
        "now deciding what the reader concludes about the mesh"
    )


def test_every_derived_bound_moves_when_the_period_moves(monkeypatch):
    """The direct check that a value assertion alone cannot make: each derived bound must be a
    function of the declared period. A bound frozen at import, or typed in, holds still here."""
    before = (DR._snapshot_late_s(), DR._snapshot_missed_s(), DR._activity_silence_s())
    monkeypatch.setattr(DR, "_SNAPSHOT_PERIOD_S", DR._SNAPSHOT_PERIOD_S * 3)
    after = (DR._snapshot_late_s(), DR._snapshot_missed_s(), DR._activity_silence_s())
    for name, b, a in zip(("late", "missed", "activity-silence"), before, after):
        assert a > b, f"the {name} bound did not move when the declared publish period tripled"

    slow_before = DR._backlog_unusable_s()
    monkeypatch.setattr(DR, "_SLOW_PASS_PERIOD_S", DR._SLOW_PASS_PERIOD_S * 3)
    assert DR._backlog_unusable_s() > slow_before, (
        "the backlog-ETA refusal did not move when the declared slow pass tripled"
    )


def test_the_bounds_are_the_multiples_they_claim_to_be():
    """Value assertions, kept together and last: on their own they prove nothing."""
    assert DR._snapshot_late_s() == DR._SNAPSHOT_PERIOD_S
    assert DR._snapshot_missed_s() == 2.0 * DR._SNAPSHOT_PERIOD_S
    assert DR._backlog_unusable_s() == 2.0 * DR._SLOW_PASS_PERIOD_S
    assert DR._activity_silence_s() == DR._ACTIVITY_SILENCE_PERIODS * DR._SNAPSHOT_PERIOD_S
