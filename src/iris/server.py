"""
agience-server-iris — MCP Server
====================================
Iris (networking — mesh, transport, comms): messaging, webhooks, connectivity.
A tekton — the networking condensor in the chorus (the tekton standard library); its tools are organons, invoked by condensation (OPERATOR-ARCHITECTURE §12).

Iris is the networking persona of chorus (operators, by domain). It connects
agents, services, and external systems by managing routing, transport, and
messaging — the communication layer that ensures reliable connectivity between
platform components and the outside world.

Iris does not execute code. It runs in the container holding chorus.private.pem
(the key every persona signs with), so nothing here may run caller-supplied
commands — see the "No shell/subprocess execution" note below and tests/.

Pipeline position: Networking & infrastructure.

Tools
-----
  send_email        — Send an email via the platform's Authorizer (Gmail API)
  send_message      — Send a message via a registered channel adapter
  get_messages      — Poll a channel for new messages since a cursor
  list_channels     — List registered channel adapters
  health_check      — Check health/availability of a service endpoint
  list_connections  — List registered service connections
  register_endpoint — Register a service endpoint for routing
  route_request     — Route a request to a registered endpoint
  proxy_tool        — Proxy an MCP tool call through a registered endpoint
  fetch_url         — Fetch content from a URL and return it inline
  ask_human         — Ask a question to the human operator (async-capable)

Auth
----
  Service identity loaded once by the chorus host (chorus.private.pem).
  Persona signs its own platform JWTs via _auth.sign_self_jwt() — no token
  exchange with Origin, no PLATFORM_INTERNAL_SECRET.

  MANTLE_URI                ⬩ Base URI of the Mantle backend
  IRIS_AUTHORIZER_ARTIFACT_ID   ⬩ Artifact ID of the email Authorizer transform
  IRIS_AUTHORIZER_WORKSPACE_ID  ⬩ Workspace ID where the Authorizer artifact lives

Transport
---------
  MCP_TRANSPORT=streamable-http
  MCP_HOST=0.0.0.0
  MCP_PORT=8086
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import pathlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

log = logging.getLogger("agience-server-iris")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s - %(name)s - %(message)s")

# Backend (Mantle) base URI. MANTLE_URI is the canonical param name.
MANTLE_URI: str = os.getenv("MANTLE_URI", "http://localhost:8081").rstrip("/")
IRIS_CLIENT_ID: str = "agience-server-iris"
IRIS_AUTHORIZER_ARTIFACT_ID: str = os.getenv("IRIS_AUTHORIZER_ARTIFACT_ID", "")
IRIS_AUTHORIZER_WORKSPACE_ID: str = os.getenv("IRIS_AUTHORIZER_WORKSPACE_ID", "")

# Gmail API endpoints (OAuth2 refresh-token exchange + send), used by send_email.
_GMAIL_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
_GMAIL_SEND_URL: str = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8086"))


# ---------------------------------------------------------------------------
# Shared authentication infrastructure (AgienceServerAuth)
# ---------------------------------------------------------------------------

from prism.trust import (
    ServerAuth as _AgienceServerAuth,
    MissingDelegationError,
)

_auth = _AgienceServerAuth(IRIS_CLIENT_ID, MANTLE_URI)


# This module has exactly one header-resolution path: `_require_user_headers`. There is no function
# that resolves the persona's own platform JWT and no fallback to one.
#
# All chorus personas share one `chorus.private.pem`. Every mantle call in this module carries a
# caller-supplied `workspace_id`/`artifact_id`/`source_artifact_id`, so a platform-JWT fallback would
# apply platform authority to a caller-chosen resource. Iris has no principal-less path: even the
# platform-email sends run as the operator, whose delegation is what holds `read` on the bound secret
# artifacts. If a principal-less path is ever needed, add an explicit `_platform_request` for it —
# never a parameter on this fail-closed path.


def _require_user_headers() -> dict[str, str]:
    """Headers carrying the caller's verified delegation JWT. Fails closed.

    The only header helper in this module. Raises `MissingDelegationError`
    (`prism/trust/server_auth.py::MissingDelegationError`) rather than falling back to a platform JWT.
    """
    return _auth.require_user_headers()


def create_iris_app():
    """Return the Iris MCP ASGI app with verified middleware and startup hooks."""
    return _auth.create_app(mcp)


mcp = FastMCP(
    "agience-server-iris",
    instructions=(
        "You are Iris, the Agience routing and communication, transport, and routing server. "
        "Use Iris to send messages through channel adapters, manage webhooks, "
        "route requests between services, and manage secure tunnels between "
        "hosts and the platform. Iris does not execute shell commands."
    ),
)

from mantle.clients.artifact_helpers import artifact_url, register_types_manifest
register_types_manifest(mcp, "iris", __file__)


# ---------------------------------------------------------------------------
# Tool: send_email
# ---------------------------------------------------------------------------

async def _fetch_secret_material(client: httpx.AsyncClient, secret_artifact_id: str) -> str:
    """Resolve a credential artifact's value with a plain artifact READ.

    Grant-checked by Mantle against the caller's delegation: this only succeeds when the send runs
    under an identity that holds `read` on the artifact (e.g. the platform operator). The credential
    never returns to the original caller — only into this (trusted) persona process for the exchange
    below.

    Changed 2026-08-25 under John's ruling that chorus adopts Mantle's position — an authorized
    reader fetches plaintext over TLS, and a credential is an ordinary artifact with its value in
    `content`. This previously POSTed `/artifacts/{id}/op/fetch`, which could not work for two
    independent reasons: the op surface **relocated from Mantle to Crystal**, so `MANTLE_URI` served
    no such route; and that operation dispatched to `secrets_service.fetch_secret_material`, deleted
    with Mantle's `/secrets` surface. `fetch` is what `read` already does.
    """
    resp = await client.get(
        artifact_url(MANTLE_URI, secret_artifact_id),
        headers=_require_user_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    content = (resp.json() or {}).get("content")
    #: Two shapes are in flight. Artifacts minted under the old two-store model wrap the value as
    #: `{"material": ...}`; the credential type carries it directly. Read either, prefer neither.
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return content
        content = parsed
    if isinstance(content, dict):
        return content.get("material") or content.get("value") or ""
    return content or ""


async def _gmail_access_token(client: httpx.AsyncClient, config: dict) -> str:
    """Exchange an OAuth2 refresh token for a fresh access token (Gmail).

    Reads client_id + token_endpoint + scopes from the authorizer config and
    resolves client_secret + refresh_token from their bound secret artifacts.
    No `provide_access_token` op; the exchange happens here, server-side.
    """
    client_secret = await _fetch_secret_material(client, config["client_secret_artifact_id"])
    refresh_token = await _fetch_secret_material(client, config["refresh_token_artifact_id"])
    resp = await client.post(
        config.get("token_endpoint", _GMAIL_TOKEN_URL),
        data={
            "grant_type": "refresh_token",
            "client_id": config["client_id"],
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "scope": config.get("scopes", ""),
        },
        timeout=15,
    )
    resp.raise_for_status()
    token = (resp.json() or {}).get("access_token")
    if not token:
        raise RuntimeError("Token endpoint returned no access_token")
    return token


@mcp.tool(
    description=(
        "Send an email via an Authorizer artifact (Gmail API). Resolves the "
        "authorizer's OAuth config + bound secret artifacts and performs the "
        "refresh-token exchange entirely server-side, then sends via Gmail. The "
        "authorizer is identified per-call via authorizer_artifact_id (an operator "
        "attaches it by edge) and falls back to IRIS_AUTHORIZER_ARTIFACT_ID. No "
        "token is ever returned to the caller."
    )
)
async def send_email(
    to: str,
    subject: str,
    body_html: str,
    authorizer_artifact_id: str = "",
    workspace_id: str = "",
) -> str:
    """Send an email using an Authorizer artifact's OAuth credentials.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body_html: HTML body of the email.
        authorizer_artifact_id: Authorizer artifact whose config + bound secrets
            mint the access token. Falls back to IRIS_AUTHORIZER_ARTIFACT_ID.
        workspace_id: Optional workspace context (unused for collection-scoped
            authorizers; reserved).
    """
    del workspace_id  # reserved; authorizer is resolved by id, not workspace
    authorizer_id = (authorizer_artifact_id or IRIS_AUTHORIZER_ARTIFACT_ID).strip()
    if not authorizer_id:
        return json.dumps({
            "error": "No authorizer configured: pass authorizer_artifact_id or set IRIS_AUTHORIZER_ARTIFACT_ID"
        })

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Read the authorizer config (content holds the OAuth profile +
            #    references to its client-secret / refresh-token secret artifacts).
            resp = await client.get(
                artifact_url(MANTLE_URI, authorizer_id),
                headers=_require_user_headers(),
            )
            resp.raise_for_status()
            authorizer = resp.json()
            raw_content = authorizer.get("content") or "{}"
            config = json.loads(raw_content) if isinstance(raw_content, str) else raw_content

            missing = [k for k in ("client_id", "client_secret_artifact_id", "refresh_token_artifact_id")
                       if not config.get(k)]
            if missing:
                return json.dumps({"error": f"Authorizer config missing fields: {missing}"})

            # 2. Resolve credentials + mint an access token (server-side). Runs
            #    under the caller's delegation — for platform sends that's the
            #    operator, who holds read on the bound secrets.
            access_token = await _gmail_access_token(client, config)
            sender_address = config.get("sender_address", "")

            # 3. Build the MIME message and send via Gmail.
            msg = MIMEMultipart("alternative")
            msg["To"] = to
            msg["From"] = sender_address or "me"
            msg["Subject"] = subject
            msg.attach(MIMEText(body_html, "html"))
            raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

            gmail_resp = await client.post(
                _GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={"raw": raw_message},
            )
            gmail_resp.raise_for_status()
            message_id = (gmail_resp.json() or {}).get("id")
    except httpx.HTTPStatusError as exc:
        return json.dumps({"error": f"send_email failed: {exc.response.status_code} {exc.response.text[:300]}"})
    # MissingDelegationError is a PermissionError, so it is not caught by the tuple below — named
    # explicitly so the fail-closed refusal comes back in the same parseable shape as every other failure
    # here rather than as an unhandled exception.
    except MissingDelegationError as exc:
        return json.dumps({"error": f"send_email refused: {exc}"})
    except (KeyError, RuntimeError, json.JSONDecodeError) as exc:
        return json.dumps({"error": f"send_email failed: {exc}"})

    return json.dumps({"status": "sent", "message_id": message_id, "to": to})


# ---------------------------------------------------------------------------
# Tool: notify_inbound
# ---------------------------------------------------------------------------

def _inbound_subject(content: dict, source: str, artifact_id: str) -> str:
    """Lead-aware subject line: prefer the submitter's email/name + source."""
    who = ""
    if isinstance(content, dict):
        who = (content.get("email") or content.get("name") or "").strip()
    label = {
        "website-contact": "Contact form",
        "website-subscribe": "Newsletter signup",
        "website-chat": "Chat lead",
    }.get(source, source or "Inbound")
    if who:
        return f"[Agience] {label}: {who}"
    return f"[Agience] {label} ({artifact_id[:8]})"


