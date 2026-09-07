"""Tests for lumen's run_workflow tool and the condition evaluator.

All platform API calls are mocked via httpx responses.

`run_workflow` reaches mantle through `_get_artifact` / `_patch_artifact_context` /
`_dispatch_child_transform`, all of which require a delegation via `_require_user_headers()`,
which fails closed: `workspace_id` and every artifact id come from the caller, and there is no
platform-JWT path in the module to fall back to. The `delegated` fixture drives the auth
ContextVar exactly as the middleware would; every test in `TestRunWorkflow` needs it as a
precondition, and `TestRunWorkflowFailsClosed` covers the no-delegation side deliberately, so
"it needs a delegation" is asserted rather than assumed.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

# Import the lumen server module by file path so the bare module name
# `server` doesn't collide with other personas' `server.py` during a bulk
# pytest run (each persona has its own `server.py`).
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

_spec = importlib.util.spec_from_file_location(
    "chorus_lumen_server", _HERE.parent / "server.py"
)
_lumen_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lumen_server)
_evaluate_condition = _lumen_server._evaluate_condition
run_workflow = _lumen_server.run_workflow


@pytest.fixture
def delegated():
    """Set the verified-delegation ContextVar, as the auth middleware does on a real request."""
    tok = _lumen_server._auth.request_user_token.set("test-delegation-token")
    try:
        yield "test-delegation-token"
    finally:
        _lumen_server._auth.request_user_token.reset(tok)


def _transform_id_from_url(url: str) -> str | None:
    """Extract the artifact id segment from ``/artifacts/{id}/invoke`` URLs.

    Child-transform dispatch carries the id in the URL, so tests inspect the URL rather than the
    request body.
    """
    if "/artifacts/" not in url:
        return None
    after = url.split("/artifacts/", 1)[1]
    segment = after.split("/", 1)[0]
    return segment or None


# ---------------------------------------------------------------------------
# _evaluate_condition
# ---------------------------------------------------------------------------

class TestEvaluateCondition:
    def test_eq_match(self):
        assert _evaluate_condition({"field": "route", "eq": "direct"}, {"route": "direct"}) is True

    def test_eq_no_match(self):
        assert _evaluate_condition({"field": "route", "eq": "direct"}, {"route": "context_retrieval"}) is False

    def test_ne_match(self):
        assert _evaluate_condition({"field": "route", "ne": "direct"}, {"route": "context_retrieval"}) is True

    def test_ne_no_match(self):
        assert _evaluate_condition({"field": "route", "ne": "direct"}, {"route": "direct"}) is False

    def test_gte_match(self):
        assert _evaluate_condition({"field": "confidence", "gte": 0.95}, {"confidence": 0.97}) is True

    def test_gte_exact(self):
        assert _evaluate_condition({"field": "confidence", "gte": 0.95}, {"confidence": 0.95}) is True

    def test_gte_below(self):
        assert _evaluate_condition({"field": "confidence", "gte": 0.95}, {"confidence": 0.80}) is False

    def test_gt(self):
        assert _evaluate_condition({"field": "count", "gt": 5}, {"count": 6}) is True
        assert _evaluate_condition({"field": "count", "gt": 5}, {"count": 5}) is False

    def test_lt(self):
        assert _evaluate_condition({"field": "count", "lt": 5}, {"count": 3}) is True
        assert _evaluate_condition({"field": "count", "lt": 5}, {"count": 5}) is False

    def test_lte(self):
        assert _evaluate_condition({"field": "count", "lte": 5}, {"count": 5}) is True
        assert _evaluate_condition({"field": "count", "lte": 5}, {"count": 6}) is False

    def test_boolean_eq(self):
        assert _evaluate_condition({"field": "should_retry", "eq": True}, {"should_retry": True}) is True
        assert _evaluate_condition({"field": "should_retry", "eq": True}, {"should_retry": False}) is False

    def test_missing_field_eq_none(self):
        assert _evaluate_condition({"field": "missing", "eq": None}, {}) is True

    def test_missing_field_ne_value(self):
        assert _evaluate_condition({"field": "missing", "ne": "something"}, {}) is True

    def test_missing_field_gt_returns_false(self):
        """Comparison with None for gt/gte/lt/lte returns False."""
        assert _evaluate_condition({"field": "missing", "gt": 5}, {}) is False

    def test_no_field_returns_true(self):
        assert _evaluate_condition({}, {"route": "direct"}) is True

    def test_no_operator_returns_true(self):
        assert _evaluate_condition({"field": "route"}, {"route": "direct"}) is True


# ---------------------------------------------------------------------------
# run_workflow — mock helpers
# ---------------------------------------------------------------------------

def _make_workflow_artifact(steps: list, retry: dict | None = None) -> dict:
    """Build a mock workflow artifact response."""
    run_block = {"type": "workflow", "steps": steps}
    if retry:
        run_block["retry"] = retry
    return {
        "id": "workflow-1",
        "context": {"run": run_block},
        "content": "",
    }


def _make_state_artifact(context: dict) -> dict:
    return {
        "id": "state-1",
        "context": context,
        "content": "{}",
    }


class MockResponse:
    """Lightweight mock for httpx.Response."""
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            request = httpx.Request("GET", "http://test")
            # Build a real httpx.Response so HTTPStatusError works
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )


def _build_mock_client(request_handler):
    """Build an AsyncMock httpx.AsyncClient that routes calls through request_handler.

    request_handler(method, url, **kwargs) -> MockResponse  (sync, NOT async)
    """
    class _MockClient:
        async def get(self, url, **kw):
            return request_handler("GET", url, **kw)

        async def patch(self, url, **kw):
            return request_handler("PATCH", url, **kw)

        async def post(self, url, **kw):
            return request_handler("POST", url, **kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    return _MockClient()


# ---------------------------------------------------------------------------
# run_workflow — integration tests
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("delegated")
class TestRunWorkflow:
    """The happy paths. Every one of these reaches mantle, and mantle is reached only under the
    caller's delegation — so the fixture is a precondition of the scenario, not test scaffolding."""

    @pytest.mark.asyncio
    async def test_missing_workspace_id(self):
        result = await run_workflow(workflow_artifact_id="wf-1")
        assert "workspace_id is required" in result
        # Error shape: the error is a JSON object, not prose. Asserted here rather than only in the
        # substring above, because "the message still contains those words" would pass on either shape.
        assert json.loads(result)["error"].startswith("workspace_id is required")

    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        """3-step workflow, no conditions — all execute in order."""
        steps = [
            {"name": "step_a", "transform_id": "t-a"},
            {"name": "step_b", "transform_id": "t-b"},
            {"name": "step_c", "transform_id": "t-c"},
        ]
        workflow_art = _make_workflow_artifact(steps)
        state_art = _make_state_artifact({"status": "ready"})
        call_log = []

        def handler(method, url, **kwargs):
            if method == "GET":
                if "wf-1" in url:
                    return MockResponse(workflow_art)
                return MockResponse(state_art)
            if method == "PATCH":
                return MockResponse({})
            if method == "POST" and "invoke" in url:
                call_log.append(_transform_id_from_url(url))
                return MockResponse({"output": "ok"})
            return MockResponse({})

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-1",
                params=json.dumps({"state_artifact_id": "state-1"}),
            )

        assert "3 steps executed" in result
        assert call_log == ["t-a", "t-b", "t-c"]

    @pytest.mark.asyncio
    async def test_condition_skip(self):
        """Step with condition not met is skipped."""
        steps = [
            {"name": "always", "transform_id": "t-1"},
            {"name": "direct_only", "transform_id": "t-2", "condition": {"field": "route", "eq": "direct"}},
            {"name": "always_too", "transform_id": "t-3"},
        ]
        workflow_art = _make_workflow_artifact(steps)
        state_art = _make_state_artifact({"status": "running", "route": "context_retrieval"})
        call_log = []

        def handler(method, url, **kwargs):
            if method == "GET":
                if "wf-1" in url:
                    return MockResponse(workflow_art)
                return MockResponse(state_art)
            if method == "PATCH":
                return MockResponse({})
            if method == "POST" and "invoke" in url:
                call_log.append(_transform_id_from_url(url))
                return MockResponse({"output": "ok"})
            return MockResponse({})

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-1",
                params=json.dumps({"state_artifact_id": "state-1"}),
            )

        assert "2 steps executed" in result
        assert "1 skipped" in result
        assert call_log == ["t-1", "t-3"]

    @pytest.mark.asyncio
    async def test_condition_pass(self):
        """Step with condition met executes normally."""
        steps = [
            {"name": "direct_only", "transform_id": "t-1", "condition": {"field": "route", "eq": "direct"}},
        ]
        workflow_art = _make_workflow_artifact(steps)
        state_art = _make_state_artifact({"route": "direct"})
        call_log = []

        def handler(method, url, **kwargs):
            if method == "GET":
                if "wf-1" in url:
                    return MockResponse(workflow_art)
                return MockResponse(state_art)
            if method == "PATCH":
                return MockResponse({})
            if method == "POST" and "invoke" in url:
                call_log.append(_transform_id_from_url(url))
                return MockResponse({"output": "ok"})
            return MockResponse({})

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-1",
                params=json.dumps({"state_artifact_id": "state-1"}),
            )

        assert "1 steps executed" in result
        assert call_log == ["t-1"]

    @pytest.mark.asyncio
    async def test_retry_triggers_restart(self):
        """Retry: should_retry=True after first pass triggers restart from step 1."""
        steps = [
            {"name": "step_a", "transform_id": "t-a"},
            {"name": "step_b", "transform_id": "t-b"},
        ]
        retry_config = {"on_field": "should_retry", "restart_from_step": 1, "max_retries": 1}
        workflow_art = _make_workflow_artifact(steps, retry=retry_config)
        state_get_count = [0]
        call_log = []

        def handler(method, url, **kwargs):
            if method == "GET":
                if "wf-1" in url:
                    return MockResponse(workflow_art)
                # State artifact is fetched many times:
                # - _patch_artifact_context GETs (for merge) during step execution
                # - Initial retry_count read
                # - While loop should_retry checks
                # Return should_retry=True until after the retry step executes,
                # then return False so the loop stops.
                state_get_count[0] += 1
                # After 5 GETs (2 step patches + initial + while check + retry step patch),
                # switch to should_retry=False
                if state_get_count[0] <= 5:
                    return MockResponse(_make_state_artifact({"should_retry": True, "retry_count": 0}))
                return MockResponse(_make_state_artifact({"should_retry": False, "retry_count": 1}))
            if method == "PATCH":
                return MockResponse({})
            if method == "POST" and "invoke" in url:
                call_log.append(_transform_id_from_url(url))
                return MockResponse({"output": "ok"})
            return MockResponse({})

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-1",
                params=json.dumps({"state_artifact_id": "state-1"}),
            )

        assert "1 retries" in result
        # Initial: t-a, t-b. Retry from step 1: t-b
        assert call_log == ["t-a", "t-b", "t-b"]

    @pytest.mark.asyncio
    async def test_retry_max_reached(self):
        """When retry_count >= max_retries, no more retries."""
        steps = [{"name": "step_a", "transform_id": "t-a"}]
        retry_config = {"on_field": "should_retry", "restart_from_step": 0, "max_retries": 1}
        workflow_art = _make_workflow_artifact(steps, retry=retry_config)
        state_art = _make_state_artifact({"should_retry": True, "retry_count": 1})
        call_log = []

        def handler(method, url, **kwargs):
            if method == "GET":
                if "wf-1" in url:
                    return MockResponse(workflow_art)
                return MockResponse(state_art)
            if method == "PATCH":
                return MockResponse({})
            if method == "POST" and "invoke" in url:
                call_log.append(_transform_id_from_url(url))
                return MockResponse({"output": "ok"})
            return MockResponse({})

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-1",
                params=json.dumps({"state_artifact_id": "state-1"}),
            )

        assert "0 retries" in result
        assert call_log == ["t-a"]

    @pytest.mark.asyncio
    async def test_step_failure_aborts(self):
        """When a step fails, the workflow aborts and returns error."""
        steps = [
            {"name": "step_a", "transform_id": "t-a"},
            {"name": "step_b", "transform_id": "t-b"},
        ]
        workflow_art = _make_workflow_artifact(steps)
        state_art = _make_state_artifact({"status": "running"})

        def handler(method, url, **kwargs):
            if method == "GET":
                if "wf-1" in url:
                    return MockResponse(workflow_art)
                return MockResponse(state_art)
            if method == "PATCH":
                return MockResponse({})
            if method == "POST" and "invoke" in url:
                if _transform_id_from_url(url) == "t-b":
                    return MockResponse({"detail": "tool failed"}, status_code=500)
                return MockResponse({"output": "ok"})
            return MockResponse({})

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-1",
                params=json.dumps({"state_artifact_id": "state-1"}),
            )

        # Asserts the shape and the step, not a substring: a loose "error" or "failed" substring
        # check would pass on any error, including one that never reached step_b at all.
        payload = json.loads(result)
        assert payload["step"] == 1 and payload["name"] == "step_b", payload
        assert "HTTP 500" in payload["error"], payload

    @pytest.mark.asyncio
    async def test_empty_workflow(self):
        """Workflow with no steps returns immediately."""
        workflow_art = _make_workflow_artifact([])

        def handler(method, url, **kwargs):
            if method == "GET":
                return MockResponse(workflow_art)
            return MockResponse({})

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-1",
            )

        assert "no steps" in result.lower()


