"""A Timer fires its target on schedule, on the key its owner issued, and stops when the key does.

2026-10-18: nothing in the platform fired a deferred action; `schedule_action` refused for that
reason. `timers.py` is the operator: a schedule, a sealed key, one pass that fires what is due.
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


def test_a_key_is_kept_sealed_under_the_nodes_chorus_key(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "chorus.private.pem").write_bytes(k.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    (tmp_path / "chorus.public.pem").write_bytes(k.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    sealed = T.seal("agk_secret_value", tmp_path)
    assert "agk_secret_value" not in sealed
    assert T.unseal(sealed, tmp_path) == "agk_secret_value"


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
    store.arm("t1", "sealed", "key-1")
    return store


def _ctx(**timer):
    return {"title": "Nightly digest",
            "timer": {"schedule": {"every_minutes": 15},
                      "target": {"artifact_id": "wf-1", "operation": "invoke", "body": {"input": "x"}},
                      **timer}}


def test_a_due_timer_fires_its_target_on_its_key_and_records_the_run(tmp_path):
    fake = FakeHttp(_ctx(results_to="log-1"))
    report = T.fire_due(_armed(tmp_path), fake.http(), "http://mantle", "http://crystal", NOW,
                        unseal_fn=lambda s: "agk_key")
    assert report == {"t1": "fired (200)"}
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert posts[0][1:] == ("http://crystal/artifacts/wf-1/op/invoke", "agk_key", {"input": "x"})
    assert all(c[2] == "agk_key" for c in fake.calls), "every call carries the timer's key"
    assert fake.ctx["timer_state"]["runs"] == 1 and fake.ctx["timer_state"]["last_status"] == 200
    assert posts[1][1] == "http://mantle/artifacts" and posts[1][3]["container_id"] == "log-1"


def test_a_timer_not_yet_due_or_paused_does_nothing(tmp_path):
    ctx = _ctx()
    ctx["timer_state"] = {"last_run": (NOW - timedelta(minutes=5)).isoformat()}
    fake = FakeHttp(ctx)
    assert T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, unseal_fn=lambda s: "k") == {"t1": "not due"}
    fake = FakeHttp(_ctx(enabled=False))
    assert T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, unseal_fn=lambda s: "k") == {"t1": "paused"}
    assert not [c for c in fake.calls if c[0] != "GET"]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_revoked_key_or_a_gone_timer_drops_the_timer(tmp_path, status):
    store = _armed(tmp_path)
    fake = FakeHttp(_ctx(), timer_status=status)
    assert T.fire_due(store, fake.http(), "m", "c", NOW, unseal_fn=lambda s: "k") == {"t1": f"dropped ({status})"}
    assert store.load() == {}, "it does not fire again"


def test_a_failed_run_is_recorded_with_its_answer(tmp_path):
    fake = FakeHttp(_ctx(), op_status=403)
    T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, unseal_fn=lambda s: "k")
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
    report = T.fire_due(_armed(tmp_path), fake.http(), "m", "c", NOW, unseal_fn=lambda s: "k")
    assert "failed" in report["t1"]
    assert fake.ctx["timer_state"]["last_ok"] is False and "HTTP 401" in fake.ctx["timer_state"]["last_error"]


# ── what its key must reach ───────────────────────────────────────────────────────────────────
# 2026-10-21: a workflow's steps are operators, and its artifacts are links, in places other than the
# timer's workspace; a key over the workspace alone was refused at the first step.

def test_a_timers_key_reaches_each_operator_and_link_its_workflow_uses_once():
    spec = {"target": {"artifact_id": "wf"}, "results_to": "runs-1", "inbox_to": "ws-1"}
    workflow = {"run": {"type": "workflow", "steps": [
        {"operator_id": "op-rec", "arguments": {"collection_id": "@link.s1.collection_id"}},
        {"operator_id": "op-raise", "arguments": {"container_id": "@link.s2.container_id", "title": "x"}},
        {"operator_id": "op-rec", "arguments": {"collection_id": "@link.s3.collection_id"}},
    ]}}
    links = {"s1.collection_id": "accounts-1", "s2.container_id": "inbox-1", "s3.collection_id": "accounts-1"}
    assert T.reach("ws-1", spec, workflow, links) == ["ws-1", "wf", "runs-1", "op-rec", "accounts-1", "op-raise", "inbox-1"]


def test_a_timer_on_anything_but_a_workflow_reaches_only_what_its_card_names():
    spec = {"target": {"artifact_id": "op-1"}, "results_to": "log-1"}
    assert T.reach("ws-1", spec, {"operator": {"server": "lumen"}}) == ["ws-1", "op-1", "log-1"]