@mcp.tool(
    description=(
        "Notify the operator about an inbound lead/artifact (contact form, "
        "newsletter subscribe, webhook, etc.). Fetches the artifact from Mantle, "
        "formats its content as an HTML email, and sends it via the platform email "
        "sender. notify_to falls back to IRIS_NOTIFY_EMAIL; the authorizer falls "
        "back to IRIS_AUTHORIZER_ARTIFACT_ID."
    )
)
async def notify_inbound(
    artifact_id: str,
    workspace_id: str,
    notify_to: str = "",
    authorizer_artifact_id: str = "",
) -> str:
    """Operator notification for any inbound artifact.

    Args:
        artifact_id: ID of the artifact to read and summarize.
        workspace_id: Workspace that owns the artifact.
        notify_to: Recipient email address. Falls back to IRIS_NOTIFY_EMAIL.
        authorizer_artifact_id: Email authorizer to send through. Falls back to
            IRIS_AUTHORIZER_ARTIFACT_ID (the platform email authorizer).
    """
    recipient = notify_to.strip() or os.getenv("IRIS_NOTIFY_EMAIL", "").strip()
    if not recipient:
        return json.dumps({"error": "notify_to not specified and IRIS_NOTIFY_EMAIL not set"})

    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": f"notify_inbound refused: {exc}"})

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, artifact_id),
            headers=headers,
        )

    if resp.status_code != 200:
        return json.dumps({"error": f"Artifact fetch failed: {resp.status_code} {resp.text[:200]}"})

    artifact = resp.json()
    content_str = artifact.get("content", "")
    context_str = artifact.get("context", "{}")

    try:
        content = json.loads(content_str) if content_str else {}
    except (json.JSONDecodeError, TypeError):
        content = {"raw": content_str[:500]}

    try:
        ctx = json.loads(context_str) if context_str else {}
    except (json.JSONDecodeError, TypeError):
        ctx = {}

    source = ctx.get("source", "unknown")
    subject = _inbound_subject(content, source, artifact_id)

    rows = "".join(
        f"<tr><td style='padding:4px 8px;font-weight:bold;'>{k}</td>"
        f"<td style='padding:4px 8px;'>{v}</td></tr>"
        for k, v in (content.items() if isinstance(content, dict) else [("content", str(content))])
    )
    body_html = (
        "<html><body style='font-family:sans-serif;'>"
        f"<h2 style='color:#333;'>Inbound: {source}</h2>"
        "<table border='1' cellpadding='0' cellspacing='0' style='border-collapse:collapse;'>"
        f"{rows}"
        "</table>"
        f"<p style='color:#888;font-size:12px;margin-top:16px;'>"
        f"artifact_id: {artifact_id} | workspace: {workspace_id}"
        "</p></body></html>"
    )

    return await send_email(
        to=recipient,
        subject=subject,
        body_html=body_html,
        authorizer_artifact_id=authorizer_artifact_id,
    )


