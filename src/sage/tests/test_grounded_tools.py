"""Tests for Sage's grounded knowledge tools: ask, research, cite_sources,
extract_information.

Platform calls are mocked at the boundaries the tools actually use: the
retrieval organon (`_op_retrieve.retrieve`) and httpx for artifact fetches.
The delegation context is driven through the auth ContextVar exactly as the
middleware would set it; tools acting on caller-chosen ids must fail closed
without it.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest


# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


# 2026-08-26: an inline `spec_from_file_location` loader stood here. `src/_persona.py` is its
# one home and does strictly more — it REGISTERS the module in `sys.modules` as
# `<persona>.server`, so repeated loads return one object instead of building a second; it pops
# a half-built module when `exec_module` raises; and it names the persona in the error when the
# file is absent.
#
# Checked before converting, because this is the shape that makes lumen's six files
# unconvertible: `_persona.load` is IDEMPOTENT, so a cached module would defeat any test that
# patches an env var and expects `server` to re-read it at import. This persona's `server.py`
# does read env at import — but no test here patches one, so nothing can collide.
import _persona  # noqa: E402

_sage_server = _persona.load("server", __file__)

ask = _sage_server.ask
research = _sage_server.research
cite_sources = _sage_server.cite_sources
extract_information = _sage_server.extract_information


@pytest.fixture
def delegated():
    tok = _sage_server._auth.request_user_token.set("test-delegation-token")
    try:
        yield "test-delegation-token"
    finally:
        _sage_server._auth.request_user_token.reset(tok)


class MockResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def json(self):
        return self._json


def _client(handler):
    class _MockClient:
        async def get(self, url, **kw):
            return handler("GET", url, **kw)

        async def post(self, url, **kw):
            return handler("POST", url, **kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    return _MockClient()


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------

class TestAsk:

    @pytest.mark.asyncio
    async def test_no_delegation_no_evidence_refuses(self):
        result = json.loads(await ask(question="what is agience?"))
        assert result["answer"] is None
        assert result["citations"] == []
        assert result["refusal"]["evidence_count"] == 0
        assert any("no verified user delegation" in f for f in result["refusal"]["findings"])

    @pytest.mark.asyncio
    async def test_empty_retrieval_refuses_with_finding(self, delegated):
        with patch.object(_sage_server._op_retrieve, "retrieve", return_value=[]):
            result = json.loads(await ask(question="unknown"))
        assert result["answer"] is None
        assert any("op.retrieve returned no evidence" in f for f in result["refusal"]["findings"])

    @pytest.mark.asyncio
    async def test_retrieval_hits_become_cited_answer(self, delegated):
        hits = [{"id": "a-1", "title": "Doc", "content": "the body", "score": 1.0}]
        with patch.object(_sage_server._op_retrieve, "retrieve", return_value=hits):
            result = json.loads(await ask(question="doc?"))
        assert result["refusal"] is None
        assert result["citations"] == ["a-1"]
        assert "the body" in result["answer"]

    @pytest.mark.asyncio
    async def test_cited_cards_fetched_under_delegation(self, delegated):
        seen = {}

        def handler(method, url, **kw):
            seen["url"] = url
            seen["headers"] = kw.get("headers")
            return MockResponse({
                "id": "card-1", "content": "card body",
                "context": {"title": "Card One"},
            })

        with patch("httpx.AsyncClient", return_value=_client(handler)), \
             patch.object(_sage_server._op_retrieve, "retrieve", return_value=[]):
            result = json.loads(await ask(
                question="q", workspace_id="ws-1", artifact_ids=["card-1"],
            ))

        # An artifact is addressed by its own id; the workspace is not in the path.
        assert "/artifacts/card-1" in seen["url"]
        assert "/workspaces/" not in seen["url"], (
            "the dead RunPod workspace prefix is back: %s" % seen["url"])
        assert seen["headers"]["Authorization"] == "Bearer test-delegation-token"
        assert result["citations"] == ["card-1"]
        assert "card body" in result["answer"]

    @pytest.mark.asyncio
    async def test_cited_cards_without_delegation_fail_closed(self):
        result = json.loads(await ask(question="q", artifact_ids=["card-1"]))
        assert result["answer"] is None
        assert any("cited-card fetch refused" in f for f in result["refusal"]["findings"])


# ---------------------------------------------------------------------------
# research
# ---------------------------------------------------------------------------

class TestResearch:

    @pytest.mark.asyncio
    async def test_no_delegation_refuses(self):
        result = json.loads(await research(query="anything"))
        assert result["answer"] is None
        assert "no verified user delegation" in result["refusal"]["reason"]

    @pytest.mark.asyncio
    async def test_empty_retrieval_refuses(self, delegated):
        with patch.object(_sage_server._op_retrieve, "retrieve", return_value=[]):
            result = json.loads(await research(query="unknown"))
        assert result["answer"] is None
        assert "op.retrieve returned no evidence" in result["refusal"]["reason"]
        assert result["steps"]  # the search step is still reported

    @pytest.mark.asyncio
    async def test_multi_step_deepens_and_cites(self, delegated):
        hits = [
            {"id": "r-1", "title": "One", "content": "truncated…", "score": 2.0},
            {"id": "r-2", "title": "Two", "content": "also truncated…", "score": 1.0},
        ]
        fetched = []

        def handler(method, url, **kw):
            assert method == "GET"
            aid = url.rsplit("/", 1)[-1]
            fetched.append(aid)
            return MockResponse({"id": aid, "content": f"FULL BODY of {aid}"})

        with patch("httpx.AsyncClient", return_value=_client(handler)), \
             patch.object(_sage_server._op_retrieve, "retrieve", return_value=hits):
            result = json.loads(await research(query="topic", workspace_id="ws-9"))

        assert result["refusal"] is None
        assert fetched == ["r-1", "r-2"]                  # step 2 deepened every hit
        assert result["citations"] == ["r-1", "r-2"]
        assert "FULL BODY of r-1" in result["answer"]     # digest uses the full content
        assert any("deepened 2/2" in s for s in result["steps"])
        # The honest scope note: op.retrieve does not take a container scope.
        assert any("not plumbed" in s for s in result["steps"])


# ---------------------------------------------------------------------------
# cite_sources
# ---------------------------------------------------------------------------

class TestCiteSources:

    @pytest.mark.asyncio
    async def test_empty_ids(self, delegated):
        result = json.loads(await cite_sources(artifact_ids=[], answer="x"))
        assert "nothing to cite" in result["error"]

    @pytest.mark.asyncio
    async def test_fails_closed_without_delegation(self):
        result = json.loads(await cite_sources(artifact_ids=["a-1"], answer="x"))
        assert "delegation" in result["error"]

    @pytest.mark.asyncio
    async def test_receipt_hashes_content_and_reports_unresolved(self, delegated):
        def handler(method, url, **kw):
            if "good-1" in url:
                return MockResponse({
                    "id": "good-1", "content": "hello", "content_type": "text/markdown",
                    "context": {"title": "Good"},
                })
            return MockResponse({"detail": "not found"}, status_code=404)

        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await cite_sources(
                artifact_ids=["good-1", "gone-2"], answer="the answer",
            ))

        assert result["complete"] is False
        assert result["unresolved"] == ["gone-2"]
        src = result["sources"][0]
        assert src["artifact_id"] == "good-1"
        assert src["content_sha256"] == hashlib.sha256(b"hello").hexdigest()
        assert src["content_length"] == 5
        assert result["answer_sha256"] == hashlib.sha256(b"the answer").hexdigest()


# ---------------------------------------------------------------------------
# extract_information
# ---------------------------------------------------------------------------

class TestExtractInformation:

    @pytest.mark.asyncio
    async def test_no_properties(self, delegated):
        result = json.loads(await extract_information("a-1", "ws-1", {}))
        assert "no 'properties'" in result["error"]

    @pytest.mark.asyncio
    async def test_fails_closed_without_delegation(self):
        result = json.loads(await extract_information(
            "a-1", "ws-1", {"properties": {"x": {}}},
        ))
        assert "delegation" in result["error"]

    @pytest.mark.asyncio
    async def test_json_content_extracted_by_key(self, delegated):
        def handler(method, url, **kw):
            return MockResponse({
                "id": "a-1",
                "content": json.dumps({"status": "open", "owner": "kai"}),
            })

        schema = {"properties": {"status": {}, "owner": {}, "due_date": {}}}
        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await extract_information("a-1", "ws-1", schema))

        assert result["extracted"] == {"status": "open", "owner": "kai"}
        assert result["methods"] == {"status": "json-key", "owner": "json-key"}
        assert result["missing"] == ["due_date"]   # reported, never guessed

    @pytest.mark.asyncio
    async def test_lexical_lines_extracted(self, delegated):
        content = "# Notes\n\n- Due Date: 2026-08-01\n**Owner**: kai\nirrelevant line\n"

        def handler(method, url, **kw):
            return MockResponse({"id": "a-1", "content": content})

        schema = {"properties": {"due_date": {}, "owner": {}}}
        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await extract_information("a-1", "ws-1", schema))

        assert result["extracted"] == {"due_date": "2026-08-01", "owner": "kai"}
        assert result["methods"]["due_date"] == "lexical-line"
        assert result["missing"] == []

    @pytest.mark.asyncio
    async def test_nothing_grounded_is_a_computed_refusal(self, delegated):
        def handler(method, url, **kw):
            return MockResponse({"id": "a-1", "content": "free prose with no fields"})

        schema = {"properties": {"status": {}}, "required": ["status"]}
        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await extract_information("a-1", "ws-1", schema))

        assert result["extracted"] == {}
        assert result["refusal"]["fields_requested"] == ["status"]
        assert "no-models" in result["refusal"]["reason"]

    @pytest.mark.asyncio
    async def test_required_missing_flagged_incomplete(self, delegated):
        def handler(method, url, **kw):
            return MockResponse({"id": "a-1", "content": "status: open"})

        schema = {"properties": {"status": {}, "owner": {}}, "required": ["owner"]}
        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await extract_information("a-1", "ws-1", schema))

        assert result["extracted"] == {"status": "open"}
        assert result["incomplete"]["required_missing"] == ["owner"]
