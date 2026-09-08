"""lumen's transducer facet binding — the language↔concept conversion.

The conversion classes (`Transducer`/`LanguageTransducer`/`StubTransducer` + `get_transducer`) are
lumen's facet binding — `entry` (surface→concept), `render` (concept→surface), `lossless` (their
composition). The measurement read (`crystal.ontology.transducer.persisted_xi`) and the shared `_REG`
cache live in `crystal.ontology.transducer`; the classes read the shared concept lattice through
`crystal.ontology.driver`. Invariants (failure mode first):

  name   — a transducer's name is `spec.name`, else the artifact id with the op-id prefix stripped; a name
           that still carried `op.gauge.` would leak the wire id into the facet's identity.
  frame  — the (T,F) axes come off the spec, not invented.
  stub   — a StubTransducer (a surface not yet measurable) converts to nothing honestly — empty/None, and
           `lossless` False — never raising, never guessing a conversion it cannot make.
  absent — `get_transducer` for an undefined transducer is None, never a fabricated one.
"""
from __future__ import annotations

from prism.grounding import TRANSDUCER_OP
from agience_chorus.lumen import transducer as T


def test_name_strips_the_op_id_prefix():
    """The prefix is derived, not spelled out, because the invariant is "whatever the prefix is, it
    gets stripped": the test says nothing about the prefix's value, so reading it from the constant
    makes the test say exactly what it means, and a rename of the op-id prefix will not fail a test
    that does not test the rename. (Where the value itself is the point, it stays spelled out
    instead: a test that derives the value it is pinning would agree with any value, including a
    wrong one.)"""
    t = T.Transducer({"id": TRANSDUCER_OP + "language.en", "spec": {}})
    assert t.name == "language.en"
    assert TRANSDUCER_OP not in t.name, "the wire id leaked into the facet's identity"


def test_name_prefers_the_spec_name():
    t = T.Transducer({"id": TRANSDUCER_OP + "x", "spec": {"name": "language.fr"}})
    assert t.name == "language.fr"


def test_frame_reads_the_spec_axes():
    t = T.Transducer({"spec": {"frame_t": "surface-sequence", "frame_f": "ontology-coordinate"}})
    assert t.frame() == ("surface-sequence", "ontology-coordinate")


def test_stub_transducer_converts_to_nothing_honestly():
    s = T.StubTransducer({"spec": {"kind": "space"}})
    assert s.entry("anything") == []
    assert s.render("concept.n.01") is None
    assert s.lossless("anything") is False           # nothing recovers → honest False, never raises


def test_get_transducer_is_none_for_an_undefined_transducer():
    T._REG.pop("language.zz-absent", None)
    assert T.get_transducer("language.zz-absent") is None   # not defined → None, never a fabricated one