# ---------------------------------------------------------------------------
# Tool: send_templated_email  (transactional: autoresponder / welcome / receipt)
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    """format_map source that renders missing fields as empty strings."""

    def __missing__(self, key):  # noqa: D401
        return ""


def _as_dict(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _resolve_field(spec: str, content: dict, context: dict):
    """Resolve a value spec: ``$.content.x`` / ``$.context.x`` walk the dicts,
    ``$.x`` tries content then context, anything else is a literal."""
    if not isinstance(spec, str) or not spec.startswith("$."):
        return spec
    path = spec[2:]
    if path.startswith("content."):
        return content.get(path[len("content."):], "")
    if path.startswith("context."):
        return context.get(path[len("context."):], "")
    return content.get(path) or context.get(path) or ""


def _render_template(template: str, content: dict, context: dict) -> str:
    """Best-effort ``{field}`` substitution from content+context (content wins)."""
    if not isinstance(template, str):
        return ""
    try:
        return template.format_map(_SafeDict({**context, **content}))
    except (ValueError, IndexError):
        return template


@mcp.tool(
    description=(
        "Send a templated transactional email driven by a triggering artifact "
        "(autoresponder, welcome, receipt, usage warning, etc.). Resolves the "
        "recipient (a literal address or a $.content/$.context path on the "
        "artifact) and renders {field} placeholders in subject/body from the "
        "artifact, then sends via the platform email sender. No token is exposed."
    )
)
async def send_templated_email(
    artifact_id: str,
    workspace_id: str,
    recipient: str,
    subject: str,
    body_html: str,
    authorizer_artifact_id: str = "",
) -> str:
    """Send a transactional email derived from a triggering artifact.

    Args:
        artifact_id: The artifact that triggered this email (e.g. the lead).
        workspace_id: Owning workspace/collection.
        recipient: Target address — a literal, or "$.content.email" /
            "$.context.email" to pull from the artifact.
        subject: Subject line; supports {field} placeholders from the artifact.
        body_html: HTML body; supports {field} placeholders from the artifact.
        authorizer_artifact_id: Email authorizer; falls back to
            IRIS_AUTHORIZER_ARTIFACT_ID.
    """
    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": f"send_templated_email refused: {exc}"})

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, artifact_id),
            headers=headers,
        )
    if resp.status_code != 200:
        return json.dumps({"error": f"Artifact fetch failed: {resp.status_code} {resp.text[:200]}"})

    artifact = resp.json()
    content = _as_dict(artifact.get("content"))
    context = _as_dict(artifact.get("context"))

    to = _resolve_field(recipient, content, context)
    if not to or "@" not in str(to):
        return json.dumps({"error": f"No valid recipient resolved from {recipient!r}"})

    return await send_email(
        to=str(to),
        subject=_render_template(subject, content, context),
        body_html=_render_template(body_html, content, context),
        authorizer_artifact_id=authorizer_artifact_id,
    )


