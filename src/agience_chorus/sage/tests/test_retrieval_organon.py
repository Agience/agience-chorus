"""sage's retrieval organon (op.retrieve) — sage's sole capability; lumen reaches it rather than
keeping a copy. Pins: the module imports cleanly (numpy + beam + stdlib only),
`register_retrieval_operators` registers op.retrieve through the fitness substrate, and retrieval
is fail-soft without a token."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

from agience_chorus.sage import retrieval  # noqa: E402


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


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _client(search_status=200):
    asked = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, **kw):
            asked.append(("get", url, None))
            return _Resp({"id": "s-1", "context": {"rank": ["rarity", "recency"], "size": 2}},
                         search_status)

        def post(self, url, json=None, **kw):
            asked.append(("post", url, json))
            hits = [{"id": "common", "title": "c", "content": "x", "matched": ["plan"],
                     "modified_time": "2026-03"},
                    {"id": "rare", "title": "r", "content": "y", "matched": ["trip"],
                     "modified_time": "2026-01"},
                    {"id": "c2", "title": "c2", "content": "z", "matched": ["plan"],
                     "modified_time": "2026-02"}]
            return _Resp({"hits": hits, "total": 3})
    return Client, asked


def test_a_search_runs_as_crystal_runs_it(monkeypatch):
    """A named Search reads what the caller may read newest first and orders it by its rank."""
    import httpx
    client, asked = _client()
    monkeypatch.setattr(httpx, "Client", client)
    hits = retrieval.retrieve("plan trip", "tok", "http://mantle", search_id="s-1")
    assert [h["id"] for h in hits] == ["rare", "common"]
    posted = [b for verb, _, b in asked if verb == "post"]
    assert posted and all(b["sort"] == "recency" and "search_id" not in b for b in posted)


def test_a_search_the_caller_cannot_read_falls_back_to_the_plain_recall(monkeypatch):
    import httpx
    client, asked = _client(search_status=403)
    monkeypatch.setattr(httpx, "Client", client)
    hits = retrieval.retrieve("plan trip", "tok", "http://mantle", k=6, search_id="s-1")
    assert [h["id"] for h in hits] == ["common", "rare", "c2"]
    assert [b for verb, _, b in asked if verb == "post"] == [
        {"query_text": "plan trip", "size": 6, "highlight": True}]
