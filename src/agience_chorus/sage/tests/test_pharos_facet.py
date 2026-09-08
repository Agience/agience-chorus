"""The `pharos` facet — one page, a browser into the canon collections.

Every answer rendered below comes from the real `canon_browse_handler`, never a hand-written dict.

Invariants:

  the tree is the folders   collections mirror the pharos directories. A bucketing of any other
                             kind is an imposed taxonomy, and the canon already has a structure.
  no search, no ranking     the browser walks structure. Any scoring here would be an instrument
                             imposed on the corpus rather than read from it.
  walkable both ways        every level is an address and every ancestor is a link; a browser you
                             can only descend is a dead end.
  dark is a state           with no tekton wired the surface says so — a 200 rendering an empty
                             tree is a measurement nobody took.
  no injection               headings and paths are corpus text and reach a browser verbatim.
"""
from __future__ import annotations



from agience_chorus.sage import canon, pharos  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


class _Store:
    def __init__(self, arts):
        self._arts = list(arts)

    def list_artifacts(self, *, content_type=None, **kw):
        return iter(self._arts)


def _art(folder, stem, section):
    source = "%s/%s.md" % (folder, stem)
    return {"id": "canon:%s#%s" % (stem, section), "content_type": canon.CANON_CT,
            "knowledge": canon.CANON_KNOWLEDGE, "source_path": source,
            "license": canon.CANON_LICENSE, "title": "%s — §%s" % (stem, section),
            "collection_id": canon._collection_of(source),
            "collections": [canon._collection_of(source)],
            "citation": {"cite_id": "canon:%s#%s" % (stem, section), "section": section,
                         "source": source, "license": canon.CANON_LICENSE,
                         "ref": "%s §%s" % (stem, section), "heading": "heading %s" % section}}


CORPUS = ([_art("p/genesis", "SCREEN", s) for s in ("intro", "1", "2", "10", "1.9", "1.10")]
          + [_art("p/genesis", "MEMBRANE", s) for s in ("intro", "3")]
          + [_art("p/theory", "PAPER", s) for s in ("intro", "1")]
          + [_art("p/theory/deep", "NOTE", "intro")]
          + [_art("p", "README", "intro")])


def _browse(arts=CORPUS):
    return canon.canon_browse_handler(_Store(arts))


# ── the tree is the folders ──────────────────────────────────────────────────────────────────────

def test_collections_are_the_pharos_FOLDERS():
    """Fails if any bucketing is not the directory the doc lives in — a taxonomy imposed on a
    corpus that already has one."""
    assert canon._collection_of("agience-pharos/genesis/GENESIS.md") == "collection:agience-pharos/genesis"
    assert canon._collection_of("agience-pharos/README.md") == "collection:agience-pharos"


def test_the_root_page_lists_the_top_FOLDERS_and_the_docs_beside_them():
    top = _browse()({})
    kinds = {i["title"]: i["kind"] for i in top["items"]}
    assert kinds.get("genesis") == "collection" and kinds.get("theory") == "collection"
    assert kinds.get("README.md") == "doc", "a doc sitting at the root was not listed"


def test_a_level_with_ONE_child_is_not_a_page_of_its_own():
    """Fails if `agience-pharos` is the entire first page — one link and a click that carries no
    choice. The root is derived as the folder prefix every doc shares."""
    only = [_art("agience-pharos/genesis", "A", "intro"), _art("agience-pharos/theory", "B", "intro")]
    top = _browse(only)({})
    assert {i["title"] for i in top["items"]} == {"genesis", "theory"}


def test_counts_are_the_SECTIONS_BELOW_a_folder_not_its_direct_children():
    """A folder's number must mean the same thing at every level, or it cannot be compared."""
    top = _browse()({})
    theory = next(i for i in top["items"] if i["title"] == "theory")
    assert theory["sections"] == 3, theory      # PAPER x2 + deep/NOTE x1
    genesis = next(i for i in top["items"] if i["title"] == "genesis")
    assert genesis["sections"] == 8


def test_a_folder_lists_its_SUBFOLDERS_and_its_docs():
    theory = _browse()({"collection": "collection:p/theory"})
    kinds = {i["title"]: i["kind"] for i in theory["items"]}
    assert kinds == {"deep": "collection", "PAPER.md": "doc"}


def test_a_doc_lists_its_SECTIONS_in_the_authors_own_order():
    """Fails if sections sort by id order, where §10 precedes §2 — a library renumbering its own
    shelves."""
    d = _browse()({"doc": "p/genesis/SCREEN.md"})
    assert [i["citation"]["section"] for i in d["items"]] == ["1", "1.9", "1.10", "2", "10", "intro"]


def test_every_section_carries_its_CITATION_and_LICENCE():
    d = _browse()({"doc": "p/genesis/SCREEN.md"})
    assert all(i["citation"]["cite_id"] and i["license"] == canon.CANON_LICENSE for i in d["items"])


