"""A timer is armed on what its owner reads (John, 2026-11-10, Q9).

A timer's settings are sealed under its owner's key, which only a live job grant opens for Lumen,
and only for the artifacts it lists. Before arming there is no grant, so `timer_reach` names what
it needs; the app reads those in the person's own session and asks again with their contexts.
Once armed, Lumen reads the timer on the grant's own delegation.
"""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agience_chorus.lumen import timers as T

from .test_chain_and_feedback import MockResponse

_spec = importlib.util.spec_from_file_location("chorus_lumen_server_arm",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

TIMER = {"timer": {"schedule": {"every_minutes": 60}, "target": {"artifact_id": "wf-1"},
                   "inbox_to": "inbox-1"}}
WORKFLOW = {"run": {"type": "workflow", "steps": [{"operator_id": "op-1"}]}}
FULL = {"t-1": (T.TIMER_TYPE, TIMER), "wf-1": ("application/vnd.agience.workflow+json", WORKFLOW)}


def _doc(doc_id, sealed):
    ctype, ctx = FULL[doc_id]
    root = {"wf-1": "wf-root"}.get(doc_id, doc_id)
    return {"id": doc_id, "root_id": root, "content_type": ctype,
            "context": json.dumps({} if sealed else ctx)}


class Mantle:
    """Mantle as a persona sees it: sealed fields missing, except on the job grant's delegation."""

    def __init__(self):
        self.calls = []

    def client(self):
        mantle = self

        class _C:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, **kw):
                auth = (headers or {}).get("Authorization", "")
                mantle.calls.append(("GET", url, auth))
                doc_id = url.rsplit("/", 1)[-1]
                if doc_id not in FULL:
                    return MockResponse({}, 404)
                return MockResponse(_doc(doc_id, sealed=auth != "Bearer job-key"), 200)
        return _C


@pytest.fixture
def person():
    tok = L._auth.request_user_token.set("delegation-for-me")
    ctok = L._auth.request_caller_token.set("persons-token")
    try:
        with patch.object(L, "_get_delegation_user_id", lambda: "me-1"), \
                patch.object(L, "_workflow_links", _no_links):
            yield
    finally:
        L._auth.request_caller_token.reset(ctok)
        L._auth.request_user_token.reset(tok)


async def _no_links(client, target):
    return {}


@pytest.mark.asyncio
async def test_lumen_names_what_it_needs_until_the_owner_s_reads_are_given(person):
    mantle = Mantle()
    with patch.object(L.httpx, "AsyncClient", mantle.client()):
        first = json.loads(await L.timer_reach("t-1"))
        assert first == {"need": ["t-1"]}
        second = json.loads(await L.timer_reach("t-1", {"t-1": TIMER}))
        assert second == {"need": ["wf-1"]}
        done = json.loads(await L.timer_reach("t-1", {"t-1": TIMER, "wf-1": WORKFLOW}))
    # Mantle opens a key by root id: a revised target's root is named too.
    assert done == {"resources": ["t-1", "wf-1", "inbox-1", "op-1", "wf-root"]}
    assert all(auth != "Bearer job-key" for *_, auth in mantle.calls)


@pytest.mark.asyncio
async def test_a_context_is_taken_only_for_an_item_the_person_can_read(person):
    mantle = Mantle()
    with patch.object(L.httpx, "AsyncClient", mantle.client()):
        out = json.loads(await L.timer_reach("gone-1", {"gone-1": TIMER}))
    assert "error" in out and "resources" not in out


@pytest.mark.asyncio
async def test_a_timer_given_without_a_schedule_is_refused(person):
    mantle = Mantle()
    with patch.object(L.httpx, "AsyncClient", mantle.client()):
        out = json.loads(await L.timer_reach("t-1", {"t-1": {"timer": {}}}))
    assert "error" in out


def _jwt(claims):
    seg = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{seg}.sig"


class _Store:
    def __init__(self):
        self.armed = {}

    def arm(self, timer_id, job_grant, person, **kw):
        self.armed[timer_id] = {"job_grant": job_grant, "principal": person, **kw}


@pytest.mark.asyncio
async def test_arming_reads_the_timer_on_its_job_grant(person):
    mantle, store = Mantle(), _Store()
    run = _jwt({"job_grant": "jg-1", "job_reach": ["t-1", "wf-1"]})
    with patch.object(L.httpx, "AsyncClient", mantle.client()), \
            patch.object(L, "_timer_store", lambda: store), \
            patch.object(L, "_timer_tokens", lambda timer_id, entry: (200, "job-key", run)):
        out = json.loads(await L.arm_timer("t-1", "jg-1"))
    assert out == {"timer_id": "t-1", "armed": True, "job_grant": "jg-1"}, out
    assert store.armed["t-1"]["schedule"] == {"every_minutes": 60}
    assert ("GET", L.artifact_url(L.MANTLE_URI, "t-1"), "Bearer job-key") in mantle.calls


