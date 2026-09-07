r"""Closes each screen where a unit stops belonging where it sits.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['resegment','read:one2','--text','<corpus-dir>/_curriculum.txt']; \
        runpy.run_module('astra.reading.resegment', run_name='__main__')"

The boundary is `optics.position_coherence`, standardised against the frame's own off-diagonal
null: is this unit more like its ordered neighbours than a random row of this frame would be?
Above zero it belongs where it sits; below zero it does not, and that is where the screen ends.
The zero is the frame's own null, not a level anyone chose.

This runs as phase two because a coordinate comes from co-presence, and co-presence is what a
screen produces — so the first pass has to bootstrap on something the text supplies, and only
then can the boundary be measured. `build_basis` uses the same staging: derive the basis as a
consolidation job against a corpus that has finished being written.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

import numpy as np

TOKEN_CT = "application/x-token"
OBS_CT = "application/x-observation"


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


def resegment(store, collection: str, text: str, say=print) -> dict:
    """Re-place the stream and close each screen where a unit stops belonging in it."""
    from _host_seams import seam as _seam
    from astra.reading.organon_reader import _unit_id
    import reading_junction as _j

    o = _seam("optics")
    t0 = time.time()
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    rd = _j.Reading(ro, collection)
    if rd.coord is None:
        ro.close()
        return {"refusal": "this collection has no coordinate yet — phase one has not run"}
    say("coordinate %s  k=%d" % (rd.M.shape, rd.B.shape[1]))

    stream = _j.place(ro, collection, text)
    ro.close()
    say("stream     %d unit(s) placed" % len(stream))

    idx, coord = rd.idx, rd.coord
    screen, rows_, obs, edges, lengths = [], [], [], [], []

    def _close():
        if not screen:
            return
        oid = "%s:seg-%d" % (collection, len(obs))
        obs.append({
            "id": oid, "content_type": OBS_CT, "name": oid.split(":")[-1],
            "collection_id": collection, "collections": [collection],
            "created_by": "ember-source", "at": len(obs),
            "content": "".join(screen), "signals": len(screen),
        })
        for m in dict.fromkeys(screen):
            edges.append((oid, _unit_id(collection, m), "observed", {}))
        lengths.append(len(screen))

    for tok in stream:
        uid = _unit_id(collection, tok)
        i = idx.get(uid)
        if i is None:
            continue                        # nothing of it in the coordinate — it cannot be placed
        screen.append(tok)
        rows_.append(coord[i])
        # The read needs four rows before it can measure anything; below that nothing has been
        # shown not to belong, so the screen keeps accumulating.
        if len(rows_) < 4:
            continue
        pc = o.position_coherence(np.vstack(rows_), len(rows_) - 1)
        if pc is not None and pc < 0.0:
            # This unit is less like its neighbours here than a random row of this frame would be.
            # The screen ends before it and opens the next one.
            screen.pop()
            rows_.pop()
            _close()
            screen, rows_ = [tok], [coord[i]]
    _close()

    for d in obs:
        store.artifacts.put_artifact(d)
    handled = store.graph.add_edges(edges)
    if handled < len(edges):
        raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                           % (handled, len(edges)))
    mean = round(sum(lengths) / max(len(lengths), 1), 2)
    say("screens    %d closed, mean %s unit(s)  (min %s, max %s)"
        % (len(obs), mean, min(lengths or [0]), max(lengths or [0])))
    say("edges      %d in %.1fs" % (len(edges), time.time() - t0))
    return {"screens": len(obs), "mean_screen": mean, "edges": len(edges), "lengths": lengths}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("--text", required=True)
    args = ap.parse_args()
    raw = open(args.text, encoding="utf-8", errors="replace").read()
    from mantle.shard.local_store import open_store
    out = resegment(open_store(), args.collection, raw)
    if out.get("refusal"):
        print("REFUSED  %s" % out["refusal"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
