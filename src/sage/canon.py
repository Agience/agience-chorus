# Operator code lives in chorus and is distributed to hosts as a content-addressed source bundle
# (agience-observe/build_bundles.py); ember executes it via ember/runtime/runner.py, sha-verified
# before exec. There are no code mirrors — changes happen here.
"""The canon knowledge base — sage's design docs as groundable, citable knowledge artifacts.

The Agience design canon (`agience-pharos/**/*.md` — CRYSTALS-GAUGES-AND-THE-MEMBRANE,
SCREEN-AND-GAUGES, COMMUNICATION-PLANE, …) is prose an ember should be able to ground in and cite,
not a pile of files only a human reads. This module makes it a wiki-like knowledge base addressed
by name: every H2/H3 section becomes one knowledge artifact in the lattice store, and each artifact
carries its own provenance — the source path, a stable citation id, the section heading, and a
CC-BY content-license marker — so a grounded answer can say "per CRYSTALS-GAUGES-AND-THE-MEMBRANE
§3a …" with the citation carried, never fabricated.

Two paths, both reusing sage's existing machinery (no new store schema, no new index):

  op.canon.source (organon)    — reach the canon prose where it lives; touches no store.
  op.canon.condense (tekton)   — chunk by heading and `put_many` the
                                 chunks as `text/markdown` artifacts (the type `content_search`
                                 already indexes). Provenance rides in the artifact doc — the
                                 lattice keeps every field in its `doc` JSON, so `citation`
                                 round-trips through `get_artifact` unchanged.
  retrieve_cited(corpus, q)    — the same BM25 recall the `op.retrieve` reach uses
                                 (`content_search.search`), but each hit is returned with the
                                 citation resolved from the artifact's own provenance. A chunk
                                 that carries no provenance is dropped (never invent a source);
                                 an empty or no-match query returns [] (the honest null — no hit,
                                 no citation).

License: canon prose is content, so ingested chunks are marked CC-BY-4.0 (the two-tier policy:
content CC-BY, persona code AGPL). This module is persona code (AGPL); the prose it carries is not.

Carrier: `retrieve_cited` is the in-process capability. Serving it as a cross-persona reach (an
`op.knowledge.cite` NEED on the ground plane) rides the same carrier `reach_provider` is waiting
on — a real fabric + fleet root, a separate gated deploy step. Until then this is loopback /
in-process, proven by the handler being called directly (same posture as
`reach_provider.serve_retrieve_if_configured`, which stays dark without a wired carrier).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

CANON_CT = "text/markdown"                       # the type content_search already indexes
CANON_LICENSE = "CC-BY-4.0"                       # content is CC-BY (two-tier policy)
CANON_KNOWLEDGE = "canon"                         # marks a chunk as canon knowledge (vs code/wordnet)
CANON_CITE_CAP = "op.knowledge.cite"             # the cited-retrieval capability name
# Deterministic creation stamp — the canon is content-addressed prose, not clock-stamped events.
_CANON_TIME = "2026-07-29T00:00:00+00:00"

__all__ = ["CANON_CT", "CANON_LICENSE", "CANON_KNOWLEDGE", "CANON_CITE_CAP",
           "CANON_SOURCE_CAP", "CANON_CONDENSE_CAP",
           "iter_canon_chunks", "canon_artifacts", "retrieve_cited",
           "CANON_BROWSE_CAP",
           "cited_retrieve_handler", "canon_source_handler", "canon_condense_handler",
           "canon_browse_handler", "canon_light_handler", "CANON_LIGHT_CAP",
           "register_canon_operators"]


# ── chunking ─────────────────────────────────────────────────────────────────────────────────
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SECT = re.compile(r"^\s*(\d+[a-z]?)\b")          # a leading "3." / "3a." section label


def _slug(text: str, *, n: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:n].rstrip("-")) or "section"


def _section_label(heading_text: str) -> str:
    """The section handle used in a citation: the doc's own number ("3", "3a") when the heading
    carries one, else a slug of the heading. Derived from the prose — nothing invented."""
    m = _SECT.match(heading_text)
    if m:
        return m.group(1)
    return _slug(heading_text)


def iter_canon_chunks(text: str, *, source: str, stem: str) -> Iterator[Dict[str, Any]]:
    """Split one canon doc into heading-delimited chunks (one per H2/H3+; the preamble before the
    first H2 — the H1 title + intro — is the 'intro' chunk). Each chunk keeps its heading line so
    BM25 matches on heading terms too. Fenced code blocks are skipped so a `#` comment inside a
    fence is never mistaken for a heading. Yields dicts {section, heading, body} in document order."""
    lines = text.splitlines()
    in_fence = False
    cur_heading: Optional[str] = None       # None until the first H2; the preamble is 'intro'
    buf: List[str] = []

    def _emit() -> Optional[Dict[str, Any]]:
        body = "\n".join(buf).strip()
        if not body:
            return None
        if cur_heading is None:
            return {"section": "intro", "heading": stem, "body": body}
        return {"section": _section_label(cur_heading), "heading": cur_heading, "body": body}

    for ln in lines:
        if _FENCE.match(ln):
            in_fence = not in_fence
            buf.append(ln)
            continue
        m = None if in_fence else _HEADING.match(ln)
        # start a new chunk at H2 or deeper; H1 stays in the intro (it names the whole doc).
        if m and len(m.group(1)) >= 2:
            chunk = _emit()
            if chunk:
                yield chunk
            cur_heading = m.group(2).strip()
            buf = [ln]
        else:
            buf.append(ln)
    tail = _emit()
    if tail:
        yield tail


def _citation(stem: str, source: str, section: str, heading: str) -> Dict[str, str]:
    """The provenance a cited answer carries. `cite_id` is the artifact id (stable + addressable);
    `ref` is the ready-to-print human form an ember drops into prose ("per <ref>")."""
    cite_id = "canon:%s#%s" % (stem, section)
    ref = stem if section == "intro" else "%s §%s" % (stem, section)   # §
    return {"cite_id": cite_id, "source": source, "section": section,
            "heading": heading, "license": CANON_LICENSE, "ref": ref}


#: The id namespace the condensation writes, derived from the one builder that writes it. Typing
#: `"canon:"` here would be a second declaration of the id scheme, free to drift from `_citation`.
_CANON_ID_PREFIX = _citation("", "", "", "")["cite_id"].split("#")[0]      # -> "canon:"

#: Collections are the pharos folders. A doc's collection is the directory it lives in — the
#: structure the canon already has on disk, read rather than invented.
COLLECTION_CT = "application/vnd.agience.collection+json"
_COLLECTION_ID_PREFIX = "collection:"


def _collection_of(source_path: str) -> str:
    """`agience-pharos/genesis/GENESIS.md` -> `collection:agience-pharos/genesis`. A file at the
    root belongs to the root collection; nothing is bucketed and nothing is renamed."""
    folder = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
    return _COLLECTION_ID_PREFIX + (folder or "")


def collection_artifacts(arts: List[Dict[str, Any]], *, author: str = "sage-canon"
                         ) -> List[Dict[str, Any]]:
    """One collection artifact per folder the canon actually occupies, plus every ancestor folder,
    so the tree has no holes: `a/b/c` implies `a/b` and `a` are real collections even when no file
    sits directly in them. Derived from the artifacts in hand — never a listing typed here."""
    folders: set = set()
    for a in arts:
        cid = str(a.get("collection_id") or "")
        if not cid.startswith(_COLLECTION_ID_PREFIX):
            continue
        parts = cid[len(_COLLECTION_ID_PREFIX):].split("/")
        for i in range(1, len(parts) + 1):
            folders.add("/".join(parts[:i]))
    out = []
    for f in sorted(folders):
        parent = f.rsplit("/", 1)[0] if "/" in f else ""
        out.append({
            "id": _COLLECTION_ID_PREFIX + f, "content_type": COLLECTION_CT, "state": "committed",
            "title": f.rsplit("/", 1)[-1], "context": "canon collection: %s" % f,
            "created_by": author, "created_time": _CANON_TIME,
            "knowledge": CANON_KNOWLEDGE, "license": CANON_LICENSE,
            "source_path": f,
            "parent": (_COLLECTION_ID_PREFIX + parent) if parent else "",
        })
    return out


#: Nothing is excluded and nothing is labelled. A directory blocklist would filter on location, and
#: staleness is not a location — it says nothing about whether a section inside the blocked
#: directory is stale, or whether one outside it is current. A `role` stamped by a rule ladder over
#: path substrings and keyword counts is not derived, it is asserted, and collapses a corpus into
#: one bucket rather than reading it.
#:
#: The organon reaches, the tekton chunks and cites, and nothing else is asserted. Supersession is
#: already in the prose — a NEED arrives, the screen reads the candidate set, and the cut resolves
#: what answers it, with no threshold anywhere. The only label an artifact carries is its citation,
#: which is a fact about where the words came from rather than a judgement about their worth.


def canon_artifacts(root: str, *, author: str = "sage-canon") -> List[Dict[str, Any]]:
    """Every canon markdown file under `root`, chunked into knowledge artifacts with provenance.
    Pure (touches no store) so it is trivially testable and the ingest is a plain `put_many`.

    Artifact id == the citation id, so citing an answer's grounded ids == naming its sources.
    Ids are de-duplicated deterministically (a repeated section label gets a `-2` suffix) so two
    unnumbered headings in one doc never collide silently.

    Nothing is excluded and nothing is labelled. An artifact asserts only its citation — a fact
    about where the words came from. See the note above."""
    base = Path(root)
    arts: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(base).as_posix()
        source = "%s/%s" % (base.name, rel) if base.name else rel
        stem = path.stem
        text = path.read_text(encoding="utf-8", errors="ignore")
        for ch in iter_canon_chunks(text, source=source, stem=stem):
            cit = _citation(stem, source, ch["section"], ch["heading"])
            cid = cit["cite_id"]
            if cid in seen:                       # deterministic de-dup — never a silent overwrite
                seen[cid] += 1
                cid = "%s-%d" % (cid, seen[cid])
                cit = dict(cit, cite_id=cid)
            else:
                seen[cid] = 1
            arts.append({
                "id": cid, "content_type": CANON_CT, "state": "committed",
                "title": "%s — %s" % (stem, ch["heading"]),
                "content": ch["body"],
                # ── THE OFFER: what this section is about, in the document's own words ────
                # The heading is the only place a section states its own subject — its body
                # does not repeat the name of the document it belongs to, and its extracted
                # key terms therefore do not either.
                #
                # The offer is the heading, not a `"canon knowledge: %s §%s"` context string,
                # which is provenance. Promoted whole to `description` by
                # `chunking.extract_text_from_context`, such a string becomes the stated offer of
                # every canon artifact in the store, and all 6,480 then position on the same two
                # nodes, `canon.n.01` and `cognition.n.01`. A field that says the same thing about
                # every member of a corpus cannot tell them apart. Where the row came from is
                # recorded below, in full.
                "description": ch["heading"],
                "created_by": author, "created_time": _CANON_TIME,
                # ── PROVENANCE (rides in the doc JSON, round-trips via get_artifact) ──
                "knowledge": CANON_KNOWLEDGE, "source_path": source,
                "license": CANON_LICENSE, "citation": cit,
                # MEMBERSHIP — the pharos folder this doc lives in. `collection_id` +
                # `collections` are the two names `mantle.shard.curate._memberships` reads.
                "collection_id": _collection_of(source),
                "collections": [_collection_of(source)],
                "doc_stem": stem,
            })
    return arts


def _ingest(store: Any, root: str, *, author: str = "sage-canon",
            rebuild_fts: bool = False) -> Dict[str, Any]:
    """Load the canon under `root` into `store` as cited knowledge artifacts, then (re)build the
    lexical index so `retrieve_cited` can find them. `store` is a lattice store bundle
    (`.artifacts.put_many` + `.db`) — the same store `op.retrieve` searches. Returns a summary.

    Reuses rather than invents a schema: chunks are ordinary `text/markdown` artifacts; provenance is extra
    doc fields the lattice already persists; the index is `corpus_fts`, the one the corpus uses."""
    # The ingest indexes what it writes. An index is derived data and the path that writes the rows
    # derives it — nothing else knows the rows exist. The lattice writer does not do this: it feeds
    # mantle's encrypted SSE index, which `content_search`'s BM25 SQL does not read, and holds no
    # `fts` table at all until something creates one. So a canon put without the `index_for` below
    # is a canon `retrieve_cited` cannot find, and the store answers "no such table: fts" rather
    # than "no hits".
    #
    # `rebuild_fts` is the separate, whole-store act and still defaults to False. `fts.rebuild_for`
    # drops and rebuilds the index from every vertex inside one write transaction — on a large
    # store, millions of rows and a long exclusive lock on production, to index a handful of new
    # ones. It is a migration (its own docstring: "for a store whose rows landed before the writer
    # maintained it"), not an ingest, so the caller asks for it rather than getting it by default.
    arts = canon_artifacts(root, author=author)
    cols = collection_artifacts(arts, author=author)
    if arts:
        import corpus_fts as _fts                 # lazy: keep canon.py import-light
        # The collections land first, so a member never points at a folder that does not exist yet.
        if cols:
            store.artifacts.put_many(cols, batch=200)
        store.artifacts.put_many(arts, batch=200)
        if rebuild_fts:
            _fts.rebuild_for(store.db)
        else:
            _fts.index_for(store.db, arts)        # only what this ingest wrote
    sources = sorted({a["source_path"] for a in arts})
    return {"artifacts": len(arts), "sources": len(sources), "collections": len(cols),
            "root": root, "license": CANON_LICENSE, "capability": CANON_CITE_CAP}


# ── cited retrieval ─────────────────────────────────────────────────────────────────────────
def _resolve_text(corpus: Any, art: Dict[str, Any]) -> str:
    try:
        from mantle.shard.content import resolve_text
        return resolve_text(corpus, art)
    except Exception:
        return art.get("content") or ""


def retrieve_cited(corpus: Any, query: str, *, k: int = 6) -> List[Dict[str, Any]]:
    """BM25 recall over the canon (the same `content_search.search` the `op.retrieve` reach uses),
    with each hit's citation resolved from the artifact's own provenance:

        [{id, title, content, score, citation: {cite_id, source, section, heading, license, ref}}]

    Returns an honest null rather than fabricating a source:
      • empty or blank query      -> []       (nothing asked, nothing cited)
      • no BM25 hit                -> []       (the corpus has no match; no source invented)
      • a hit with no citation     -> dropped  (cited only when the provenance is actually held)
    Score is negated (`higher = better`), matching sage's `op.retrieve` convention."""
    if not (query or "").strip():
        return []
    # The one reach this organon makes outside itself, and it is declared as a host seam: `canon`
    # travels as a bundle, but `content_search` does not travel with it, because its own closure
    # pulls in `answer_shape`, `offer`, `condense` and `ember.signal` — carrying that would make the
    # canon payload a copy of sage's whole retrieval stack. So the bundle declares it as a host seam
    # (`host_seams: ["content_search"]`), exactly as the `operators` group declares `match`, and the
    # host either fills it or does not. Chorus fills nothing (`registered_seams() == {}`), so here
    # the second leg answers — which is why the fallbacks below are kept rather than replaced.
    try:                                             # 1 · the declared seam, if a host bound one
        from . import content_search as _cs          # (bundle context — resolves only via the seam)
    except ImportError:
        try:                                         # 2 · robust: cross-persona host vs in-persona
            from sage import content_search as _cs   # (chorus/src on path) — sage's own retrieval tekton
        except ImportError:
            import content_search as _cs             # (sage/ on path)
    # Scoped to the canon in SQL, not filtered after the LIMIT: filtering after the limit would ask
    # the whole store for its top-k and then drop everything without a citation, so a canon section
    # would have to out-rank every indexed doc — including WordNet's own entries — for a slot it was
    # never competing for. The indexed id-range predicate scopes the search before ranking, and is
    # faster for the same reason: the range predicate cuts the join.
    hits: List[Dict[str, Any]] = []
    for aid, _ct, score in _cs.search(corpus, query, k=k, id_prefix=_CANON_ID_PREFIX):
        art = corpus.artifacts.get_artifact(aid)
        if not art:
            continue
        cit = art.get("citation")
        if not cit or not cit.get("cite_id"):        # never manufacture a citation
            continue
        hits.append({"id": aid, "title": str(art.get("title") or ""),
                     "content": _resolve_text(corpus, art) or "",
                     "score": round(-float(score), 6), "citation": cit})
    return hits


