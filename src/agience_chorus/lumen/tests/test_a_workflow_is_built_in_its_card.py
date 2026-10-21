"""A workflow is built in its own card from operators: the builder is offered the operators the person
may invoke (the platform's, their own, ones shared with them), and a step's artifacts are typed links
from the workflow, not ids typed into strings.

2026-10-19: the only way to make a workflow was to write its JSON through the API.
2026-10-21 (John): the builder offered every persona tool to everyone — "how do we ensure that the
tools themselves have grants", and "everything should be linked to other artifacts".
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
OP = "application/vnd.agience.operator+json"
SCHEMA = {"properties": {"collection_id": {"type": "string", "format": "artifact-id"}}}


def _op(oid, title, by):
    return {"id": oid, "content_type": OP, "created_by": by,
            "context": json.dumps({"title": title, "input_schema": SCHEMA})}


class World:
    def __init__(self, run=None, may_invoke=True):
        self.docs = {"wf": {"id": "wf", "collection_id": "ws-1", "content_type": T,
                            "context": json.dumps({"title": "Routine", "run": run or {"type": "workflow", "steps": []}})},
                     "op-plat": _op("op-plat", "Reconcile accounts", "u-platform"),
                     "op-fake": {**_op("op-fake", "Send email", "someone"),
                                 "context": json.dumps({"title": "Send email", "platform": True})}}
        self.links = []
        self.may_invoke = may_invoke
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
                world.calls.append(("GET", url, headers, params))
                if url.endswith("/artifacts/platform-operators"):
                    return MockResponse({"items": [{"id": "op-plat", "slug": "op-reconcile-accounts"}]})
                if url.endswith("/artifacts/visible") and (params or {}).get("content_type") == OP:
                    assert params.get("action") == "invoke", "only what the person may invoke"
                    return MockResponse({"items": [world.docs["op-fake"], _op("op-mine", "My step", "me-1"),
                                                   world.docs["op-plat"]]})
                if url.endswith("/artifacts/visible"):
                    return MockResponse({"items": [
                        {"id": "later", "created_by": "me-1", "created_time": "2026-10-19"},
                        {"id": "inbox", "created_by": "me-1", "created_time": "2026-10-01"},
                        {"id": "theirs", "created_by": "someone", "created_time": "2026-01-01"}]})
                if url.endswith("/wf/children") and (params or {}).get("links") == "*":
                    return MockResponse({"items": world.links})
                if url.endswith("/grants/my-access"):
                    return MockResponse({"allowed": world.may_invoke})
                doc = world.docs.get(url.rsplit("/", 1)[-1])
                return MockResponse(doc or {}, 200 if doc else 404)

            async def post(self, url, headers=None, json=None, **kw):
                world.calls.append(("POST", url, json))
                world.links.append({"id": json["source_artifact_id"], "relationship": json["relationship"],
                                    "context": '{"title": "Accounts"}'})
                return MockResponse({"id": "link-new"}, 201)

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
async def test_the_builder_is_offered_the_operators_the_person_may_invoke(person):
    world = World()
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.workflow_catalog("wf"))
    assert out["workspace_id"] == "ws-1" and out["inbox_id"] == "inbox", "the person's oldest own workspace"
    assert [(o["id"], o["group"]) for o in out["operators"]] == [
        ("op-plat", "platform"), ("op-mine", "mine"), ("op-fake", "shared")]
    assert out["operators"][0]["slug"] == "op-reconcile-accounts"
    assert out["operators"][0]["input_schema"] == SCHEMA
    assert "tools" not in out, "no raw tool is offered"


@pytest.mark.asyncio
async def test_an_operator_that_calls_itself_the_platforms_is_not(person):
    world = World()
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.workflow_catalog("wf"))
    assert next(o for o in out["operators"] if o["id"] == "op-fake")["group"] == "shared"


@pytest.mark.asyncio
async def test_adding_a_step_links_its_artifacts_from_the_workflow(person):
    world = World()
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.add_workflow_step("wf", "op-plat", {"limit": 3}, {"collection_id": "acc-1"}))
        catalog = json.loads(await L.workflow_catalog("wf"))
    (link,) = [c[2] for c in world.calls if c[0] == "POST"]
    key = out["key"]
    assert link == {"container_id": "wf", "source_artifact_id": "acc-1", "relationship": f"{key}.collection_id"}
    (step,) = json.loads(world.docs["wf"]["context"])["run"]["steps"]
    assert step == {"name": "Reconcile accounts", "key": key, "operator_id": "op-plat",
                    "arguments": {"limit": 3, "collection_id": f"@link.{key}.collection_id"}}
    assert catalog["steps"][0]["links"] == {"collection_id": {"id": "acc-1", "title": "Accounts"}}
    assert catalog["steps"][0]["arguments"] == {"limit": 3}


@pytest.mark.asyncio
async def test_a_step_needs_an_operator_the_person_may_invoke(person):
    world = World(may_invoke=False)
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.add_workflow_step("wf", "op-plat"))
    assert "may not invoke" in out["error"]
    assert not [c for c in world.calls if c[0] in ("POST", "PATCH")]


@pytest.mark.asyncio
async def test_a_single_step_card_is_not_silently_turned_into_a_workflow(person):
    world = World(run={"type": "mcp-tool", "server": "sage", "tool": "browse_collections"})
    with patch.object(L.httpx, "AsyncClient", world.client()):
        out = json.loads(await L.add_workflow_step("wf", "op-plat"))
    assert "make it a workflow first" in out["error"]
    assert not [c for c in world.calls if c[0] in ("POST", "PATCH")]


@pytest.mark.asyncio
async def test_removing_a_step_removes_its_links_and_keeps_the_others(person):
    world = World(run={"type": "workflow", "steps": [
        {"name": "A", "key": "sa", "operator_id": "op-plat", "arguments": {"collection_id": "@link.sa.collection_id"}},
        {"name": "B", "key": "sb", "operator_id": "op-plat", "arguments": {}}]})
    deleted = []

    async def delete(self, url, headers=None, **kw):
        deleted.append(url)
        return MockResponse({"removed": 1}, 200)

    C = world.client()
    C.delete = delete
    with patch.object(L.httpx, "AsyncClient", C):
        out = json.loads(await L.remove_workflow_step("wf", 0))
    assert [s["name"] for s in json.loads(world.docs["wf"]["context"])["run"]["steps"]] == ["B"]
    assert deleted and deleted[0].endswith("/artifacts/wf/links/sa") and out["links_removed"] == 1
