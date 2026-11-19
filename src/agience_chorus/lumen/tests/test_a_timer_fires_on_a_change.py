"""A timer can fire on the changes inside a container in place of a schedule (FR-007).

It hears them on Mantle's event stream, on the timer's Lumen delegation, from the cursor it last
kept; it fires once for each event, with the changed artifact in the run's params, and never on its
own card or on what it records or raises.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from agience_chorus.lumen import timers as T

NOW = datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)
ON = {"container_id": "inbox-c", "event_names": ["artifact.created"]}


def _ctx(**timer):
    return {"title": "Triage",
            "timer": {"on": ON,
                      "target": {"artifact_id": "wf-1", "operation": "invoke",
                                 "body": {"params": {"mode": "fast"}}},
                      "results_to": "runs-c", "inbox_to": "owner-inbox", **timer}}


class FakeHttp:
    def __init__(self, ctx, timer_status=200):
        self.ctx, self.timer_status, self.calls = ctx, timer_status, []

    def http(self):
        def get(url, key):
            self.calls.append(("GET", url, key))
            return self.timer_status, {"id": "t1", "context": json.dumps(self.ctx)}

        def post(url, key, body):
            self.calls.append(("POST", url, key, body))
            return 200, {"content": [{"type": "text", "text": "ran"}]}

        def patch(url, key, body):
            self.calls.append(("PATCH", url, key, body))
            self.ctx = json.loads(body["context"])
            return 200, {}
        return T.Http(get=get, post=post, patch=patch)

    def runs(self):
        return [c for c in self.calls if c[0] == "POST" and "/op/" in c[1]]


def _tokens(status=200):
    return lambda timer_id, entry: (status, "m-tok", "c-tok") if status == 200 else (status, None, None)


def _armed(tmp_path, **extra):
    store = T.Store(tmp_path)
    store.arm("t1", "jg-1", "p-1", on=ON)
    if extra:
        store.note("t1", **extra)
    return store


def _event(art_id="a-9", name="artifact.created", event_id="e-1", cursor="m1:7", collection="inbox-c"):
    return {"event": name, "event_id": event_id, "cursor": cursor, "sub_id": "t1",
            "payload": {"artifact": {"id": art_id, "collection_id": collection}}}


# ── what a timer fires on ─────────────────────────────────────────────────────────────────────
def test_changes_are_validated():
    assert T.check_on({"container_id": " c1 "}) == {"container_id": "c1",
                                                    "event_names": ["artifact.created"]}
    assert T.check_on({"container_id": "c1", "event_names": "artifact.updated"})["event_names"] == [
        "artifact.updated"]
    for bad in (None, {}, {"container_id": ""}, {"container_id": "c1", "event_names": ["artifact.observed"]},
                {"container_id": "c1", "event_names": ["anything"]}):
        with pytest.raises(T.ScheduleError):
            T.check_on(bad)


def test_a_timer_names_a_schedule_or_changes_never_both():
    assert T.check_when({"schedule": {"every_minutes": 5}}) == ("schedule", {"every_minutes": 5})
    assert T.check_when({"on": {"container_id": "c1"}})[0] == "on"
    for bad in ({}, {"schedule": {"every_minutes": 5}, "on": {"container_id": "c1"}}, None):
        with pytest.raises(T.ScheduleError):
            T.check_when(bad)


def test_the_grant_reaches_the_container_it_listens_to():
    out = T.reach("t1", _ctx()["timer"])
    assert out == ["t1", "wf-1", "runs-c", "owner-inbox", "inbox-c"]


# ── firing once per event ─────────────────────────────────────────────────────────────────────
def test_an_event_fires_the_target_with_the_changed_artifact(tmp_path):
    store, fake = _armed(tmp_path), FakeHttp(_ctx())
    what = T.fire_on_event(store, fake.http(), "http://m", "http://c", NOW, _tokens(), "t1", _event())
    assert what == "fired (200)"
    (_, url, key, body), = fake.runs()
    assert url == "http://c/artifacts/wf-1/op/invoke" and key == "c-tok"
    assert body["params"] == {"mode": "fast", "artifact_id": "a-9", "event": "artifact.created"}
    assert fake.ctx["timer_state"]["runs"] == 1
    entry = store.load()["t1"]
    assert entry["since"] == "m1:7" and entry["heard"] == ["e-1"] and entry["on"] == ON


def test_an_event_delivered_twice_fires_once(tmp_path):
    store, fake = _armed(tmp_path), FakeHttp(_ctx())
    http = fake.http()
    T.fire_on_event(store, http, "http://m", "http://c", NOW, _tokens(), "t1", _event())
    assert T.fire_on_event(store, http, "http://m", "http://c", NOW, _tokens(), "t1",
                           _event()) == "already heard"
    assert len(fake.runs()) == 1


@pytest.mark.parametrize("event,why", [
    (_event(art_id="t1"), "its own card"),
    (_event(collection="runs-c"), "its own record"),
    (_event(collection="owner-inbox"), "its own record"),
    (_event(name="artifact.deleted"), "not an event it fires on"),
])
def test_a_timer_never_fires_on_itself_or_what_it_writes(tmp_path, event, why):
    store, fake = _armed(tmp_path), FakeHttp(_ctx())
    what = T.fire_on_event(store, fake.http(), "http://m", "http://c", NOW, _tokens(), "t1", event)
    assert what == f"passed over ({why})" and not fake.runs()
    assert store.load()["t1"]["since"] == "m1:7"


def test_a_paused_trigger_fires_nothing(tmp_path):
    store, fake = _armed(tmp_path), FakeHttp(_ctx(enabled=False))
    assert T.fire_on_event(store, fake.http(), "http://m", "http://c", NOW, _tokens(), "t1",
                           _event()) == "paused"
    assert not fake.runs()


def test_a_refused_grant_disarms_the_trigger(tmp_path):
    store, fake = _armed(tmp_path), FakeHttp(_ctx())
    assert T.fire_on_event(store, fake.http(), "http://m", "http://c", NOW, _tokens(403), "t1",
                           _event()) == "dropped (grant 403)"
    assert "t1" not in store.load()


def test_a_card_saved_to_a_schedule_goes_back_to_the_pass(tmp_path):
    ctx = _ctx()
    ctx["timer"].pop("on")
    ctx["timer"]["schedule"] = {"every_minutes": 5}
    store, fake = _armed(tmp_path), FakeHttp(ctx)
    assert T.fire_on_event(store, fake.http(), "http://m", "http://c", NOW, _tokens(), "t1",
                           _event()) == "no longer listening"
    entry = store.load()["t1"]
    assert not entry.get("on") and entry["schedule"] == {"every_minutes": 5}


def test_the_pass_over_due_timers_leaves_a_trigger_alone(tmp_path):
    store, fake = _armed(tmp_path), FakeHttp(_ctx())
    assert T.fire_due(store, fake.http(), "http://m", "http://c", NOW, _tokens()) == {"t1": "listening"}
    assert fake.calls == []


def test_a_schedule_saved_as_changes_is_handed_to_a_listener(tmp_path):
    store = T.Store(tmp_path)
    store.arm("t1", "jg-1", "p-1", schedule={"every_minutes": 5})
    fake = FakeHttp(_ctx())
    assert T.fire_due(store, fake.http(), "http://m", "http://c", NOW, _tokens()) == {"t1": "listening"}
    assert store.load()["t1"]["on"] == ON and not fake.runs()


def test_the_cursor_moves_each_origin_forward():
    assert T.advance("m1:7,m2:3", "m1:9") == "m1:9,m2:3"
    assert T.advance("m1:9", "m1:4,m2:1") == "m1:9,m2:1"
    assert T.advance("", "bad,m1:x") == ""


# ── the listener ──────────────────────────────────────────────────────────────────────────────
class FakeSocket:
    def __init__(self, frames):
        self.frames, self.sent = list(frames), []

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if not self.frames:
            raise ConnectionError("closed")
        return json.dumps(self.frames.pop(0))


def test_the_listener_subscribes_on_the_lumen_delegation_and_fires_each_event(tmp_path):
    store = _armed(tmp_path, since="m1:3")
    sockets, opened, fired = [FakeSocket([{"ack": "t1", "delivery": "live"}, _event()])], [], []

    @asynccontextmanager
    async def connect(url, key):
        opened.append((url, key))
        yield sockets.pop(0)

    def fire(event):
        fired.append(event["event_id"])
        store.disarm("t1")            # the owner disarms it after this run
        return "fired (200)"

    sock = sockets[0]
    why = asyncio.run(T.listen(store, "t1", _tokens(), connect, "ws://m/events", fire, retry=0))
    assert why == "not listening"
    assert opened == [("ws://m/events", "m-tok")]
    assert sock.sent == [{"op": "subscribe", "id": "t1", "since": "m1:3",
                          "filter": {"container_id": "inbox-c", "event_names": ["artifact.created"]}}]
    assert fired == ["e-1"]


def test_the_listener_opens_the_stream_again_when_it_closes(tmp_path):
    store = _armed(tmp_path)
    opened = []

    @asynccontextmanager
    async def connect(url, key):
        opened.append(key)
        if len(opened) == 2:
            store.disarm("t1")
        yield FakeSocket([])

    why = asyncio.run(T.listen(store, "t1", _tokens(), connect, "ws://m/events",
                               lambda e: "fired (200)", retry=0))
    assert why == "not listening" and len(opened) == 2


def test_the_listener_stops_when_the_grant_is_refused(tmp_path):
    store = _armed(tmp_path)

    @asynccontextmanager
    async def connect(url, key):                                       # pragma: no cover
        raise AssertionError("no stream without a delegation")
        yield

    why = asyncio.run(T.listen(store, "t1", _tokens(401), connect, "ws://m/events",
                               lambda e: "", retry=0))
    assert why == "dropped (grant 401)" and "t1" not in store.load()


# ── the server keeps one listener per armed trigger ───────────────────────────────────────────
def test_the_server_keeps_one_listener_per_trigger(tmp_path, monkeypatch):
    from agience_chorus.lumen import server as S
    store = T.Store(tmp_path)
    store.arm("t1", "jg-1", "p-1", on=ON)
    store.arm("t2", "jg-2", "p-1", schedule={"every_minutes": 5})
    started = []

    async def listen(store_, tid, tokens, connect, url, fire, retry=T.RETRY_SECONDS):
        started.append((tid, url))
        await asyncio.sleep(3600)

    monkeypatch.setattr(S._timers, "listen", listen)
    monkeypatch.setattr(S, "MANTLE_URI", "https://mantle.example")

    async def run():
        listeners = {}
        S._keep_listeners(store, listeners, None)
        S._keep_listeners(store, listeners, None)
        await asyncio.sleep(0)
        assert set(listeners) == {"t1"}
        store.disarm("t1")
        S._keep_listeners(store, listeners, None)
        assert listeners == {}

    asyncio.run(run())
    assert started == [("t1", "wss://mantle.example/events")]