@pytest.mark.asyncio
async def test_a_target_with_nothing_to_run_is_refused_before_origin_is_asked(person, monkeypatch):
    """BUG-043 (2026-11-10): a timer armed on an empty workflow failed every run; it is refused at
    arming, in words, before anything is approved."""
    timer = {"timer": {"schedule": {"every_minutes": 60}, "target": {"artifact_id": "wf-empty"}}}
    monkeypatch.setitem(FULL, "t-2", (T.TIMER_TYPE, timer))
    monkeypatch.setitem(FULL, "wf-empty", ("application/vnd.agience.workflow+json", {}))
    with patch.object(L.httpx, "AsyncClient", Mantle().client()):
        out = json.loads(await L.timer_reach("t-2", {"t-2": timer, "wf-empty": {}}))
    assert "nothing to run" in out.get("error", "") and "resources" not in out
    # The editor's "No steps yet": a workflow run block with no steps (BUG-043, reopened).
    no_steps = {"run": {"type": "workflow", "steps": []}}
    monkeypatch.setitem(FULL, "wf-empty", ("application/vnd.agience.transform+json", no_steps))
    with patch.object(L.httpx, "AsyncClient", Mantle().client()):
        out = json.loads(await L.timer_reach("t-2", {"t-2": timer, "wf-empty": no_steps}))
    assert "nothing to run" in out.get("error", ""), out
    # A run block under `transform`, where the runner also finds one, is something to run.
    nested = {"transform": {"run": {"type": "mcp-tool", "server": "astra", "tool": "noop"}}}
    monkeypatch.setitem(FULL, "wf-empty", ("application/vnd.agience.transform+json", nested))
    with patch.object(L.httpx, "AsyncClient", Mantle().client()):
        ok = json.loads(await L.timer_reach("t-2", {"t-2": timer, "wf-empty": {"run": nested["transform"]["run"]}}))
    assert "t-2" in ok.get("resources", []), ok


LINKED = {"run": {"type": "workflow", "steps": [
    {"name": "Read", "key": "s2", "operator_id": "op-read", "arguments": {"artifact_id": "@link.s2.artifact_id"}}]}}


@pytest.mark.asyncio
async def test_a_run_s_reach_is_the_workflow_its_operators_and_the_items_it_links(person, monkeypatch):
    """Run now's one-shot grant (John, 2026-11-10) reaches what the run touches; the links come
    from the person's session, since a persona cannot list a link to a sealed item (BUG-051)."""
    monkeypatch.setitem(FULL, "wf-l", ("application/vnd.agience.transform+json", {}))
    with patch.object(L.httpx, "AsyncClient", Mantle().client()):
        out = json.loads(await L.workflow_reach("wf-l", LINKED, {"s2.artifact_id": "note-1"}))
    assert out == {"resources": ["wf-l", "op-read", "note-1"]}


@pytest.mark.asyncio
async def test_a_timer_s_reach_takes_the_links_the_person_s_session_lists(person, monkeypatch):
    timer = {"timer": {"schedule": {"every_minutes": 60}, "target": {"artifact_id": "wf-l"}}}
    monkeypatch.setitem(FULL, "t-3", (T.TIMER_TYPE, timer))
    monkeypatch.setitem(FULL, "wf-l", ("application/vnd.agience.transform+json", LINKED))
    with patch.object(L.httpx, "AsyncClient", Mantle().client()):
        out = json.loads(await L.timer_reach("t-3", {"t-3": timer, "wf-l": LINKED}, {"s2.artifact_id": "note-1"}))
    assert "note-1" in out["resources"], out


@pytest.mark.asyncio
async def test_a_run_now_runs_once_through_the_gateway_on_its_grant(person, monkeypatch):
    posted = []

    class Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            posted.append(("mint", json))
            return MockResponse({"access_token": _jwt({"job_grant": "jg-r", "job_reach": ["wf-l", "note-1"]})}, 200)

    class AClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            posted.append(("invoke", url, headers["Authorization"].startswith("Bearer "), json))
            return MockResponse({"content": [{"type": "text", "text": "{\"status\": \"completed\"}"}]}, 200)

    monkeypatch.setattr(L._auth, "sign_exchange_jwt", lambda: "lumen-key")
    with patch.object(L.httpx, "Client", Client), patch.object(L.httpx, "AsyncClient", AClient):
        refused = json.loads(await L.run_workflow_now("wf-l", "lumen.run.wf-l.extra.ab12cd", "jg-r", LINKED))
        out = json.loads(await L.run_workflow_now("wf-l", "lumen.run.wf-l.ab12cd", "jg-r", LINKED))
    assert "not a run of this workflow" in refused["error"]
    assert posted[0] == ("mint", {"principal": "me-1", "job": "lumen.run.wf-l.ab12cd", "audience": "crystal",
                                  "job_grant": "jg-r"})
    assert posted[1][0] == "invoke" and posted[1][1].endswith("/artifacts/wf-l/op/invoke") and posted[1][3] == {"context": LINKED}
    assert out["content"][0]["text"] == "{\"status\": \"completed\"}"