# ── the honest nulls ─────────────────────────────────────────────────────────────────────────────

def test_an_EMPTY_canon_names_what_would_fill_it():
    a = _browse([])({})
    assert a["observed"] is False and canon.CANON_CONDENSE_CAP in a["why"]
    assert "<ul>" not in pharos.render(a)


def test_an_unknown_doc_is_an_honest_null():
    a = _browse()({"doc": "p/nope.md"})
    assert a["observed"] is False
    assert "no doc at this path" in pharos.render(a)


# ── the page ─────────────────────────────────────────────────────────────────────────────────────

def test_the_page_carries_NO_search_and_NO_score():
    """Fails if a scoring or query control creeps onto a browser. Retrieval here would be an
    instrument imposed on the corpus; the tree is what the canon already is."""
    html = pharos.render(_browse()({}))
    low = html.lower()
    for banned in ("<input", "<form", "search", "bm25", "score", "rank"):
        assert banned not in low, banned


def test_every_ANCESTOR_is_a_link():
    """Fails if the browser can only be descended, never walked back up."""
    html = pharos.render(_browse()({"collection": "collection:p/theory/deep"}))
    assert "?collection=collection%3Ap%2Ftheory" in html
    assert "href='?'" in html                                   # and the root


def test_every_level_is_an_ADDRESS():
    top = pharos.render(_browse()({}))
    assert "?collection=collection%3Ap%2Fgenesis" in top
    folder = pharos.render(_browse()({"collection": "collection:p/genesis"}))
    assert "?doc=p%2Fgenesis%2FSCREEN.md" in folder


def test_corpus_TEXT_reaches_the_page_ESCAPED():
    evil = _art("p/x", "T<script>alert(1)</script>", "intro")
    html = pharos.render(_browse([evil])({}))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_a_DARK_canon_says_so_and_answers_503():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(pharos.pharos_router())
    assert pharos._BROWSE_CARRIER is None, "this test measures the UNWIRED state"
    r = TestClient(app).get("/pharos")
    assert r.status_code == 503 and "dark on this node" in r.text


def test_the_route_walks_the_tree_from_the_query_string():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(pharos.pharos_router())
    prior = pharos._BROWSE_CARRIER
    pharos._BROWSE_CARRIER = _browse()
    try:
        c = TestClient(app)
        assert "genesis" in c.get("/pharos").text
        assert "SCREEN.md" in c.get("/pharos?collection=collection:p/genesis").text
        assert "canon:SCREEN#1.10" in c.get("/pharos?doc=p/genesis/SCREEN.md").text
    finally:
        pharos._BROWSE_CARRIER = prior


# ── access: the browser shows a delegate exactly its own light-cone ──────────────────────────────

class _GrantStore(_Store):
    """A store that carries grants, so the access layer is live rather than absent."""

    def __init__(self, arts, gated=(), public=(), reach=None):
        super().__init__(arts)
        self.gated, self.public, self.reach = set(gated), set(public), dict(reach or {})

        class _DB:
            pass

        class _Arts:
            db = _DB()

            @staticmethod
            def get_artifact(aid):
                return next((a for a in arts if a["id"] == aid), None)

        self.artifacts = _Arts()

    def list_artifacts(self, *, content_type=None, **kw):
        return iter(self._arts)


def _patched_access(monkeypatch, store):
    """Bind the real access contract to this fake's grant sets — the names `_readable` reads."""
    import types
    mod = types.SimpleNamespace(
        PUBLIC_PRINCIPAL="public",
        gated_collections=lambda s: store.gated,
        reachable_collections=lambda s, p: (store.public if p == "public"
                                            else set(store.reach.get(p, ()))),
        grounding_of=lambda a: a.get("collection_id") or None)
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "mantle.db.access", mod)
    monkeypatch.setitem(_sys.modules, "mantle.db",
                        types.SimpleNamespace(access=mod))


def test_a_GATED_collection_is_absent_for_anonymous(monkeypatch):
    """Fails if a private folder is listed to the open internet. `p/legacy` is gated by a Read
    grant and not granted to the public, so an anonymous light-cone reaches nothing in it — the
    folder does not appear at all."""
    arts = CORPUS + [_art("p/legacy", "OLD", "intro"), _art("p/legacy", "OLD", "1")]
    store = _GrantStore(arts, gated={"collection:p/legacy"})
    _patched_access(monkeypatch, store)
    top = canon.canon_browse_handler(store)({})
    assert "legacy" not in {i["title"] for i in top["items"]}
    assert top["extent"] == len(CORPUS)


