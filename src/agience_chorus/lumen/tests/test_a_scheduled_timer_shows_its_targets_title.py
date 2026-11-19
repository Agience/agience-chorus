"""A timer made by Schedule carries the titles its view shows (`timer.titles`), so a timer opened
before anyone saves it shows the workflow's title as its Target, not the workflow's id (BUG-009)."""
from __future__ import annotations

import json

import pytest

from agience_chorus.lumen import server as L
from agience_chorus.lumen.tests.test_a_run_is_recorded_and_its_outputs_flow import Scheduling


def _timer_of(world):
    return json.loads(world.created[-1]["context"])["timer"]


@pytest.mark.asyncio
async def test_a_scheduled_workflow_timer_holds_the_workflows_title(monkeypatch):
    world = Scheduling({"title": "Morning check", "run": {"type": "workflow", "steps": []}})
    world.docs["inbox-1"] = {"id": "inbox-1", "name": "Inbox"}
    # The Runs collection Schedule makes is the fake's first post, `made-1`.
    world.docs["made-1"] = {"id": "made-1", "name": "Runs — Morning check"}
    monkeypatch.setattr(L.httpx, "AsyncClient", world.client())
    monkeypatch.setattr(L, "_require_user_headers", lambda: {"Authorization": "Bearer d"})
    await L.schedule_action("ws-1", "wf", every_minutes=30, inbox_to="inbox-1")
    titles = _timer_of(world)["titles"]
    assert titles["target"] == "Morning check"
    assert titles["results_to"] == "Runs — Morning check"
    assert titles["inbox_to"] == "Inbox"


@pytest.mark.asyncio
async def test_a_target_the_person_cannot_read_is_left_to_its_id(monkeypatch):
    world = Scheduling({"title": "One step", "run": {"type": "mcp-tool", "server": "sage", "tool": "x"}})
    monkeypatch.setattr(L.httpx, "AsyncClient", world.client())
    monkeypatch.setattr(L, "_require_user_headers", lambda: {"Authorization": "Bearer d"})
    await L.schedule_action("ws-1", "gone", every_minutes=30)
    assert "titles" not in _timer_of(world)
