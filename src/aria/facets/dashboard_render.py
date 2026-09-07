"""Pure mesh-dashboard renderer with no ember-internal imports (stdlib only), so the same code renders
the dashboard on box 71 (via browse.dashboard_page) and on the public status.agience.ai VPS (which has
no artifact store at all, only S3 read access to the mesh-stats snapshots). One renderer, no drift.

Input is a list of per-node snapshot dicts (the mesh-stats/*.json objects, each with an `age_s` added)
plus the viewer's own node id (optional). Output is the full HTML page."""
from __future__ import annotations

import hashlib
import time as _time
from typing import Any, Dict, List, Optional

try:                                   # inlined Agience brand (favicon + wordmark) as PNG data URIs
    from aria.facets.dashboard_assets import FAVICON, LOGO
except Exception:                      # renderer must never break if assets are missing on a node
    FAVICON = LOGO = ""


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# The publisher's cadences — the only free numbers in this module, and every staleness bound below
# is an integer multiple of one of them.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
# "Is this snapshot stale?" is not answerable from the snapshot alone: it carries `ts` and nothing
# that says how often another one was due. The publisher knows its own period; the snapshot does
# not carry it. So the period is declared here, once, as a property of `ember/surface/stats.py` — a
# fact about the producer, not a judgement about health — and every bound is derived from it and
# says how many periods it is.
#
# The producer could instead publish its own period alongside `ts`, and this block would become
# `b.get("publish_period_s")` per node, with no declaration here at all. Until that field exists, a
# stated period with derived multiples is the honest shape — one number to be wrong about instead
# of six, and each of the six says what it means.
#
# A different value is right if, and only if, the producer's loop period changes. Nothing about the
# mesh's health, size or workload should move any of these.

#: `ember/surface/stats.py::write_stats` — the fast publish cycle ("Safe to call every 20s: it does
#: not scan the corpus"), run from both the serve loop and the health loop. Declared at 60s: the
#: slowest cadence any of those loops has been observed to hold, so a bound built on it does not
#: cry wolf on a box whose loop is merely at the slow end.
_SNAPSHOT_PERIOD_S = 60.0

#: `ember/surface/stats.py` — the slow pass, the one that measures `drain_backlog`. The 900s figure
#: is the producer's own, recorded in `_drainsub` below and in ember's genesis (`slow_s or 900`).
_SLOW_PASS_PERIOD_S = 900.0

#: How many publish cycles an ingest/drain worker may be silent before its last log line stops
#: describing now. Unlike the two periods above this is not a loop period — no worker publishes one
#: — so it is a stated tolerance and not a derived one, and it is expressed in publish cycles so it
#: at least moves with the producer. A different value is right if a healthy worker can legitimately
#: be quiet for longer than five cycles; measuring the inter-line gap on a working box would settle it.
_ACTIVITY_SILENCE_PERIODS = 5.0

# ── derived from the periods above; nothing below this line is typed in ────────────────────────
# These are functions, not constants, so that a test perturbing `_SNAPSHOT_PERIOD_S` reaches every
# bound below: a value assigned once at import time would freeze the moment it runs, and a
# regression to a bare literal in its place would pass unnoticed by any test that only perturbs
# the period.

def _snapshot_late_s() -> float:
    """A snapshot arriving on schedule is never older than one period, so anything older is late."""
    return 1.0 * _SNAPSHOT_PERIOD_S


def _snapshot_missed_s() -> float:
    """Older than two periods and a publish did not merely arrive late — it did not happen."""
    return 2.0 * _SNAPSHOT_PERIOD_S


def _backlog_unusable_s() -> float:
    """A backlog older than two slow passes has survived a pass that should have replaced it, so it
    is not a measurement of now and cannot denominate an ETA. See `_drainsub`."""
    return 2.0 * _SLOW_PASS_PERIOD_S


def _activity_silence_s() -> float:
    """How long a worker may be silent before its last log line stops describing now.
    `_ACTIVITY_SILENCE_PERIODS` is the one stated tolerance in this module; see its definition."""
    return _ACTIVITY_SILENCE_PERIODS * _SNAPSHOT_PERIOD_S

#: Specifications — the units the durations are rendered in. Not judgements.
_S_PER_MIN = 60.0
_MIN_PER_H = 60.0
_S_PER_H = _S_PER_MIN * _MIN_PER_H


