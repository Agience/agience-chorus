"""Every run of a workflow is a Run card — each step's status, output and error — and a step can take
what an earlier step returned as its input.

2026-10-19 (John): "Probably need a state artifact/object for each run. That would give it
inspectability." A step could take only the values fixed when it was built, and nothing showed what
a run had done beyond its last line.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agience_chorus.lumen import runs as R

from .test_chain_and_feedback import MockResponse

_spec = importlib.util.spec_from_file_location("chorus_lumen_server_runs",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


# ── paths and outputs ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,value", [
    ("previous", {"id": "r-1", "items": [{"n": 1}]}),
    ("previous.id", "r-1"),
    ("previous.items[0].n", 1),
    ("steps.List.count", 3),
])
def test_a_path_reads_what_an_earlier_step_returned(path, value):
    scope = {"previous": {"id": "r-1", "items": [{"n": 1}]}, "steps": {"List": {"count": 3}}}
    assert R.resolve(path, scope) == value


def test_a_path_that_leads_nowhere_leaves_the_argument_out():
    got = R.resolve_mapping({"a": "$.previous.missing", "b": "$.steps.Nope", "c": "literal", "d": 5},
                            {"previous": {"id": 1}, "steps": {}})
    assert got == {"c": "literal", "d": 5}


def test_a_steps_output_is_its_answer_not_its_envelope():
    inner = {"content": [{"type": "text", "text": json.dumps({"reconciliation_id": "r-1"})}]}
    wrapped = {"content": [{"type": "text", "text": json.dumps(inner)}]}
    assert R.output_of(wrapped) == {"reconciliation_id": "r-1"}, "a Transform passes its tool's result on whole"
    assert R.output_of({"content": [{"type": "text", "text": "Hello"}]}) == "Hello"


# ── a run ─────────────────────────────────────────────────────────────────────────────────────
WORKFLOW = {"id": "wf", "collection_id": "ws-1", "context": json.dumps({
    "title": "Morning check", "run": {"type": "workflow", "steps": [
        {"name": "Reconcile", "transform_id": "t1"},
        {"name": "Tell me", "transform_id": "t2", "input_mapping": {"source_id": "$.previous.reconciliation_id"}},
    ]}})}


class World:
    def __init__(self, fail_second=False):
        self.fail_second = fail_second
        self.created, self.patched, self.dispatched, self.runs = [], [], [], {}

    def client(self):
        world = self

        class _C:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None, **kw):
                world.created.append(json)
                return MockResponse({"id": f"made-{len(world.created)}"}, 201)

            async def patch(self, url, headers=None, json=None, **kw):
                world.patched.append((url, json))
                return MockResponse({}, 200)
        return _C


@pytest.fixture
def run_world(monkeypatch):
    def go(world):
        async def get_artifact(client, ws, aid):
            if aid == "wf":
                return WORKFLOW
            return {"id": aid, "context": json.dumps(world.runs.get(aid, {}))}

        async def patch_ctx(client, ws, aid, updates):
            world.runs.setdefault(aid, {}).update(updates)

        async def child(client, ws, tid, params):
            world.dispatched.append((tid, params))
            if tid == "t2" and world.fail_second:
                return {"content": [{"type": "text", "text": json.dumps({"error": "mail refused"})}]}
            text = json.dumps({"reconciliation_id": "r-1", "conflicts": 1}) if tid == "t1" else "raised"
            return {"content": [{"type": "text", "text": text}]}

        monkeypatch.setattr(L, "_get_artifact", get_artifact)
        monkeypatch.setattr(L, "_patch_artifact_context", patch_ctx)
        monkeypatch.setattr(L, "_dispatch_child_transform", child)
        monkeypatch.setattr(L.httpx, "AsyncClient", world.client())
        monkeypatch.setattr(L, "_require_user_headers", lambda: {"Authorization": "Bearer d"})
    return go


@pytest.mark.asyncio
async def test_a_run_writes_its_card_in_the_workflows_runs_and_feeds_each_step_the_last(run_world):
    world = World()
    run_world(world)
    out = await L.run_workflow("wf", workspace_id="ws-1")
    assert out.startswith("Workflow completed: 2 steps executed") and out.endswith("Run: made-2.")

    runs_collection, run_card = world.created
    assert runs_collection["name"] == "Runs — Morning check", "the first run makes the workflow's Runs"
    assert json.loads(world.patched[0][1]["context"])["runs_to"] == "made-1", "and the workflow remembers it"
    assert run_card["container_id"] == "made-1" and run_card["content_type"] == R.RUN_TYPE

    (_, first), (_, second) = world.dispatched
    assert second["previous"] == {"reconciliation_id": "r-1", "conflicts": 1}
    assert second["source_id"] == "r-1", "the step's mapping reads the step before"
    assert second["steps"]["Reconcile"]["conflicts"] == 1

    record = world.runs["made-2"]
    assert record["status"] == "completed" and record["finished_at"]
    assert [s["status"] for s in record["steps"]] == ["completed", "completed"]
    assert json.loads(record["steps"][0]["output"])["reconciliation_id"] == "r-1"
    assert record["steps"][1]["output"] == "raised"


@pytest.mark.asyncio
async def test_a_failed_step_is_on_the_run_card_with_its_error(run_world):
    world = World(fail_second=True)
    run_world(world)
    out = json.loads(await L.run_workflow("wf", workspace_id="ws-1"))
    assert "mail refused" in out["error"] and out["run_id"] == "made-2"
    record = world.runs["made-2"]
    assert record["status"] == "failed" and "mail refused" in record["error"]
    assert [s["status"] for s in record["steps"]] == ["completed", "failed"]
    assert "mail refused" in record["steps"][1]["error"]
