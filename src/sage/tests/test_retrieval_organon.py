"""sage's retrieval organon (op.retrieve) — sage's sole capability; lumen reaches it rather than
keeping a copy. Pins: the module imports cleanly (numpy + beam + stdlib only),
`register_retrieval_operators` registers op.retrieve through the fitness substrate, and retrieval
is fail-soft without a token."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

import retrieval  # noqa: E402


class _Capture:
    def __init__(self):
        self.docs = {}

    def get_artifact(self, aid):
        return self.docs.get(aid)

    def put_artifact(self, doc):
        self.docs[doc["id"]] = dict(doc)
        return doc


def test_retrieval_registers_op_retrieve():
    store = _Capture()
    n = retrieval.register_retrieval_operators(store)
    assert n == 1
    doc = store.docs["op.retrieve"]
    assert doc["content_type"] == "application/vnd.agience.operator+json"


def test_retrieval_is_fail_soft_without_a_token():
    # No token -> no network, empty evidence. Never raises.
    assert retrieval.retrieve("anything", None, "http://mantle.invalid") == []


def test_no_prompt_builder_survives():
    """This module carries no `build_grounding_message` or `augment`: no LLM system prompt is
    assembled here and no messages array is built for a model to consume. The no-models rule
    means retrieval returns evidence, never a prompt shaped to feed a model."""
    assert not hasattr(retrieval, "build_grounding_message")
    assert not hasattr(retrieval, "augment")
    assert "augment" not in retrieval.__all__
