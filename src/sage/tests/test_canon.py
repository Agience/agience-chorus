"""The canon knowledge base: ingest the design docs as cited knowledge artifacts, then retrieve a
chunk with its carried citation — and refuse to invent one when nothing matches.

Both halves reuse sage's real machinery, proven end-to-end here:

  ingest     — `op.canon.condense` (the TEKTON) chunks markdown by heading and lands the chunks as
               ordinary `text/markdown` artifacts into a real indexed lattice store (the same store
               `op.retrieve` searches). Provenance (source path + stable citation id + CC-BY marker)
               rides in the artifact doc and round-trips through `get_artifact` unchanged.
  retrieve   — `canon.retrieve_cited` runs the same `content_search.search` BM25 the reach uses, and
               returns each hit with the citation resolved from the artifact's own provenance, in the
               `[{id,title,content,score,citation}]` shape an ember cites from.
  honest null— an absent-token query and an empty query both return [] — no hit, so no fabricated
               citation. (WordNet recall is stubbed to [] so the match is pure BM25 over our fixture,
               exactly as `test_reach_provider_store` does — no dependence on an ambient corpus.)

Carrier note: serving this as a cross-persona `op.knowledge.cite` reach rides the same gated carrier
`reach_provider` waits on; here the capability is proven in-process (handler called directly).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare imports

import canon  # noqa: E402  (sage-local)

import ember.ontology.match as _ember_match  # noqa: E402  (stubbed → pure-BM25, WordNet-free)
from mantle.shard.local_store import LocalStore  # noqa: E402
from mantle.db import open_lattice as _open_lattice  # noqa: E402


# ── a tiny, self-contained canon: real heading shapes (intro, numbered §, lettered §3a) ──────────
_DOC1 = """# Widget design — the architecture

Intro prose introducing widgets at a high level.

## 0. The layering

The layering paragraph, top to bottom, names stratacake as its keystone.

## 3. The crystal

The crystal is the gauge helper. Its distinctive token is transistorium.

### 3a. The transistor detail

The transistor reads the settled screen. Unique marker: flibberwocket.
"""

_DOC2 = """# Screen notes

## 2. Coupling

