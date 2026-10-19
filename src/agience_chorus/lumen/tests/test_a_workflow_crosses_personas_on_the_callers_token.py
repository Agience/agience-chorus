"""A workflow step on another persona carries the caller's own token, and a failed step fails.

2026-10-18, measured on staging: a workflow whose step called sage answered "Workflow completed: 1
steps executed" while the step itself had answered 401 — lumen forwarded its own delegation, which
sage refused, and the runner recorded the error as a completed step. `synthesize`'s corpus leg was
dark in every deployment for want of a retrieval reach.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import importlib.util
from pathlib import Path

from agience_chorus.lumen import timers as T

from .test_chain_and_feedback import MockResponse, _client

# A private copy of the server module, as the other lumen tests load it: importing the package
# module here would cache it for tests that reload it under different settings.
_spec = importlib.util.spec_from_file_location("chorus_lumen_server_crosses",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


@pytest.fixture
def delegated():
    tok = L._auth.request_user_token.set("test-delegation-token")
    ctok = L._auth.request_caller_token.set("test-user-token")
    try:
        yield
    finally:
        L._auth.request_caller_token.reset(ctok)
        L._auth.request_user_token.reset(tok)


@pytest.fixture
def only_a_delegation():
    """A request that arrived with a delegation addressed to lumen: nothing to pass on."""
    tok = L._auth.request_user_token.set("lumen-delegation")
    try:
        yield
    finally:
        L._auth.request_user_token.reset(tok)


@pytest.mark.asyncio
async def test_a_chain_from_a_delegation_alone_says_why_it_cannot_reach_another_persona(only_a_delegation):
    steps = json.dumps([{"server": "sage", "tool": "search", "arguments": {}}])
    out = json.loads(await L.chain_tasks(steps=steps))
    assert "addressed to lumen" in out["error"]


@pytest.mark.parametrize("result,failed", [
    ({"content": [{"type": "text", "text": json.dumps({"error": "Tool execution failed: HTTP 401"})}]}, True),
    ({"content": [{"type": "text", "text": "x"}], "isError": True}, True),
    ({"content": [{"type": "text", "text": "Workflow completed: 1 steps executed"}]}, False),
    ({"content": [{"type": "text", "text": json.dumps({"rows": []})}]}, False),
    # A Transform's result carrying its tool's refusal, as Crystal returned it on staging.
    ({"content": [{"type": "text", "text": json.dumps({"content": [{"type": "text", "text": "Unknown tool: x"}],
                                                       "isError": True})}], "isError": False}, True),
    ({"content": [{"type": "text", "text": json.dumps({"content": [{"type": "text", "text": "rows"}]})}]}, False),
])
def test_a_result_carrying_an_error_is_a_failure(result, failed):
    assert (T.step_failure(result) is not None) is failed


@pytest.mark.asyncio
async def test_a_workflow_whose_step_failed_reports_the_failure(delegated):
    workflow = {"id": "wf", "context": json.dumps({"run": {"type": "workflow",
                                                           "steps": [{"name": "s", "transform_id": "t1"}]}})}

    async def get_artifact(client, ws, aid):
        return workflow

    async def child(client, ws, tid, params):
        return {"content": [{"type": "text", "text": json.dumps({"error": "Tool execution failed: HTTP 401"})}]}

    with patch.object(L, "_get_artifact", get_artifact), patch.object(L, "_dispatch_child_transform", child):
        out = await L.run_workflow(workflow_artifact_id="wf", workspace_id="ws-1")
    assert "completed" not in out.lower()
    assert "HTTP 401" in json.loads(out)["error"]


@pytest.mark.asyncio
async def test_synthesize_grounds_on_sage_through_crystal_with_the_callers_token(delegated):
    calls = []

    def handler(method, url, **kw):
        calls.append((url, kw.get("json"), kw.get("headers")))
        evidence = [{"id": "a1", "title": "North well", "content": "the quillfern reading is 7", "score": 1.0}]
        return MockResponse({"content": [{"type": "text", "text": json.dumps({"evidence": evidence})}]})

    with patch.object(L, "_RETRIEVE_REACH", None), patch("httpx.AsyncClient", return_value=_client(handler)):
        out = json.loads(await L.synthesize(input="what is the quillfern reading?"))
    url, body, headers = calls[0]
    assert url.endswith("/personas/sage/tools/call") and body["name"] == "retrieve"
    assert headers["Authorization"] == "Bearer test-user-token"
    assert out["citations"] == ["a1"] and "quillfern reading is 7" in out["answer"]
    assert out["refusal"] is None
