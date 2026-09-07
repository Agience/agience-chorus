"""The output screen reads the answer, not the field the propagation placed.

`conversation.respond` hands `activation.output_membrane` the concepts the answer cites
(`compose`'s own citation list), not `acts_for_compose` — the seed's whole resonant field, which
at corpus scale can be tens of thousands of concepts. `output_membrane` reads the concepts the
answer names back through the same instrument: it measures whether the concepts about to be said
are one coherent, resolved thing, which only requires the cited subset, not the full field.

The full field is not truncated by this: it still rides out whole on `activations`. Only which
set reaches the output screen is narrowed, and that set is measured — it is what `compose`
cited — not chosen by a size limit.

Every other conversation test runs on a store with a handful of concepts, where the placed field
and the answer's concepts are nearly the same list, so the tests below state the corpus-scale
field size explicitly rather than relying on a fixture to exercise the distinction.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import conversation as C            # noqa: E402
from ember.ontology import activation as A       # noqa: E402


class _Store:
    """Enough store for `respond`'s tail. Nothing is written."""
    class _Arts:
        def get_artifact(self, aid):
            return {"id": aid, "content": "a gloss", "cited_from": "cite.wordnet"}

        def put_artifact(self, *a, **k):
            return None
    artifacts = _Arts()


class _Delegate:
    id = "d.test"
    person = "test@local"
    host = "h"
    origin = "o"
    store = _Store()

    def load_obs(self):
        return None

    def obs_matching(self, **k):
        return []

    def remember_obs(self, doc):
        return None
    obs = []

    class _L:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False
    _obs_lock = _L()


def _run_respond(monkeypatch, *, placed, cited):
    """Drive `respond` with a placed field of `placed` concepts and an answer citing `cited`.

    Everything the corpus would supply is stubbed, so what this measures is the plumbing decision:
    which set reaches `output_membrane`.
    """
    seen = {}
    acts = [{"concept": "c%d.n.01" % i, "salience": 1.0 / (i + 1), "activation": 1.0 / (i + 1)}
            for i in range(placed)]

    monkeypatch.setattr(C, "_answer_by_offers", lambda d, t: None)
    monkeypatch.setattr(C, "_triple", lambda t: {"relation": None, "subject": None, "object": None,
                                                 "leading": False, "topic": None,
                                                 "has_relation": False})
    monkeypatch.setattr(C, "_quantitative", lambda t: None)
    monkeypatch.setattr(C, "_record_private", lambda *a, **k: None)
    # Associative spreading runs through `activation._discharge`, which bounds each vertex's reach
    # by the charge it actually holds rather than allowing every vertex the same jump — this keeps
    # the fired field bounded on the live answer path.
    #
    # The invariant these tests pin: the output screen reads what the answer cited, never the
    # whole fired field.
    monkeypatch.setattr(A, "recognize", lambda *a, **k: list(acts))
    monkeypatch.setattr(A, "vertex_field", lambda *a, **k: [])
    monkeypatch.setattr(A, "_tokens", lambda t: t.split())
    monkeypatch.setattr(A, "_word", lambda n: str(n).split(".")[0])
    # the answer cites a subset — this is what "the concepts the answer names" means
    monkeypatch.setattr(A, "compose", lambda *a, **k: ("an answer", list(cited)))

    def _membrane(store, given):
        seen["names"] = [g.get("concept") for g in given]
        return {"read": True, "rows": len(given)}
    monkeypatch.setattr(A, "output_membrane", _membrane)

    out = C.respond(_Delegate(), "what is a c0")
    return out, seen


def test_the_output_screen_is_handed_the_ANSWER_not_the_placed_field(monkeypatch):
    """At corpus scale the placed field can be tens of thousands of concepts while the answer names
    only a handful. If the screen were handed the field instead of the answer's own concepts, it
    would build a frame sized to the whole field rather than the cited subset. The assertion is on
    the set the screen receives, not on a size limit."""
    cited = ["wn-c1.n.01", "wn-c3.n.01"]
    out, seen = _run_respond(monkeypatch, placed=5000, cited=cited)

    assert seen["names"] == ["c1.n.01", "c3.n.01"], (
        "the output screen was handed %d concepts; it must be handed the answer's own"
        % len(seen["names"]))


def test_the_placed_field_is_NOT_truncated_by_this(monkeypatch):
    """The control that separates narrowing what the output screen reads from narrowing what the
    turn measured: the whole placed field still rides out on `activations`, so conservation holds
    and a later reader still sees everything the propagation reached."""
    out, seen = _run_respond(monkeypatch, placed=5000, cited=["wn-c1.n.01"])
    assert len(out["activations"]) == 5000, (
        "the placed field was truncated to %d — this was supposed to change which set is READ, "
        "not destroy the measurement" % len(out["activations"]))
    assert len(seen["names"]) == 1


def test_a_citation_that_is_not_a_synset_id_does_not_become_a_concept(monkeypatch):
    """Citations carry artifact ids (`wn-dog.n.01`) and source anchors (`cite.wordnet`,
    `cite.genesis`). Only the ones naming a concept in the field may reach the screen — a source
    anchor is not a concept, and passing it would ask the instrument to read a row that does not
    exist."""
    out, seen = _run_respond(monkeypatch, placed=50,
                             cited=["wn-c2.n.01", "cite.wordnet", "cite.genesis"])
    assert seen["names"] == ["c2.n.01"]


def test_an_answer_that_cites_nothing_reads_an_empty_screen(monkeypatch):
    """The computed null stays cheap and never falls back to the whole field, even through an
    empty-set guard."""
    out, seen = _run_respond(monkeypatch, placed=5000, cited=[])
    assert seen["names"] == [], "an uncited answer fell back to reading the placed field"