def box_label(node, is_me: bool = False) -> str:
    # node-ids are set to friendly, stable names via EMBER_NODE_ID; show them cleanly (71/45/TU/T5/MANTLE).
    names = {"71": "71", "45": "45", "t5": "T5", "tu": "TU",
             "agience-public": "MANTLE", "agience-mantle": "MANTLE", "mantle": "MANTLE"}
    name = names.get(str(node), str(node).upper())
    return (name + " · authoritative") if is_me else name


def _anon_label(node) -> str:
    """Public label — an opaque, stable, non-identifying id (no hostname, no IP, no friendly name).
    Deterministic from the node id so the same box is the same 'node·xxxx' on every box's render."""
    return "node·" + hashlib.blake2b(str(node).encode("utf-8"), digest_size=2).hexdigest()


def _backlog_age(b: Dict[str, Any]) -> str:
    """Label the publish-backlog tile with when it was measured, and whether it is capped.

    The count comes from `pending_publish()` on the lattice path: uncached, and capped.
    `publish_backlog_exact=False` means the count hit the cap and the true figure is higher, so
    that is surfaced here rather than dropped — a capped count rendered bare is indistinguishable
    from a real one. The age is shown alongside the count for the same reason: a stale number that
    looks live is worse than a missing one."""
    at = b.get("publish_backlog_at")
    label = "rows peers cannot see"
    if b.get("publish_backlog_exact") is False:
        label = "rows peers cannot see · <b>at least</b>"
    if b.get("publish_backlog") is None or not isinstance(at, (int, float)):
        return label
    age = max(0, int(_time.time() - at))
    # Unit selection, derived from the unit itself: seconds until there is a whole minute to show.
    # `90` sat here, which showed "89s ago" and then "1m ago" — a reader cannot tell whether the
    # jump is the clock or the rule.
    if age < _S_PER_MIN:
        return "%s · %ds ago" % (label, age)
    return "%s · <b>%dm ago</b>" % (label, age // _S_PER_MIN)


def _backlogcls(b: Dict[str, Any]) -> str:
    """Colour for the publish-backlog tile. Green only on the measured converged signal; no colour
    at all above it, because nothing here measures whether a non-zero backlog is a problem.

    `0` is green because it is a real converged signal: `pending_publish` counts rows per feed above
    that feed's own cursor, and each term reaches 0 exactly when its feed drains.

    There is no size-based threshold (e.g. `n > 250_000 -> red`), because a node in steady state
    sits in the low thousands or at 0, with no realistic population between those two — any level in
    that gap would separate "backfilling" from "not backfilling", two expected operating states,
    rather than anything about health. A branch that fires for every node throughout a normal
    backfill and for none afterwards is not a safety net; it is a second name for "is a backfill
    running", which the page already says. Rendering nothing is the honest output of an instrument
    that has nothing to report: "not drained" is not rendered as "bad" on the strength of a number
    nothing derived ([[absence-is-not-an-affirmative-claim]]).

    What would restore a colour here: `publish_backlog_at` is already published beside the count.
    Two consecutive snapshots would give a drain rate with no constant anywhere — red when the
    backlog is growing, which is a claim about the node rather than about the size of its queue.
    That needs the renderer to see the previous snapshot; it currently sees one.
    """
    n = b.get("publish_backlog")
    if n is None:
        return ""                        # not measured — rendered as an em-dash, never as 0
    return "good" if n == 0 else ""      # drained is measured; everything else is not


def _draincls(b) -> str:
    """Colour the content-drain number by whether the box is safe to retire.

    `drain_done` is true only when the promote cursor has exhausted and wrapped. That is the one
    signal that says every ref this box holds is confirmed in the durable origin — cursor position
    does not say it, and `promoted_total` does not say it either. Getting this wrong means
    retiring a box whose content exists nowhere else, so it gets its own colour rather than being
    inferred from a number that always looks large."""
    if b.get("drain_done"):
        return "good"
    return "warn" if b.get("drain_cursor") else ""


def _drainsub(b) -> str:
    """Rate and backlog — the two numbers that answer "is it moving, and how much is left".

    Deliberately not the cursor id. `wiki-en-54855567` is not information: it does not say how far
    along, how fast, or how much remains, and it changes constantly so the card looks alive while
    telling you nothing. `promoted_total` is no better as a progress signal — most pages promote 0
    because the ref is already in S3, so the number sits still while the drain works hard.
    `backlog` absent means not measured (the slow pass has not run or failed) — never 0."""
    if b.get("drain_done"):
        return "drained ✓ safe to retire"
    import time as _t
    rate = b.get("drain_per_min")
    backlog = b.get("drain_backlog")
    at = b.get("drain_backlog_at")
    bits = []
    if isinstance(rate, (int, float)):
        bits.append(f"{rate:,.0f}/min")
    if isinstance(backlog, (int, float)):
        # `backlog` and `rate` come from different clocks: `backlog` is measured on the 900s slow
        # pass — and retained at its old value when that pass fails — while `rate` is differenced
        # over ~30s. Dividing them directly would give an ETA that refreshes every 30s (so it reads
        # as live) from a backlog that could be hours stale, so `drain_backlog_at`'s age is checked
        # first. `_backlog_unusable_s()` is two slow passes: a backlog that has survived a pass which
        # should have replaced it is not a measurement of now, whatever the rate says, and it is
        # derived from the producer's own period so it moves if the producer's slow pass does.
        age = (_t.time() - float(at)) if isinstance(at, (int, float)) and at else None
        if age is None:
            bits.append(f"{backlog:,} left (age unknown)")
        elif age > _backlog_unusable_s():
            bits.append(f"{backlog:,} left ({age/_S_PER_H:.1f}h old — no ETA)")
        elif isinstance(rate, (int, float)) and rate > 0:
            eta_m = backlog / rate
            # Unit selection from the unit, not from a chosen crossover: hours once there is a
            # whole hour to show.
            eta = f"{eta_m/_MIN_PER_H:.1f}h" if eta_m >= _MIN_PER_H else f"{eta_m:.0f}m"
            bits.append(f"{backlog:,} left · ETA {eta} (backlog {age/_S_PER_MIN:.0f}m old)")
        else:
            bits.append(f"{backlog:,} left")
    elif b.get("drain_cursor"):
        bits.append("backlog not measured")
    return " · ".join(bits)


def _ingestsub(b) -> str:
    """Shard progress, or nothing. Never a made-up denominator.

    A box whose EMBER_SHARDS is not a numeric range (71 uses "all") has no `assigned`, and
    rendering `0/None shards` reads as "this box has ingested nothing" when it means "there is no
    range to compare against"."""
    ing = b.get("ingest") or {}
    if not ing:
        return ""
    if ing.get("converged"):
        return "converged"
    assigned = ing.get("assigned")
    done = ing.get("done", 0)
    if assigned:
        return f"{done}/{assigned} shards"
    return f"{done} shards done" if done else ""


def _detect_shard_overlap(boxes) -> bool:
    """Do two ingest boxes claim overlapping shard ranges?

    This matters because `whole_art = max(nodes)` is only valid when some consumer holds the union;
    with overlapping ingest ranges and no full consumer, `max` under-counts and the page would print
    the under-count labelled confidently "(union)" unless the overlap banner fires."""
    seen = []
    for b in boxes:
        rng = str((b.get("ingest") or {}).get("range") or "")
        lo, _, hi = rng.partition("-")
        try:
            a, z = int(lo), int(hi)
        except ValueError:
            continue
        for (a2, z2) in seen:
            if a <= z2 and a2 <= z:
                return True
        seen.append((a, z))
    return False


def render_dashboard(boxes: List[Dict[str, Any]], my_node: Optional[str] = None,
                     public: bool = False) -> str:
    """Renders (1) overall health of the whole universe — total artifacts, compaction (ρ), index
    stats — and (2) every known peer as its own card with independent stats and how it compares to
    the whole.

    public=True renders the anonymized view for status.agience.ai: opaque node labels (no hostnames/IPs),
    no shard ranges, peer-consumption shown as a count only. Private topology never crosses this boundary.
    """
    boxes = sorted((dict(s) for s in boxes), key=lambda d: str(d.get("node")))

    def esc(x):
        return (str(x) if x is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def num(x):
        try:
            return f"{int(x):,}"
        except Exception:
            return "—"

    def _i(b, k):
        try:
            return int(b.get(k) or 0)
        except Exception:
            return 0

    # ── the whole ─────────────────────────────────────────────────────────────────────────────────
    # The universe total is the union of distinct artifacts. Every node publishes its shard to S3 and
    # the consumers (t5, 71) pull the whole union, so they converge to full — the most-converged box is
    # the union (its count ≈ the distinct-object count in S3). Summing nodes would double-count, because
    # a consumer's total already includes what it pulled from the ingest shards. Hence: whole = max(nodes).
    # The headline panel must not take its figures from a box that has missed a publish, even
    # though the same box's own card is allowed to render stale: `lead` prefers fresh boxes, falling
    # back to all boxes only if none are fresh, and marks the fallback so it is visible.
    _now_t = _time.time()
    def _fresh_box(b, limit=_snapshot_missed_s()):
        """May this box set the whole-universe panel? Only if it has not missed a publish.

        The bound is the same derived one the per-card staleness badge uses, and deliberately so: a
        box the page marks red on its own card must not be the box the headline is taken from."""
        try:
            return (_now_t - float(b.get("ts") or 0)) <= limit
        except Exception:
            return False
    _fresh_boxes = [b for b in boxes if _fresh_box(b)]
    _lead_pool = _fresh_boxes or boxes
    _lead_stale = not _fresh_boxes and bool(boxes)
    whole_art = max((_i(b, "artifacts") for b in _lead_pool), default=0)
    shards_overlap = _detect_shard_overlap(boxes)
    lead = max(_lead_pool, key=lambda b: _i(b, "artifacts"), default={}) if _lead_pool else {}
    rho = lead.get("rho"); cov = lead.get("keyed_coverage"); dark = lead.get("dark_matter")
    # `stats` carries `metrics_sampled` / `metrics_sample_n` so an estimate is never read as a
    # census — dark_matter in particular is an absolute count capped at a 20,000-row sample, so a
    # node with far more dark rows than that would otherwise have its sampled figure shown as the
    # universe total with no indication it is a sample.
    _sampled = bool(lead.get("metrics_sampled"))
    _sample_n = lead.get("metrics_sample_n")
    _samp_note = (f" <span class=warn>(sampled {num(_sample_n)})</span>" if _sampled else "")
    # Peers we could not read at all — a shrunken mesh must not look like a smaller mesh.
    _unreadable = 0
    for _b in boxes:
        if _b.get("_peers_unreadable"):
            _unreadable = int(_b["_peers_unreadable"]); break
    ops_n = lead.get("operators"); wn = lead.get("wordnet"); con = lead.get("concepts")
    content_s3 = sum(_i(b, "promoted_total") for b in boxes)
    ingesting = [b for b in boxes if (b.get("role") == "ingest" or _i(b.get("ingest") or {}, "assigned"))
                 and not (b.get("ingest") or {}).get("converged")]

    def _idle(b):
        q = b.get("queue") or {}; ing = b.get("ingest") or {}
        return bool(ing.get("converged")) and not _i(q, "pending") and not _i(q, "claimed") \
            and b.get("purpose") != "tests" and b.get("role") != "full"
    idle_boxes = [b for b in boxes if _idle(b)]
    stale = [b for b in boxes if isinstance(b.get("age_s"), (int, float))
             and b["age_s"] > _snapshot_missed_s()]

    # ── per-peer cards ────────────────────────────────────────────────────────────────────────────
    ROLE_BADGE = {"ingest": ("#9a6700", "ingest"), "full": ("#0969da", "full")}
    cards = []
    for b in boxes:
        node = b.get("node"); is_me = (my_node is not None and node == my_node)
        role = b.get("role") or "?"; purpose = b.get("purpose") or ""
        ing = b.get("ingest") or {}; q = b.get("queue") or {}; prov = b.get("provenance") or {}
        art = _i(b, "artifacts")
        share = (100.0 * art / whole_art) if whole_art else 0     # comparative-to-whole
        conv = bool(ing.get("converged"))
        pend, run = _i(q, "pending"), _i(q, "claimed")
        age = b.get("age_s")
        if _idle(b):
            bg, txt = "#cf222e", "IDLE — needs work"
        elif isinstance(age, (int, float)) and age > _snapshot_missed_s():
            bg, txt = "#8b949e", "stale snapshot"
        elif purpose == "compress" and conv:
            bg, txt = "#8250df", "compressing"
        elif purpose == "tests":
            bg, txt = "#0969da", "tests · sync"
        elif conv:
            bg, txt = "#1a7f37", "converged · full"
        else:
            bg = ROLE_BADGE.get(role, ("#656d76", role))[0]
            txt = "ingesting" if role == "ingest" else role
        badge = f'<span class=badge style="background:{bg}">{esc(txt)}</span>'
        disk = b.get("disk_pct"); dfree = b.get("disk_free_gb")
        # 60/85 are declared operator alarm levels for a disk gauge — the one place on this page
        # where a typed band is defensible, because "how full is too full" depends on what the
        # operator intends to put on the box next, which no snapshot carries. It is safe to keep
        # because it decides a colour only (`diskcls` reaches the card's HTML and nothing else; it
        # does not feed `health` below, so the page's overall verdict is never computed from it —
        # grep before changing that), and because the number itself is rendered beside it, so a
        # reader who disagrees with the band can see what it was applied to.
        # A different value is right if a box's headroom requirement changes. The band could be
        # removed entirely if a node also published its own growth rate alongside `disk_free_gb`,
        # giving a time-to-full, which is a measurement rather than a level.
        diskcls = ("bad" if isinstance(disk, (int, float)) and disk > 85
                   else "warn" if isinstance(disk, (int, float)) and disk > 60 else "")
        agecls = ("bad" if (isinstance(age, (int, float)) and age > _snapshot_missed_s())
                  else "warn" if (isinstance(age, (int, float)) and age > _snapshot_late_s())
                  else "muted")
        prov_ok = prov.get("invariant_holds")
        s3s = b.get("s3sync") or {}
        pub_seg = s3s.get("published_segments")
        consumed = s3s.get("consumed_from") or {}
        # Node names are shown in both views, by operator choice: friendly 71/45/TU/T5/MANTLE even
        # on the public page. Other detail (shard range, per-peer consumption list) is still gated below.
        label = box_label(node, is_me)
        subline = esc(role) + ((' · ' + esc(purpose)) if purpose else '')
        if not public and ing.get("range"):
            subline += ' · shards ' + esc(ing.get("range"))
        if public:
            consumed_html = (' · consumes %d peers' % len(consumed)) if consumed else ''
        else:
            consumed_html = (' · consumes ' + esc(", ".join(sorted(consumed)))) if consumed else ''
        # There is no share-based colour band here (e.g. `share >= 95 -> good, >= 5 -> warn`):
        # "holds essentially the whole universe" is `ingest.converged`, published per node, and a
        # share threshold against `max(nodes)` is only a guess at it. An ingest box is supposed to
        # hold a fraction of the union, so a band that colours the middle of that range would flag
        # every healthy shard node for doing its job while leaving a node doing less of it neutral —
        # inverted on the quantity it colours. Green on the measured `conv` signal; no colour
        # otherwise, because nothing here measures whether a partial share is a problem, and the bar
        # next to it already shows the size.
        sharecls = "good" if conv else ""
        # What it is working on, in words: a count alone cannot distinguish a node that gained rows
        # this hour from one that is wedged, since both render as a number. This line says which
        # shard is claimed, or that ingest is deliberately yielding to the publish backlog, or where
        # the content drain has reached.
        w = b.get("working_on") or {}
        c_at = b.get("content_at") or {}
        bits = []
        # `_activity` takes the newest matching line from the log tail regardless of age and stores
        # `ts` alongside `state`/`shard`/`at`; `ts` is checked here so a crashed ingest service does
        # not render as busy just because the last log line it wrote is stale — `write_stats` keeps
        # succeeding even while a worker's own activity has stopped, so the snapshot can be fresh
        # while its contents are hours dead.
        _now = _time.time()
        def _fresh(d, limit=_activity_silence_s()):
            t = d.get("ts")
            try:
                return t and (_now - float(t)) <= limit
            except Exception:
                return False
        def _stale_age(d):
            t = d.get("ts")
            try:
                a = _now - float(t)
                # Same bound `_fresh` uses, so "not fresh" and "stalled" are one statement.
                return (f" <span class=warn>(stalled {a/_S_PER_MIN:.0f}m)</span>"
                        if a >= _activity_silence_s() else "")
            except Exception:
                return " <span class=warn>(age unknown)</span>"

        if w.get("state") == "claimed" and w.get("shard"):
            _lbl = "ingesting" if _fresh(w) else "last ingested"
            bits.append("%s <b>%s</b>%s" % (_lbl, esc(str(w["shard"]).split("/")[-1]), _stale_age(w)))
        elif w.get("state") == "yield_to_publish":
            bits.append("<span class=warn>ingest paused</span> — draining publish backlog"
                        + (" (%s)" % num(w.get("backlog")) if w.get("backlog") else "")
                        + _stale_age(w))
        if c_at.get("at"):
            _lbl = "content drain at" if _fresh(c_at) else "content drain last at"
            bits.append("%s <b>%s</b>%s" % (_lbl, esc(str(c_at["at"])[:28]), _stale_age(c_at)))
        work_html = " · ".join(bits) if bits else "&nbsp;"
        cards.append(f'''<div class=card>
          <div class=cardhdr><b>{esc(label)}</b>
            <span class=range>{subline}</span>
            {badge}</div>
          <div class=share><div class=sharebar><i style="width:{min(share,100):.1f}%"></i></div>
            <span class="sharepct {sharecls}">{share:.0f}% of the whole</span></div>
          <div class=grid>
            <div><span class=k>artifacts</span><span class=v>{num(art)}</span><span class=sub2>of {num(whole_art)}</span></div>
            <div><span class=k>disk</span><span class="v {diskcls}">{f"{disk}%" if disk is not None else "—"}</span><span class=sub2>{f"{dfree}GB free" if dfree is not None else ""}</span></div>
            <div><span class=k>&rho; compaction</span><span class=v>{f"{b.get('rho'):.4f}" if isinstance(b.get('rho'),(int,float)) else "—"}</span></div>
            <div><span class=k>keyed cov</span><span class=v>{f"{b.get('keyed_coverage')*100:.0f}%" if isinstance(b.get('keyed_coverage'),(int,float)) else "—"}</span></div>
            <div><span class=k>content &rarr; S3</span><span class="v {_draincls(b)}">{num(b.get("promoted_total"))}</span><span class=sub2>{_drainsub(b)}</span></div>
            <div><span class=k>S3 segments pub</span><span class=v>{num(pub_seg) if pub_seg is not None else "—"}</span></div>
            <div><span class=k>rows/min</span><span class="v {'good' if (b.get('rows_per_min') or 0) > 0 else ''}">{f"{b.get('rows_per_min'):+,.0f}" if isinstance(b.get('rows_per_min'),(int,float)) else "—"}</span><span class=sub2>{f"last {b.get('sample_s')}s" if b.get('sample_s') else ""}</span></div>
            <div><span class=k>ingest</span><span class="v {'good' if (b.get('ingest') or {}).get('converged') else ''}">{(b.get('ingest') or {}).get('range') or "—"}</span><span class=sub2>{_ingestsub(b)}</span></div>
            <div><span class=k>publish backlog</span><span class="v {_backlogcls(b)}">{num(b.get("publish_backlog")) if b.get("publish_backlog") is not None else "—"}</span><span class=sub2>{_backlog_age(b)}</span></div>
          </div>
          <div class=queue>{work_html}</div>
          <div class=queue>queue: <b>{pend}</b> pending · <b>{run}</b> running · {q.get("done","?")} done{f' · <span class=bad>{q["failed"]} failed</span>' if q.get("failed") else ""}{consumed_html}</div>
          <div class=foot>
            <span class="{'good' if prov_ok else 'bad'}">{'✓ cited' if prov_ok else '⚠ uncited'}</span>
            <span class={agecls}>reported {age}s ago</span>
          </div>
        </div>''')

    # A finished mesh — every box converged and drained, `ingesting` empty — is healthy, not
    # degraded, so `healthy` does not require a non-empty `ingesting`. Any stale box is at least
    # `watch`, and a majority stale is `degraded`, so partial staleness escalates rather than sitting
    # on `watch` regardless of how many boxes are affected.
    _majority_stale = bool(stale) and len(stale) * 2 >= len(boxes)
    if idle_boxes or _majority_stale:
        health = "degraded"
    elif stale:
        health = "watch"
    else:
        health = "healthy"          # converged + drained + nothing stale is healthy
    hbg = {"healthy": "#1a7f37", "watch": "#9a6700", "degraded": "#cf222e"}[health]
    return f"""<!doctype html><meta charset=utf-8><title>Agience · Mesh</title>
<link rel=icon href="{FAVICON}">
<meta http-equiv=refresh content=15>
<style>
 :root{{color-scheme:light dark}}
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f8fa;color:#1f2328}}
 @media(prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}.card,.whole{{background:#161b22 !important;border-color:#30363d !important}}.sharebar{{background:#30363d !important}}}}
 header{{padding:20px 24px;border-bottom:1px solid #d0d7de;display:flex;align-items:center;gap:12px}}
 h1{{margin:0;font-size:20px;font-weight:600;color:#656d76}} .sub{{color:#656d76;margin-top:4px}}
 .logo{{height:26px;display:block}}
 .pill{{color:#fff;font-size:12px;padding:3px 10px;border-radius:20px;font-weight:600}}
 .whole{{margin:18px 24px;background:#fff;border:1px solid #d0d7de;border-radius:12px;padding:16px 20px}}
 .whole h2{{margin:0 0 12px;font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:#656d76}}
 .totals{{display:flex;gap:32px;flex-wrap:wrap}}
 .tot{{min-width:110px}} .tot .big{{font-size:26px;font-weight:700}} .tot .lbl{{color:#656d76;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
 .cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;padding:8px 24px 32px}}
 .card{{background:#fff;border:1px solid #d0d7de;border-radius:12px;padding:16px}}
 .cardhdr{{display:flex;align-items:center;gap:8px;margin-bottom:10px}}
 .range{{color:#656d76;font-size:12px}}
 .badge{{margin-left:auto;color:#fff;font-size:11px;padding:2px 8px;border-radius:20px;white-space:nowrap}}
 .share{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
 .sharebar{{flex:1;height:8px;background:#eaeef2;border-radius:6px;overflow:hidden}}
 .sharebar i{{display:block;height:100%;background:linear-gradient(90deg,#2da44e,#0969da)}}
 .sharepct{{font-size:12px;font-weight:600;white-space:nowrap}}
 .grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px 14px}}
 .grid .k{{color:#656d76;font-size:11px;display:block}} .grid .v{{font-size:16px;font-weight:600}}
 .grid .sub2{{color:#8b949e;font-size:11px;display:block}}
 .queue{{margin-top:12px;padding-top:10px;border-top:1px solid #eaeef2;color:#424a53;font-size:13px}}
 .foot{{display:flex;justify-content:space-between;margin-top:10px;font-size:12px}}
 .good{{color:#1a7f37}} .bad{{color:#cf222e}} .muted{{color:#8b949e}} .warn{{color:#9a6700}}
</style>
<header>
  {f'<img src="{LOGO}" alt="Agience" class=logo>' if LOGO else ''}
  <h1>Mesh</h1>
  <span class=pill style="background:{hbg}">{health}</span>
  <div class=sub>{len(boxes)} peers{f' <span class=bad>(+{_unreadable} unreadable)</span>' if _unreadable else ''} · {len(ingesting)} ingesting · {len(idle_boxes)} idle · auto-refresh 15s · passive snapshots
  {'<span class=bad> · ⚠ shard ranges OVERLAP — ingest is redundant; union under-counted</span>' if shards_overlap else ''}</div>
</header>
<div class=whole>
  <h2>Overall health · the whole universe</h2>
  <div class=totals>
    <div class=tot><div class=big>{whole_art:,}</div><div class=lbl>total artifacts{' (≈ max; shards overlap)' if shards_overlap else ' (union)'}</div></div>
    <div class=tot><div class="big">{f"{rho:.4f}" if isinstance(rho,(int,float)) else "—"}</div><div class=lbl>&rho; compaction</div></div>
    <div class=tot><div class=big>{f"{cov*100:.0f}%" if isinstance(cov,(int,float)) else "—"}</div><div class=lbl>keyed coverage</div></div>
    <div class=tot><div class=big>{num(dark)}{_samp_note}</div><div class=lbl>dark matter</div></div>
    <div class=tot><div class=big>{num(wn)}</div><div class=lbl>wordnet</div></div>
    <div class=tot><div class=big>{num(con)}</div><div class=lbl>concepts</div></div>
    <div class=tot><div class=big>{num(ops_n)}</div><div class=lbl>operators</div></div>
    <div class=tot><div class=big>{num(content_s3)}</div><div class=lbl>content &rarr; S3</div></div>
    <div class=tot><div class="big {'bad' if idle_boxes else ''}">{len(idle_boxes)}</div><div class=lbl>idle (paid!)</div></div>
  </div>
</div>
<div class=cards>{''.join(cards)}</div>
"""
