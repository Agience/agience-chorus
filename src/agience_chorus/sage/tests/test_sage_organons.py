"""sage's tekton-tool organons: op.describe.* (operators.py), op.docs.* (docs_ops.py), op.corpus.*
(corpus.py). Each registers its operators into a capture store through the fitness substrate;
sha-stable, no persistence. (retrieval / op.retrieve is sage's too but carries the lumen→sage reach —
handled separately.)"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

from agience_chorus.sage import corpus  # noqa: E402
from agience_chorus.sage import docs_ops  # noqa: E402
import agience_chorus.sage.operators as describe_operators  # noqa: E402


class _Capture:
    def __init__(self):
        self.docs = {}

    def get_artifact(self, aid):
        return self.docs.get(aid)

    def put_artifact(self, doc):
        self.docs[doc["id"]] = dict(doc)
        return doc


def test_describe_registers_op_describe():
    cap = _Capture()
    describe_operators.register_operators(cap)
    ids = {i for i in cap.docs if i.startswith("op.describe.")}
    assert ids == set(cap.docs) and len(ids) == 3            # generic + markdown + python


def test_docs_registers_op_docs():
    cap = _Capture()
    docs_ops.register_docs_operators(cap)
    ids = {i for i in cap.docs if i.startswith("op.docs.")}
    assert ids == set(cap.docs) and len(ids) == 5


def test_corpus_registers_op_corpus():
    cap = _Capture()
    corpus.register_corpus_operators(cap)
    ids = {i for i in cap.docs if i.startswith("op.corpus.")}
    assert ids == set(cap.docs) and len(ids) == 3            # audit + near_duplicates + dedup


def test_each_registered_operator_is_wellformed():
    cap = _Capture()
    for reg in (describe_operators.register_operators, docs_ops.register_docs_operators,
                corpus.register_corpus_operators):
        reg(cap)
    for doc in cap.docs.values():
        assert doc["content_type"] == "application/vnd.agience.operator+json"
        assert doc["id"].startswith("op.")
