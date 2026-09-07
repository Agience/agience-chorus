"""Reading — astra's ingest leg: text arrives, and the ontology gains what it could not absorb.

Reading belongs to astra, the intake persona, rather than to lumen's reasoning: reading is where a
signal's residual is high — something arrived that the ontology does not hold — and that residual
precipitating is the ingest act.

    organon_reader.py   the streaming reader — characters in, conservation exact per token
    overlap.py          paragraphs -> shared spans -> concept decomposition
    tekton_lexicon.py   on-demand sense fetch, one lookup per unit the reading formed
    educate.py          driver: read the book, then demand meaning for every unit it formed

The handoff is the store, never an import. astra writes a collection to the lattice; lumen reaches
that collection to reason over it. A persona that imports a sibling cannot be deployed on its own —
`src/tests/test_persona_isolation.py` is the guard.

`organon_reader.py` is named for what it does rather than for the concept it instantiates: naming a
module after "organon" tells a reader nothing about the file, and would collide with names the
instrument itself already owns.
"""
