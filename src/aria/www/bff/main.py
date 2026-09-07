"""Classic BFF for agience.ai — stand-in for the Agience artifact backend.

The website (src/utils/api.ts) calls these relative routes under /api, which the
shared Caddy proxies here while the full Agience stack (Origin/Mantle/Chorus)
isn't running:

  GET  /api/contact/nonce   GET /api/chat/nonce   -> bot-protection token (optional)
  POST /api/contact         -> lead capture (contact form + newsletter subscribe)
  POST /api/chat            -> chat assistant (reached via lumen's op.respond, when wired)
  GET  /api/blog            -> blog list   GET /api/blog/{id} -> single post

Leads are always persisted to a JSONL file (durable, never lost) and, if
configured, emailed and/or POSTed to a webhook (Slack/Discord/Zapier).
"""
from __future__ import annotations

import base64
import json
import os
import smtplib
import ssl
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from typing import Any, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

# ── Config (all via env; everything optional except where noted) ──────────────
DATA_DIR = Path(os.getenv("BFF_DATA_DIR", "/data"))
LEADS_FILE = DATA_DIR / "leads.jsonl"
BLOG_FILE = DATA_DIR / "blog.json"  # optional: drop an array of posts here

# Where lead notifications go / appear to come from.
LEAD_TO = os.getenv("LEAD_TO", "connect@agience.ai")
LEAD_FROM = os.getenv("LEAD_FROM", "webadmin@agience.ai")

# Gmail API sending (preferred — matches the platform's email sender). Reuses the
# GMAIL_OAUTH_* refresh-token creds from my-agience-ai/.env (gmail.send scope).
GMAIL_CLIENT_ID = os.getenv("GMAIL_OAUTH_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_OAUTH_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_OAUTH_REFRESH_TOKEN")

# SMTP sending (fallback — e.g. smtp.gmail.com:587 with a Google app password).
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

_GMAIL_READY = bool(GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN)
_SMTP_READY = bool(SMTP_HOST and SMTP_USER and SMTP_PASS)

# Optional generic webhook for instant notifications (Slack/Discord/Zapier).
LEAD_WEBHOOK_URL = os.getenv("LEAD_WEBHOOK_URL")

# Chat assistant = lumen's conversation tekton (op.respond), reached over the shared ground
# plane via ember.runtime.reach — not a model call in this process. Remote model APIs count as
# trained weights under the no-models rule ([[no-trained-weights]]), so this process holds no
# model client of its own. The reach needs a live carrier (a ground-plane fabric + the fleet
# root_secret + a grant store); wiring that is a separate, gated deploy step, so the carrier is
# dark by default. While dark, chat degrades to an "assistant offline" state rather than
# fabricate a reply. See _respond_carrier / _reach_respond below.
RESPOND_TO = os.getenv("RESPOND_CAP", "op.respond")
RESPOND_PRINCIPAL = os.getenv("RESPOND_PRINCIPAL", "aria")

app = FastAPI(title="agience.ai BFF")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # same-origin via Caddy in prod; permissive for local dev
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_lead(record: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LEADS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _build_email(record: dict) -> EmailMessage:
    content = record.get("content", {})
    context = record.get("context", {})
    msg = EmailMessage()
    who = content.get("name") or content.get("email") or "website visitor"
    msg["Subject"] = f"New lead: {who} ({context.get('source', 'website')})"
    msg["From"] = LEAD_FROM
    msg["To"] = LEAD_TO
    if content.get("email"):
        msg["Reply-To"] = content["email"]
    body = "\n".join(f"{k}: {v}" for k, v in content.items())
    msg.set_content(
        f"New submission from agience.ai\n\n{body}\n\n"
        f"source: {context.get('source')}\nreceived: {record['received_at']}\n"
    )
    return msg


def _send_via_gmail_api(msg: EmailMessage) -> None:
    # Exchange the refresh token for a short-lived access token, then send.
    token = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GMAIL_CLIENT_ID,
            "client_secret": GMAIL_CLIENT_SECRET,
            "refresh_token": GMAIL_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    token.raise_for_status()
    access = token.json()["access_token"]
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = httpx.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access}"},
        json={"raw": raw},
        timeout=15,
    )
    sent.raise_for_status()


def _send_via_smtp(msg: EmailMessage) -> None:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


