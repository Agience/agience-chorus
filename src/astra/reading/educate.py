"""Educate the fresh collection — read the book, then demand meaning for what it learned.

The order is the point and it is not reversible:

    1. the reading forms units from characters      (the book, and nothing else, decides what exists)
    2. each unit demands a sense from the substrate (a tekton, on demand, one lookup per unit)
    3. what resolves gains an is-a coordinate; what misses keeps only the book's co-presence

Every unit is asked, and the misses are left as misses. There is no filter deciding which tokens "look
like words" — the reading has already decided what a unit is. A space, a fragment, or a proper name
simply fails to resolve, and the failure is data: it separates what English could tell us from what
only this book can.

Run (the host must be imported first — it binds the seams):

    python -m astra.reading.educate --text <corpus-dir>/pride.txt --limit 20000
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

from astra.reading import tekton_lexicon

TOKEN_CT = "application/x-token"


def main() -> int:
    ap = argparse.ArgumentParser()
    # No box-specific default: the store is named by $MANTLE_SQLITE or on the command line,
    # and argparse refuses the run when neither says.
    ap.add_argument("--sqlite", default=os.getenv("MANTLE_SQLITE"),
                    required=not os.getenv("MANTLE_SQLITE"),
                    help="the lattice.db to read/write; defaults to $MANTLE_SQLITE")
    ap.add_argument("--collection", default="read:pride-and-prejudice")
    args = ap.parse_args()

    # The write side is the mantle store; the read side stays a read-only connection because it
    # reads the substrate (`wn-*`), which this module must never modify.
    from mantle.shard.local_store import open_store
    store = open_store()
    ro = sqlite3.connect("file:%s?mode=ro" % args.sqlite, uri=True)

    rows = ro.execute(
        "SELECT doc FROM vertex WHERE id LIKE ? AND ct = ?",
        (args.collection + ":%", TOKEN_CT)).fetchall()
    if not rows:
        print("no token artifacts in %s — read the book first (astra.reading.organon_reader)"
              % args.collection)
        return 2

    surfaces = []
    for (doc,) in rows:
        try:
            surfaces.append(json.loads(doc).get("name") or "")
        except Exception:
            continue
    surfaces = [s for s in surfaces if s]

    print("the reading produced %d unit(s); every one of them is asked." % len(surfaces))
    out = tekton_lexicon.fetch(ro, store, args.collection, surfaces)

    print("")
    print("  demanded              %6d   units the reading formed" % out["demanded"])
    print("  resolved              %6d   found a sense in the substrate" % out["resolved"])
    print("  missed                %6d   no dictionary meaning — the book is their only source"
          % out["missed"])
    print("  senses (direct)       %6d" % out["senses_direct"])
    print("  senses (+ancestors)   %6d   the is-a chain walked to the root" % out["senses_with_ancestors"])
    print("  is-a edges written    %6d   <- the coordinate the reading could not produce"
          % out["isa_edges"])
    print("  entry edges written   %6d   surface -> sense" % out["entry_edges"])

    # The on-demand claim, measured: a tekton that quietly pulled the whole lexicon would look
    # identical from the inside, so the fraction of the substrate left untouched is reported here.
    # A bounded probe (rather than a full count of every synset in the store) is enough to support
    # "this pulled a small fraction" without dereferencing the largest content type on every run.
    _probe = ro.execute("SELECT id FROM vertex WHERE id LIKE 'wn-%' LIMIT 200001").fetchall()
    total = len(_probe)
    _capped = total > 200000
    took = out["senses_with_ancestors"]
    print("")
    print("  the substrate holds %s%d synsets; this pulled %d (%.2f%% or less). %d+ never touched."
          % ("at least " if _capped else "", total, took,
             100.0 * took / max(total, 1), total - took))
    print("  a sample of what only the book can explain: %s" % (out["misses"][:12],))
    return 0


if __name__ == "__main__":
    sys.exit(main())
