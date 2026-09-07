"""A real cross-persona reach, end-to-end: ember reaches sage's `op.retrieve` over the ground plane.

Both sides of the wire are real and independent, proving the pattern rather than a stub:

  - provider = sage. `sage.reach_provider.serve_retrieve(...)` stands sage up as the provider of
    `op.retrieve`, wired with the chorus-side plane adapters (`iris/comms/wiring.MantleKeyring/
    MantleLightcone`) over sage's own grant light-cone (`mantle.db.access.reachable_collections`),
    resolving with sage's real retrieval shape (`local_retrieve` → `[{id,title,content,score}]`), not a
    canned stub.
  - requester = ember. `ember.runtime.reach.reach(store, principal, need, to="op.retrieve", ...)` — the
    exact call an Apache runner makes. Ember imports no chorus; it reaches over `beam.comms` only.

Both share one `LoopbackFabric` and one `root_secret`, so the ground key each derives (ember's
`EmberKeyring` vs sage's `MantleKeyring`, both `collection_key(root, group)`) coincides and the circuit
completes. To the `TEST-ARCHITECTURE.md` bar, the named invariants proven here are:

  delivery   — ember gets exactly sage's hits (the `local_retrieve` result, verbatim), sealed and crossed
               the plane (`handled[handle] == evidence`, not a shared object); and the fire-and-collect
               `ember.runtime.reach.reach(...)` convenience returns the same.
  provenance — the evidence references the need (`root == in_reply_to == handle`, `origin == "sage"`); ember
               correlates by provenance on the ground, no carried return address.
  isolation  — a principal grounded on a different plane than sage picks up nothing (ground isolation); and a
               would-be provider whose light-cone does not reach `op.retrieve` absorbs nothing (key-gated).
  real shape — the evidence is sage's `[{id,title,content,score}]` contract, computed by a query-dependent
               ranker (two different queries → different rankings), so the reach is proven against sage's
               real retrieval, not a placeholder.

Cross-process carrier wiring (a real WebRTC/QUIC/RF fabric plus a durable ground carrier) is a separate
gated deploy step; this suite runs loopback, same-process, by design.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare `import reach_provider`

import _persona  # noqa: E402

# `sys.modules` is keyed by name and process-global, so a bare `import reach_provider` /
# `import manifest` means whichever persona imported it first — and several personas own a
# module by each of those names, so a combined chorus run risks handing one persona's tests
# another persona's module. `_persona.load` loads this persona's copy under the unique name
# `<persona>.<module>`, so substitution is impossible.
reach_provider = _persona.load("reach_provider", __file__)

import ember.runtime.reach as er  # noqa: E402  (the Apache runner side — imports no chorus)
import ember.ontology.match as _ember_match  # noqa: E402  (patched to keep the real-corpus test WordNet-free)
# The router lives in lumen (it dispatches and composes prose — persona acts). This test exercises
# the cross-persona path lumen-router -> sage `op.retrieve`, which is persona-to-persona over the
# plane, not a runner call site.
from lumen import router as _ember_router  # noqa: E402
from mantle.shard.local_store import LocalStore  # noqa: E402
from prism.streams import LoopbackFabric  # noqa: E402
from mantle.db import open_lattice as _open_lattice  # noqa: E402
import corpus_fts as _fts  # noqa: E402  (chorus's vendored lexical index — see corpus_fts.py)

_GRANT_CT = "application/vnd.agience.grant+json"


# ── a tiny real grant store: drives `mantle.db.access.reachable_collections` on both sides ────────────────
class _FakeArtifacts:
    def __init__(self, grants):
        self._grants = list(grants)

    def list_artifacts(self, content_type=None, state=None, include_archived=False):
        # `include_archived` is part of the store contract the light-cone calls against:
        # `lattice_api._grant_docs_by` falls back to `list_artifacts(..., include_archived=True)`
        # when the seek index is absent, because a grant's authority is judged from every lifecycle
        # state and not only the active one. A fake that drops the argument is not the store.
        if content_type != _GRANT_CT:
            return []
        return [g for g in self._grants
                if (state is None or g.get("state") == state)
                and (include_archived or g.get("state") != "archived")]


class _FakeStore:
    def __init__(self, grants):
        self.artifacts = _FakeArtifacts(grants)
        self.graph = None


def _grant(grantee, resource):
    # `effect` is half of a grant's authority and is matched positively: `entities.grant.mask_of`
    # reads the CRUDEASIO bits for WHICH action and `effect` for whether the grant authorizes at
    # all, and an absent or unrecognized effect confers nothing (fail-closed, so a deny grant can
    # never read as an allow). A doc without it is not a grant the light-cone reaches through.
    return {"content_type": _GRANT_CT, "state": "active", "effect": "allow",
            "grantee_id": grantee, "grantee_type": "user",
            "can_read": True, "resource_id": resource}


def _store_granting(offers):
    """A real store whose grants encode `offers = {principal -> {caps}}`: reaching a capability collection
    = being granted read on it (so the principal's ember-access light-cone reaches it)."""
    grants = [_grant(p, c) for p, cs in offers.items() for c in cs]
    return _FakeStore(grants)


# ── the corpus sage retrieves over (a throwaway in-memory doc set, sage-owned scoring) ────────────────
DOCS = [
    {"id": "d.hamlet", "title": "Hamlet", "content": "Hamlet is a tragedy written by William Shakespeare."},
    {"id": "d.macbeth", "title": "Macbeth", "content": "Macbeth is a tragedy written by William Shakespeare."},
    {"id": "d.newton", "title": "Principia", "content": "Isaac Newton described the laws of motion and gravity."},
    {"id": "d.gravity", "title": "Gravity", "content": "Gravity is the attraction between masses, per Newton."},
]


def _wire(offers, *, docs=DOCS, sage_ground="ground", req_ground="ground", requester="lumen"):
    """Stand up sage (provider) + a requester (ember runner) on one fabric, over one grant store."""
    store = _store_granting(offers)
    root = b"genesis-fleet-root"
    fabric = LoopbackFabric()
    sage = reach_provider.serve_retrieve(store, root_secret=root, fabric=fabric, docs=docs,
                                         ground=sage_ground)
    req = er.reactor(store, requester, root_secret=root, fabric=fabric, ground=req_ground)
    return store, root, fabric, sage, req


# ── delivery + real shape + provenance: ember reaches sage's op.retrieve, gets sage's real hits ───────
def test_ember_reaches_sage_op_retrieve_over_the_ground():
    store, root, fabric, sage, lumen = _wire({"sage": {"op.retrieve"}})

    need = {"query": "who wrote Hamlet?"}
    # the call site — ember places the NEED on op.retrieve; evidence returns via the ground plane.
    handle = lumen.reach(need, to="op.retrieve")
    evidence = lumen.evidence(handle)

    # delivery + real shape: exactly sage's own retrieval result, in the [{id,title,content,score}] contract.
    oracle = reach_provider.local_retrieve(need["query"], DOCS)
    assert evidence == oracle
    assert oracle[0]["id"] == "d.hamlet"                             # the ranker actually ranked (Hamlet top)
    assert all(set(h) == {"id", "title", "content", "score"} for h in evidence)

    # crossed the plane sealed, not a shared object: sage absorbed the same band it discharged.
    assert sage._providers[0].handled[handle] == evidence

    # provenance: the evidence references the need; ember correlates on the ground, no return address.
    prov = lumen.provenance(handle)
    assert prov and prov[0]["in_reply_to"] == handle and prov[0]["root"] == handle
    assert prov[0]["origin"] == "sage" and prov[0]["cap"] == "op.retrieve"

    # and the fire-and-collect convenience (the one an ember call site actually uses) returns the same.
    ev2 = er.reach(store, "lumen", need, to="op.retrieve", root_secret=root, fabric=fabric)
    assert ev2 == evidence


# ── real shape: a query-dependent ranker (two queries → different rankings), not a canned stub ────────
def test_retrieval_is_query_dependent_not_a_stub():
    _store, _root, _fabric, _sage, lumen = _wire({"sage": {"op.retrieve"}})

    top_shakespeare = lumen.evidence(lumen.reach({"query": "Shakespeare tragedy"}, to="op.retrieve"))
    top_gravity = lumen.evidence(lumen.reach({"query": "Newton gravity motion"}, to="op.retrieve"))

    assert top_shakespeare and top_gravity
    assert {h["id"] for h in top_shakespeare} <= {"d.hamlet", "d.macbeth"}     # only the Shakespeare docs
    assert {h["id"] for h in top_gravity} <= {"d.newton", "d.gravity"}         # only the physics docs
    assert top_shakespeare != top_gravity                                      # the query changed the answer


# ── delivery: the top-k budget (need's `k`) is honored end-to-end ─────────────────────────────────────
def test_need_k_bounds_the_hits_returned():
    _store, _root, _fabric, _sage, lumen = _wire({"sage": {"op.retrieve"}})
    ev = lumen.evidence(lumen.reach({"query": "William Shakespeare Newton", "k": 1}, to="op.retrieve"))
    assert len(ev) == 1                                                         # k rode the NEED across the plane


# ── isolation: a requester grounded on a different plane than sage picks up nothing ───────────────────
def test_requester_on_a_different_ground_gets_nothing():
    # sage discharges evidence onto ground "mesh"; a snoop connected to a different ground "other" is not on
    # sage's return surface, so the circuit stays open for it — even though it, too, is granted op.retrieve.
    store = _store_granting({"sage": {"op.retrieve"}, "lumen": {"op.retrieve"}, "snoop": {"op.retrieve"}})
    root = b"root"
    fabric = LoopbackFabric()
    reach_provider.serve_retrieve(store, root_secret=root, fabric=fabric, docs=DOCS, ground="mesh")
    lumen = er.reactor(store, "lumen", root_secret=root, fabric=fabric, ground="mesh")   # same ground → connected
    snoop = er.reactor(store, "snoop", root_secret=root, fabric=fabric, ground="other")  # a different ground

    handle = lumen.reach({"query": "Hamlet"}, to="op.retrieve")
    assert lumen.evidence(handle)[0]["id"] == "d.hamlet"               # shares sage's ground → gets the answer
    assert snoop._inbox.bands(handle) == []                           # not on sage's ground → nothing at all


# ── isolation: a would-be provider whose light-cone lacks op.retrieve absorbs nothing (key-gated) ─────
def test_a_non_granted_provider_absorbs_nothing():
    # mallory subscribes a rival op.retrieve handler but is granted nothing → never derives the cap key, so
    # the sealed NEED is opaque to it. Only sage (granted) opens the question.
    store = _store_granting({"sage": {"op.retrieve"}})               # mallory absent → no op.retrieve key
    root = b"root"
    fabric = LoopbackFabric()
    reach_provider.serve_retrieve(store, root_secret=root, fabric=fabric, docs=DOCS)
    mallory = er.reactor(store, "mallory", root_secret=root, fabric=fabric)
    mal_prov = mallory.serve("op.retrieve", lambda need: [{"id": "STOLEN", "title": "", "content": "", "score": 9}])
    lumen = er.reactor(store, "lumen", root_secret=root, fabric=fabric)

    handle = lumen.reach({"query": "Hamlet"}, to="op.retrieve")
    assert lumen.evidence(handle)[0]["id"] == "d.hamlet"             # sage answered
    assert mal_prov.handled == {}                                    # isolation: mallory opened no sealed NEED


# ── discipline: the requester side (ember.runtime.reach) pulls in no chorus/sage even after a full reach ──────
def test_ember_side_pulls_in_no_chorus_module():
    # The ember requester must reach sage without importing chorus/sage. (This test file itself imports both,
    # so we only assert ember.runtime.reach's own module surface stays clean — the AGPL boundary ember must hold.)
    import inspect
    src = inspect.getsource(er)
    for banned in ("import iris", "from iris", "import chorus", "from chorus",
                   "import sage", "from sage", "import lumen", "from lumen"):
        assert banned not in src, "ember/reach.py must stay runner-side — found %r" % banned


# ── content_search: the provider backs onto the real content_search tekton (BM25 over a tiny corpus) ──
# A throwaway indexed lattice store — real vertices and a real FTS index — so `content_search.search`
# runs end-to-end. `wn_synsets_for` is stubbed to [] so the recall path is pure BM25 and does not
# depend on an ambient WordNet corpus (the proper-noun fallback the tekton already has).
_CORPUS_DOCS = [
    {"id": "d.hamlet", "content_type": "text/markdown", "state": "committed", "title": "Hamlet",
     "content": "Hamlet is a tragedy written by William Shakespeare."},
    {"id": "d.macbeth", "content_type": "text/markdown", "state": "committed", "title": "Macbeth",
     "content": "Macbeth is a tragedy written by William Shakespeare."},
    {"id": "d.newton", "content_type": "text/markdown", "state": "committed", "title": "Principia",
     "content": "Isaac Newton described the laws of motion and gravity."},
    {"id": "d.gravity", "content_type": "text/markdown", "state": "committed", "title": "Gravity",
     "content": "Gravity is the attraction between masses, described by Newton."},
]


def _corpus_store(tmp_path):
    """A real (tiny) ember store bundle: vertices written and an FTS index built, so
    `content_search.search` reads it exactly as it reads the live corpus."""
    L = _open_lattice(str(tmp_path / "corpus.db"), origin="test-node")
    L.artifacts.ensure_schema()
    docs = [dict(d, created_by="u", created_time="2026-01-01T00:00:00+00:00") for d in _CORPUS_DOCS]
    L.artifacts.put_many(docs, batch=100)
    _fts.rebuild_for(L.db)                       # derive the lexical index the tekton searches
    return LocalStore(artifacts=L.artifacts, graph=getattr(L, "graph", None), content=None)


def test_provider_backs_on_real_content_search(tmp_path, monkeypatch):
    """Real shape against a real index: the provider resolves `op.retrieve` with the `content_search`
    BM25 tekton over an actual indexed store, not `local_retrieve`. Ember reaches it and gets the
    corpus hit, in the `[{id,title,content,score}]` contract."""
    monkeypatch.setattr(_ember_match, "wn_synsets_for", lambda w: [])   # pure-BM25, WordNet-free
    corpus = _corpus_store(tmp_path)
    grants = _store_granting({"sage": {"op.retrieve"}})
    root = b"genesis-fleet-root"
    fabric = LoopbackFabric()
    reach_provider.serve_retrieve(grants, root_secret=root, fabric=fabric, corpus=corpus)
    lumen = er.reactor(grants, "lumen", root_secret=root, fabric=fabric)

    ev = lumen.evidence(lumen.reach({"query": "who wrote Hamlet?"}, to="op.retrieve"))
    assert ev, "the real content_search returned no hits for a corpus that holds Hamlet"
    assert ev[0]["id"] == "d.hamlet"                                    # BM25 put the only 'hamlet' doc top
    assert all(set(h) == {"id", "title", "content", "score"} for h in ev)   # op.retrieve contract
    assert "Shakespeare" in ev[0]["content"]                           # real resolved text, not a stub

    # query-dependent over the same real index (the direct handler, no plane): different query → physics docs
    grav = reach_provider.store_retrieve(corpus, "Newton gravity motion")
    assert grav and grav[0]["id"] in {"d.newton", "d.gravity"}
    assert reach_provider.store_retrieve(corpus, "") == []             # fail-soft on empty query


def test_router_content_arm_reaches_sage_op_retrieve(tmp_path, monkeypatch):
    """The runner seam, end-to-end: ember's `router.route` content arm, given a loopback fabric and
    the fleet root, reaches sage's `op.retrieve` (backed by the real content_search) and returns a
    grounded, cited answer under domain 'content' — the arm that is inactive (skipped) without a
    carrier."""
    monkeypatch.setattr(_ember_match, "wn_synsets_for", lambda w: [])
    corpus = _corpus_store(tmp_path)
    grants = _store_granting({"sage": {"op.retrieve"}})
    root = b"genesis-fleet-root"
    fabric = LoopbackFabric()
    reach_provider.serve_retrieve(grants, root_secret=root, fabric=fabric, corpus=corpus)

    ans, domain = _ember_router.route(corpus.artifacts, None, "who wrote Hamlet?", store=corpus,
                                      fabric=fabric, root_secret=root, reach_principal="ember")
    assert domain == "content" and ans.grounded
    assert "d.hamlet" in ans.cited
    assert "Shakespeare" in ans.text
    assert ans.read.get("via") == "reach:op.retrieve"                  # the answer came through the plane
