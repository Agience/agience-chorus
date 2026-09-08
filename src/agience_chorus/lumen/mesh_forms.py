"""The surface-form mesh — which surface forms have been observed realizing which senses.

A surface form is language evidence, and the language-concept binding belongs with lumen's lexicon
layer (ember keeps the measurement primitives; the lexical observations recorded here do not).

What is measured, and from what: nothing is fetched and nothing is invented. A sense already
carries its own text — its gloss and its examples — and that text is the corpus showing its words
in use. For each sense, the surface forms appearing in its own text are forms observed realizing it:

    dog     gloss/examples contain "dog", "dogs"   -> both observed for that sense
    i       gloss "the 9th letter of the Roman alphabet"; no example contains "is"
            -> "is" has never been observed realizing the letter, and the reading earns nothing

This is evidence, not a rule. A stop-list would say "ignore `is`"; the mesh instead records
something checkable: whether the corpus has ever shown that word meaning that sense. If a corpus
arrives where it has, the mesh records it and the reading counts.

The mesh is built during consolidation, not read at query time: it needs the whole level present —
a form observed nowhere yet is not the same as a form checked and found absent — and it must not
run against a corpus still being written, for the same reason compression must not
(`CURRICULUM-DATA-PLAN.md` §4).

Coverage is bounded by the source text: WordNet gives at most three examples per synset, so the
evidence recorded here is sparse. The relation that says "this word, in this context, means this
sense" is associative, which the IS-A tree does not express; ConceptNet supplies that relation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Set, Tuple

# The ontology tokeniser has one home (`crystal.ontology.lookup`). `minimum=1` below keeps this
# file's own policy: a surface form harvested from a gloss may be a single letter, where a query
# token may not. The alphabet is shared; the length is this caller's.
from crystal.ontology.lookup import lemma_tokens as _lemma_tokens

# The mesh is stored as one artifact so it replicates like everything else, and a node that has
# never consolidated is distinguishable from one whose mesh is empty (absent vs {}).
MESH_ID = "mesh.surface-forms"
MESH_CONTENT_TYPE = "application/vnd.agience.form-mesh+json"


def _forms_in(text: str) -> Set[str]:
    return set(_lemma_tokens(text or "", minimum=1))


def observed_forms(doc: Dict[str, Any]) -> Set[str]:
    """The surface forms this sense's own text shows in use — its gloss and examples.

    Its lemmas count too: a lemma is the form the source itself recorded for this sense, which is
    the strongest observation available. The corpus is not asked to prove what it already asserts."""
    seen: Set[str] = set()
    for lm in (doc.get("lemmas") or []):
        seen.add(str(lm).lower())
    seen |= _forms_in(str(doc.get("gloss") or ""))
    for ex in (doc.get("examples") or []):
        seen |= _forms_in(str(ex))
    return seen


def build(store, *, content_type: str = "text/x-wordnet",
          limit: Optional[int] = None) -> Dict[str, Any]:
    """Consolidation-phase build. Walks the level and records, per lemma, which surface forms its
    own senses were observed using. Returns the summary; writes the mesh as an artifact.

    Keyed on the lemma, not the synset: morphology asks "can this surface form be this word", which
    is a property of the word. Keying per sense would need far more text than a lexicon holds and
    would report absence as evidence."""
    from mantle import lattice_mint as g
    forms: Dict[str, Set[str]] = {}
    n = 0
    for doc in store.artifacts.list_artifacts(content_type=content_type):
        n += 1
        if limit is not None and n > limit:
            break
        seen = observed_forms(doc)
        for lm in (doc.get("lemmas") or []):
            forms.setdefault(str(lm).lower(), set()).update(seen)
    payload = {k: sorted(v) for k, v in forms.items()}
    store.artifacts.put_artifact({
        "id": MESH_ID,
        "content_type": MESH_CONTENT_TYPE,
        "state": "committed",
        "title": "surface-form mesh",
        "gloss": "which surface forms each lemma's own senses were observed using",
        "content": "",
        "lemmas": sorted(payload.keys())[:1],     # keyed lookup is by id, not by lemma
        "mesh": payload,
        "collection_id": "stage.0.lexicon",
        "provenance": g.P_OBSERVED,
        "via": "op.consolidate.mesh",
        "created_by": g._author_ref(store, "connect@agience.ai"),
        "created_time": g._now(),
    })
    return {"lemmas": len(payload), "senses_read": n,
            "forms": sum(len(v) for v in payload.values())}


_CACHE: Dict[int, Dict[str, Set[str]]] = {}


def load(store) -> Optional[Dict[str, Set[str]]]:
    """The mesh, or None when this node has never consolidated.

    None and {} are different and stay different: None means "no evidence has been gathered",
    which is not a reason to refuse a reading; {} means "gathered, and nothing was observed",
    which is."""
    key = id(store)
    if key in _CACHE:
        return _CACHE[key]
    try:
        doc = store.artifacts.get_artifact(MESH_ID)
    except Exception:
        doc = None
    if not doc or not isinstance(doc.get("mesh"), dict):
        _CACHE[key] = None
        return None
    out = {k: set(v or ()) for k, v in doc["mesh"].items()}
    _CACHE[key] = out
    return out


def supports(store, surface: str, lemma: str) -> Optional[bool]:
    """Has `surface` ever been observed realizing `lemma`?

    Returns True, False, or None. The None is load-bearing: a node with no mesh does not behave
    as though every reading were unsupported. Absence of evidence is reported as absence, never
    as evidence of absence."""
    mesh = load(store)
    if mesh is None:
        return None
    seen = mesh.get(str(lemma).lower())
    if seen is None:
        return None                              # this lemma was never read
    return str(surface).lower() in seen


def invalidate(store=None) -> None:
    if store is None:
        _CACHE.clear()
    else:
        _CACHE.pop(id(store), None)


__all__ = ["MESH_ID", "MESH_CONTENT_TYPE", "observed_forms", "build", "load", "supports",
           "invalidate"]
