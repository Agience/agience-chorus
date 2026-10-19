"""An Inbox item is what needs a person: it says why, moves new → triaged → resolved, and an
approval runs its action on the approver's own credential.

2026-10-19: use cases 01, 02, 04 and 05 each need something to put in front of a person — an
outlier, a failed routine, a draft to approve — and nothing in the platform did. A timer whose run
failed recorded it on its own card, where nobody was looking.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from agience_chorus.lumen import inbox as I
from agience_chorus.lumen import timers as T

from .test_a_timer_fires_on_its_owners_key import FakeHttp, _armed, _ctx
from .test_chain_and_feedback import MockResponse

_spec = importlib.util.spec_from_file_location("chorus_lumen_server_inbox",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)


# ── the item ──────────────────────────────────────────────────────────────────────────────────
def test_a_new_item_says_why_and_what_it_came_from():
    ctx = I.new_context("Revenue fell", "down 40% on last week", evidence=["fig-1", " "],
                        action={"artifact_id": "draft-1", "body": {"x": 1}}, by="me", at="t0")
    item = ctx["item"]
    assert ctx["content_type"] == I.ITEM_TYPE and item["state"] == "new"
    assert item["evidence"] == ["fig-1"]
    assert item["action"] == {"artifact_id": "draft-1", "operation": "invoke", "body": {"x": 1}}
    assert item["history"] == [{"state": "new", "at": "t0", "by": "me"}]


@pytest.mark.parametrize("title,reason,action", [
    ("", "why", None), ("t", "", None), ("t", "why", {"operation": "invoke"}), ("t", "why", {"artifact_id": "a", "body": []}),
])
def test_an_item_without_a_title_a_reason_or_a_runnable_action_is_refused(title, reason, action):
    with pytest.raises(I.ItemError):
        I.new_context(title, reason, action=action)


@pytest.mark.parametrize("path,ok", [
    (["triaged", "resolved"], True),
    (["resolved"], True),
    (["resolved", "new", "triaged"], True),
    (["triaged", "triaged"], False),
    (["resolved", "triaged"], False),
    (["done"], False),
])
def test_an_item_moves_forward_and_can_be_reopened(path, ok):
    ctx = I.new_context("t", "why")
    try:
        for to in path:
            ctx = I.move(ctx, to, by="me", at="t1")
    except I.ItemError:
        assert not ok
        return
    assert ok and ctx["item"]["state"] == path[-1]
    assert [h["state"] for h in ctx["item"]["history"]] == ["new", *path]


def test_a_card_that_is_not_an_item_cannot_be_moved():
    with pytest.raises(I.ItemError):
        I.move({"title": "x"}, "resolved")


# ── a timer whose run failed ──────────────────────────────────────────────────────────────────
def test_a_failed_timer_run_is_raised_in_the_inbox_its_owner_named(tmp_path):
    fake = FakeHttp(_ctx(inbox_to="inbox-1"), op_status=500)
    T.fire_due(_armed(tmp_path), fake.http(), "http://mantle", "http://crystal", NOW, unseal_fn=lambda s: "agk_key")
    raised = [c for c in fake.calls if c[0] == "POST" and c[3].get("container_id") == "inbox-1"]
    assert len(raised) == 1 and raised[0][2] == "agk_key", "on the timer's own key"
    body = raised[0][3]
    assert body["content_type"] == I.ITEM_TYPE
    item = json.loads(body["context"])["item"]
    assert item["state"] == "new" and item["reason"]
    assert item["source"] == {"artifact_id": "t1", "kind": "timer"} and "wf-1" in item["evidence"]
    assert item["action"] == {"artifact_id": "wf-1", "operation": "invoke", "body": {"input": "x"}},         "approving it runs the routine again"


def test_a_timer_run_that_succeeded_raises_nothing(tmp_path):
    fake = FakeHttp(_ctx(inbox_to="inbox-1"))
    T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, unseal_fn=lambda s: "k")
    assert not [c for c in fake.calls if c[0] == "POST" and c[3].get("container_id") == "inbox-1"]


# ── the tools ─────────────────────────────────────────────────────────────────────────────────
class Store:
    """Mantle and Crystal, as far as the tools reach them."""

    def __init__(self, item_ctx=None, op_status=200, op_text="done"):
        self.docs = {}
        if item_ctx is not None:
            self.docs["item-1"] = {"id": "item-1", "content_type": I.ITEM_TYPE, "context": json.dumps(item_ctx)}
        self.op_status, self.op_text = op_status, op_text
        self.calls = []

    def client(self):
        store = self

        class _C:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, **kw):
                store.calls.append(("GET", url, headers))
                doc = store.docs.get(url.rsplit("/", 1)[-1])
                return MockResponse(doc or {}, 200 if doc else 404)

            async def post(self, url, headers=None, json=None, **kw):
                store.calls.append(("POST", url, headers, json))
                if "/op/" in url:
                    return MockResponse({"content": [{"type": "text", "text": store.op_text}]}, store.op_status)
                store.docs["new-1"] = {"id": "new-1", **json}
                return MockResponse({"id": "new-1"}, 201)

            async def patch(self, url, headers=None, json=None, **kw):
                store.calls.append(("PATCH", url, headers, json))
                store.docs[url.rsplit("/", 1)[-1]]["context"] = json["context"]
                return MockResponse({}, 200)
        return _C

    def item(self, key="item-1"):
        return json.loads(self.docs[key]["context"])["item"]


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
async def test_raising_an_item_places_it_on_the_callers_credential(person):
    store = Store()
    with patch.object(L.httpx, "AsyncClient", store.client()):
        out = json.loads(await L.raise_item("inbox-1", "Approve the reply", "a draft to send",
                                            evidence=["mail-1"], action={"artifact_id": "send-1"}))
    assert out == {"item_id": "new-1", "state": "new"}
    post = store.calls[0]
    assert post[2]["Authorization"] == "Bearer delegation-for-me" and post[3]["container_id"] == "inbox-1"
    assert store.item("new-1")["action"]["artifact_id"] == "send-1"
    assert store.item("new-1")["history"][0]["by"] == "me-1"


@pytest.mark.asyncio
async def test_a_move_is_checked_and_recorded_with_who_made_it(person):
    store = Store(I.new_context("t", "why"))
    with patch.object(L.httpx, "AsyncClient", store.client()):
        assert json.loads(await L.set_item_state("item-1", "triaged", note="looking"))["state"] == "triaged"
        refused = json.loads(await L.set_item_state("item-1", "triaged"))
    assert "cannot be moved" in refused["error"]
    assert store.item()["history"][-1] == {**store.item()["history"][-1], "state": "triaged", "by": "me-1", "note": "looking"}


@pytest.mark.asyncio
async def test_approving_runs_the_action_as_the_approver_and_resolves_the_item(person):
    store = Store(I.new_context("t", "why", action={"artifact_id": "send-1", "body": {"to": "x"}}))
    with patch.object(L.httpx, "AsyncClient", store.client()):
        out = json.loads(await L.approve_item("item-1"))
    assert out["state"] == "resolved"
    run = [c for c in store.calls if c[0] == "POST" and "/op/" in c[1]][0]
    assert run[1].endswith("/artifacts/send-1/op/invoke") and run[3] == {"to": "x"}
    assert run[2]["Authorization"] == "Bearer persons-token", "the approver's own credential"
    assert store.item()["state"] == "resolved" and store.item()["outcome"]["ok"] is True


@pytest.mark.asyncio
async def test_an_approval_whose_action_failed_is_recorded_and_leaves_the_item_open(person):
    store = Store(I.new_context("t", "why", action={"artifact_id": "send-1"}),
                  op_text=json.dumps({"error": "mail refused"}))
    with patch.object(L.httpx, "AsyncClient", store.client()):
        out = json.loads(await L.approve_item("item-1"))
    assert "mail refused" in out["error"]
    assert store.item()["state"] == "new" and store.item()["outcome"]["ok"] is False


@pytest.mark.asyncio
async def test_an_item_without_an_action_or_a_card_that_is_not_one_is_not_approved(person):
    store = Store(I.new_context("t", "why"))
    store.docs["note-1"] = {"id": "note-1", "content_type": "text/plain", "context": "{}"}
    with patch.object(L.httpx, "AsyncClient", store.client()):
        assert "no action" in json.loads(await L.approve_item("item-1"))["error"]
        assert "not an inbox item" in json.loads(await L.approve_item("note-1"))["error"]
        assert "cannot read" in json.loads(await L.approve_item("gone"))["error"]
    assert not [c for c in store.calls if "/op/" in c[1]], "nothing ran"