def cited_retrieve_handler(corpus: Any, *, k: int = 6) -> Callable[[Any], List[Dict[str, Any]]]:
    """The injected `need -> cited-evidence` handler for `op.knowledge.cite`. NEED is `{query, k?}`;
    EVIDENCE is `retrieve_cited`'s cited shape. Serving this over the ground plane reuses
    `reach_provider.serve_retrieve`'s wiring against this cap name — a gated carrier step. Proven
    here in-process by calling the handler directly (fail-soft: missing/empty query -> [])."""
    def handler(need: Any) -> List[Dict[str, Any]]:
        need = need or {}
        return retrieve_cited(corpus, need.get("query", ""), k=int(need.get("k", k)))
    return handler


# ── the information path — organon -> tekton, no other way in ────────────────────────────────
#
# Information moves by tektons and organons only, never by a one-off script or a REPL session
# reading prose off disk directly. `_ingest` is private and reachable only through the two
# capabilities below.
#
#   op.canon.source    organon — the only thing that touches the pharos tree. A real-world
#                      instrument, exactly like astra's `op.fetch.get`. Returns raw docs — the
#                      filesystem, a git remote, a mesh peer, all equally — and the tekton cannot
#                      tell the difference, which is the whole reason this is a separate noun.
#   op.canon.condense  tekton, domain `canon` — prose in, denser information out: chunk at H2/H3,
#                      derive the citation, land the artifacts. It excludes nothing.
#
# Nothing polls: `[[operator-is-observation]]` — observation follows demand. The condense NEED is
# raised because canon was asked for and could not be answered, never on a tick.

