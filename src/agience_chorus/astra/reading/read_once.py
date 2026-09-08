r"""Streams a text once, closing a "screen" (an in-progress context) when its residual is spent, and
forming a junction inline whenever a pair's counts cross the threshold that makes joining it cheaper
than keeping it apart.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['read_once','read:one1','--text','<corpus-dir>/_curriculum.txt']; \
        runpy.run_module('astra.reading.read_once', run_name='__main__')"

Every unit that leaves the stream splits its own incident energy by its own surprisal:

    r = surprisal / ceiling      T = sqrt(r)  residual      A = sqrt(1 - r)  absorbed
    A^2 + T^2 = 1, exactly, per unit

A screen closes when what arrives is more novel than what is already on it: the incoming residual is
compared against the mean residual of what stands on the screen so far. Both are measured quantities,
so there is no fixed threshold, and the comparison adapts to what the reader has already seen: early on
almost everything is novel, so screens are small, and as the reading absorbs more, fewer units arrive
novel and screens lengthen on their own.

A junction forms as counts cross, inline, rather than as a batch pass afterward. A pair is worth joining
when doing so explains its members for fewer bits than they cost apart — `cost(a+b) < cost(a) + cost(b)`
— and only once the pair has recurred: a pair seen once has `p(b|a) = 1` by construction, so its cost is
maximal on no evidence and the second sighting is what turns the ratio into a measurement.

The coordinate is derived after this pass (`read_basis` / `projection.read_cloud`), since a cloud needs
the co-presence this pass produces. Saturation (`optics.scale_read`, where the coherence peak marks a
concept complete) is available only from that second phase on; this module's conservation boundary is
what determines screen closure during the first phase.
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys
import time

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


def read_once(store, collection: str, text: str, say=print) -> dict:
    """Overlap for the vocabulary, then one streaming pass that closes screens and forms junctions."""
    import math

    from agience_chorus._host_seams import seam as _seam
    from agience_chorus.astra.reading import overlap as _ov
    from agience_chorus.astra.reading.organon_reader import _unit_id
    import agience_chorus.reading_junction as _j

    bits = _seam("optics").self_information_bits
    t0 = time.time()

    # 1. the vocabulary the text shares with itself — exact, nothing thresholded.
    spans = _ov.shared_spans(text)
    for s, w in spans.items():
        store.artifacts.put_artifact({
            "id": _unit_id(collection, s), "content_type": TOKEN_CT,
            "name": s, "content": s, "length": len(s), "witnesses": int(w),
            "collection_id": collection, "collections": [collection],
            "created_by": "ember-source",
        })
    say("overlap    %d maximal repeat(s) written as vocabulary" % len(spans))

    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    stream = _j.place(ro, collection, text)
    ro.close()
    say("stream     %d unit(s) placed" % len(stream))

    # 2. one pass. Counts accumulate as the reader goes — it never knows at unit 12 what unit 90,000
    #    will be, so every cost below is over what has been seen so far.
    seen = collections.Counter()
    pair_n = collections.Counter()
    N = 0
    screen, screen_res, obs_rows, edges, junctions = [], [], [], [], []
    formed = set()
    prev = None
    lengths = []

    for tok in stream:
        N += 1
        seen[tok] += 1
        surprisal = bits(float(seen[tok]), float(N))
        ceiling = bits(1.0, float(N)) if N > 1 else 1.0
        if surprisal is None or not ceiling:
            r = 1.0
        else:
            r = min(max(float(surprisal) / float(ceiling), 0.0), 1.0)
        absorbed, residual = 1.0 - r, r

        # The comparison is against the screen the unit is arriving at, not a constant: a screen
        # closes when what arrives is more novel than what is already here, measured as the
        # incoming residual against the mean residual of what stands. A screen of novel things
        # tolerates novelty, a screen of familiar things breaks on it, and screens lengthen as the
        # reading absorbs more — thought-length emerges from what is known rather than from a
        # fixed threshold.
        _mean_res = (sum(screen_res) / len(screen_res)) if screen_res else 0.0
        if screen and residual > _mean_res:
            oid = "%s:obs-%d" % (collection, len(obs_rows))
            obs_rows.append({
                "id": oid, "content_type": OBS_CT, "name": oid.split(":")[-1],
                "collection_id": collection, "collections": [collection],
                "created_by": "ember-source", "at": len(obs_rows),
                "content": "".join(screen), "signals": len(screen),
            })
            for m in dict.fromkeys(screen):
                edges.append((oid, _unit_id(collection, m), "observed", {}))
            lengths.append(len(screen))
            screen, screen_res = [], []

        screen.append(tok)
        screen_res.append(residual)

        # The colimit, as the counts cross: cheaper than its parts, and recurred.
        if prev is not None:
            pair_n[(prev, tok)] += 1
            n = pair_n[(prev, tok)]
            joined = prev + tok
            if n >= 2 and joined not in seen and joined not in formed:
                c_j = bits(float(n), float(N))
                c_a = bits(float(seen[prev]), float(N))
                c_b = bits(float(seen[tok]), float(N))
                if None not in (c_j, c_a, c_b) and c_j < (c_a + c_b):
                    formed.add(joined)
                    vid = _unit_id(collection, joined)
                    saved = round(float((c_a + c_b) - c_j), 6)
                    junctions.append({
                        "id": vid, "content_type": TOKEN_CT, "name": joined, "content": joined,
                        "collection_id": collection, "collections": [collection],
                        "created_by": "ember-source", "length": len(joined),
                        "witnesses": int(n), "bits_saved": saved,
                    })
                    for m in (prev, tok):
                        edges.append((vid, _unit_id(collection, m), "observed",
                                      {"bits_saved": saved}))
        prev = tok

    if screen:
        oid = "%s:obs-%d" % (collection, len(obs_rows))
        obs_rows.append({
            "id": oid, "content_type": OBS_CT, "name": oid.split(":")[-1],
            "collection_id": collection, "collections": [collection],
            "created_by": "ember-source", "at": len(obs_rows),
            "content": "".join(screen), "signals": len(screen),
        })
        for m in dict.fromkeys(screen):
            edges.append((oid, _unit_id(collection, m), "observed", {}))
        lengths.append(len(screen))

    for d in obs_rows + junctions:
        store.artifacts.put_artifact(d)
    handled = store.graph.add_edges(edges)
    if handled < len(edges):
        raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                           % (handled, len(edges)))

    mean_len = round(sum(lengths) / max(len(lengths), 1), 2)
    say("screens    %d closed, mean %s unit(s) each  (first %s, last %s)"
        % (len(obs_rows), mean_len, lengths[:1] or [0], lengths[-1:] or [0]))
    say("colimit    %d junction(s) formed inline" % len(junctions))
    say("edges      %d in %.1fs" % (len(edges), time.time() - t0))
    return {"spans": len(spans), "screens": len(obs_rows), "junctions": len(junctions),
            "edges": len(edges), "mean_screen": mean_len, "lengths": lengths}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("--text", required=True)
    ap.add_argument("--chars", type=int, default=0, help="0 = the whole text")
    args = ap.parse_args()
    raw = open(args.text, encoding="utf-8", errors="replace").read()
    if args.chars:
        raw = raw[:args.chars]
    from mantle.shard.local_store import open_store
    read_once(open_store(), args.collection, raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
