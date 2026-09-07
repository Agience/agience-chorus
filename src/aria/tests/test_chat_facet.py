"""aria's chat facet — the single-page chat UI plus the op.respond reach wiring.

The chat surface is served by aria's www bff tekton (op.web.bff): a GET /chat page (the
presentation surface for lumen conversations) backed by POST /api/chat, which reaches
lumen's op.respond over the ground plane via ember.runtime.reach.

The live carrier is a gated deploy step, so op.respond is dark by default. When dark, POST /api/chat
honest-degrades: it returns an explicit "assistant offline" state, never a fabricated assistant reply.
These tests pin both halves: the page serves, and the endpoint's dark-path response carries no
fabricated answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

import web_bff  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


# ── The chat UI page serves ───────────────────────────────────────────────────

def test_chat_page_serves_with_root_element():
    app = web_bff.bff_app()
    with TestClient(app) as client:
        resp = client.get("/chat")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    # The chat root elements are present (the conversation thread + the composer form).
    assert 'id="messages"' in body, "chat page missing the message-thread root element"
    assert 'class="composer"' in body, "chat page missing the composer"
    # And it declares the honest posture in-page (never fabricate).
    assert "never fabricate" in body.lower()


def test_chat_route_is_declared():
    assert "GET /chat" in web_bff.BFF_ROUTES, "the chat UI route must be declared on the tekton"


# ── POST /api/chat honest-degrades when lumen op.respond is dark ───────────────

def test_chat_endpoint_honest_degrades_when_dark():
    app = web_bff.bff_app()
    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"params": {"messages": [
            {"role": "user", "content": "What is Agience?"},
        ]}})
    # Honest-offline is a 200 state (not an error, not a fabricated 200 answer).
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("offline") is True, "dark op.respond must report offline"
    assert data.get("grounded") is False, "no live model ⇒ nothing grounded"
    # No pre-baked refusal sentence: a hand-authored "offline" message would be prose this stage
    # created rather than measured. The state is already fully reported by the fields, so the dark
    # path emits no words of its own.
    assert (data.get("text") or "") == "", "a dark carrier must emit no words it did not receive"
    assert not data.get("cited"), "nothing grounded it, so nothing may be cited"

    # Silence is not the same as an answer. A fabricated reply would answer the question; this must not.
    assert "agience is" not in (data.get("text") or "").lower()


def test_chat_carrier_is_dark_by_default():
    """The reach carrier is None on a plain boot (mirrors lumen.reach_provider /
    ember.router — both dark by default). This is what forces the honest-offline path."""
    mod = web_bff._load_bff_module()
    assert mod._respond_carrier() is None
    # healthz reports the honest carrier state (chat=False while dark).
    app = web_bff.bff_app()
    with TestClient(app) as client:
        assert client.get("/healthz").json().get("chat") is False