# ---------------------------------------------------------------------------
# Tool: send_message
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Send a message via a registered channel adapter (Telegram, Slack, email). "
        "The message is routed through the platform's channel infrastructure."
    )
)
async def send_message(
    channel: str,
    text: str,
    recipient: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        channel: Channel adapter name (e.g. 'telegram', 'slack', 'email').
        text: Message body text.
        recipient: Target recipient (chat ID, channel name, email address).
        workspace_id: Optional workspace context.
    """
    # Errors are returned as {"error": ...} JSON, matching the success shape, so callers can always
    # json.loads the result.
    if not workspace_id:
        return json.dumps({"error": "workspace_id is required for the MVP Iris send_message flow."})

    payload = {
        "context": {
            "type": "message",
            "direction": "outbound",
            "channel": channel,
            "recipient": recipient,
            "iris": {"delivery": "recorded-only"},
        },
        "content": text,
    }

    # A workspace is an ordinary container artifact, so membership is expressed via `container_id`.
    # Setting it here is not optional: without it the artifact is created top-level, outside the
    # workspace the caller named.
    payload["container_id"] = workspace_id
    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": str(exc)})
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{MANTLE_URI}/artifacts",
            headers=headers,
            json=payload,
            timeout=30,
        )
    if resp.status_code >= 400:
        return json.dumps({"error": f"{resp.status_code} — {resp.text[:300]}"})
    return json.dumps(resp.json(), indent=2)


# ---------------------------------------------------------------------------
# Tool: get_messages
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Poll a channel adapter for new messages since a given cursor. "
        "Returns message list sorted by time."
    )
)
async def get_messages(
    channel: str,
    cursor: Optional[str] = None,
    limit: int = 20,
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        channel: Channel adapter name (e.g. 'telegram', 'slack').
        cursor: Opaque cursor from a previous call (omit for latest).
        limit: Max messages to return.
    """
    # Errors are returned as {"error": ...} JSON; this tool's success is a JSON array, so callers can
    # always json.loads the result.
    if not workspace_id:
        return json.dumps({"error": "workspace_id is required for the MVP Iris get_messages flow."})

    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": str(exc)})

    # A workspace is a container artifact, so "its artifacts" are its children. `workspace_id` is also
    # passed as the query param on purpose: that is what makes draft children visible, and a draft is
    # workspace-private, so omitting it silently hides uncommitted rows.
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, workspace_id, "children"),
            headers=headers,
            params={"workspace_id": workspace_id},
            timeout=30,
        )
    if resp.status_code >= 400:
        return json.dumps({"error": f"{resp.status_code} — {resp.text[:300]}"})

    cards = resp.json() or []
    filtered = []
    for card in cards:
        raw_context = card.get("context") or {}
        if isinstance(raw_context, str):
            try:
                raw_context = json.loads(raw_context)
            except Exception:
                raw_context = {}

        card_channel = raw_context.get("channel") or raw_context.get("inbound", {}).get("channel")
        if card_channel != channel:
            continue
        if raw_context.get("type") != "message" and "inbound" not in raw_context:
            continue
        filtered.append(card)

    if cursor:
        filtered = [card for card in filtered if str(card.get("id")) > cursor]

    return json.dumps(filtered[:limit], indent=2)


