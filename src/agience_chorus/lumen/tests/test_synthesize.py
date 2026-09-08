"""Tests for lumen's synthesize tool — retrieve, reason, respond.

All platform calls are mocked at the boundaries the tool actually uses: the retrieval reach
(`server._RETRIEVE_REACH`), the reasoning organon (`ReasoningRouter.reason`), and httpx for
cited-artifact fetches. The delegation context is driven through the auth ContextVar, exactly as the
middleware would set it.

The retrieval seam is lumen's own `_RETRIEVE_REACH` hook: a `(query, token) -> [evidence]` callable a
host wires to a reach on `op.retrieve`. Setting the hook exercises the contract lumen actually depends
on, rather than patching a foreign module's function.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

_spec = importlib.util.spec_from_file_location(
    "chorus_lumen_server_synth", _HERE.parent / "server.py"
)
_lumen_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lumen_server)

synthesize = _lumen_server.synthesize


class _Reach:
    """A stub retrieval reach that records its calls.

    Records rather than just returning hits, because the load-bearing assertion is that the reach
    receives the caller's delegation token — retrieval runs under the user's own grants, so lumen
    only ever grounds on what that user is authorised to see. A stub that only returned hits could
    not prove it.
    """

    def __init__(self, hits):
        self._hits = hits
        self.calls = []

    def __call__(self, query, token):
        self.calls.append((query, token))
        return self._hits


class _retrieval_reach:
    """Install a stub on `server._RETRIEVE_REACH` for the block, then restore.

    Setting lumen's own hook exercises the contract lumen actually depends on, rather than patching a
    foreign module's internals.
    """

    def __init__(self, hits):
        self._reach = _Reach(hits)
        self._saved = None

    def __enter__(self):
        self._saved = _lumen_server._RETRIEVE_REACH
        _lumen_server._RETRIEVE_REACH = self._reach
        return self._reach

    def __exit__(self, *exc):
        _lumen_server._RETRIEVE_REACH = self._saved
        return False


@pytest.fixture
def delegated():
    """Simulate a verified delegation in the request context."""
    tok = _lumen_server._auth.request_user_token.set("test-delegation-token")
    try:
        yield "test-delegation-token"
    finally:
        _lumen_server._auth.request_user_token.reset(tok)


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
# Refusal paths — computed findings, never canned
# ---------------------------------------------------------------------------

class TestSynthesizeRefusal:

    @pytest.mark.asyncio
    async def test_no_delegation_no_evidence_refuses(self):
        """Without a delegation there is no corpus leg; the refusal names it."""
        result = json.loads(await synthesize(input="what is agience?"))
        assert result["answer"] is None
        assert result["citations"] == []
        assert result["refusal"] is not None
        assert result["refusal"]["evidence_count"] == 0
        # The missing leg is a named computed finding, not a generic apology.
        assert any("no verified user delegation" in f for f in result["refusal"]["findings"])

    @pytest.mark.asyncio
    async def test_empty_retrieval_refuses_with_finding(self, delegated):
        """Delegated but zero hits: refusal reports the measured empty retrieve."""
        with _retrieval_reach([]) as ret:
            result = json.loads(await synthesize(input="unknown topic"))
        assert len(ret.calls) == 1, "the retrieval reach was not called exactly once: %r" % (ret.calls,)
        assert ret.calls[0][0] == "unknown topic"
        assert ret.calls[0][1] == "test-delegation-token", \
            "the reach must receive the CALLER's delegation token — retrieval respects the user's grants"
        assert result["answer"] is None
        assert result["refusal"]["evidence_count"] == 0
        assert any("op.retrieve returned no evidence" in f for f in result["refusal"]["findings"])

    @pytest.mark.asyncio
    async def test_non_compact_series_refusal_is_computed(self):
        """A numeric series with no compact law: the quantitative refusal carries
        the measured regime, and with no evidence the whole answer refuses."""
        _op_reason = _lumen_server._op_reason

        series = "\n".join(f"{i} {i * 3}" for i in range(1, 13))
        refused = _op_reason.ReasoningResult(_op_reason.NON_COMPACT, complexity=5, curve=[5])
        with patch.object(_op_reason.ReasoningRouter, "reason", return_value=refused):
            result = json.loads(await synthesize(input=series))
        assert result["answer"] is None
        assert result["reasoning"]["regime"] == _op_reason.NON_COMPACT
        assert "non-compact" in result["reasoning"]["refusal"]
        assert "non-compact" in result["refusal"]["reason"]


# ---------------------------------------------------------------------------
# Grounded answers — cited, budgeted, honest about every leg
# ---------------------------------------------------------------------------

class TestSynthesizeGrounded:

    @pytest.mark.asyncio
    async def test_retrieval_hits_become_cited_answer(self, delegated):
        hits = [
            {"id": "art-1", "title": "Doc One", "content": "alpha content", "score": 2.0},
            {"id": "art-2", "title": "Doc Two", "content": "beta content", "score": 1.0},
        ]
        with _retrieval_reach(hits):
            result = json.loads(await synthesize(input="alpha?"))
        assert result["refusal"] is None
        assert result["citations"] == ["art-1", "art-2"]
        assert "Doc One" in result["answer"]
        assert "alpha content" in result["answer"]

    @pytest.mark.asyncio
    async def test_cited_artifacts_fetched_under_delegation(self, delegated):
        """Explicit artifact_ids are fetched with the caller's delegation JWT."""
        seen_headers = {}

        def handler(method, url, **kw):
            seen_headers.update(kw.get("headers") or {})
            assert method == "GET" and "cited-1" in url
            return MockResponse({
                "id": "cited-1",
                "content": "the cited body",
                "context": {"title": "Cited Card"},
            })

        with patch("httpx.AsyncClient", return_value=_client(handler)), \
             _retrieval_reach([]):
            result = json.loads(await synthesize(
                input="about the cited card",
                artifact_ids=["cited-1"],
                workspace_id="ws-1",
            ))

        assert seen_headers.get("Authorization") == "Bearer test-delegation-token"
        assert result["citations"] == ["cited-1"]
        assert "the cited body" in result["answer"]
        # The empty corpus leg is still reported honestly alongside the answer.
        assert any("op.retrieve returned no evidence" in f for f in result["findings"])

    @pytest.mark.asyncio
    async def test_cited_artifacts_without_delegation_fail_closed(self):
        """Caller-supplied ids with no delegation: the fetch is refused, not
        escalated to the persona's platform identity."""
        result = json.loads(await synthesize(input="q", artifact_ids=["a-1"]))
        assert result["answer"] is None
        assert any("cited-artifact fetch refused" in f for f in result["refusal"]["findings"])

    @pytest.mark.asyncio
    async def test_deterministic_series_yields_unverified_projection(self):
        """A compact numeric read is answered as an UNVERIFIED projection —
        the same honesty contract as op.reason's own grounding message."""
        import numpy as np
        _op_reason = _lumen_server._op_reason

        series = "\n".join(f"{i} {i * 2}" for i in range(1, 13))
        res = _op_reason.ReasoningResult(
            _op_reason.DETERMINISTIC, "ember.optics",
            np.array([[13.0, 26.0], [14.0, 28.0]]), None, 3, float("nan"), [3],
        )
        with patch.object(_op_reason.ReasoningRouter, "reason", return_value=res):
            result = json.loads(await synthesize(input=series))
        assert result["refusal"] is None
        assert "UNVERIFIED projection" in result["answer"]
        assert result["reasoning"]["regime"] == _op_reason.DETERMINISTIC
        assert result["reasoning"]["forecast"] == [[13.0, 26.0], [14.0, 28.0]]
        # No corpus evidence was involved: the projection cites nothing.
        assert result["citations"] == []
