"""The offer generator projects, never composes — the information decides what renders.

There is no `context_schema.required` gate: an artifact that resolves any template field has an
offer; one that resolves none has nothing to advertise. A template field's derivation from the data
is declared by the type (`field_source`, a dotted path), not computed here — that declaration is
the type's colimit, not a rule baked into this reader.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


# 2026-08-26: was loaded by path with no `sys.modules` registration — every import built a
# second module object. `offer.py` still has no dependency on the `ember` package (whose
# __init__ pulls the whole boot chain), which is why it is loaded from the persona rather than
# imported: `_persona.load` reaches the file directly and registers it once as `sage.offer`.
from agience_chorus import _persona  # noqa: E402

O = _persona.load("offer", __file__)

MARKDOWN = {
    "declares": "text/markdown",
    "offer_template": "{title}: {summary}",
    "context_schema": {"properties": {"title": {"type": "string"},
                                      "summary": {"type": "string"}}},
}
# The real wn shape: rows carry `lemmas` (a list), and the type declares how the template's
# `lemma`/`alt` fields derive from it via `field_source`.
WORDNET = {
    "declares": "text/x-wordnet",
    "offer_template": "the definition and meaning of the word {lemma} (also: {alt}): {gloss}",
    "field_source": {"lemma": "lemmas.0", "alt": "lemmas.1:"},
    "for-ai": [{"instruction": "What is this content type, and what does describing it mean?",
                "input": "", "output": "A WordNet synset: ONE sense of one or more words."}],
    "field_guidance": {"gloss": [{"instruction": "How do I obtain a valid value for this field?",
                                  "input": "", "output": "Read the CAS blob at doc.content_ref."}]},
}


def _md(**kw):
    return dict({"id": "x", "content_type": "text/markdown"}, **kw)


def _wn(**kw):
    return dict({"id": "wn-x", "content_type": "text/x-wordnet"}, **kw)


# ── projection, not composition ─────────────────────────────────────────────────
def test_renders_from_fields_the_artifact_carries():
    assert O.offer(MARKDOWN, _md(title="Hercule Poirot", summary="a detective")) \
        == "Hercule Poirot: a detective"


# ── the declared derivation: field_source resolves a path, not a flat key ────────
def test_field_source_resolves_the_declared_path():
    """The row carries `lemmas`, the template says `{lemma}`, and the type declares
    `lemma <- lemmas.0`. The reader follows the declared hop instead of a hardcoded flat key."""
    out = O.offer(WORDNET, _wn(lemmas=["dog"], gloss="a canine", pos="n"))
    assert out == "the definition and meaning of the word dog: a canine"
    assert "also" not in out and "()" not in out          # empty `alt` slice drops its clause


def test_field_source_slice_populates_the_alt_clause():
    out = O.offer(WORDNET, _wn(lemmas=["dog", "canis familiaris", "domestic dog"],
                               gloss="a canine", pos="n"))
    assert out == ("the definition and meaning of the word dog "
                   "(also: canis familiaris, domestic dog): a canine")


def test_resolve_path_reads_index_and_slice_and_nested_keys():
    a = {"lemmas": ["x", "y", "z"], "context": {"name": "n"}}
    assert O._resolve_path(a, "lemmas.0") == "x"
    assert O._resolve_path(a, "lemmas.1:") == ["y", "z"]
    assert O._resolve_path(a, "context.name") == "n"
    assert O._resolve_path(a, "lemmas.9") is None          # out of range -> honest None
    assert O._resolve_path(a, "missing.deep") is None


# ── the information decides: partial info -> partial offer, not a refusal ───────
def test_partial_information_still_produces_an_offer():
    """The presence of any resolvable field means there is something to advertise — a wn row with
    a lemma but no gloss still renders, rather than losing a usable offer built from real
    information."""
    out = O.offer(WORDNET, _wn(lemmas=["dog"]))          # no gloss, no pos, no alt
    assert out == "the definition and meaning of the word dog"
    assert out and "{" not in out


def test_optional_fields_are_omitted_not_blanked():
    """`"{title}: {summary}"` with no summary must not render `"Hercule Poirot: "` — a dangling
    separator asserts an empty value where there is simply none."""
    out = O.offer(MARKDOWN, _md(title="Hercule Poirot"))
    assert out == "Hercule Poirot"
    assert not out.endswith(":") and not out.endswith(": ")


def test_a_later_field_alone_still_renders():
    """Only `summary` present (no title): the information still decides there is an offer."""
    out = O.offer(MARKDOWN, _md(summary="a detective"))
    assert "a detective" in out and "{" not in out


# ── refusal only when nothing renders, or there is no template ──────────────────
def test_refuses_when_no_template_field_resolves():
    """A text/markdown row with neither title nor summary advertises nothing of this type — a
    finding (a format wearing a type it is not), reported rather than counted as zero. The absence
    is the data's, not a hardcoded contract's."""
    out, err = O.offer_or_none(MARKDOWN, {"id": "mem-b9a46f05", "content_type": "text/markdown"})
    assert out is None
    assert isinstance(err, O.OfferRefused)
    assert set(err.missing) == {"title", "summary"}       # all template fields, since none resolved


def test_empty_string_list_dict_are_ABSENT_not_values():
    """`title: ""` has no title. With no other field either, the render is empty — no offer."""
    for empty in ("", [], {}):
        out, err = O.offer_or_none(MARKDOWN, _md(title=empty))
        assert out is None and isinstance(err, O.OfferRefused)


def test_missing_template_refuses_structurally():
    """A type with no template genuinely cannot be described. This is a structural gap (the type
    is incomplete), not the information deciding."""
    with pytest.raises(O.OfferRefused) as e:
        O.offer({"declares": "x/y"}, {"id": "a", "anything": "here"})
    assert e.value.missing == ["<offer_template>"]


def test_offer_or_none_returns_the_refusal_rather_than_swallowing_it():
    """A bulk pass must record every case that cannot be described. Discarding it silently converts
    'cannot describe' into 'no offer' — the same lie in a different shape."""
    out, err = O.offer_or_none(MARKDOWN, {"id": "m", "content_type": "text/markdown"})
    assert out is None and isinstance(err, O.OfferRefused)
    out, err = O.offer_or_none(MARKDOWN, _md(title="ok"))
    assert out == "ok" and err is None


# ── `for-ai` is surfaced, never interpreted ─────────────────────────────────────
def test_guidance_is_surfaced_not_executed():
    root = O.guidance(WORDNET)
    assert root and set(root[0]) == {"instruction", "input", "output"}
    assert "synset" in root[0]["output"]
    fld = O.guidance(WORDNET, "gloss")
    assert fld and "content_ref" in fld[0]["output"]
    assert O.guidance(WORDNET, "nonexistent") == []
    assert O.guidance(MARKDOWN) == []          # absent, not empty-shaped


def test_template_fields_are_the_only_syntax():
    """No expressions, no conditionals, no nesting — a template language is a program, and a
    program in a data field is a place for arbitrary logic to hide. (`field_source` paths are a
    separate, declared map — not template syntax.)"""
    assert O.template_fields("{a} and {b}: {c}") == ["a", "b", "c"]
    assert O.template_fields("{ not a field }") == []
    assert O.template_fields("{a.b}") == []


# ── format is not type ───────────────────────────────────────────────────────────
def test_data_type_is_explicit_never_guessed():
    assert O.data_type({"content_type": "text/markdown"}) is None
    assert O.data_type({"content_type": "text/markdown", "data_type": ""}) is None
    assert O.data_type({"data_type": "wiki-article"}) == "wiki-article"


def test_describer_key_prefers_data_type_over_format():
    assert O.describer_key({"content_type": "text/markdown"}) == "text/markdown"
    assert O.describer_key({"content_type": "text/markdown",
                            "data_type": "wiki-article"}) == "wiki-article"


def test_refusal_reports_the_resolved_type_not_the_format():
    """When nothing renders for a row, the report names the resolved data type if there is one, so
    the finding blames the type level, not the format."""
    out, err = O.offer_or_none(MARKDOWN, {"id": "x", "content_type": "text/markdown",
                                          "data_type": "changelog"})
    assert out is None and err.content_type == "changelog"