def _email_lead(record: dict) -> None:
    if not (_GMAIL_READY or _SMTP_READY):
        return
    msg = _build_email(record)
    try:
        if _GMAIL_READY:
            _send_via_gmail_api(msg)
        else:
            _send_via_smtp(msg)
    except Exception as e:  # never let email failure lose the lead (it's stored)
        print(f"[bff] email send failed: {e}", flush=True)


def _webhook_lead(record: dict) -> None:
    if not LEAD_WEBHOOK_URL:
        return
    content = record.get("content", {})
    context = record.get("context", {})
    summary = ", ".join(f"{k}: {v}" for k, v in content.items())
    text = f"📥 New {context.get('source', 'website')} lead — {summary}"
    try:
        httpx.post(LEAD_WEBHOOK_URL, json={"text": text, "content": content,
                                           "context": context}, timeout=10)
    except Exception as e:
        print(f"[bff] webhook post failed: {e}", flush=True)


def _parse_maybe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


# ── Nonce (bot-protection token) ──────────────────────────────────────────────
# The SPA fetches these on load and replays the token as X-Agience-Challenge.
# This stand-in issues an opaque token without verifying it; the cross-origin
# guard in Caddy is what actually blocks unauthorized writes.
def _nonce():
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    return {"nonce": uuid.uuid4().hex, "expires_at": expires.isoformat()}


@app.get("/api/contact/nonce")
@app.get("/api/chat/nonce")
def nonce():
    return _nonce()


# ── Contact + subscribe ───────────────────────────────────────────────────────
@app.post("/api/contact")
async def contact(request: Request, bg: BackgroundTasks):
    payload = await request.json()
    record = {
        "id": uuid.uuid4().hex,
        "received_at": _now_iso(),
        "content": _parse_maybe_json(payload.get("content")),
        "context": _parse_maybe_json(payload.get("context")),
        "container_id": payload.get("container_id"),
    }
    _store_lead(record)  # durable first — never lose a lead
    bg.add_task(_email_lead, record)  # email + webhook after responding
    bg.add_task(_webhook_lead, record)
    return JSONResponse({"ok": True, "id": record["id"]}, status_code=201)


# ── Chat = reach lumen op.respond (honest-degrade when dark) ───────────────────
# Injection seam for a live carrier: a dict, or a zero-arg callable returning one. Either
# {respond: (query)->evidence}  (store-and-forward; the host owns the serve-loop) OR
# {store, root_secret, fabric[, principal]}  (live streaming). None means dark, and chat
# answers with the honest-offline state below. A wired host sets `main._RESPOND_CARRIER`
# at runtime; nothing here fabricates one.
_RESPOND_CARRIER: Any = None

# This layer emits exactly what the pipeline produced, with no invented text: a dark carrier
# returns this empty string rather than a hand-authored apology, and a refusal (below) carries
# no invented reason either. The fields already carry the measurement (`offline`, `grounded`,
# `cited`); a presentation surface can render the absence however it likes, but this layer
# supplies no words the pipeline did not produce.
_OFFLINE_TEXT = ""

def _respond_carrier() -> Optional[dict]:
    """The live carrier for reaching lumen's op.respond, or None when dark.

    A live carrier is {store, root_secret, fabric[, principal]} — the ground-plane
    fabric + fleet key + grant store that let a need addressed to op.respond be placed
    and its evidence picked up. Wiring it is a separate, gated deploy step (mirrors
    lumen.reach_provider.serve_respond_if_configured and ember.router.route, both dark
    by default). Until then this returns None and chat honest-degrades rather than
    fabricate. Any missing piece or error resolves to None so the endpoint stays honest."""
    c = _RESPOND_CARRIER
    try:
        c = c() if callable(c) else c
    except Exception:
        return None
    if not c:
        return None
    # Two live shapes. Store-and-forward: a host-provided synchronous `respond(query)->evidence` — the
    # host owns the ember requester + lumen provider + StoreCarrier + serve-loop and exposes a
    # `beam.pump.resolve`-backed responder (the bff stays pure presentation, knows no reactors). Live
    # streaming: the fabric triple {store, root_secret, fabric}, reached one-shot via ember.runtime.reach.
    if callable(c.get("respond")):
        return c
    if c.get("fabric") is not None and c.get("root_secret") is not None and c.get("store") is not None:
        return c
    return None


