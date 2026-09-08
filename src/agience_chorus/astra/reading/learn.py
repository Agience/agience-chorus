r"""Learning materialises the junction the screen could not find — in realtime, per step.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['learn','read:colimit','Elizabeth']; \
        runpy.run_module('astra.reading.learn', run_name='__main__')"

The failure to cover is the signal. `reading_junction.cover` walks the screen absorbing what
each junction can take and re-placing the residual. When the walk ends with residual still on the
screen, the instrument has said something exact: no vertex in this ontology sits over what is
present. That is not an error and not an empty answer — it is the universal object being missing,
and the colimit's whole job is to make it exist.

There is no threshold here, and none is possible: "uncovered" is `next_by_coupling` returning
nothing above the float-noise floor — the instrument's own termination, derived from the dtype and the
arithmetic.

The triple is what gets written, and it is why the triple exists:

    context   the screen — the vertices that were present when this was learned
    content   the new vertex — the universal object over them
    operator  `op.colimit` — the act that formed it, so a later read can tell a junction the
              reading formed from one it was handed

`src --colimit--> dst` is `context --operator--> content` read the other way up: given the junction
and the act, the members are recoverable; given the members and the act, the junction is. Two of
three infer the third, which is the only reason one edge can carry all of it.

Realtime means the next step sees it: a vertex materialised at step `n` is in the ontology for step
`n+1`, so the reading's ability to cover a screen grows as it reads — which is what makes this
learning rather than logging. `Elizabeth` costs nine junctions once and one vertex thereafter.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

TOKEN_CT = "application/x-token"
#: one artifact per learning step — the same content type the reader writes for an
#: ordinary screen read, because a learning step is a screen read that formed something.
OBS_CT = "application/x-observation"
COLIMIT = "colimit"


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


def learn_step(store, ro, collection: str, signal: str) -> dict:
    """One step: place the signal, find the junction over it, and materialise one if none exists.

    Returns what happened and why — `{learned, vertex, members, hops, absorbed, why}`. `learned` is
    False when a junction already covered the screen, which is recognition rather than a no-op."""
    import agience_chorus.reading_junction as _j

    cov = _j.cover(ro, collection, signal)
    placed = cov.get("placed") or []
    if not placed:
        return {"learned": False, "vertex": None, "members": [], "hops": 0,
                "why": cov.get("refusal") or "nothing of this signal could be placed"}

    # A screen of one vertex is its own universal object: once placement finds the longest vertex
    # rather than walking a prefix chain, a signal the ontology already holds places as exactly one
    # thing, and there is nothing above one vertex to look for. Re-forming a single recognised
    # vertex on every feed and calling it learning would be the [[verification-that-cannot-fail]]
    # shape wearing a write — an act that always "succeeds" has measured nothing.
    if len(placed) == 1:
        from agience_chorus.astra.reading.organon_reader import _unit_id as _uid
        return {"learned": False, "vertex": _uid(collection, placed[0]),
                "members": placed, "hops": 1, "absorbed": 1.0,
                "why": "the signal placed as a single vertex the ontology already holds — "
                       "recognised, and one vertex needs no junction above it"}

    # A screen already covered by one junction has its universal object; nothing to form.
    if not cov.get("refusal") and cov.get("hops") == 1:
        return {"learned": False, "vertex": cov["junctions"][0]["id"],
                "members": placed, "hops": 1,
                "absorbed": cov.get("screen_absorbed"),
                "why": "a junction already sits over this screen — recognised, not learned"}

    # The universal object is missing, so it is made. Its members are the vertices that were on
    # the screen: they are what it must explain, and they are exactly what the colimit is taken over.
    from agience_chorus.astra.reading.organon_reader import _unit_id
    vid = _unit_id(collection, signal)
    doc = {
        "id": vid, "content_type": TOKEN_CT, "name": signal, "content": signal,
        "collection_id": collection, "collections": [collection],
        "created_by": "ember-source",
        # The triple, on the artifact as well as on the edges: what was present, what was formed,
        # and the act that formed it.
        "context": collection, "operator": "op.colimit",
        "length": len(signal), "members": len(placed),
        "formed_over": placed,
        # How much of the screen the existing ontology could take before this was formed. A vertex
        # that was needed badly and one that was barely needed are different facts, and this is the
        # measurement that separates them.
        "screen_absorbed_before": cov.get("screen_absorbed"),
        "hops_before": cov.get("hops"),
    }
    # Nothing is written until everything is built: writing the vertex before its edges are
    # constructed would risk a failure in between leaving the vertex written with no members and no
    # context, which the next feed would then place as a recognised single vertex for a signal
    # nothing had actually learned. A half-written junction claims coverage it cannot provide, which
    # is worse than no junction.
    edges = [(vid, _unit_id(collection, m), COLIMIT,
              {"of": signal, "parts": len(placed), "operator": "op.colimit"})
             for m in placed]

    # A vertex with no context edge cannot be reached: `content` (the vertex) and `operator`
    # (`op.colimit`) alone are not enough, because `project` reaches through `observed` edges, and a
    # newly-formed vertex with none would exist, have parts, and sit nowhere retrieval can find it.
    #
    # The context is the step itself: the learning step is a thing that happened, so it is an
    # artifact, and everything that was on the screen at that moment hangs off it — including the
    # vertex the step formed. That is the same shape the reader already writes for an ordinary
    # observation: one artifact per screen read, an edge to each signal it held.
    #
    # The context is not derived as the intersection of the members' existing contexts (the places
    # they had all been present together), because members of a newly-formed junction generally have
    # never co-occurred anywhere — if they had, the junction would already exist, so that derivation
    # would be empty exactly when it is needed. The context is not something to infer: it is what
    # the screen was holding, which the step knows first-hand.
    step_id = "%s:step-%s" % (collection, abs(hash((collection, signal, tuple(placed)))))
    step_doc = ({
        "id": step_id, "content_type": OBS_CT, "name": step_id.split(":")[-1],
        "collection_id": collection, "collections": [collection],
        "created_by": "ember-source",
        "operator": "op.colimit", "content": signal, "signals": len(placed) + 1,
    })
    for m in placed:                      # everything that was on the screen
        edges.append((step_id, _unit_id(collection, m), "observed",
                      {"of": signal, "operator": "op.colimit", "role": "screen"}))
    edges.append((step_id, vid, "observed",
                  {"of": signal, "operator": "op.colimit", "role": "formed"}))

    # Built. Now write — artifacts first (an edge to a missing vertex is the dangling reference
    # `node-repair` exists to catch), then the edges in one call.
    store.artifacts.put_artifact(doc)
    store.artifacts.put_artifact(step_doc)
    # `add_edges` returns the number handled; a shortfall is data loss and is raised rather than
    # counted, because a junction missing half its members is not a smaller junction.
    handled = store.graph.add_edges(edges)
    if handled < len(edges):
        raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                           % (handled, len(edges)))
    return {"learned": True, "vertex": vid, "members": placed, "hops": cov.get("hops"),
            "absorbed": cov.get("screen_absorbed"),
            "why": "no junction sat over this screen, so the universal object over it was formed"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("signal", nargs="+")
    args = ap.parse_args()

    from mantle.shard.local_store import open_store
    store = open_store()
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    for sig in args.signal:
        out = learn_step(store, ro, args.collection, sig)
        # A held read snapshot does not see what was just written, so the connection is reopened
        # after a learn: without this, `place()` would keep decomposing against an ontology that no
        # longer reflects the write, and a reader that cannot see what it just learned is not
        # learning in realtime, it is logging.
        if out.get("learned"):
            ro.close()
            ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
        print("")
        print("SIGNAL %r" % sig)
        print("  %-9s %s" % ("LEARNED" if out["learned"] else "recognised", out["why"]))
        if out.get("members"):
            print("  members   %s" % (out["members"],))
        if out.get("hops") is not None:
            print("  screen    %s junction(s) covered %s of it before this step"
                  % (out["hops"], out.get("absorbed")))
        if out["learned"]:
            print("  vertex    %s" % out["vertex"])
    print("")
    print("node-repair.py after any run that LEARNED — this writes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