Coupling is derived at the membrane, keyed by the word entangulate.
"""


def _canon_dir(tmp_path):
    d = tmp_path / "pharos"
    (d / "genesis").mkdir(parents=True)
    (d / "genesis" / "WIDGET-DESIGN.md").write_text(_DOC1, encoding="utf-8")
    (d / "genesis" / "SCREEN-NOTES.md").write_text(_DOC2, encoding="utf-8")
    return d


def _ingested_store(tmp_path):
    """Ingest the fixture canon into a REAL indexed lattice store, wrapped as the ember bundle the
    retrieval tekton reads (content=None → inline resolution, like `test_reach_provider_store`)."""
    d = _canon_dir(tmp_path)
    L = _open_lattice(str(tmp_path / "canon.db"), origin="test-node")
    L.artifacts.ensure_schema()
    # Ingest goes through the tekton, not a bare function call: `_ingest` is private, reachable only
    # via `op.canon.condense`. The test drives what production drives — a need to the tekton handler.
    summary = canon.canon_condense_handler(L, str(d))({})
    corpus = LocalStore(artifacts=L.artifacts, graph=getattr(L, "graph", None), content=None)
    return corpus, summary


# ── ingest: chunks land as artifacts carrying provenance + a stable citation + CC-BY ─────────────
def test_ingest_lands_chunks_with_provenance_and_citation(tmp_path):
    corpus, summary = _ingested_store(tmp_path)

    # 6 chunks: DOC1 {intro, §0, §3, §3a} + DOC2 {intro (title stub), §2} — every doc's preamble
    # (H1 + any intro prose) is itself a citable chunk.
    assert summary["artifacts"] == 6
    assert summary["sources"] == 2
    assert summary["license"] == "CC-BY-4.0"

    # the §3a chunk is addressable by its stable citation id, and its provenance is fully carried.
    art = corpus.artifacts.get_artifact("canon:WIDGET-DESIGN#3a")
    assert art is not None, "the citation id must be the artifact id (addressed by name)"
    assert art["content_type"] == "text/markdown"
    assert art["source_path"] == "pharos/genesis/WIDGET-DESIGN.md"
    assert art["license"] == "CC-BY-4.0"
    cit = art["citation"]
    assert cit["cite_id"] == "canon:WIDGET-DESIGN#3a"
    assert cit["section"] == "3a"
    assert cit["ref"] == "WIDGET-DESIGN §3a"            # ready-to-print human ref
    assert cit["license"] == "CC-BY-4.0"
    assert cit["source"] == "pharos/genesis/WIDGET-DESIGN.md"

    # every canon artifact is marked CC-BY content (two-tier policy) and knows its source.
    ids = {"canon:WIDGET-DESIGN#intro", "canon:WIDGET-DESIGN#0", "canon:WIDGET-DESIGN#3",
           "canon:WIDGET-DESIGN#3a", "canon:SCREEN-NOTES#2"}
    for aid in ids:
        a = corpus.artifacts.get_artifact(aid)
        assert a is not None and a["license"] == "CC-BY-4.0" and a["knowledge"] == "canon"


# ── retrieve: the right chunk comes back with its citation ────────────────────────────────────────
def test_retrieve_returns_the_right_chunk_and_its_citation(tmp_path, monkeypatch):
    monkeypatch.setattr(_ember_match, "wn_synsets_for", lambda w: [])   # pure BM25, WordNet-free
    corpus, _ = _ingested_store(tmp_path)

    hits = canon.retrieve_cited(corpus, "flibberwocket")
    assert hits, "BM25 found no chunk for a token that occurs in exactly one section"
    top = hits[0]
    assert top["id"] == "canon:WIDGET-DESIGN#3a"                        # the section that holds it
    assert "flibberwocket" in top["content"]                           # real resolved text, not a stub
    assert set(top) == {"id", "title", "content", "score", "citation"}  # the cited-evidence contract
    assert top["citation"]["ref"] == "WIDGET-DESIGN §3a"           # an ember can print "per <ref>"
    assert top["citation"]["license"] == "CC-BY-4.0"

    # query-dependent: a term unique to a DIFFERENT doc cites that doc, not this one.
    other = canon.retrieve_cited(corpus, "entangulate")
    assert other and other[0]["id"] == "canon:SCREEN-NOTES#2"
    assert other[0]["citation"]["ref"] == "SCREEN-NOTES §2"

    # the in-process capability handler yields the same cited evidence (the reach seam, called direct).
    handled = canon.cited_retrieve_handler(corpus)({"query": "flibberwocket"})
    assert handled == hits


# ── honest null: no match → [] → no fabricated citation ──────────────────────────────────────────
def test_no_match_yields_no_citation(tmp_path, monkeypatch):
    monkeypatch.setattr(_ember_match, "wn_synsets_for", lambda w: [])
    corpus, _ = _ingested_store(tmp_path)

    assert canon.retrieve_cited(corpus, "quibnorptzz") == []            # absent token → nothing cited
    assert canon.retrieve_cited(corpus, "   ") == []                    # empty query → honest null
    assert canon.cited_retrieve_handler(corpus)({"query": ""}) == []    # handler is fail-soft too


# ── smoke: the real aria/pharos canon ingests as CC-BY cited artifacts (skip if absent) ──────────
def test_real_pharos_canon_ingests_with_citations(tmp_path):
    """Searches every known home for the real pharos canon, newest first, the same way
    `agience-cloud/deploy/doc_paths_check.py` resolves it, and skips only when none exists.

    A skip that fires because the canon's location moved is indistinguishable from a skip on a
    genuinely canon-less checkout, and both silently stop this smoke test from running. The
    candidate list is append-only — entries are added as new canon locations appear, never
    removed — so a rename never leaves a location silently unchecked."""
    import pytest
    here = Path(__file__).resolve()
    candidates = [
        here.parents[4] / "agience-pharos" / "genesis",   # <workspace>/agience-pharos/genesis
        here.parents[4] / "_pharos" / "genesis",          # workspace root, alternate name
        here.parents[2] / "aria" / "pharos" / "genesis",  # chorus-internal
    ]
    root = next((c for c in candidates if c.exists()), None)
    if root is None:
        pytest.skip("no pharos genesis canon in this checkout (looked in: %s)"
                    % ", ".join(str(c) for c in candidates))

    arts = canon.canon_artifacts(str(root))
    assert arts, "the real canon produced no knowledge artifacts"
    assert all(a["license"] == "CC-BY-4.0" for a in arts)              # content stays CC-BY
    assert all(a["citation"]["cite_id"].startswith("canon:") for a in arts)
    # the flagship design doc is present and every chunk names its source path.
    stems = {a["citation"]["source"].split("/")[-1] for a in arts}
    assert "CRYSTALS-GAUGES-AND-THE-MEMBRANE.md" in stems
    assert all(a["source_path"].endswith(".md") for a in arts)
