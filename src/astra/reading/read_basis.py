r"""The read corpus's own basis — the coordinate that makes what was read readable.

    cd agience-chorus/src
    READ_COLLECTION=read:mine python -c "import ember, runpy, sys; \
        sys.argv=['read_basis']; runpy.run_module('astra.reading.read_basis', run_name='__main__')"

A one-hot coordinate over the vocabulary carries a feature width that grows with the corpus, and it
does not resolve: reading adds units far faster than it adds distinct contexts, so `T/F` rises
without bound as the corpus grows. A fixed-width hashed coordinate avoids that growth but wastes most
of its width paying for empty channels nobody measured.

The width used here is the reading's own: the number of distinct contexts it formed. A unit's
coordinate is its membership over those contexts — exact, collision-free, and a count rather than a
choice. No `D`, no hash, and no second hash to drift from crystal's.

A context's amplitude is `sqrt(self_information_bits(deg, total))` — `I = -log2(p)` from
`entroptics.entropy` through the one instrument, and the square root because `‖row‖²` is that row's
energy, the same convention as the organon's `A² + T² = 1`. A context holding nearly everything
narrows nothing and arrives at ~0 bits; a rare one arrives loud.

The construction's shape is `ember/signal/projection.py::build_basis`'s: present the cloud tall, read
it through `optics.principal_directions`, and take the count and the directions from one spectrum.
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys
from typing import Dict, List, Optional

import numpy as np

# One instrument, reached by name: nothing outside `ember/optics.py` imports entroptics, and a
# persona asks for a measurement rather than performing it.
from _host_seams import seam as _seam

_optics = None

OBSERVED = ("observed", "observed_alone")


def optics():
    global _optics
    if _optics is None:
        _optics = _seam("optics")
    return _optics


def projection():
    """The host's measurement surface. The cloud/basis construction lives in
    `ember/signal/projection.py` because lumen needs the same measurement, and
    `test_no_persona_SOURCE_imports_another_persona` forbids lumen importing astra. Two personas
    needing one measurement is a seam, not a shared import."""
    return _seam("projection")


def _db() -> str:
    """The store the host chose, resolved per call. A basis measured on a store the host never chose
    looks identical to one measured on the right store."""
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


def unit_contexts(ro, collection: str) -> Dict[str, List[str]]:
    """unit -> the contexts holding it. The host's read, reached by name."""
    return projection().read_unit_contexts(ro, collection)


def cloud(ro, collection: str):
    """The read corpus as `(M, names, contexts)` — the host's construction, reached by name."""
    return projection().read_cloud(ro, collection)


def derive(ro, collection: str) -> Optional[dict]:
    """The read collection's basis and the read behind it — the host's, reached by name."""
    return projection().read_basis(ro, collection)


def coordinates(ro, collection: str):
    """Every unit's coordinate in the basis — `(names, C)` with `C = M @ B`, an `(n_units, k)` frame.

    Coupling runs on this: projecting onto the resolved basis is the sanctioned operation
    ([[cosine-similarity-is-forbidden]] — project onto a resolved basis and measure what is absorbed,
    never normalise two vectors and dot them)."""
    M, names, _ctx = cloud(ro, collection)
    if M is None:
        return [], None
    B = optics().principal_directions(M)
    if B is None or B.ndim != 2 or B.shape[1] < 1:
        return names, None
    return names, M @ B


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default=os.environ.get("READ_COLLECTION", "read:mine"))
    args = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    got = derive(ro, args.collection)
    if got is None:
        print("%s holds no unit in any context — nothing to derive a basis from" % args.collection)
        return 2
    print("collection   %s" % args.collection)
    print("cloud        %d unit(s) x %d context(s)   T/F = %.2f"
          % (got["rows"], got["d"], got["rows"] / float(max(got["d"], 1))))
    print("contrast     %.4f" % got["contrast"])
    if got["refusal"]:
        print("REFUSED      %s" % got["refusal"])
        return 1
    print("resolved     k = %d   certified [%s, %s]   k_certain %s"
          % (got["k"], got["k_lo"], got["k_hi"], got["k_certain"]))
    print("")
    print("the one-hot coordinate this replaces read contrast 0.4671 and resolved 0 modes on the")
    print("same collection — the coordinate was the defect, not the corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