CANON_SOURCE_CAP = "op.canon.source"        # organon: reach the prose where it actually lives
CANON_CONDENSE_CAP = "op.canon.condense"    # tekton:  prose -> cited knowledge artifacts


def canon_source_handler(root: str) -> Callable[[Any], List[Dict[str, Any]]]:
    """ORGANON handler. NEED is `{}` (or `{root}` to override); the answer is the raw prose with its
    paths — no chunking, no store, no interpretation.

    Kept separate from the tekton so the source can change without the condensation changing: a git
    remote, a mounted volume or a mesh peer all satisfy this shape."""
    def handler(need: Any) -> List[Dict[str, Any]]:
        need = need or {}
        base = Path(str(need.get("root") or root))
        out: List[Dict[str, Any]] = []
        for path in sorted(base.rglob("*.md")):
            rel = path.relative_to(base).as_posix()
            out.append({"source_path": "%s/%s" % (base.name, rel) if base.name else rel,
                        "stem": path.stem,
                        "text": path.read_text(encoding="utf-8", errors="ignore")})
        return out
    return handler


def canon_condense_handler(store: Any, root: str, *,
                           author: str = "sage-canon") -> Callable[[Any], Dict[str, Any]]:
    """TEKTON handler. NEED is `{}`; the answer is a summary of what was condensed and landed.

    It reaches the prose through the organon, never through the filesystem directly — that is what
    makes the source swappable and what keeps this the only write path.

    `rebuild_fts` defaults to False here, matching `_ingest`, so a caller does not silently arm a
    full-index rebuild on the only path anything actually calls. A NEED may still ask for a rebuild
    explicitly; that is the point.
    """
    def handler(need: Any) -> Dict[str, Any]:
        need = need or {}
        return _ingest(store, str(need.get("root") or root), author=author,
                       rebuild_fts=bool(need.get("rebuild_fts", False)))
    return handler


