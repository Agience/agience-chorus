"""The router's content arm is a reach, and it is inactive without a carrier (no fabrication).

BM25 retrieval lives in sage, not ember ([[ember-is-a-runner]]); the router reaches sage's `op.retrieve`
over the ground plane. These are the ember-side (chorus-free) contracts:

  - default None fabric/root_secret ⇒ the arm is skipped, and with no working set the router
    answers honestly (domain 'semantic') rather than manufacturing a content answer — the whole
    point of not shipping the carrier on a hunch;
  - `_answer_from_evidence` shapes sage's `[{id,title,content,score}]` evidence into a grounded,
    cited Answer, and empty evidence is not grounded (silence stays silence).

The active arm (loopback fabric + a real sage provider) is proven cross-boundary in
`agience-chorus/src/sage/tests/test_reach_provider.py::test_router_content_arm_reaches_sage_op_retrieve`.
"""
# The router is lumen's, so these tests live in lumen/tests: the content arm is a reach, inactive
# without a carrier, and empty evidence is not grounded (silence stays silence).
try:                                             # robust: cross-persona host vs in-persona process
    from agience_chorus.lumen import router                     # (chorus/src on path)
except ImportError:
    from agience_chorus.lumen import router                                # (lumen/ on path)


class _Arts:
    def get_artifact(self, _aid):
        return None


class _Store:
    artifacts = _Arts()
    graph = None
    content = None


def test_content_arm_is_inactive_without_a_carrier():
    # store present, but no fabric/root_secret: the reach arm must not fire. With ember=None and no
    # content index reachable, the honest outcome is an ungrounded answer (domain 'semantic'), never
    # a fabricated content answer produced by a carrier that was never wired.
    ans, domain = router.route(_Store.artifacts, None, "the french revolution", store=_Store())
    assert domain == "semantic"
    assert not ans.grounded


def test_answer_from_evidence_shapes_a_grounded_cited_answer():
    ev = [{"id": "d.1", "title": "Ada Lovelace",
           "content": "Ada Lovelace wrote the first algorithm.", "score": 0.9}]
    a = router._answer_from_evidence("who was ada lovelace", ev)
    assert a.grounded
    assert "d.1" in a.cited
    assert "Ada Lovelace" in a.text
    assert a.read.get("via") == "reach:op.retrieve"


def test_empty_evidence_is_not_grounded():
    a = router._answer_from_evidence("anything", [])
    assert not a.grounded and a.cited == []