class TestRunWorkflowFailsClosed:
    """Without a delegation — deliberately no `delegated` fixture.

    Pins the failure mode: `run_workflow` takes a caller-supplied `workspace_id` and
    `workflow_artifact_id`. If `_headers()` — a platform JWT signed with the `chorus.private.pem`
    every chorus persona shares — were reinstated, mantle would apply platform authority to a
    caller-chosen workspace: a cross-tenant read/write primitive reachable from an MCP tool. That
    regression is silent by construction: reinstating `_headers`/`_user_headers` leaves every test
    above passing, because they all supply a delegation. Only a test that supplies none can tell
    the difference; this class must never gain the fixture.
    """

    @pytest.mark.asyncio
    async def test_no_delegation_refuses_and_never_calls_mantle(self):
        calls = []

        def handler(method, url, **kwargs):
            calls.append((method, url))
            return MockResponse(_make_workflow_artifact([]))

        with patch("httpx.AsyncClient", return_value=_build_mock_client(handler)):
            result = await run_workflow(
                workflow_artifact_id="wf-1",
                workspace_id="ws-someone-elses",
            )

        # The error is in the parseable shape — not prose, and not an unhandled exception.
        assert json.loads(result)["error"].startswith("agience-server-lumen:"), result
        assert "delegation" in result
        # And it happens before the wire: no platform-identity request was ever issued.
        assert calls == [], f"mantle was called without a delegation: {calls!r}"

    def test_the_module_has_no_platform_identity_helper_left(self):
        """The structural half. `_require_user_headers` fails closed only while there is nothing else to
        reach for; a reinstated `_headers`/`_user_headers` is what the whole class guards against."""
        for gone in ("_headers", "_user_headers"):
            assert not hasattr(_lumen_server, gone), (
                f"lumen/server.py grew back `{gone}()` — it resolves the shared chorus platform JWT. "
                "Every mantle call in lumen carries a caller-supplied id; there is no principal-less "
                "path here to need it.")
        assert hasattr(_lumen_server, "_require_user_headers")
