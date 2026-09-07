"""The lexicon tekton — meaning fetched on demand for what the reading actually condensed.

Not an ingest: the collection starts empty and gains a sense only because a token the reading
condensed demanded one. What was never read is never fetched, and the report says how much of the
substrate was left untouched — "on demand" is a claim that has to be measurable, and a tekton that
quietly pulled the whole lexicon would look identical to one that pulled what it needed.

What it writes, and why each piece is there rather than convenient:

    <col>:tok:<surface>   --lex:en-->    <col>:wn-<synset>      the entry edge: this surface, that sense
    <col>:wn-<synset>     --hypernym-->  <col>:wn-<parent>      the is-a coordinate, walked to the root

Every sense of a demanded lemma is pulled, never just one: picking a single sense here
(`wn.synsets(word)[0]`) can silently return a different concept than the one actually meant, so
activation decides which sense the context lights instead — that is the whole reason the coordinate
exists.

The hypernym walk goes to the root, with no depth parameter: a truncated walk would hand back a
synset whose parent is missing, which reads exactly like a genuine root.

What gets no sense is the point, not a gap. `lemma:darcy` resolves to nothing in the substrate: a
proper name out of a novel has no dictionary meaning and must not be given one, since what "Darcy"
means is carried entirely by the book's own co-presence. The tekton reporting a miss there is it
working; a fallback that reached for something near would be false grounding on a fragment.
"""
from __future__ import annotations

import json
from typing import Dict, Iterable, List, Set, Tuple

#: the substrate's own vocabulary — read, never written by this module.
ENTRY_LABEL = "lex:en"
LEMMA_PREFIX = "lemma:"
ISA_LABEL = "hypernym"
SENSE_CT = "text/x-wordnet"


def _sense_id(collection: str, wn_id: str) -> str:
    return "%s:%s" % (collection, wn_id)


def _unit_id(collection: str, tok: str) -> str:
    """The organon's own unit id — imported, never re-derived.

    A second copy of an id rule is how two derivations agree on the day they are written and drift
    silently after: the codepoint form here is `"+".join("u%04x")`, and a rule that instead joined
    on `"-"` or included a literal `+` would agree on every alphanumeric unit and disagree on every
    space, comma, and newline — the highest-count units in a reading, so the drift would be
    invisible in a spot check and total in the graph."""
    from astra.reading.organon_reader import _unit_id as _real
    return _real(collection, tok)


def demand_senses(ro, surfaces: Iterable[str]) -> Tuple[Dict[str, List[str]], Set[str]]:
    """For each surface the reading condensed, the senses the substrate offers it.

    Returns `(surface -> [wn ids], the set of misses)`. One indexed lookup per demanded surface —
    the work is set by what was read, not by the size of the lexicon."""
    found: Dict[str, List[str]] = {}
    missed: Set[str] = set()
    for s in surfaces:
        key = LEMMA_PREFIX + s
        rows = ro.execute("SELECT dst FROM edge WHERE src = ? AND label = ?",
                          (key, ENTRY_LABEL)).fetchall()
        if rows:
            found[s] = [r[0] for r in rows]
        else:
            missed.add(s)
    return found, missed


def _walk_to_root(ro, seeds: Iterable[str]) -> Set[str]:
    """Every synset reachable upward from the seeds. Terminates on the visited set, so a substrate
    with a cycle costs one extra visit rather than hanging — the DAG is the source's, not ours."""
    seen: Set[str] = set()
    frontier = list(seeds)
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for (parent,) in ro.execute("SELECT dst FROM edge WHERE src = ? AND label = ?",
                                    (cur, ISA_LABEL)):
            if parent not in seen:
                frontier.append(parent)
    return seen


def fetch(ro, store, collection: str, surfaces: Iterable[str]) -> Dict[str, object]:
    """Pull the senses the reading demanded into `collection`, with their is-a coordinate.

    `ro` reads the substrate; `store` writes the fresh collection through mantle. Nothing in the
    substrate is modified — this is a read of the ground and a write of what was asked for."""
    surfaces = sorted(set(surfaces))
    found, missed = demand_senses(ro, surfaces)

    direct = {w for ids in found.values() for w in ids}
    closure = _walk_to_root(ro, direct)          # the senses + everything they are a kind of

    sense_rows, isa_rows, entry_rows = [], [], []
    for wn_id in sorted(closure):
        row = ro.execute("SELECT doc FROM vertex WHERE id = ?", (wn_id,)).fetchone()
        if row is None:
            continue                              # the substrate names a parent it does not hold
        doc = json.loads(row[0])
        aid = _sense_id(collection, wn_id)
        # The triple, on every artifact this writes: context is where it was pulled into and why,
        # content is the sense itself, operator is the act that produced it — so a later read can
        # tell a demanded sense from one the reading formed on its own, and cite accordingly.
        sense_rows.append((aid, SENSE_CT, json.dumps({
            "id": aid, "content_type": SENSE_CT, "name": wn_id,
            "collection_id": collection, "collections": [collection],
            "created_by": "ember-source",
            "context": collection, "content": doc.get("gloss") or wn_id,
            "operator": "op.demand.lexicon",
            "gloss": doc.get("gloss"), "ic": doc.get("ic"),
            "cited_from": "cite.wordnet", "demanded": True})))
        for (parent,) in ro.execute("SELECT dst FROM edge WHERE src = ? AND label = ?",
                                    (wn_id, ISA_LABEL)):
            if parent in closure:
                isa_rows.append((aid, _sense_id(collection, parent), ISA_LABEL,
                                 json.dumps({"of": wn_id})))

    for surface, ids in found.items():
        for wn_id in ids:
            # Entries address the organon's own unit id (`_unit_id(collection, tok)` — `<col>:<tok>`),
            # the same node its `observed` edges point to. A parallel `<col>:tok:<surf>` node here
            # would put the book's co-presence and the lexicon's senses in two components joined only
            # at the seed, so context could never flow into the senses — a tie between senses that
            # does not move with the reach horizon is exactly that disconnection, not a pruning.
            entry_rows.append((_unit_id(collection, surface),
                               _sense_id(collection, wn_id), ENTRY_LABEL,
                               json.dumps({"surface": surface})))

    # Written through the store, not raw SQL: `put_artifact` allocates `_seq` and stamps `_origin`;
    # `add_edges` computes the 16-byte digest and is idempotent on it; `collection_member` is
    # carried by the artifact's own `collections` field rather than written beside it. Raw SQL would
    # skip all three and write rows that can never publish.
    for _aid, _ct, _doc in sense_rows:
        store.artifacts.put_artifact(json.loads(_doc))
    _edges = [(s, d, l, json.loads(p)) for (s, d, l, p) in (isa_rows + entry_rows)]
    handled = store.graph.add_edges(_edges)
    if handled < len(_edges):
        raise RuntimeError("edge write shortfall: %d of %d handled — rows were LOST."
                           % (handled, len(_edges)))

    return {"demanded": len(surfaces), "resolved": len(found), "missed": len(missed),
            "senses_direct": len(direct), "senses_with_ancestors": len(sense_rows),
            "isa_edges": len(isa_rows), "entry_edges": len(entry_rows),
            "misses": sorted(missed)}