# ── op.canon.browse — the library view ───────────────────────────────────────────────────────
#
# Emits the structure rather than picking a cut: this tekton answers the tree the canon already
# has — collections (pharos folders) -> docs -> sections.
#
CANON_BROWSE_CAP = "op.canon.browse"        # tekton: the canon's own structure, at a chosen zoom


def _page_canon(pager: Callable[..., List[Dict[str, Any]]]) -> Iterator[Dict[str, Any]]:
    """Walk the canon's id range on the PK index, keyset-paged — never `count(*)`, never `SKIP`.

    Selecting by content_type and filtering in Python touches every `text/markdown` row in the
    store to find the canon's own small fraction of them; the indexed id range answers directly,
    because the work scales with rows touched rather than with the LIMIT
    [[limit-bounds-output-not-work]].

    The two reads do not return the same shape: `list_artifacts` yields the artifact flat, while
    `page_by_id` yields `{id, content_ref, _origin, _seq, doc: {...}}` with the artifact nested.
    The doc is unwrapped here so both callers see the same flat shape and `knowledge` stays
    readable regardless of which path served the row.
    """
    after = _CANON_ID_PREFIX
    while True:
        page = pager(after=after, limit=500)
        if not page:
            return
        for row in page:
            rid = str(row.get("id") or "")
            if not rid.startswith(_CANON_ID_PREFIX):
                return                                   # left the range — the walk is done
            doc = row.get("doc")
            yield dict(doc, id=rid) if isinstance(doc, dict) else row
        after = page[-1]["id"]


