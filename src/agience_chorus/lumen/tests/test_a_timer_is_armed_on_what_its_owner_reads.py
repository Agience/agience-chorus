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