def test_the_SAME_collection_is_present_for_a_delegate_that_holds_the_grant(monkeypatch):
    """The control: without it, the assertion above would pass on a browser that shows nothing."""
    arts = CORPUS + [_art("p/legacy", "OLD", "intro"), _art("p/legacy", "OLD", "1")]
    store = _GrantStore(arts, gated={"collection:p/legacy"},
                        reach={"john": {"collection:p/legacy"}})
    _patched_access(monkeypatch, store)
    top = canon.canon_browse_handler(store)({"principal": "john"})
    assert "legacy" in {i["title"] for i in top["items"]}
    assert top["extent"] == len(CORPUS) + 2


def test_a_gated_SECTION_reads_as_ABSENT_not_as_forbidden(monkeypatch):
    """Fails if the answer is "you may not read this", which tells an anonymous caller the section
    exists — and its id carries the doc name. A gated section and a missing section must look the
    same to an anonymous caller."""
    arts = CORPUS + [_art("p/legacy", "OLD", "intro")]
    store = _GrantStore(arts, gated={"collection:p/legacy"},
                        reach={"john": {"collection:p/legacy"}})
    _patched_access(monkeypatch, store)
    b = canon.canon_browse_handler(store)
    anon = b({"section": "canon:OLD#intro"})
    assert anon["observed"] is False and "no section at this id" in anon["why"]
    assert b({"section": "canon:OLD#intro", "principal": "john"})["observed"] is True


def test_a_PUBLIC_grant_opens_a_gated_collection_to_everyone(monkeypatch):
    """Making a private thing public is a Read grant to the public entity — no copy, no re-key."""
    arts = CORPUS + [_art("p/legacy", "OLD", "intro")]
    store = _GrantStore(arts, gated={"collection:p/legacy"}, public={"collection:p/legacy"})
    _patched_access(monkeypatch, store)
    assert "legacy" in {i["title"] for i in canon.canon_browse_handler(store)({})["items"]}


def test_the_section_view_renders_the_PROSE_with_its_citation():
    art = dict(_art("p/genesis", "SCREEN", "1"), content="the body of the section")
    class _ById(_Store):                # no `.db`: a store with no grant layer, so nothing is gated
        artifacts = type("A", (), {"get_artifact": staticmethod(lambda aid: art)})()

    store = _ById([art])
    a = canon.canon_browse_handler(store)({"section": "canon:SCREEN#1"})
    assert a["observed"] is True and a["content"] == "the body of the section"
    html = pharos.render(a)
    assert "the body of the section" in html and "canon:SCREEN#1" in html


# ── op.canon.light — a position, and the absence of one ─────────────────────────────────────────

def _lightable(arts):
    """A store the lighting tekton can read and write."""
    class _S(_Store):
        written = []

        class artifacts:
            db = None

            @staticmethod
            def put_many(docs, **kw):        # not `batch=`: the handler passes batch= as a keyword
                _S.written.extend(docs)

    s = _S(arts)
    s.artifacts.put_many = _S.artifacts.put_many
    return s


def test_a_section_that_fires_NOTHING_has_its_stale_position_CLEARED(monkeypatch):
    """Fails if prose that fires no concept keeps whatever the field already held: a query for
    "sections with no position" would then return 0 while the count reads clean and the section
    itself carries stale words. Absent must look absent."""
    monkeypatch.setattr(canon, "_fired_names", lambda text: [])
    art = dict(_art("p/x", "A", "intro"), lemmas=["imap", "mcp_tool"])
    store = _lightable([art])
    res = canon.canon_light_handler(store)({"relight": True})
    assert res["unpositioned"] == 1 and res["cleared"] == 1 and res["lit"] == 0
    assert "lemmas" not in store.written[0], "the stale words survived"


def test_relight_writes_NOTHING_when_the_position_is_unchanged(monkeypatch):
    """Fails if an unchanged position still writes — every rewrite is a lattice write with its own
    _seq, proper time spent on no change."""
    monkeypatch.setattr(canon, "_fired_names", lambda text: ["coupling", "surface"])
    art = dict(_art("p/x", "A", "intro"), lemmas=["coupling", "surface"])
    store = _lightable([art])
    res = canon.canon_light_handler(store)({"relight": True})
    assert res["lit"] == 0 and res["cleared"] == 0
    assert store.written == [], "an unchanged position was rewritten"


def test_a_position_is_what_the_prose_FIRES_not_its_frequent_words():
    """Fails if the position reaches for `astra.doc_index.extract_terms` — word frequency plus an
    identifier regex, capped at 30. A position is which concepts resolve, uncapped."""
    import inspect
    src = inspect.getsource(canon._fired_names)
    assert "wn_synsets_for" in src
    # The body, not the docstring — which names those very instruments to say it does not use them.
    body = src.split('"""')[-1]
    for banned in ("Counter", "most_common", "max_terms", "extract_terms"):
        assert banned not in body, banned
