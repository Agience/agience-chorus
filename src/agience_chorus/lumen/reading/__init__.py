"""Lumen's reasoning leg: what a question reaches, and what the operator can say.

    query_neighbourhood.py    opens a neighbourhood around a query and couples against it — the read
                         that answers, bounded by the question rather than by the store
    operator_predict.py  fits the ordered-stream operator and rolls it within its own measured
                         horizon (CLI)
    operator_respond.py  builds a responder over that same operator and exports it; serves nothing
    heldout.py           next-unit prediction on text never read, against uniform / unigram /
                         n-gram baselines — a measurement nobody can re-run is an anecdote, so this
                         lives here, tracked

The three personas hand off over the store and the plane, never by import:

    astra   reads the text           ->  writes a collection to the lattice
    lumen   reaches that collection  ->  the neighbourhood couples, and reasons
    aria    receives the responder   ->  placed by the host (personas.py::_wire_conversation_carrier)

`operator_respond.py` stays in lumen. It fits a Koopman operator over the text, which is reasoning,
and merely hands the result out; putting it in aria would move model-fitting into the response
persona and invert the split. What aria owns is the surface the reply is emitted on
(`aria/web_bff.py`); placing the responder is the host's act.

Module names avoid generic terms that collide elsewhere in the codebase: `neighbourhood.py` is named
`query_neighbourhood.py` because `entroptics/neighbourhood.py` is the instrument's own front door;
`operator.py` is named `operator_predict.py` because of `mantle/services/operator.py` and the stdlib
`operator` module; `serve_aria.py` is named `operator_respond.py` because it builds a responder over
the operator rather than serving anything itself. All three live inside packages, so imports resolve
by dotted path and a duplicate basename does not shadow across packages — see
[[pytest-module-shadowing-silent-substitution]] for why that distinction matters under pytest's
rootdir-relative module naming.
"""