def _reach_respond(query: str, carrier: dict) -> Optional[dict]:
    """Reach lumen's op.respond and return the evidence (the op.respond shape: {answer, cited, grounded,
    ...}), or None if nothing resolves (inactive carrier / honest silence). Two paths: the host's
    synchronous `respond(query)` (store-and-forward, driven by the host's serve-loop via
    `beam.pump.resolve`), or a one-shot reach through the fabric (`reach_wiring` — beam's Reactor over
    the mantle-backed plane, no ember)."""
    respond = carrier.get("respond")
    if callable(respond):
        return respond(query)                     # host's resolve-backed responder; op.respond shape or None
    from reach_wiring import reach as _reach          # imported lazily: only needed for the live-fabric one-shot path
    return _reach(carrier["store"], carrier.get("principal", RESPOND_PRINCIPAL),
                  {"query": query, "text": query},
                  to=RESPOND_TO, root_secret=carrier["root_secret"], fabric=carrier["fabric"])


@app.post("/api/chat")
async def chat(request: Request):
    payload = await request.json()
    messages = (payload.get("params") or {}).get("messages") or []
    # The need is the latest user turn (full history is kept client-side for display).
    query = ""
    for m in reversed(messages):
        if m.get("role", "user") == "user" and (m.get("content") or "").strip():
            query = m["content"].strip()
            break
    if not query and messages:
        query = (messages[-1].get("content") or "").strip()

    carrier = _respond_carrier()
    if carrier is None:
        # Dark: no live carrier connected. Degrade honestly rather than fabricate a reply.
        return JSONResponse({"offline": True, "grounded": False, "cited": [],
                             "text": _OFFLINE_TEXT}, status_code=200)
    try:
        evidence = _reach_respond(query, carrier)
    except Exception as e:
        print(f"[bff] op.respond reach error: {e}", flush=True)
        evidence = None
    # ── The honesty gate ──────────────────────────────────────────────────────────────────────
    # The gate asks only whether there is answer text. `conversation.respond` expresses a need
    # that fired nothing as `answer: ""` with `activations: []` and `cited: []`; checking `is None`
    # alone would miss that and publish the empty string as a reply. Checking for text handles
    # every falsy shape the tekton might return the same way.
    answer = (evidence or {}).get("answer")
    if not evidence or answer is None or not str(answer).strip():
        # A live carrier with no evidence is a refusal; only a dark carrier is an outage, and that
        # case already returned above, so reaching here always means the tekton answered with
        # nothing. `refused` is derived from the absence of answer text; no narrative reason is
        # attached, since the underlying cause (e.g. a malformed or empty query) isn't measured here.
        return JSONResponse({"offline": False, "grounded": False, "refused": True,
                             "cited": [], "text": ""}, status_code=200)

    # Groundedness is measured from the evidence: an answer is grounded iff it cites something.
    # An explicit `grounded` key from the tekton wins over that default, because that is the
    # tekton reporting its own measurement; `conversation.respond` does not currently emit the key,
    # so this default carries most real answers.
    cited = evidence.get("cited") or []
    grounded = bool(evidence["grounded"]) if "grounded" in evidence else bool(cited)
    return {"text": answer, "offline": False, "grounded": grounded, "cited": cited}


# ── Chat UI (the aria facet page) ─────────────────────────────────────────────
_CHAT_HTML = Path(__file__).resolve().parent / "chat.html"


@app.get("/chat")
def chat_ui():
    """Serve the polished single-page chat UI — the presentation surface for lumen
    conversations, wired to POST /api/chat above (honest-offline until the carrier lands)."""
    return HTMLResponse(_CHAT_HTML.read_text(encoding="utf-8"))


# ── Blog (optional; serves /data/blog.json if present, else empty) ─────────────
@app.get("/api/blog")
def blog_list():
    if BLOG_FILE.exists():
        try:
            return json.loads(BLOG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[bff] blog read error: {e}", flush=True)
    return []


@app.get("/api/blog/{post_id}")
def blog_post(post_id: str):
    if BLOG_FILE.exists():
        try:
            posts = json.loads(BLOG_FILE.read_text(encoding="utf-8"))
            for p in posts if isinstance(posts, list) else []:
                if str(p.get("id")) == post_id:
                    return p
        except Exception as e:
            print(f"[bff] blog read error: {e}", flush=True)
    return {}


@app.get("/healthz")
def healthz():
    # `chat` reports whether a live op.respond carrier is wired: false while dark, which is
    # when the UI shows "assistant offline". It is true only when a real carrier is present.
    return {"ok": True, "ts": time.time(), "chat": bool(_respond_carrier()),
            "email": "gmail" if _GMAIL_READY else ("smtp" if _SMTP_READY else False),
            "lead_to": LEAD_TO, "lead_from": LEAD_FROM}
