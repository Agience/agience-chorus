r"""Compaction: fuses vertices that always travel together, iterating until the ontology stops
changing.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['compact','read:cat1']; \
        runpy.run_module('astra.reading.compact', run_name='__main__')"

`overlap` finds maximal repeats exactly, but without respecting any boundary, so on a small corpus it
can produce vocabulary like

    'at.\n\nThe cat in the hat '        '.\n\nElizabeth walked to the garden gate'      ' in the '

which straddles sentence ends and starts mid-word. A prefix then places onto a vertex it only partly
covers, so a completion can begin mid-token. Compaction is what corrects this: two adjacent vertices
that keep arriving together are one thing the reading has not named yet, and naming it is the
universal object. The pass repeats until nothing new forms, which is the ontology signalling it has
finished — words fuse at the early passes, phrases at the later ones.

The rule, with no threshold in it:

    fuse(a, b)  iff  cost(a+b) < cost(a) + cost(b)          and the pair recurred

`cost` is `self_information_bits` over what this reading has placed. The junction is worth having
exactly when it explains its members for fewer bits than they cost apart; zero is the definition of
"cheaper", not a bar anyone chose.

Recurrence is required for a separate reason, and it is not a frequency filter: a pair seen once has
`p(b|a) = 1` by construction, so its cost looks maximal on no evidence — the estimator is degenerate
at n=1 rather than merely noisy. The second sighting is what makes it a measurement.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import sys

TOKEN_CT = "application/x-token"
#: There is no `colimit` edge label. Stamping a kind on an edge decides at write time what a later
#: reader may ask; what makes a junction a junction is that it explains its members for fewer bits
#: than they cost apart, and `bits_saved` is already on the edge as that measurement. One edge kind;
#: the reading is off the bits.
OBSERVED = "observed"


def _db() -> str:
    # The shard is a data volume, not part of the checkout, so no default here could be right
    # on another box. Unset is REFUSED rather than guessed: a reader silently opening a store
    # nobody chose does not fail, it reports an empty corpus — which reads as "nothing found"
    # when the truth is "nothing configured".
    root = (os.environ.get("EMBER_SQLITE_DIR") or "").strip()
    if not root:
        raise RuntimeError(
            "EMBER_SQLITE_DIR is unset. Point it at the directory holding lattice.db.")
    return os.path.join(root, os.environ.get("EMBER_SQLITE_DB", "lattice.db"))


def contexts(ro, collection):
    """Every step artifact and the text it was read from — the paths the reading has walked."""
    out = []
    for i, d in ro.execute("SELECT id, doc FROM vertex WHERE id >= ? AND id < ?",
                           (collection + ":", collection + ";")):
        try:
            doc = json.loads(d) or {}
        except Exception:
            continue
        if doc.get("content_type") == "application/x-observation" and doc.get("content"):
            out.append((i, doc["content"]))
    return out


def one_pass(store, ro, collection, say=print):
    """One compaction pass: place every context, fuse the adjacent pairs that pay."""
    import agience_chorus.reading_junction as _j
    from agience_chorus.astra.reading.organon_reader import _unit_id
    from agience_chorus._host_seams import seam as _seam
    bits = _seam("optics").self_information_bits

    paths = [(_cid, _j.place(ro, collection, body)) for _cid, body in contexts(ro, collection)]
    if not paths:
        return 0, 0

    # What the reading has placed — the counts every cost below is taken over.
    unit_n = collections.Counter()
    pair_n = collections.Counter()
    # Also tracks where each pair occurred, so a formed junction is reachable through the context
    # that holds it rather than sitting nowhere. A junction inherits the contexts its pair occurred
    # in: it was present wherever its members were adjacent, which is where the pass just saw it, so
    # the context edge is written from the same observation that formed it. Keeping a vertex is not
    # enough on its own — it must stay reachable, and a vertex is reached through its context.
    pair_ctx = collections.defaultdict(set)
    for _cid, placed in paths:
        for t in placed:
            unit_n[t] += 1
        for a, b in zip(placed, placed[1:]):
            pair_n[(a, b)] += 1
            pair_ctx[(a, b)].add(_cid)
    total = max(sum(unit_n.values()), 1)

    formed, edges, rows = 0, [], []
    for (a, b), n in pair_n.items():
        if n < 2:
            continue                       # degenerate at n=1 — not evidence, see the header
        joined = a + b
        if joined in unit_n:
            continue                       # already a vertex; nothing to form
        c_j = bits(float(n), float(total))
        c_a = bits(float(unit_n[a]), float(total))
        c_b = bits(float(unit_n[b]), float(total))
        if c_j is None or c_a is None or c_b is None:
            continue
        if c_j >= (c_a + c_b):
            continue                       # the junction costs more than its parts — not a colimit
        vid = _unit_id(collection, joined)
        rows.append({
            "id": vid, "content_type": TOKEN_CT, "name": joined, "content": joined,
            "collection_id": collection, "collections": [collection],
            "created_by": "ember-source", "operator": "op.colimit",
            "length": len(joined), "witnesses": int(n),
            "bits_saved": round(float((c_a + c_b) - c_j), 6),
        })
        for m in (a, b):
            edges.append((vid, _unit_id(collection, m), OBSERVED,
                          {"bits_saved": round(float((c_a + c_b) - c_j), 6)}))
        for _cid in sorted(pair_ctx[(a, b)]):
            edges.append((_cid, vid, OBSERVED, {}))
        formed += 1

    # No positions are rewritten here: order lives in the observations, one per tick, so compaction
    # cannot stale it and there are no `char` offsets on context edges to refresh.
    for r in rows:
        store.artifacts.put_artifact(r)
    if edges:
        handled = store.graph.add_edges(edges)
        if handled < len(edges):
            raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                               % (handled, len(edges)))
    return formed, len(edges)


def compact(store, collection, say=print):
    """Iterate until the ontology stops changing — the reading's own stopping condition.

    There is no pass limit: the loop ends when a pass forms nothing, which is the colimit closing on
    its own. A typed maximum would stop it at a point the measurement did not choose."""
    n_pass, total = 0, 0
    while True:
        ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
        formed, edges = one_pass(store, ro, collection, say=say)
        ro.close()
        n_pass += 1
        total += formed
        say("pass %d: %d junction(s), %d morphism(s)" % (n_pass, formed, edges))
        if not formed:
            break
    say("closed after %d pass(es), %d junction(s) formed" % (n_pass, total))
    return {"passes": n_pass, "formed": total}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    args = ap.parse_args()
    from mantle.shard.local_store import open_store
    compact(open_store(), args.collection)
    return 0


if __name__ == "__main__":
    sys.exit(main())
