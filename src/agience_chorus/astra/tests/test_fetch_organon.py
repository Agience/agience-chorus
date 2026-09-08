"""astra's fetch organon (op.fetch.get) lives in the ingestion persona that owns it. It reaches the
real world (an external network GET), so it carries a real-world `requires`. Pins: registration
writes op.fetch.get through the fitness substrate."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

from agience_chorus.astra import fetch  # noqa: E402


class _Capture:
    def __init__(self):
        self.docs = {}

    def get_artifact(self, aid):
        return self.docs.get(aid)

    def put_artifact(self, doc):
        self.docs[doc["id"]] = dict(doc)
        return doc


def test_fetch_registers_op_fetch_get():
    cap = _Capture()
    n = fetch.register_fetch_operators(cap)
    assert n == 1
    assert set(cap.docs) == {"op.fetch.get"}
    doc = cap.docs["op.fetch.get"]
    assert doc["content_type"] == "application/vnd.agience.operator+json"
