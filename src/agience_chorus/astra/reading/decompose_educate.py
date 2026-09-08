r"""Read full text, break it into shared vocabulary by overlap, then place each
paragraph into that vocabulary with context.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['decompose_educate','read:edu2','--text','<corpus-dir>/pride-novel.txt', \
                  '--chars','20000']; \
        runpy.run_module('astra.reading.decompose_educate', run_name='__main__')"

The three steps run in the order the ontology needs them:

    1. overlap   the corpus against itself -> the shared spans, written as vertices
    2. place     each paragraph places into those spans, and the step-artifact carries the
                 context — everything that was on the screen when it was read
    3. colimit   a screen that still cannot be covered forms its universal object (`learn_step`)

Decomposition comes first, and it is exact: `overlap.shared_spans` finds every maximal repeat —
a span occurring at least twice that cannot be extended either way without losing an occurrence.
Nothing is thresholded, no minimum length, no vocabulary size — what the text shares with itself
is a fact about the text. Those spans are the vocabulary a paragraph places into. `learn_step` is
the act that fires when a screen the reading already has vocabulary for still cannot be covered —
it presumes a vocabulary, so overlap runs first to build one.

Step 2 is where context enters. A span written by step 1 knows what it is and nothing about where
it sits; the step-artifact is what puts it somewhere. `project` travels `observed` edges, so a
vertex with no context cannot be projected from.
"""
from __future__ import annotations

import argparse
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


def paragraphs(text: str):
    """The text's own paragraphs. The blank line is the text's delimiter, not a rule about English —
    the same standing this module's whitespace tokenisation has: it is what the file supplies."""
    return [p for p in text.split("\n\n") if p.strip()]


def educate(store, collection: str, text: str, say=print) -> dict:
    """Overlap the corpus, write its vocabulary, then place every paragraph into it with context."""
    from agience_chorus.astra.reading import overlap as _ov
    from agience_chorus.astra.reading.organon_reader import _unit_id

    t0 = time.time()
    spans = _ov.shared_spans(text)
    say("overlap    %d maximal repeat(s) — what the text shares with itself" % len(spans))

    # 1. the vocabulary. A span is an artifact; its witness count is what the overlap measured.
    rows = []
    for s, w in spans.items():
        rows.append({
            "id": _unit_id(collection, s), "content_type": TOKEN_CT,
            "name": s, "content": s, "length": len(s), "witnesses": int(w),
            "collection_id": collection, "collections": [collection],
            "created_by": "ember-source", "operator": "op.overlap",
        })
    for d in rows:
        store.artifacts.put_artifact(d)
    say("vocabulary %d span(s) written" % len(rows))

    # 2. place each paragraph, and let the step carry the context.
    import agience_chorus.reading_junction as _j
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    paras = paragraphs(text)
    edges, steps, placed_total = [], 0, 0
    tick = 0
    for n, para in enumerate(paras):
        placed = _j.place(ro, collection, para)
        if len(placed) < 2:
            continue
        placed_total += len(placed)
        # One observation is written per placed unit, each carrying its own position (`at`) in the
        # stream, rather than one context per paragraph with order encoded as edge properties.
        # Sequence is then the sequence of observations, recoverable from the artifacts themselves;
        # the edge itself says only that this was on that screen, so it carries no classification
        # that could go stale when compaction changes the vocabulary it was recorded against.
        for i, m in enumerate(placed):
            tick += 1
            oid = "%s:obs-%d" % (collection, tick)
            store.artifacts.put_artifact({
                "id": oid, "content_type": OBS_CT, "name": "obs-%d" % tick,
                "collection_id": collection, "collections": [collection],
                "created_by": "ember-source",
                # The observation's own position in the reading — first-hand, not a claim about
                # any edge. `of` names the paragraph it was read from so the source is citable.
                "at": tick, "of": "para-%d" % n, "content": m,
            })
            edges.append((oid, _unit_id(collection, m), "observed", {}))
            steps += 1
    ro.close()
    handled = store.graph.add_edges(edges)
    if handled < len(edges):
        raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                           % (handled, len(edges)))
    say("placed     %d paragraph(s) -> %d observation(s), %d edge(s) in %.1fs"
        % (len(paras), steps, len(edges), time.time() - t0))
    return {"spans": len(rows), "steps": steps, "edges": len(edges),
            "mean_placed": round(placed_total / max(len(paras), 1), 2)}


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
    out = educate(open_store(), args.collection, raw)
    print("")
    print("mean %s vertices per paragraph — concept-sized, not characters" % out["mean_placed"])
    print("node-repair.py after this — it writes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
