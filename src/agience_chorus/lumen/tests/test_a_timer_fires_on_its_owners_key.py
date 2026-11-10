"""A Timer fires its target on schedule, on its owner's job grant, and stops when the grant does.

2026-10-18: nothing in the platform fired a deferred action; `schedule_action` refused for that
reason. `timers.py` is the operator: a schedule, a job grant at Origin, one pass that fires what is
due. 2026-11-10 (BUG-024/BUG-035): it ran on a grant key Mantle no longer issues, over the whole
workspace; it runs on an Origin job grant over what it reaches, and keeps no key.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agience_chorus.lumen import timers as T

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("schedule,last,due", [
    ({"every_minutes": 15}, None, True),
    ({"every_minutes": 15}, (NOW - timedelta(minutes=14)).isoformat(), False),
    ({"every_minutes": 15}, (NOW - timedelta(minutes=15)).isoformat(), True),
    ({"daily_at": "11:30"}, None, True),
    ({"daily_at": "11:30"}, (NOW - timedelta(minutes=20)).isoformat(), False),
    ({"daily_at": "11:30"}, (NOW - timedelta(hours=1)).isoformat(), True),
    ({"daily_at": "12:30"}, (NOW - timedelta(hours=20)).isoformat(), False),
    ({"at": "2026-10-18T11:00:00Z"}, None, True),
    ({"at": "2026-10-18T13:00:00Z"}, None, False),
    ({"at": "2026-10-18T11:00:00Z"}, (NOW - timedelta(minutes=50)).isoformat(), False),
])
def test_a_schedule_says_when_a_run_is_due(schedule, last, due):
    assert T.is_due(schedule, last, NOW) is due


@pytest.mark.parametrize("schedule", [
    {}, {"every_minutes": 0}, {"every_minutes": "5"}, {"daily_at": "25:00"}, {"at": "soon"},
    {"every_minutes": 5, "daily_at": "07:00"}, None,
])
def test_an_unreadable_schedule_is_refused(schedule):
    with pytest.raises(T.ScheduleError):
        T.check_schedule(schedule)


class FakeHttp:
    def __init__(self, timer_ctx, timer_status=200, op_status=200):
        self.ctx, self.timer_status, self.op_status = timer_ctx, timer_status, op_status
        self.calls = []

    def http(self):
        def get(url, key):
            self.calls.append(("GET", url, key))
            return self.timer_status, {"id": "t1", "context": json.dumps(self.ctx)}

        def post(url, key, body):
            self.calls.append(("POST", url, key, body))
            return self.op_status, {"content": [{"type": "text", "text": "ran"}]}

        def patch(url, key, body):
            self.calls.append(("PATCH", url, key, body))
            self.ctx = json.loads(body["context"])
            return 200, {}
        return T.Http(get=get, post=post, patch=patch)


def _armed(tmp_path):
    store = T.Store(tmp_path)
    store.arm("t1", "jg-1", "p-1")
    return store


def _tokens(status=200):
    """Origin's answer for a firing: Lumen's server delegation and the one narrowed to Crystal."""
    return lambda timer_id, entry: (status, "m-tok", "c-tok") if status == 200 else (status, None, None)


def _ctx(**timer):
    return {"title": "Nightly digest",
            "timer": {"schedule": {"every_minutes": 15},
                      "target": {"artifact_id": "wf-1", "operation": "invoke", "body": {"input": "x"}},
                      **timer}}


def test_a_due_timer_fires_its_target_on_its_key_and_records_the_run(tmp_path):
    fake = FakeHttp(_ctx(results_to="log-1"))
    report = T.fire_due(_armed(tmp_path), fake.http(), "http://mantle", "http://crystal", NOW,
                        tokens=_tokens())
    assert report == {"t1": "fired (200)"}
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert posts[0][1:] == ("http://crystal/artifacts/wf-1/op/invoke", "c-tok", {"input": "x"})
    assert all(c[2] == "m-tok" for c in fake.calls if "/op/" not in c[1]), \
        "Lumen's own delegation for the timer's card and its records"
    assert fake.ctx["timer_state"]["runs"] == 1 and fake.ctx["timer_state"]["last_status"] == 200
    assert posts[1][1] == "http://mantle/artifacts" and posts[1][3]["container_id"] == "log-1"


def test_a_timer_not_yet_due_or_paused_does_nothing(tmp_path):
    ctx = _ctx()
    ctx["timer_state"] = {"last_run": (NOW - timedelta(minutes=5)).isoformat()}
    fake = FakeHttp(ctx)
    assert T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, tokens=_tokens()) == {"t1": "not due"}
    fake = FakeHttp(_ctx(enabled=False))
    assert T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, tokens=_tokens()) == {"t1": "paused"}
    assert not [c for c in fake.calls if c[0] != "GET"]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_gone_timer_drops_the_timer(tmp_path, status):
    store = _armed(tmp_path)
    fake = FakeHttp(_ctx(), timer_status=status)
    assert T.fire_due(store, fake.http(), "m", "c", NOW, tokens=_tokens()) == {"t1": f"dropped ({status})"}
    assert store.load() == {}, "it does not fire again"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_revoked_or_expired_grant_drops_the_timer(tmp_path, status):
    store = _armed(tmp_path)
    fake = FakeHttp(_ctx())
    assert T.fire_due(store, fake.http(), "m", "c", NOW, tokens=_tokens(status)) == \
        {"t1": f"dropped (grant {status})"}
    assert store.load() == {} and fake.calls == [], "nothing is read or run"


def test_origin_out_of_reach_keeps_the_timer_for_the_next_pass(tmp_path):
    store = _armed(tmp_path)
    fake = FakeHttp(_ctx())
    assert T.fire_due(store, fake.http(), "m", "c", NOW, tokens=_tokens(599)) == {"t1": "no delegation (599)"}
    assert "t1" in store.load() and fake.calls == []


def test_a_timer_armed_on_a_key_is_armed_again(tmp_path):
    store = T.Store(tmp_path)
    store._save({"t1": {"sealed_key": "s", "key_id": "k"}})
    fake = FakeHttp(_ctx())
    assert "arm it again" in T.fire_due(store, fake.http(), "m", "c", NOW, tokens=_tokens())["t1"]
    assert store.load() == {}


def test_disarming_names_the_grant_it_ran_on(tmp_path):
    store = _armed(tmp_path)
    assert store.disarm("t1")["job_grant"] == "jg-1" and store.disarm("t1") is None


def test_a_failed_run_is_recorded_with_its_answer(tmp_path):
    fake = FakeHttp(_ctx(), op_status=403)
    T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, tokens=_tokens())
    assert fake.ctx["timer_state"]["last_status"] == 403 and fake.ctx["timer_state"]["last_error"]


def test_a_run_the_gateway_answered_200_for_but_whose_workflow_failed_is_recorded_as_failed(tmp_path):
    """2026-10-18: a timer recorded a run as successful because Crystal answered 200, while the
    workflow inside had failed."""
    class Failing(FakeHttp):
        def http(self):
            h = super().http()
            inner = h.post

            def post(url, key, body):
                if "/op/" in url:
                    self.calls.append(("POST", url, key, body))
                    return 200, {"content": [{"type": "text", "text": json.dumps({"error": "Step 0 failed: HTTP 401"})}]}
                return inner(url, key, body)
            return T.Http(get=h.get, post=post, patch=h.patch)

    fake = Failing(_ctx())
    report = T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, tokens=_tokens())
    assert "failed" in report["t1"]
    assert fake.ctx["timer_state"]["last_ok"] is False and "HTTP 401" in fake.ctx["timer_state"]["last_error"]


# ── what its grant must reach ─────────────────────────────────────────────────────────────────
# 2026-10-21: a workflow's steps are operators, and its artifacts are links, in places other than the
# timer's workspace; a key over the workspace alone was refused at the first step. 2026-11-10
# (BUG-035): the grant reaches the timer itself, never its workspace.

def test_a_timers_key_reaches_each_operator_and_link_its_workflow_uses_once():
    spec = {"target": {"artifact_id": "wf"}, "results_to": "runs-1", "inbox_to": "ws-1"}
    workflow = {"run": {"type": "workflow", "steps": [
        {"operator_id": "op-rec", "arguments": {"collection_id": "@link.s1.collection_id"}},
        {"operator_id": "op-raise", "arguments": {"container_id": "@link.s2.container_id", "title": "x"}},
        {"operator_id": "op-rec", "arguments": {"collection_id": "@link.s3.collection_id"}},
    ]}}
    links = {"s1.collection_id": "accounts-1", "s2.container_id": "inbox-1", "s3.collection_id": "accounts-1"}
    assert T.reach("t1", spec, workflow, links) == ["t1", "wf", "runs-1", "ws-1", "op-rec", "accounts-1",
                                                     "op-raise", "inbox-1"]


def test_a_timer_never_reaches_its_workspace():
    assert T.reach("t1", {"target": {"artifact_id": "wf"}}, {"run": {"type": "workflow", "steps": []}}) == \
        ["t1", "wf"]


def test_a_timer_on_anything_but_a_workflow_reaches_only_what_its_card_names():
    spec = {"target": {"artifact_id": "op-1"}, "results_to": "log-1"}
    assert T.reach("t1", spec, {"operator": {"server": "lumen"}}) == ["t1", "op-1", "log-1"]


def test_a_card_that_calls_a_tool_directly_reaches_the_operator_that_offers_it():
    """A card made before steps were operators calls persona tools directly; the platform's gate
    asks the key for the operator behind each one, so the key reaches it."""
    platform = {("sage", "browse_collections"): "op-list", ("lumen", "reconcile"): "op-rec"}
    got = T.reach("t1", {"target": {"artifact_id": "wf"}}, {"run": {"type": "workflow", "steps": []}},
                  tools=[("sage", "browse_collections"), ("lumen", "workflow_catalog")], platform=platform)
    assert got == ["t1", "wf", "op-list"], "a tool no operator offers adds nothing"


# ── Origin is asked only for a timer that is due ──────────────────────────────────────────────
def _counting():
    asked = []

    def tokens(timer_id, entry):
        asked.append(timer_id)
        return 200, "m-tok", "c-tok"
    return asked, tokens


def test_a_timer_not_due_by_its_last_read_card_asks_origin_for_nothing(tmp_path):
    store = T.Store(tmp_path)
    store.arm("t1", "jg-1", "p-1", schedule={"every_minutes": 15},
              last_run=(NOW - timedelta(minutes=5)).isoformat())
    asked, tokens = _counting()
    assert T.fire_due(store, FakeHttp(_ctx()).http(), "m", "c", NOW, tokens=tokens) == {"t1": "not due"}
    assert asked == []
    # Once due it is asked for, it fires, and the run is kept so the next pass waits again.
    later = NOW + timedelta(minutes=11)
    assert T.fire_due(store, FakeHttp(_ctx()).http(), "m", "c", later, tokens=tokens) == {"t1": "fired (200)"}
    assert asked == ["t1"] and store.load()["t1"]["last_run"] == later.isoformat()
    assert T.fire_due(store, FakeHttp(_ctx()).http(), "m", "c", later + timedelta(minutes=1),
                      tokens=tokens) == {"t1": "not due"}
    assert asked == ["t1"]


def test_a_paused_timer_is_read_again_only_now_and_then(tmp_path):
    store = _armed(tmp_path)
    asked, tokens = _counting()
    fake = FakeHttp(_ctx(enabled=False))
    assert T.fire_due(store, fake.http(), "m", "c", NOW, tokens=tokens) == {"t1": "paused"}
    assert T.fire_due(store, fake.http(), "m", "c", NOW + timedelta(minutes=5), tokens=tokens) == {"t1": "paused"}
    assert asked == ["t1"]
    T.fire_due(store, fake.http(), "m", "c", NOW + T.PAUSED_RECHECK, tokens=tokens)
    assert asked == ["t1", "t1"]