# ---------------------------------------------------------------------------
# Tool: list_channels
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "List registered channel adapters for the current user. "
        "Returns available channels and their connection status."
    )
)
async def list_channels() -> str:
    channels = [
        {
            "name": "webhook",
            "direction": "inbound",
            "status": "ready",
            "delivery": "card-scoped inbound webhook",
        },
        {
            "name": "workspace-card",
            "direction": "outbound",
            "status": "ready",
            "delivery": "records outbound messages as workspace cards",
        },
    ]
    return json.dumps(channels, indent=2)


# ---------------------------------------------------------------------------
# create_webhook does not exist; no route in this server mints inbound keys.
#
# Inbound-key enforcement itself is live in mantle: `check_inbound_nonce`
# (`mantle/services/dependencies.py`) gates artifact creation for keys flagged
# `requires_nonce`, wired into `POST /artifacts` (`mantle/routers/artifacts_router.py`) — this is how
# the website's lead/subscribe forms post today. There is no mantle route that mints an inbound key
# for a card (no `/artifacts/{id}/inbound-key`), so a tool here cannot hand one out until mantle-side
# minting exists.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tool: health_check
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Check the health and availability of a service endpoint. "
        "Returns status, latency, and any error details."
    )
)
async def health_check(
    url: str,
    timeout: int = 10,
) -> str:
    """
    Args:
        url: URL of the service endpoint to check.
        timeout: Max seconds to wait for response.
    """
    raise NotImplementedError(f"health_check is a declared placeholder. url={url}")


