r"""The reading along its clock — how much of each context the ones before it already explained.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['read_over_time','--collection','market:news2']; \
        runpy.run_module('astra.reading.read_over_time', run_name='__main__')"

The invocation imports the host, and this module does not — the same form every other reader in this
directory carries. `optics` is reached through the seam `read_basis.optics()` declares, so what binds
that seam is the host's answer; a `python -m` run would leave it unfilled and the module would have to
name ember itself, which is the L3 sideways edge `src/tests/test_chorus_does_not_import_ember.py`
holds at zero. Chorus does not install ember and the shipped image carries prism and crystal only, so
the import could not have resolved on a node in any case.

`read_basis` reads the corpus whole: one basis over every context, which is what a corpus read wants
and what makes it useless for a forward signal. Its basis is derived from all contexts in the
collection, so asking "how novel was context 40" against it asks a question whose answer already
contains contexts that arrived after it.

So this walks the same cloud in arrival order and gives each context a basis built strictly from the
contexts before it. What that basis cannot absorb is the residual: what this context said that the
reading had not already accounted for.

## What is reused, and what is new

Reused, because it exists: `read_basis.cloud` (the coordinate — membership over contexts, amplitude
`sqrt(self_information_bits)`, `‖row‖²` = energy), `optics.principal_directions` (the resolved basis),
`optics.absorb_transmit` (project onto it and measure what is absorbed — the sanctioned operation;
normalising two vectors and dotting them is cosine and is not used here).

New, and only this: the order, the causal window, and the clock. Nothing here re-derives a
coordinate, a basis, or a projection.

## Three properties this measurement depends on

**The basis never sees the future.** Row `t` is measured against rows `< t`, never `<= t`. A single
off-by-one would put the context inside its own basis and every reading would read 0.

**Absence of a basis is not read as novelty.** `principal_directions` resolves nothing on too few
rows, and an empty basis absorbs nothing, so an early context scored against it would read 1.0 —
maximal novelty exactly where a backtest starts, biasing everything after it. Contexts before the
basis resolves are skipped, not scored, and the count of skipped ones is returned rather than left
silent.

**The clock comes from the artifact, not the text.** The publish time is read off the artifact
(`published_at`, written by `overlap.read(meta=…)`), never parsed out of the content. A timestamp in
the text is unique by construction and would make every context maximally novel if used as the clock.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Dict, List, Optional

from agience_chorus.astra.reading import read_basis as _rb

PARA_CT = "application/x-paragraph"


def _context_times(store, collection: str) -> Dict[str, str]:
    """context id -> its publish time, off the artifact. Contexts without one are absent from the
    map rather than defaulted: a context that cannot be placed in time must not be placed anyway."""
    out: Dict[str, str] = {}
    for a in store.artifacts.list_artifacts(collection_id=collection):
        if a.get("content_type") != PARA_CT:
            continue
        ts = a.get("published_at")
        if ts:
            out[a["id"]] = ts
    return out


def residual_over_time(store, ro, collection: str, *, window: Optional[int] = None) -> Dict[str, object]:
    """Each context in arrival order, with the share of its energy the prior contexts did not absorb.

    Returns `{"rows": [{ts, context, residual, n_prior}], "skipped_no_basis": int, "contexts": int,
    "unplaced": int}`.

    `window` bounds how many prior contexts form the basis — `None` means all of them. It is a memory
    span, not a tuning knob, and it is reported per row (`n_prior`) so a reader can see what each
    score was measured against instead of assuming it was constant.

    `residual` is a share of incident energy, in `[0, 1]`, because `absorb_transmit` splits by
    `A² + T² = 1` — the organon's own convention. It is not a probability and not a score.
    """
    M, names, contexts = _rb.cloud(ro, collection)
    if M is None:
        raise RuntimeError("collection %r holds no unit in any context — nothing to read" % collection)

    times = _context_times(store, collection)
    # Order is the causality here. Contexts with no time are dropped, and counted, rather than sorted
    # to one end where they would silently become either the oldest or the newest evidence.
    placed = [(times[c], i, c) for i, c in enumerate(contexts) if c in times]
    placed.sort()
    unplaced = len(contexts) - len(placed)

    optics = _rb.optics()
    rows: List[Dict[str, object]] = []
    skipped = 0
    # A context is a column of the cloud; the clock is on that axis, so the walk is over `M.T`.
    by_context = M.T

    for pos, (ts, idx, cid) in enumerate(placed):
        lo = 0 if window is None else max(0, pos - int(window))
        prior_idx = [j for _t, j, _c in placed[lo:pos]]
        if len(prior_idx) < 2:
            skipped += 1
            continue
        prior = by_context[prior_idx]
        basis = optics.principal_directions(prior)
        if basis is None or getattr(basis, "ndim", 0) != 2 or basis.shape[1] < 1:
            # The reading has not yet resolved anything to be novel against. Not a zero, not a one.
            skipped += 1
            continue
        cur = by_context[idx]
        # Two identical rows: `absorb_transmit` reads an ordered frame, and one row carries no order.
        res = optics.absorb_transmit([cur, cur], basis=basis)
        if res is None:
            skipped += 1
            continue
        absorbed, transmitted, _k = res
        e_ab = float((absorbed ** 2).sum())
        e_tr = float((transmitted ** 2).sum())
        total = e_ab + e_tr
        if total <= 0.0:
            skipped += 1
            continue
        rows.append({"ts": ts, "context": cid, "residual": e_tr / total,
                     "n_prior": len(prior_idx)})

    return {"rows": rows, "skipped_no_basis": skipped, "contexts": len(contexts),
            "unplaced": unplaced}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default=os.environ.get("READ_COLLECTION", "read:mine"))
    ap.add_argument("--window", type=int, default=None,
                    help="how many prior contexts form the basis (default: all before)")
    a = ap.parse_args()

    # The host binds the seams, and the invocation at the top of this file is where it is named —
    # see that note. Nothing here imports it.
    from mantle.shard.local_store import open_store
    store = open_store()
    ro = sqlite3.connect(_rb._db())
    try:
        out = residual_over_time(store, ro, a.collection, window=a.window)
    finally:
        ro.close()

    rows = out["rows"]
    print("collection   %s" % a.collection)
    print("contexts     %d   placed in time %d   unplaced %d"
          % (out["contexts"], len(rows) + out["skipped_no_basis"], out["unplaced"]))
    print("scored       %d   skipped (no basis yet) %d" % (len(rows), out["skipped_no_basis"]))
    if not rows:
        print("nothing scored — the reading resolved no basis to be novel against")
        return 0
    vals = sorted(r["residual"] for r in rows)
    print("residual     min %.4f   median %.4f   max %.4f"
          % (vals[0], vals[len(vals) // 2], vals[-1]))
    print()
    print("MOST novel (the residual — what the reading had not already accounted for):")
    for r in sorted(rows, key=lambda r: -r["residual"])[:5]:
        print("   %.4f  %s  n_prior=%d" % (r["residual"], r["ts"][:16], r["n_prior"]))
    print("LEAST novel (already explained by what came before):")
    for r in sorted(rows, key=lambda r: r["residual"])[:5]:
        print("   %.4f  %s  n_prior=%d" % (r["residual"], r["ts"][:16], r["n_prior"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
