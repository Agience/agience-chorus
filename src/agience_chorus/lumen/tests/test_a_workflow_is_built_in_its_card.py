"""A workflow is built in its own card: the builder is offered every tool the person can use (with
its inputs), the steps beside it and their Inbox, and adding a step makes the step and appends it.

2026-10-19: the only way to make a workflow was to write its JSON through the API. The Transform
card's view was read-only, and the palette it pointed to was mounted nowhere.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from .test_chain_and_feedback import MockResponse

_spec = importlib.util.spec_from_file_location("chorus_lumen_server_builder",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

T = "application/vnd.agience.transform+json"
WS = "application/vnd.agience.workspace+json"


class World:
    def __init__(self, run=None):
        self.docs = {"wf": {"id": "wf", "collection_id": "ws-1", "content_type": T,
                            "context": json.dumps({"title": "Routine", "run": run or {"type": "workflow", "steps": []}})}}
        self.calls = []

    def client(self):
        world = self

        class _C:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, params=None, **kw):
                world.calls.append(("GET", url, headers))
                if url.endswith("/personas"):
                    return MockResponse({"items": [
                        {"server": "lumen", "status": "ok", "tools": [
                            {"name": "reconcile", "description": "Reconcile", "input_schema": {"properties": {"collection_id": {"type": "string"}}}}]},
                        {"server": "sage", "status": "down", "tools": [{"name": "hidden"}]}]})
                if url.endswith("/ws-1/children"):
                    return MockResponse({"items": [
                        {"id": "s1", "content_type": T, "context": json.dumps({"title": "List", "run": {"type": "mcp-tool", "server": "sage", "tool": "browse_collections"}})},
                        {"id": "n1", "content_type": "text/plain", "context": "{}"}]})
                if url.endswith("/artifacts/visible"):
                    return MockResponse({"items": [
                        {"id": "later", "created_by": "me-1", "created_time": "2026-10-19"},
                        {"id": "inbox", "created_by": "me-1", "created_time": "2026-10-01"},
                        {"id": "theirs", "created_by": "someone", "created_time": "2026-01-01"}]})
                doc = world.docs.get(url.rsplit("/", 1)[-1])
                return MockResponse(doc or {}, 200 if doc else 404)

            async def post(self, url, headers=None, json=None, **kw):
                world.calls.append(("POST", url, json))
                return MockResponse({"id": "step-new"}, 201)

            async def patch(self, url, headers=None, json=None, **kw):
                world.calls.append(("PATCH", url, json))
                world.docs["wf"]["context"] = json["context"]
                return MockResponse({}, 200)
        return _C


@pytest.fixture
def person():
    tok = L._auth.request_user_token.set("delegation-for-me")
    ctok = L._auth.request_caller_token.set("persons-token")
    try:
        with patch.object(L, "_get_delegation_user_id", lambda: "me-1"):
            yield
    finally:
        L._auth.request_caller_token.reset(ctok)
        L._auth.request_user_token.reset(tok)


@pytest.mark.asyncio
async def test_the_builder_is_offered_the_tools_the_steps_and_the_persons_inbox(person):
    world = World()
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.workflow_catalog("wf"))
    assert out["workspace_id"] == "ws-1" and out["inbox_id"] == "inbox", "the person's oldest own workspace"
    assert [(t["server"], t["name"]) for t in out["tools"]] == [("lumen", "reconcile")], "a persona that is down offers nothing"
    assert out["tools"][0]["input_schema"]["properties"] == {"collection_id": {"type": "string"}}
    assert out["steps"] == [{"id": "s1", "title": "List", "does": "sage: browse_collections"}]
    personas = next(c for c in world.calls if c[1].endswith("/personas"))
    assert personas[2]["Authorization"] == "Bearer persons-token", "the catalogue is the caller's own"


@pytest.mark.asyncio
async def test_adding_a_step_makes_it_beside_the_workflow_and_appends_it(person):
    world = World()
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.add_workflow_step("wf", "lumen", "reconcile", {"collection_id": "c-1"}, "Reconcile"))
    made = next(c for c in world.calls if c[0] == "POST")[2]
    assert made["container_id"] == "ws-1" and made["content_type"] == T
    assert json.loads(made["context"])["run"] == {"type": "mcp-tool", "server": "lumen", "tool": "reconcile",
                                                  "input_mapping": {"collection_id": "c-1"}}
    assert out["run"]["steps"] == [{"name": "Reconcile", "transform_id": "step-new"}]
    assert json.loads(world.docs["wf"]["context"])["run"]["steps"][0]["transform_id"] == "step-new"


@pytest.mark.asyncio
async def test_a_single_step_card_is_not_silently_turned_into_a_workflow(person):
    world = World(run={"type": "mcp-tool", "server": "sage", "tool": "browse_collections"})
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.add_workflow_step("wf", "lumen", "reconcile"))
    assert "make it a workflow first" in out["error"]
    assert not [c for c in world.calls if c[0] in ("POST", "PATCH")]