# ---------------------------------------------------------------------------
# Tool: list_connections
# ---------------------------------------------------------------------------

@mcp.tool(
    description="List registered service connections and their current status."
)
async def list_connections() -> str:
    raise NotImplementedError("list_connections is a declared placeholder.")


# ---------------------------------------------------------------------------
# Tool: register_endpoint
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Register a service endpoint for routing. "
        "Registered endpoints can be targeted by route_request and proxy_tool."
    )
)
async def register_endpoint(
    name: str,
    url: str,
    protocol: str = "http",
) -> str:
    """
    Args:
        name: Logical name for the endpoint.
        url: Base URL of the service.
        protocol: Protocol type — 'http', 'grpc', 'websocket'.
    """
    raise NotImplementedError(f"register_endpoint is a declared placeholder. name={name}, url={url}")


# ---------------------------------------------------------------------------
# Tool: route_request
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Route an HTTP request to a registered endpoint. "
        "Acts as a platform-aware proxy with auth injection."
    )
)
async def route_request(
    endpoint: str,
    method: str = "GET",
    path: str = "/",
    body: Optional[str] = None,
) -> str:
    """
    Args:
        endpoint: Name of a registered endpoint.
        method: HTTP method — GET, POST, PUT, DELETE.
        path: Request path appended to the endpoint base URL.
        body: Optional request body (JSON string).
    """
    raise NotImplementedError(f"route_request is a declared placeholder. endpoint={endpoint}, path={path}")


# ---------------------------------------------------------------------------
# No shell/subprocess execution
# ---------------------------------------------------------------------------
#
# Iris runs in the container holding `chorus.private.pem`, the RS256 key every persona signs with.
# Do not add a tool that executes caller-supplied commands here: any caller reaching Iris, or any
# prompt injection into an agent wired to Iris, could read that key and forge service JWTs to Mantle
# and Origin. Command/build execution belongs in a separate workload that does not hold the signing
# key, behind an explicit operator entitlement, with argv (no shell), a confined cwd, and resource
# limits.


