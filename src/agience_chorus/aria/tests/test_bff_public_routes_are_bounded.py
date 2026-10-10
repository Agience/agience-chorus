"""aria's bff answers strangers, so every route it serves them is bounded.

POST /api/contact sends mail on the credential that also sends sign-in codes. It needs the signed
challenge the form fetches from /api/contact/nonce, is rate-limited per client and overall, and
reads at most a small body. /healthz does not name the lead addresses.

POST /api/chat caps what it reads, runs the synchronous responder off the event loop, and passes no
slash command to the responder — `/use` and `/collections` would let a stranger switch and list the
collections the responder reads. The reading responder itself keeps state per caller: an anonymous
caller carries nothing between turns, and one caller's screen is never another's context.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from starlette.testclient import TestClient

from agience_chorus.aria import web_bff

mod = web_bff._load_bff_module()


@pytest.fixture
def bff(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "LEADS_FILE", tmp_path / "leads.jsonl")
    monkeypatch.setattr(mod, "_GMAIL_READY", False)
    monkeypatch.setattr(mod, "_SMTP_READY", False)
    monkeypatch.setattr(mod, "LEAD_WEBHOOK_URL", None)
    if hasattr(mod, "_Window"):                          # fresh windows: no budget spent by others
        monkeypatch.setattr(mod, "_contact_per_client", mod._Window(5, 600.0))
        monkeypatch.setattr(mod, "_contact_global", mod._Window(60, 3600.0))
    with TestClient(mod.app) as client:
        yield client


_LEAD = {"content": json.dumps({"email": "p@example.com", "name": "P"}),
         "context": json.dumps({"source": "website-contact"})}


def _challenge(client):
    return client.get("/api/contact/nonce").json()["nonce"]


def _post_lead(client, token, body=None):
    headers = {"X-Agience-Challenge": token} if token is not None else {}
    return client.post("/api/contact", json=body if body is not None else _LEAD, headers=headers)


# ── contact: challenge ────────────────────────────────────────────────────────────────────────────

def test_a_lead_with_a_fresh_challenge_is_stored(bff, tmp_path):
    r = _post_lead(bff, _challenge(bff))
    assert r.status_code == 201, r.text
    assert (tmp_path / "leads.jsonl").read_text(encoding="utf-8").count("\n") == 1


@pytest.mark.parametrize("token", [None, "", "deadbeef", "1.2.3", "9999999999.abcd.0000"])
def test_a_lead_without_a_valid_challenge_is_refused(bff, tmp_path, token):
    r = _post_lead(bff, token)
    assert r.status_code == 403
    assert not (tmp_path / "leads.jsonl").exists()


def test_an_expired_challenge_is_refused(bff):
    payload = "%d.%s" % (int(time.time()) - 60, "ab" * 16)
    expired = "%s.%s" % (payload, mod._nonce_sig(payload))
    assert _post_lead(bff, expired).status_code == 403


# ── contact: rate limits and size ─────────────────────────────────────────────────────────────────

def test_one_client_is_limited(bff):
    token = _challenge(bff)
    codes = [_post_lead(bff, token).status_code for _ in range(7)]
    assert codes[:5] == [201] * 5 and codes[5:] == [429, 429]


def test_the_route_is_limited_overall(bff, monkeypatch):
    monkeypatch.setattr(mod, "_contact_per_client", mod._Window(1000, 600.0))
    monkeypatch.setattr(mod, "_contact_global", mod._Window(3, 3600.0))
    token = _challenge(bff)
    codes = [_post_lead(bff, token).status_code for _ in range(5)]
    assert codes == [201, 201, 201, 429, 429]


def test_an_oversize_body_is_refused(bff, tmp_path):
    big = {"content": "x" * (mod._CONTACT_MAX_BYTES + 1), "context": "{}"}
    r = _post_lead(bff, _challenge(bff), body=big)
    assert r.status_code == 413
    assert not (tmp_path / "leads.jsonl").exists()


def test_healthz_names_no_mail_address(bff):
    body = bff.get("/healthz").json()
    assert "lead_to" not in body and "lead_from" not in body
    assert "@" not in json.dumps(body)


# ── chat ──────────────────────────────────────────────────────────────────────────────────────────

def _chat(client, text):
    return client.post("/api/chat", json={"params": {"messages": [{"role": "user", "content": text}]}})


def test_an_overlong_message_is_refused_before_the_responder(bff, monkeypatch):
    seen = []
    monkeypatch.setattr(mod, "_RESPOND_CARRIER", {"respond": lambda q: seen.append(q)})
    r = _chat(bff, "x" * (mod._CHAT_MAX_CHARS + 1))
    assert r.status_code == 413 and seen == []


@pytest.mark.parametrize("text", ["/collections", "/use read:private-diary", "/anything"])
def test_slash_commands_never_reach_the_responder(bff, monkeypatch, text):
    seen = []
    monkeypatch.setattr(mod, "_RESPOND_CARRIER",
                        {"respond": lambda q: seen.append(q) or {"answer": "listed"}})
    body = _chat(bff, text).json()
    assert seen == []
    assert body.get("refused") is True and body.get("text") == ""


def test_the_responder_runs_off_the_event_loop(bff, monkeypatch):
    where = {}

    def _respond(q):
        try:
            asyncio.get_running_loop()
            where["on_loop"] = True
        except RuntimeError:
            where["on_loop"] = False
        return {"answer": "ok", "cited": ["c"]}

    monkeypatch.setattr(mod, "_RESPOND_CARRIER", {"respond": _respond})
    assert _chat(bff, "hello").json().get("text") == "ok"
    assert where == {"on_loop": False}


# ── the reading responder's state ─────────────────────────────────────────────────────────────────

@pytest.fixture
def reading_chat(monkeypatch, tmp_path):
    """`lumen.reading.chat.respond` over a stub reading and a recording `complete`."""
    import sqlite3
    from agience_chorus.lumen.reading import chat as rc
    from agience_chorus.lumen.reading import complete as rcomplete

    db = tmp_path / "lattice.db"
    sqlite3.connect(db).execute("CREATE TABLE vertex (id TEXT)").connection.close()
    monkeypatch.setenv("EMBER_SQLITE_DIR", str(tmp_path))
    monkeypatch.setenv("READ_COLLECTION", "read:public")
    if hasattr(rc, "_STATES"):
        monkeypatch.setattr(rc, "_STATES", type(rc._STATES)())

    class _Reading:
        idx = [1]

    monkeypatch.setattr(rc, "_reading", lambda ro, col: _Reading())
    log = []

    def _complete(ro, col, q, reading=None, carried=None):
        log.append((col, list(carried or [])))
        return {"completion": "said " + q, "on_screen": ["screen-of-" + q], "steps": []}

    monkeypatch.setattr(rcomplete, "complete", _complete)
    return rc, log


def test_an_anonymous_caller_cannot_switch_or_list_collections(reading_chat):
    rc, log = reading_chat
    for q in ("/use read:private", "/collections"):
        out = rc.respond(q)
        assert out.get("refused") is True and out.get("answer") == ""
    assert log == []


def test_anonymous_turns_carry_nothing(reading_chat):
    rc, log = reading_chat
    rc.respond("first stranger's secret")
    rc.respond("second stranger")
    assert log == [("read:public", []), ("read:public", [])]


def test_identified_callers_keep_separate_state(reading_chat):
    rc, log = reading_chat
    rc.respond("alpha", caller="a")
    rc.respond("beta", caller="b")
    rc.respond("again", caller="a")
    assert log == [("read:public", []), ("read:public", []),
                   ("read:public", ["screen-of-alpha"])]