def _readable(store: Any, principal: Optional[str]):
    """`art -> bool` for this principal, with the grant sets read once.

    Access is the CRUDEASIO light-cone (`mantle.db.access`): an artifact is readable if it is
    public — born public (its collection is gated by no grant) or made public (a Read grant to
    `PUBLIC_PRINCIPAL`) — or if this principal's own grants reach its collection.

    Fails closed: if the access module cannot be reached at all, nothing is readable. A browser
    that silently degrades to "show everything" when the gate is missing is how a private
    collection ends up on the open internet.

    The sets are computed once per browse, not per artifact, since re-deriving both on every call
    would mean thousands of grant scans over a large browse.
    """
    # Does this store even carry grants? A store with no grant layer has no private collection to
    # protect — everything in it is the un-keyed top — so ungated is the truth, not a bypass. A store
    # that has one and fails to answer is the dangerous case, and that one fails closed.
    grant_capable = getattr(getattr(store, "artifacts", None), "db", None) is not None
    try:
        from mantle.db import access as _access
    except Exception:
        return (lambda art: False) if grant_capable else (lambda art: True)
    try:
        gated = _access.gated_collections(store)
        public = _access.reachable_collections(store, _access.PUBLIC_PRINCIPAL)
        mine = _access.reachable_collections(store, principal) if principal else set()
    except Exception:
        return (lambda art: False) if grant_capable else (lambda art: True)

    def ok(art: Dict[str, Any]) -> bool:
        g = _access.grounding_of(art)
        if g is None or g not in gated:
            return True                                     # born public — the un-keyed top
        aid = str(art.get("id") or "")
        return g in public or aid in public or g in mine or aid in mine

    return ok