# ---------------------------------------------------------------------------
# Tool: proxy_tool
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Proxy an MCP tool call through a registered endpoint. "
        "Forwards the tool invocation to a remote MCP server and returns the result."
    )
)
async def proxy_tool(
    endpoint: str,
    tool_name: str,
    arguments: Optional[str] = None,
) -> str:
    """
    Args:
        endpoint: Name of a registered endpoint.
        tool_name: Name of the MCP tool to invoke on the remote server.
        arguments: JSON string of tool arguments.
    """
    raise NotImplementedError(f"proxy_tool is a declared placeholder. endpoint={endpoint}, tool={tool_name}")


# ---------------------------------------------------------------------------
# Tool: fetch_url
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Fetch content from a URL and return it inline. "
        "Useful for reading web pages, API responses, or any HTTP-accessible resource. "
        "Does NOT create an artifact — use create_artifact separately to persist."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
)
async def fetch_url(
    url: str,
    query: Optional[str] = None,
    format: Optional[str] = "text",
    timeout: int = 30,
    max_length: int = 100000,
) -> str:
    """
    Args:
        url: The URL to fetch.
        query: Optional — extract only content relevant to this query (requires LLM).
        format: Response format — 'text' (default), 'markdown', or 'html'.
        timeout: Max seconds to wait for response.
        max_length: Max characters to return (default 100k, truncates with notice).
    """
    import re

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Agience/1.0 (Iris)"})
    except httpx.TimeoutException:
        return json.dumps({"error": f"Request timed out after {timeout}s", "url": url})
    except httpx.RequestError as exc:
        return json.dumps({"error": f"Request failed: {exc}", "url": url})

    if resp.status_code >= 400:
        return json.dumps({"error": f"HTTP {resp.status_code}", "url": url, "body": resp.text[:500]})

    content_type = resp.headers.get("content-type", "")
    raw_text = resp.text

    # Strip HTML tags for text/markdown output
    if format in ("text", "markdown") and "html" in content_type:
        # Basic tag stripping — good enough for inline reading
        raw_text = re.sub(r"<script[^>]*>.*?</script>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
        raw_text = re.sub(r"<style[^>]*>.*?</style>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
        raw_text = re.sub(r"<[^>]+>", " ", raw_text)
        raw_text = re.sub(r"\s+", " ", raw_text).strip()
    elif format == "html":
        pass  # Return raw HTML

    # Truncate if needed
    truncated = False
    if len(raw_text) > max_length:
        raw_text = raw_text[:max_length]
        truncated = True

    result: dict = {
        "url": url,
        "status": resp.status_code,
        "content_type": content_type,
        "length": len(raw_text),
        "content": raw_text,
    }
    if truncated:
        result["truncated"] = True
        result["notice"] = f"Content truncated to {max_length} characters."

    # The "extract" agent has no server mapping, so query-driven extraction via
    # fetch_url is not implemented — callers should use Lumen's invoke_llm
    # directly with a properly configured connection artifact.
    if query and raw_text:
        log.info("fetch_url: query parameter ignored (extract agent not available)")

    return json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: ask_human
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Ask a question to the human operator. Creates a pending question artifact "
        "in the workspace and attempts delivery through available channels: "
        "browser relay (if connected), configured notification channel, or "
        "async artifact (human answers when they return). "
        "Use urgency='blocking' to wait for a response, 'deferred' to continue working."
    ),
)
async def ask_human(
    workspace_id: str,
    question: str,
    options: Optional[list[str]] = None,
    urgency: str = "deferred",
    timeout_seconds: int = 120,
) -> str:
    """
    Args:
        workspace_id: Workspace where the question artifact will be created.
        question: The question text to present to the human.
        options: Optional list of structured answer choices.
        urgency: 'blocking' to wait for an answer, 'deferred' to return immediately.
        timeout_seconds: Max seconds to wait when urgency is 'blocking'.
    """
    # 1. Create a pending-question artifact in the workspace
    question_context = {
        "type": "pending_question",
        "question": question,
        "status": "pending",
    }
    if options:
        question_context["options"] = options

    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": f"ask_human refused: {exc}"})
    async with httpx.AsyncClient(timeout=30) as client:
        create_resp = await client.post(
            f"{MANTLE_URI}/artifacts",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "content": question,
                "context": json.dumps(question_context),
            },
        )

    if create_resp.status_code >= 400:
        return json.dumps({"error": f"Failed to create question artifact: {create_resp.status_code}"})

    artifact = create_resp.json().get("artifact", create_resp.json())
    artifact_id = artifact.get("id")

    # 2. Check relay presence — is the human connected via browser?
    relay_connected = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            relay_resp = await client.get(
                f"{MANTLE_URI}/mcp",
                headers=headers,
                params={"tool": "relay_status"},
            )
            if relay_resp.status_code == 200:
                relay_data = relay_resp.json()
                relay_connected = relay_data.get("connected", False)
    except Exception:
        pass  # Relay check is best-effort

    # 3. Deliver the question
    delivery_method = "artifact_only"

    if relay_connected:
        # Human is online — the artifact creation event will notify them via
        # the WebSocket event stream. The question card appears in their workspace.
        delivery_method = "relay_event"

    # 4. For blocking mode, poll for an answer
    if urgency == "blocking" and relay_connected:
        import time
        deadline = time.time() + timeout_seconds
        poll_interval = 3  # seconds

        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    check_resp = await client.get(
                        artifact_url(MANTLE_URI, workspace_id, "artifacts", artifact_id),
                        headers=headers,
                    )
                if check_resp.status_code == 200:
                    updated = check_resp.json()
                    ctx = updated.get("context", {})
                    if isinstance(ctx, str):
                        ctx = json.loads(ctx)
                    if ctx.get("status") == "answered":
                        return json.dumps({
                            "status": "answered",
                            "answer": ctx.get("answer"),
                            "artifact_id": artifact_id,
                            "delivery_method": delivery_method,
                        })
            except Exception:
                pass

        return json.dumps({
            "status": "timeout",
            "artifact_id": artifact_id,
            "delivery_method": delivery_method,
            "message": f"No answer received within {timeout_seconds}s. Question remains pending.",
        })

    return json.dumps({
        "status": "pending",
        "artifact_id": artifact_id,
        "delivery_method": delivery_method,
        "message": "Question created. Human will see it when they access the workspace.",
    })


