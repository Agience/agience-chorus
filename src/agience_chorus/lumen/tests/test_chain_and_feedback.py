"""Tests for Lumen's chain_tasks and submit_feedback tools.

Platform calls are mocked via httpx; the delegation context is driven through
the auth ContextVar exactly as the middleware would set it. Both tools act on
caller-chosen resources, so both must fail closed without a delegation.
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
    "chorus_lumen_server_chain", _HERE.parent / "server.py"
)
_lumen_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lumen_server)

chain_tasks = _lumen_server.chain_tasks
submit_feedback = _lumen_server.submit_feedback


@pytest.fixture
def delegated():
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

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            request = httpx.Request("POST", "http://test")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=request, response=response)


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
# chain_tasks
# ---------------------------------------------------------------------------

class TestChainTasks:

    @pytest.mark.asyncio
    async def test_invalid_json(self, delegated):
        result = json.loads(await chain_tasks(steps="not json"))
        assert "not valid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_steps(self, delegated):
        result = json.loads(await chain_tasks(steps="[]"))
        assert "non-empty" in result["error"]

    @pytest.mark.asyncio
    async def test_fails_closed_without_delegation(self):
        steps = json.dumps([{"server": "sage", "tool": "search", "arguments": {}}])
        result = json.loads(await chain_tasks(steps=steps))
        assert "delegation" in result["error"]

    @pytest.mark.asyncio
    async def test_sequential_chain_threads_prev(self, delegated):
        """Two steps: the second receives the first's result via "$prev"."""
        calls = []

        def handler(method, url, **kw):
            assert method == "POST"
            calls.append((url, kw.get("json"), kw.get("headers")))
            n = len(calls)
            return MockResponse({"output": f"result-{n}"})

        steps = json.dumps([
            {"server": "sage", "tool": "search", "arguments": {"query": "alpha"}},
            {"server": "aria", "tool": "present", "arguments": {"content": "$prev"}},
        ])
        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await chain_tasks(steps=steps, workspace_id="ws-1"))

        assert result["steps_executed"] == 2
        assert result["final"] == {"output": "result-2"}
        # First call: dispatched to sage via the artifact-invoke path.
        url0, body0, hdrs0 = calls[0]
        assert "/artifacts/sage/op/invoke" in url0
        assert body0 == {"name": "search", "arguments": {"query": "alpha"}, "workspace_id": "ws-1"}
        assert hdrs0["Authorization"] == "Bearer test-delegation-token"
        # Second call: "$prev" resolved to the first step's full result.
        _, body1, _ = calls[1]
        assert body1["arguments"]["content"] == {"output": "result-1"}

    @pytest.mark.asyncio
    async def test_aborts_on_step_failure(self, delegated):
        def handler(method, url, **kw):
            if "bad" in url:
                return MockResponse({"detail": "boom"}, status_code=500)
            return MockResponse({"output": "ok"})

        steps = json.dumps([
            {"server": "good", "tool": "t1", "arguments": {}},
            {"server": "bad", "tool": "t2", "arguments": {}},
            {"server": "never", "tool": "t3", "arguments": {}},
        ])
        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await chain_tasks(steps=steps))

        assert "aborted at step 1" in result["error"]
        statuses = [r["status"] for r in result["results"]]
        assert statuses == ["completed", "error"]  # step 2 never dispatched


# ---------------------------------------------------------------------------
# submit_feedback
# ---------------------------------------------------------------------------

class TestSubmitFeedback:

    @pytest.mark.asyncio
    async def test_nothing_to_record(self, delegated):
        result = json.loads(await submit_feedback(artifact_id="a-1"))
        assert "nothing to record" in result["error"]

    @pytest.mark.asyncio
    async def test_rating_outside_declared_scale(self, delegated):
        result = json.loads(await submit_feedback(artifact_id="a-1", rating=9))
        assert "1-5" in result["error"]

    @pytest.mark.asyncio
    async def test_fails_closed_without_delegation(self):
        result = json.loads(await submit_feedback(artifact_id="a-1", rating=4))
        assert "delegation" in result["error"]

    @pytest.mark.asyncio
    async def test_records_feedback_artifact(self, delegated):
        captured = {}

        def handler(method, url, **kw):
            assert method == "POST" and url.endswith("/artifacts")
            captured["payload"] = kw.get("json")
            captured["headers"] = kw.get("headers")
            return MockResponse({"id": "fb-1"})

        with patch("httpx.AsyncClient", return_value=_client(handler)):
            result = json.loads(await submit_feedback(
                artifact_id="a-1", rating=5, feedback="good", workspace_id="ws-1",
            ))

        assert result["recorded"] is True
        assert result["feedback_artifact_id"] == "fb-1"
        payload = captured["payload"]
        assert payload["content_type"] == "application/vnd.agience.feedback+json"
        assert payload["container_id"] == "ws-1"
        ctx = json.loads(payload["context"])
        assert ctx["operator"] == "lumen:submit_feedback"
        assert ctx["subject_artifact_id"] == "a-1"
        body = json.loads(payload["content"])
        assert body == {"subject_artifact_id": "a-1", "rating": 5, "feedback": "good"}
        # Written under the caller's delegation, never the service identity.
        assert captured["headers"]["Authorization"] == "Bearer test-delegation-token"