def _canon_head(store: Any, *, source: Optional[str] = None,
                principal: Optional[str] = None) -> List[Dict[str, Any]]:
    """Canon artifacts, head-only, filtered to what `principal` may read.

    `content_type` is not the discriminator: `CANON_CT` is `text/markdown`, which the whole doc
    corpus shares. `knowledge == CANON_KNOWLEDGE` is what the condensation actually stamps, so that
    is what selects; browsing by type alone would serve the code docs as canon.

    Two reads, and the keyset one is preferred wherever the store offers it. A store with no
    `page_by_id` still answers correctly, just by streaming — correctness does not depend on the
    fast path, which is what keeps the fallback honest rather than decorative.
    """
    pager = getattr(getattr(store, "artifacts", None), "page_by_id", None)
    rows: Iterable[Dict[str, Any]] = (_page_canon(pager) if callable(pager)
                                      else store.list_artifacts(content_type=CANON_CT))
    may_read = _readable(store, principal)
    out = []
    for a in rows:
        if a.get("knowledge") != CANON_KNOWLEDGE:
            continue
        if source is not None and a.get("source_path") != source:
            continue
        if not may_read(a):
            continue
        out.append(a)
    return out



def _section_key(art: Dict[str, Any]) -> tuple:
    """Order sections by the label the document itself wrote, natural-sorted.

    Not id order, which is what the store returns: `cite_id` is `canon:<stem>#<section>`, so a
    lexicographic sort would put §10 before §2 and §1.10 before §1.9 — a library that renumbers its
    own shelves. Splitting the label into digit and non-digit runs reads the numbering the author
    chose rather than imposing one; a non-numeric label (`intro`) still sorts stably by its text.

    This orders by the section label the document assigned, not the order sections appeared in the
    source — that ordering is not stored, and recovering it would mean re-reading the prose.
    """
    cit = art.get("citation") or {}
    label = str(cit.get("section") or art.get("id") or "")
    return tuple((0, int(t)) if t.isdigit() else (1, t)
                 for t in re.findall(r"\d+|\D+", label)) or ((1, ""),)


CANON_LIGHT_CAP = "op.canon.light"          # tekton: give each section its ontology position


def _fired_names(text: str) -> List[str]:
    """The ontology positions this prose actually resolves to, in first-appearance order.

    Not `astra.doc_index.extract_terms`, which is word frequency (`Counter(...).most_common(30)`)
    plus an identifier regex — a lexical statistic with a typed cap, the instrument this system
    does not use. A position is not "the 30 commonest words"; it is which concepts the text fires.
    Every token that resolves contributes and none is capped, so the extent of a section's position
    is the section's own, not a number chosen here.

    A token that fires nothing is dropped rather than kept as a bare word: it names no position, so
    it cannot participate in a coupling. That is a different act from the recall filter in
    `content_search` (GAPS 2.12) — nothing is being ranked, and no answer turns on it.
    """
    from crystal.ontology.lookup import wn_synsets_for as _wsf
    from corpus_stats import terms as _terms

    out, seen = [], set()
    for t in _terms(text or ""):
        if t in seen:
            continue
        seen.add(t)
        if _wsf(t):
            out.append(t)
    return out


def canon_light_handler(store: Any) -> Callable[[Any], Dict[str, Any]]:
    """TEKTON handler (domain: canon). Give every canon section its ontology position.

    Until a section has a position, it has no place in the frame `projection.frame(store, names)`
    builds, so nothing can couple to it.

    Scoped to the canon's id range: `astra.doc_index.index_docs` is a full pass over
    `list_artifacts` — its own docstring records `text/markdown` timing out at 120s on a large
    store — so it is not usable against the live store at all. The canon walks its own indexed
    range instead.

    NEED `{}` lights only the dark sections; `{"relight": true}` redoes every one.
    """
    def handler(need: Any) -> Dict[str, Any]:
        need = need or {}
        relight = bool(need.get("relight"))
        principal = need.get("principal") or None
        arts = _canon_head(store, principal=principal)
        lit = dark = 0
        batch: List[Dict[str, Any]] = []
        cleared = 0
        for a in arts:
            held = list(a.get("lemmas") or [])
            if held and not relight:
                continue
            names = _fired_names(_resolve_text(store, a) or a.get("content") or "")
            if names == held:
                continue                      # already at this position — a rewrite would say nothing
            if not names:
                dark += 1                     # prose that fires nothing has no position, honestly
                if held:
                    # The old value must go: leaving it would mean the field holds positions the
                    # current text does not support, while a query for "sections with no position"
                    # returns zero — absent must look absent.
                    batch.append({k: v for k, v in a.items() if k != "lemmas"})
                    cleared += 1
                continue
            batch.append(dict(a, lemmas=names))
            lit += 1
        if batch:
            store.artifacts.put_many(batch, batch=200)
        return {"lit": lit, "unpositioned": dark, "cleared": cleared,
                "considered": len(arts), "capability": CANON_LIGHT_CAP}

    return handler