# ---------------------------------------------------------------------------
# UI Resources
# ---------------------------------------------------------------------------

@mcp.resource("ui://iris/vnd.agience.host.html")
async def host_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.host+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.host+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://iris/vnd.agience.mcp-client.html")
async def mcp_client_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.mcp-client+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.mcp-client+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://iris/vnd.agience.mcp-server.html")
async def mcp_server_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.mcp-server+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.mcp-server+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Standard server interface (used by _host and standalone)
# ---------------------------------------------------------------------------

def create_server_app():
    """Return the Iris ASGI app with verified middleware and startup hooks."""
    return create_iris_app()


async def server_startup() -> None:
    """Run Iris startup tasks. The trust map is on disk; nothing to fetch."""
    await _auth.startup()


# ---------------------------------------------------------------------------
# Self-registration: this persona owns its registration.
# The host holds no roster — it calls each persona's register(). `PERSONA` is the
# single source of truth for {name, role, endpoint}; register() self-registers
# with Mantle (server record) + the crystal gateway (owned types).
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "iris",
    "kind": "tekton",
    "role": "Routing & Communication",
    "endpoint": "/iris/mcp",
    "client_id": IRIS_CLIENT_ID,
}


def register(register_fn) -> bool:
    """Self-register this persona (server + owned types). True on success."""
    return register_fn(
        name=PERSONA["name"],
        role=PERSONA["role"],
        endpoint=PERSONA["endpoint"],
        client_id=PERSONA["client_id"],
        server_file=__file__,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting agience-server-iris — transport=%s port=%s", MCP_TRANSPORT, MCP_PORT)
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn
        uvicorn.run(create_server_app(), host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run()
