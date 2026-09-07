r"""The held-out oracle — three reads, all of them the instrument's.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['heldout','--collection','read:mine', \
                  '--text','<corpus-dir>/pride-novel.txt']; \
        runpy.run_module('lumen.reading.heldout', run_name='__main__')"

Every read here delegates to entroptics rather than re-implementing its own statistic:

    n-gram structure                  ->  `surrogate_significance` (block entropy vs shuffles)
    perplexity / log-loss             ->  the `H_n` ladder the same read returns
    "is it better than chance?"       ->  the permutation null, which is the comparison

A shuffle has the same length, alphabet and symbol frequencies as the real stream, so a plug-in block
entropy estimator carries the identical bias at every `n` in both the real and the shuffled read, and
that bias cancels exactly in the difference — a property no hand-typed backoff constant can match.

The three reads answer different questions; none of them substitutes for another:

  1. structure — is there anything in the text to capture? `surrogate_significance` on the stream.
     This is the ceiling, and it is a property of the text, not of the reading.
  2. resolution — does the reading's coordinate resolve? The host's `projection.read_basis`.
     A reading that resolves nothing cannot complete anything, and says so.
  3. completion — does the coupling rank a held-out unit above a permutation of itself?
     The instrument's own coupling, scored against the null the instrument computes.

No perplexity number is reported. `entroptics.sequence`'s header is explicit that a collapsed rate
means almost nothing and that only a differential study makes sense — the `H_n` ladder is reported
against its shuffle, which is the differential, and never as a single score to rank models by.
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys

import numpy as np

from _host_seams import seam as _seam

_optics = None


def optics():
    global _optics
    if _optics is None:
        _optics = _seam("optics")
    return _optics


def _db() -> str:
    # The shard is a data volume, not part of the checkout, so no default here could be right
    # on another box. Unset is REFUSED rather than guessed: a reader silently opening a store
    # nobody chose does not fail, it reports an empty corpus — which reads as "nothing found"
    # when the truth is "nothing configured".
    db = (os.environ.get("EMBER_SQLITE_DB") or "").strip()
    if db:
        return db
    d = (os.environ.get("EMBER_SQLITE_DIR") or "").strip()
    if not d:
        raise RuntimeError(
            "EMBER_SQLITE_DIR is unset. Point it at the directory holding lattice.db.")
    return os.path.join(d, "lattice.db")


# ══════════════════════════════════════════════════════════════════════════════
# 1. structure — what is in the text at all
# ══════════════════════════════════════════════════════════════════════════════

def structure(text: str, unit: str = "char") -> dict:
    """`surrogate_significance` on the stream: does the order carry anything?

    `z_n` below zero is the finding — less block entropy than the shuffle means the order carries
    structure. `z_1` must be exactly zero (a permutation cannot change the symbol histogram), and the
    read returns `control_H1_exact` so that control cannot be skipped."""
    seq = list(text) if unit == "char" else text.split()
    return optics().surrogate_significance(seq)


# ══════════════════════════════════════════════════════════════════════════════
# 3. completion — does the coupling rank a held-out unit above its own permutation?
# ══════════════════════════════════════════════════════════════════════════════

def completion(ro, collection: str, seed: int = 0) -> dict:
    """Hold one unit out of a context, and ask the coupling to put it back.

    For each context the reading formed, one of its units is withheld. The remaining units are the
    query; every unit in the collection is a candidate; the coupling ranks them by the energy each
    absorbs from the query's band. The score is where the withheld unit lands.

    The null is the same measurement on a permutation, so no baseline is invented. A rank that beats
    the permuted rank is the reading completing; a rank that matches it is the reading doing nothing,
    and the two are told apart by the instrument rather than by a threshold.

    Candidates are ranked by the energy they absorb from a projection onto the query's resolved band,
    via `absorb_transmit` — never by an angle between two raw vectors.
    """
    # Not `from astra.reading import ...` — a persona may not import a sibling, and
    # `test_no_persona_SOURCE_imports_another_persona` pins it. The cloud is the host's measurement,
    # reached by name.
    _proj = _seam("projection")
    M, names, contexts = _proj.read_cloud(ro, collection)
    if M is None:
        return {"refusal": "the collection holds no unit in any context"}
    B = optics().principal_directions(M)
    if B is None or B.ndim != 2 or B.shape[1] < 1:
        return {"refusal": "the reading's coordinate resolved no mode — nothing to couple in"}
    C = M @ B                                    # every unit's coordinate IN the resolved basis
    idx = {u: i for i, u in enumerate(names)}

    uc = _proj.read_unit_contexts(ro, collection)
    held = collections.defaultdict(list)
    for u, ctxs in uc.items():
        for c in ctxs:
            held[c].append(u)

    rng = np.random.default_rng(seed)
    ranks, null_ranks = [], []
    for c in contexts:
        us = [u for u in held.get(c, ()) if u in idx]
        if len(us) < 3:
            continue                              # a context of two has no "rest" to query from
        for pos in range(len(us)):
            truth = us[pos]
            rest = [u for j, u in enumerate(us) if j != pos]
            q = C[[idx[u] for u in rest]]
            if q.shape[0] < 2:
                continue
            Bq = optics().principal_directions(q)
            if Bq is None or Bq.ndim != 2 or Bq.shape[1] < 1:
                continue
            # energy each candidate absorbs from the query's band — the instrument's own split
            res = optics().absorb_transmit(C, basis=Bq)
            if res is None:
                continue
            ab, _tr, _k = res
            absorbed = (np.abs(ab) ** 2).sum(axis=1)
            order = np.argsort(-absorbed)
            pos_of = {int(k): r for r, k in enumerate(order)}
            ranks.append(pos_of[idx[truth]])
            null_ranks.append(pos_of[int(rng.integers(0, len(names)))])
            break                                 # one hold-out per context: contexts are the sample
    if not ranks:
        return {"refusal": "no context held enough units to withhold one"}
    return {"contexts_scored": len(ranks), "candidates": len(names),
            "median_rank": float(np.median(ranks)),
            "median_rank_null": float(np.median(null_ranks)),
            "mean_rank": float(np.mean(ranks)), "mean_rank_null": float(np.mean(null_ranks)),
            "refusal": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default=os.environ.get("READ_COLLECTION", "read:mine"))
    # The text is a corpus file, not part of the checkout: the caller names it.
    ap.add_argument("--text", required=True, help="the text to read")
    ap.add_argument("--chars", type=int, default=40000, help="how much of the stream to read")
    ap.add_argument("--unit", choices=("char", "word"), default="char")
    args = ap.parse_args()

    print("=" * 78)
    print("1. STRUCTURE — is there ordered structure in the text at all?")
    print("=" * 78)
    text = open(args.text, encoding="utf-8", errors="replace").read()[:args.chars]
    st = structure(text, args.unit)
    if not st:
        print("   the stream is unreadable at this length")
    else:
        print("   N %d   alphabet %d   draws %d" % (st["N"], st["alphabet"], st["draws"]))
        print("   control_H1_exact %s   <- a permutation cannot change the histogram; if this is"
              % st["control_H1_exact"])
        print("                            False every other row below is meaningless")
        print("   onset %s   <- the shortest window in which any structure is visible" % st["onset"])
        print("   n     H_n(real)  H_n(shuffled)      z")
        for n, (hr, hn, z) in enumerate(zip(st["H_n_real"], st["H_n_null_mean"], st["z"]), start=1):
            print("   %-5d %9.2f %14.2f %8.1f" % (n, hr, hn, z))

    print("")
    print("=" * 78)
    print("2. RESOLUTION — does the reading's own coordinate resolve?")
    print("=" * 78)
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    got = _seam("projection").read_basis(ro, args.collection)
    if got is None:
        print("   %s holds no unit in any context" % args.collection)
        return 2
    print("   cloud %d unit(s) x %d context(s)   T/F = %.2f"
          % (got["rows"], got["d"], got["rows"] / float(max(got["d"], 1))))
    print("   contrast %.4f" % got["contrast"])
    if got["refusal"]:
        print("   REFUSED  %s" % got["refusal"])
        return 1
    print("   resolved k = %d   certified [%s, %s]   k_certain %s"
          % (got["k"], got["k_lo"], got["k_hi"], got["k_certain"]))

    print("")
    print("=" * 78)
    print("3. COMPLETION — does the coupling put a held-out unit back?")
    print("=" * 78)
    cp = completion(ro, args.collection)
    if cp.get("refusal"):
        print("   REFUSED  %s" % cp["refusal"])
        return 1
    print("   %d context(s) scored, %d candidate(s) each" % (cp["contexts_scored"], cp["candidates"]))
    print("   median rank of the withheld unit   %8.1f" % cp["median_rank"])
    print("   median rank under permutation      %8.1f   <- the null the instrument computes"
          % cp["median_rank_null"])
    print("   mean   rank                        %8.1f  (null %.1f)"
          % (cp["mean_rank"], cp["mean_rank_null"]))
    print("")
    print("   READ: a withheld unit ranked far above its permutation is the reading completing.")
    print("         Ranks that match the null mean the coupling carries nothing here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