def _raise_demand(store: Any, capability: str) -> bool:
    """A NEED that could not be answered raises demand against the capability that would answer it.

    This is the trigger, and it is why nothing polls: `[[operator-is-observation]]` — observation
    follows demand. The condense runs because demand accumulated, never because a tick fired: an
    empty canon that nobody asks about stays empty, and one that is asked about repeatedly makes
    that fact measurable.

    Mass accumulates here, not in the store: `demand_set` replaces (`SET mass = excluded.mass`), so
    a caller recording the same value every time would record "asked once" forever no matter how
    often it was asked — which is precisely the signal this exists to carry.

    Returns whether demand was recorded. A store with no demand cache simply cannot carry it; that
    is a fact about the store, not a failure of the read, so the answer is unchanged either way.
    """
    arts = getattr(store, "artifacts", None)
    getter, setter = getattr(arts, "demand_get", None), getattr(arts, "demand_set", None)
    if not (callable(getter) and callable(setter)):
        return False
    try:
        import time as _time
        prior = getter(capability) or {}
        setter(capability, float(prior.get("mass") or 0.0) + 1.0, _time.time())
        return True
    except Exception:                       # a read must not fail because demand could not be noted
        return False


def canon_browse_handler(store: Any) -> Callable[[Any], Dict[str, Any]]:
    """TEKTON handler (domain: canon). The canon's own structure — pharos folders, the docs in
    them, and a doc's sections. Three shapes, one for each level of the tree:

        {}                       -> the collections at the top, each with its child count
        {"collection": "<id>"}   -> that folder's sub-folders and docs
        {"doc": "<source_path>"} -> that doc's sections, in the label order the author wrote

    Condenses: many artifacts in, the structure over them out. Writes nothing, reaches nothing —
    the prose came in through the organon.

    No search, no ranking, no zoom. The tree is what the canon already is on disk; a browser walks
    it. Density/zoom is separate work and is deliberately absent rather than half-present.

    An empty canon answers `observed: False` — "no canon is condensed" and "this folder is empty"
    are different facts.
    """
    def handler(need: Any) -> Dict[str, Any]:
        need = need or {}
        # Who is asking: anonymous reaches only the public top; a delegate reaches exactly the
        # collections its grants cover. The read is scoped at the source, never filtered after.
        principal = need.get("principal") or None

        section = need.get("section") or None
        if section:                                        # one section: the prose itself
            art = None
            get = getattr(getattr(store, "artifacts", None), "get_artifact", None)
            if callable(get):
                art = get(str(section))
            if art and art.get("knowledge") != CANON_KNOWLEDGE:
                art = None
            if art and not _readable(store, principal)(art):
                # Indistinguishable from absent, deliberately: "you may not read this" tells an
                # anonymous caller that it exists, which is itself the private fact.
                art = None
            if not art:
                return {"level": "section", "locus": str(section), "observed": False,
                        "why": "no section at this id", "items": []}
            return {"level": "section", "locus": str(section), "observed": True,
                    "title": art.get("title"), "citation": art.get("citation"),
                    "license": art.get("license"), "collection": art.get("collection_id") or "",
                    "doc": art.get("source_path") or "",
                    "content": _resolve_text(store, art), "items": []}

        doc = need.get("doc") or None
        if doc:                                            # a doc's sections
            arts = _canon_head(store, source=doc, principal=principal)
            if not arts:
                return {"level": "doc", "locus": doc, "observed": False,
                        "why": "no doc at this path", "items": []}
            items = [{"id": a["id"], "title": a.get("title"), "citation": a.get("citation"),
                      "license": a.get("license")} for a in sorted(arts, key=_section_key)]
            return {"level": "doc", "locus": doc, "observed": True,
                    "collection": (arts[0].get("collection_id") or ""),
                    "extent": len(items), "items": items}

        arts = _canon_head(store, principal=principal)
        if not arts:
            # The demand trigger: the canon was asked for and could not be answered, so the
            # capability that would answer it gains mass. Naming it in `why` tells a human; this
            # tells the system.
            raised = _raise_demand(store, CANON_CONDENSE_CAP)
            return {"level": "collection", "locus": need.get("collection") or "", "observed": False,
                    "why": "no canon is condensed in this store — raise a %s NEED" % CANON_CONDENSE_CAP,
                    "demand": CANON_CONDENSE_CAP if raised else None, "items": []}

        here = str(need.get("collection") or "").strip()
        if not here:
            # Start at the canon's own root, derived as the longest folder prefix every doc shares.
            # Without it the first page is one link ("agience-pharos") and a click that tells you
            # nothing — a level of tree that carries no choice.
            paths = [str(a.get("collection_id") or "")[len(_COLLECTION_ID_PREFIX):] for a in arts]
            paths = [p for p in paths if p]
            if paths:
                common = paths[0].split("/")
                for p in paths[1:]:
                    parts = p.split("/")
                    common = [x for i, x in enumerate(common) if i < len(parts) and parts[i] == x]
                    if not common:
                        break
                if common:
                    here = _COLLECTION_ID_PREFIX + "/".join(common)
        prefix = here[len(_COLLECTION_ID_PREFIX):] if here.startswith(_COLLECTION_ID_PREFIX) else ""

        folders: Dict[str, int] = {}                        # immediate children, by doc count below
        docs: Dict[str, int] = {}                           # docs directly in `here`
        for a in arts:
            cid = str(a.get("collection_id") or "")
            path = cid[len(_COLLECTION_ID_PREFIX):] if cid.startswith(_COLLECTION_ID_PREFIX) else ""
            if prefix:
                if path != prefix and not path.startswith(prefix + "/"):
                    continue
                rest = path[len(prefix):].lstrip("/")
            else:
                rest = path
            if rest:                                        # lives deeper — count toward the child
                child = (prefix + "/" + rest.split("/")[0]) if prefix else rest.split("/")[0]
                folders[child] = folders.get(child, 0) + 1
            else:                                           # directly here
                sp = str(a.get("source_path") or "")
                docs[sp] = docs.get(sp, 0) + 1
        return {
            "level": "collection", "locus": here, "observed": True,
            "extent": sum(folders.values()) + sum(docs.values()),
            "items": ([{"kind": "collection", "id": _COLLECTION_ID_PREFIX + f,
                        "title": f.rsplit("/", 1)[-1], "sections": n}
                       for f, n in sorted(folders.items())]
                      + [{"kind": "doc", "id": sp, "title": sp.rsplit("/", 1)[-1],
                          "sections": n, "license": CANON_LICENSE}
                         for sp, n in sorted(docs.items())]),
        }

    return handler


