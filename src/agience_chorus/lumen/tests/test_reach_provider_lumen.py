"""The P7 capstone reach, end-to-end: ember reaches lumen's `op.respond` over the ground plane.

The conversation tekton lives in lumen (`lumen/conversation.py`); ember is simply a runner and reaches
it. This proves the wiring on both sides of the wire (mirrors `sage/tests/test_reach_provider.py`):

  - Provider = lumen. `lumen.reach_provider.serve_respond(...)` stands lumen up as the provider of
    `op.respond`, wired with the chorus-side plane adapters (`iris/comms/wiring.MantleKeyring/
    MantleLightcone`) over lumen's real grant light-cone (`mantle.db.access.reachable_collections`).
  - Requester = ember. `ember.runtime.reach.reach(store, principal, need, to="op.respond", ...)` — the exact call
    the runner makes. Ember imports no chorus; it reaches over `beam.comms` only.

Both share one `LoopbackFabric` and one `root_secret`, so the ground key each derives coincides and the
circuit completes. Named invariants proven (to `TEST-ARCHITECTURE.md`):

  delivery   — ember gets exactly lumen's op.respond evidence (the handler result, verbatim), sealed and
               crossed the plane (`handled[handle] == evidence`, not a shared object); and the
               fire-and-collect `ember.runtime.reach.reach(...)` convenience returns the same.
  provenance — the evidence references the need (`root == in_reply_to == handle`, `origin == "lumen"`,
               `cap == "op.respond"`); ember correlates by provenance, no carried return address.
  isolation  — a principal grounded on a different plane than lumen picks up nothing (ground isolation).
  honesty    — without a substrate the provider resolves with `local_respond` = the computed null
               (`answer=None`, no citation) echoing the query. It never fabricates; full conversation
               behavior (respond/learn/act over WordNet) is verified in `test_conversation.py`, which
               needs a built substrate and skips without one (gated). Cross-process carrier wiring is a
               separate gated deploy step — this suite is loopback/same-process by design.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare `import reach_provider`

from agience_chorus import _persona  # noqa: E402

# `sys.modules` is keyed by name and process-global, so a bare `import reach_provider` /
# `import manifest` resolves to whichever persona imported it first — several personas own a
# module by each of those names, and in a combined chorus run that misdirects sage's tests to
# lumen's provider (`AttributeError: … no attribute 'serve_retrieve'`). `_persona.load` loads
# this persona's copy under the unique name `<persona>.<module>`, so that substitution is
# impossible.
reach_provider = _persona.load("reach_provider", __file__)

import ember.runtime.reach as er  # noqa: E402  (the Apache runner side — imports no chorus)
from prism.streams import LoopbackFabric  # noqa: E402

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


def _wire(offers, *, lumen_ground="ground", req_ground="ground", requester="ember"):
    """Stand up lumen (provider) + a requester (ember runner) on one fabric, over one grant store."""
    store = _store_granting(offers)
    root = b"genesis-fleet-root"
    fabric = LoopbackFabric()
    lumen = reach_provider.serve_respond(store, root_secret=root, fabric=fabric, ground=lumen_ground)
    req = er.reactor(store, requester, root_secret=root, fabric=fabric, ground=req_ground)
    return store, root, fabric, lumen, req


# ── delivery + honesty + provenance: ember reaches lumen's op.respond, gets lumen's evidence ──────────
def test_ember_reaches_lumen_op_respond_over_the_ground():
    store, root, fabric, lumen, ember = _wire({"lumen": {"op.respond"}})

    need = {"text": "what is a dog"}
    # the call site — ember places the need on op.respond; evidence returns via the ground plane.
    handle = ember.reach(need, to="op.respond")
    evidence = ember.evidence(handle)

    # delivery + honesty: exactly lumen's op.respond result (the honest computed null, query echoed).
    oracle = reach_provider.local_respond(need["text"], act="respond")
    assert evidence == oracle
    assert evidence["answer"] is None and evidence["cited"] == []       # never fabricates without substrate
    assert evidence["echo"] == "what is a dog"                          # query-dependent (crossed the plane)

    # crossed the plane sealed, not a shared object: lumen absorbed the same band it discharged.
    handled = None
    for prov in lumen._providers:
        if handle in prov.handled:
            handled = prov.handled[handle]
    assert handled == evidence

    # provenance: the evidence references the need; ember correlates on the ground, no return address.
    prov = ember.provenance(handle)
    assert prov and prov[0]["in_reply_to"] == handle and prov[0]["root"] == handle
    assert prov[0]["origin"] == "lumen" and prov[0]["cap"] == "op.respond"

    # and the fire-and-collect convenience (the one an ember call site actually uses) returns the same.
    ev2 = er.reach(store, "ember", need, to="op.respond", root_secret=root, fabric=fabric)
    assert ev2 == evidence


# ── honesty: a query-dependent echo (two texts → different evidence), and the act siblings are served ─
def test_respond_is_query_dependent_and_the_act_siblings_serve():
    _store, _root, _fabric, lumen, ember = _wire({"lumen": {"op.respond", "op.act", "op.learn", "op.thought"}})

    a = ember.evidence(ember.reach({"text": "what is a dog"}, to="op.respond"))
    b = ember.evidence(ember.reach({"text": "what is a cat"}, to="op.respond"))
    assert a["echo"] != b["echo"]                                       # the query changed the evidence

    # the act/learn/thought siblings are served by the same provider (each in its own act shape).
    act = ember.evidence(ember.reach({"text": "a dog says woof"}, to="op.act"))
    learn = ember.evidence(ember.reach({"text": "a dog says woof"}, to="op.learn"))
    thought = ember.evidence(ember.reach({"text": "what says woof"}, to="op.thought"))
    assert act["act"] == "act" and learn["act"] == "learn" and thought["act"] == "think"


# ── isolation: a requester grounded on a different plane than lumen picks up nothing ──────────────────
def test_requester_on_a_different_ground_gets_nothing():
    store = _store_granting({"lumen": {"op.respond"}, "ember": {"op.respond"}, "snoop": {"op.respond"}})
    root = b"root"
    fabric = LoopbackFabric()
    reach_provider.serve_respond(store, root_secret=root, fabric=fabric, ground="mesh")
    ember = er.reactor(store, "ember", root_secret=root, fabric=fabric, ground="mesh")   # same ground
    snoop = er.reactor(store, "snoop", root_secret=root, fabric=fabric, ground="other")  # different ground

    handle = ember.reach({"text": "what is a dog"}, to="op.respond")
    assert ember.evidence(handle) == reach_provider.local_respond("what is a dog")   # shares ground → gets it
    assert snoop._inbox.bands(handle) == []                                          # not on lumen's ground


# ── discipline: the requester side (ember.runtime.reach) pulls in no chorus/lumen even after a full reach ─────
def test_ember_side_pulls_in_no_chorus_module():
    import inspect
    src = inspect.getsource(er)
    for banned in ("import iris", "from iris", "import chorus", "from chorus",
                   "import lumen", "from lumen", "import sage", "from sage"):
        assert banned not in src, "ember/reach.py must stay runner-side — found %r" % banned