# ── registration — sage's canon capabilities ─────────────────────────────────────────────────
_CANON_OPS = [
    (CANON_LIGHT_CAP, "TEKTON (domain: canon): gives each canon section its ONTOLOGY POSITION — the "
     "concepts its own prose fires, every one that resolves and none capped. Without a position a "
     "section cannot take part in a coupling, so nothing can reach it except by walking to it. "
     "Scoped to the canon's id range; a section whose prose fires nothing is reported unpositioned "
     "rather than given a made-up place"),
    (CANON_CITE_CAP, "grounds a query in the design CANON (agience-pharos) and returns matching "
     "chunks WITH their carried citation (source path + stable cite id + CC-BY marker); "
     "no match -> no citation (honest null, never fabricated)"),
    (CANON_SOURCE_CAP, "ORGANON: reaches the design canon where it lives (the agience-pharos tree) "
     "and returns the raw prose with its source paths; touches no store and interprets nothing, so "
     "the source can move to a git remote or a mesh peer without the condensation changing"),
    (CANON_CONDENSE_CAP, "TEKTON (domain: canon): condenses canon prose into CITED knowledge "
     "artifacts — one per H2/H3 section, each carrying source path, stable cite id and the CC-BY "
     "marker — and lands them where op.knowledge.cite can ground in them. EXCLUDES NOTHING and "
     "LABELS NOTHING: an artifact asserts only its citation, so a reader judges by the source it "
     "names rather than by a stamp this tekton is in no position to derive"),
    (CANON_BROWSE_CAP, "TEKTON (domain: canon): the canon's own STRUCTURE — collections (the pharos "
     "folders), the docs in them, and a doc's sections in the label order the author wrote, each "
     "carrying its citation. A browser walks it; there is no search, no ranking and no zoom. "
     "Empty canon answers observed:false, never an empty tree"),
]


def register_canon_operators(store, *, author: str = "sage-canon") -> int:
    """Register sage's canon capabilities — the cited read and the organon/tekton write path."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _CANON_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": f"sage canon operator {name}: {offer}",
            "created_by": author}))
    return len(_CANON_OPS)
