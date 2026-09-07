"""
agience-server-aria — MCP Server
==================================
Aria (output — presentation): formatting, visualization, language, usability.
A tekton — the output condensor in the chorus (the tekton standard library); its tools are organons, invoked by condensation (OPERATOR-ARCHITECTURE §12).

Aria is the output persona of chorus (operators, by domain). It communicates
results to humans through language, formatting, visualization, and interface
presentation while ensuring clarity and usability.

Pipeline position: Output & user interaction (last mile to the human).

Tools
-----
  format_response      — Format content for human consumption
  render_visualization — Create charts, diagrams, or visual representations
  adapt_tone           — Adjust language tone/style for target audience
  present_card         — Present a card's content with appropriate formatting
  narrate              — Generate natural-language narrative from structured data

Auth
----
  Service identity loaded once by the chorus host (chorus.private.pem).
  Persona signs its own platform JWTs via _auth.sign_self_jwt() — no token
  exchange with Origin, no PLATFORM_INTERNAL_SECRET. Inbound delegation JWTs
  verified against Mantle's inline JWKS in the platform authority manifest.

  MANTLE_URI ⬩ Base URI of the Mantle backend

Transport
---------
  MCP_TRANSPORT=streamable-http (default for Agience)
  MCP_HOST=0.0.0.0
  MCP_PORT=8083
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("agience-server-aria")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s - %(name)s - %(message)s")

MANTLE_URI: str = os.getenv("MANTLE_URI", "http://localhost:8081").rstrip("/")
ARIA_CLIENT_ID: str = "agience-server-aria"
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8083"))


# ---------------------------------------------------------------------------
# Shared authentication infrastructure (AgienceServerAuth)
# ---------------------------------------------------------------------------

from prism.trust import (
    ServerAuth as _AgienceServerAuth,
    MissingDelegationError,
)

_auth = _AgienceServerAuth(ARIA_CLIENT_ID, MANTLE_URI)


def create_aria_app():
    """Return the Aria MCP ASGI app with verified middleware and startup hooks."""
    return _auth.create_app(mcp)


# ---------------------------------------------------------------------------
# Standard server interface (used by _host and standalone)
# ---------------------------------------------------------------------------

def create_server_app():
    """Return the Aria ASGI app with verified middleware and startup hooks."""
    return create_aria_app()


async def server_startup() -> None:
    """Run Aria startup tasks. The trust map is on disk; nothing to fetch."""
    await _auth.startup()


# ---------------------------------------------------------------------------
# Self-registration (GENESIS-NEXT §B1.10): this persona owns its registration.
# The host holds no roster — it calls each persona's register(). PERSONA is the
# single source of truth for {name, role, endpoint}; register() self-registers
# with Mantle (server record) + the crystal gateway (owned types).
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "aria",
    "kind": "tekton",
    "role": "Presentation & Interface",
    "endpoint": "/aria/mcp",
    "client_id": ARIA_CLIENT_ID,
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
# Platform auth — Aria signs its own platform JWT via the chorus service identity
# ---------------------------------------------------------------------------


# Aria has no function that resolves the persona's platform JWT for a caller-chosen resource: all
# chorus personas share one `chorus.private.pem`, and `present_card`, `_get_workspace_artifact` and
# `_update_workspace_artifact` each take a caller-supplied `artifact_id`/`workspace_id`, so applying
# platform authority to that resource would be a cross-tenant primitive — a write one, in the case
# of `_update_workspace_artifact`'s PATCH. Aria has no principal-less path at all; if one is ever
# needed, it should be an explicit `_platform_request` rather than a fallback threaded through the
# user-header helper, since a fallback there would fire silently on exactly the requests that failed
# authentication.


def _require_user_headers() -> dict[str, str]:
    """Headers carrying the caller's verified delegation JWT — fails closed.

    The only header helper in this module. Raises `MissingDelegationError`
    (`prism/trust/server_auth.py::MissingDelegationError`) rather than falling back to aria's
    platform JWT: there is no fallback to fall back to.
    """
    return _auth.require_user_headers()


mcp = FastMCP(
    "agience-server-aria",
    instructions=(
        "You are Aria, the Agience presentation and interface server. "
        "You communicate results to humans through language, formatting, "
        "visualization, and interface presentation. Your goal is clarity "
        "and usability � transform structured data into human-readable output."
    ),
)

from mantle.clients.artifact_helpers import artifact_url, register_types_manifest
register_types_manifest(mcp, "aria", __file__)


# ---------------------------------------------------------------------------
# Tool: format_response
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Format content for human consumption. Transforms raw or structured "
        "data into a polished response with appropriate markup and layout."
    )
)
async def format_response(
    content: str,
    format: str = "markdown",
    style: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        content: Raw content to format.
        format: Target output format — 'markdown', 'html', 'plain'.
        style: Optional style hint — 'concise', 'detailed', 'executive', 'technical'.
        workspace_id: Optional workspace context.
    """
    # Declared but not implemented: formatting content deterministically without generating it has
    # no backend, and any dispatch target for this tool would recurse into this tool itself.
    _ = (content, format, style, workspace_id)  # unused — kept for stable tool signature
    raise NotImplementedError("format_response is a declared placeholder.")


# ---------------------------------------------------------------------------
# Tool: render_visualization
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Create a visual representation of structured data � charts, diagrams, "
        "tables, or other visual formats suitable for human review."
    )
)
async def render_visualization(
    data: str,
    chart_type: str = "auto",
    title: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        data: JSON string of data to visualize.
        chart_type: 'auto', 'bar', 'line', 'pie', 'table', 'diagram'.
        title: Optional title for the visualization.
        workspace_id: Optional workspace to store the visualization card.
    """
    raise NotImplementedError(f"render_visualization is a declared placeholder. chart_type={chart_type}")


# ---------------------------------------------------------------------------
# Tool: adapt_tone
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Raises. Tone and register rewriting is model generation — no-models rule, "
        "universal and including BYOK. This surface answers in the source's own words."
    )
)
async def adapt_tone(
    content: str,
    audience: str = "general",
    tone: str = "professional",
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        content: Text to adapt.
        audience: Target audience — 'executive', 'technical', 'general', 'casual'.
        tone: Desired tone — 'professional', 'friendly', 'formal', 'concise'.
        workspace_id: Optional workspace context.
    """
    # Rewriting text into a different tone/register has no deterministic implementation — it is
    # generation, and the no-models rule is universal, including BYOK, the same rule `extract_units`,
    # `attach_provenance mode='evidence'`, and `run_chat_turn` enforce elsewhere in this file. This
    # tool cannot exist here; it raises rather than carrying a TODO that invites someone to implement
    # it and breach the rule.
    _ = (content, audience, tone, workspace_id)  # unused — kept for stable tool signature
    raise NotImplementedError(
        "adapt_tone: tone/register rewriting is model generation — no-models rule (universal, incl. "
        "BYOK). There is no grounded operator for it; the surface answers with the source's own "
        "words, never a restyled paraphrase."
    )


# ---------------------------------------------------------------------------
# Tool: present_card
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Present a card's content with appropriate formatting and context "
        "for human review. Resolves the card by ID and renders its content."
    )
)
async def present_card(
    artifact_id: str,
    workspace_id: Optional[str] = None,
    format: str = "markdown",
) -> str:
    """
    Args:
        artifact_id: ID of the card to present.
        workspace_id: Workspace containing the card (optional).
        format: Presentation format — 'markdown', 'html', 'plain', 'summary'.
    """
    # The id is encoded as ONE path segment — an artifact id is opaque and this corpus's
    # ids carry characters with URL meaning. `canon:best-practices#intro` interpolated
    # into an f-string yields the path `/artifacts/canon:best-practices` with `#intro`
    # split off as a fragment the server never receives, so the request asks for a
    # different artifact and gets a plausible answer for it.
    #
    # `workspace_id` stays in the signature for callers and selects nothing: both branches resolve
    # to the same string.
    url = artifact_url(MANTLE_URI, artifact_id)
    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": str(exc)})
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=15)
    if resp.status_code >= 400:
        # Error shape: a JSON object, not prose. `present_card`'s success is rendered markdown, and a
        # plain `f"Error: {code} — {body}"` string would be indistinguishable from a card whose content
        # happened to start with the word Error, leaving no machine-readable way to tell a 403 from a
        # document. `{"error": ...}` avoids that: success never starts with `{`, and a caller that does
        # try `json.loads` gets the reason instead of a JSONDecodeError at char 0.
        return json.dumps({"error": f"{resp.status_code} — {resp.text[:300]}"})
    card = resp.json()
    title = card.get("title", "(untitled)")
    content = card.get("content", "")
    content_type = card.get("content_type", "text/plain")
    return f"# {title}\n\nType: {content_type}\n\n{content}"


# ---------------------------------------------------------------------------
# Tool: narrate
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Raises. Turning data into narrative prose is model generation — no-models "
        "rule, universal and including BYOK. Grounded operators return what the "
        "sources say; they do not retell it."
    )
)
async def narrate(
    content: str,
    context: Optional[str] = None,
    style: str = "informative",
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        content: Structured data or results to narrate.
        context: Optional background context for the narrative.
        style: Narrative style — 'informative', 'executive-brief', 'tutorial', 'story'.
        workspace_id: Optional workspace context.
    """
    # Same reasoning as `adapt_tone`: turning data into a story is generation by definition, and
    # there is no grounded operator that invents narrative prose. An answer is the source's own
    # definition, not a generated retelling.
    _ = (content, context, style, workspace_id)  # unused — kept for stable tool signature
    raise NotImplementedError(
        "narrate: turning data into narrative prose is model generation — no-models rule (universal, "
        "incl. BYOK). Grounded operators return what the sources say; they do not retell it."
    )


# ---------------------------------------------------------------------------
# REST helpers for artifact CRUD
# ---------------------------------------------------------------------------

async def _get_workspace_artifact(workspace_id: str, artifact_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, artifact_id),
            headers=_require_user_headers(),
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


async def _update_workspace_artifact(workspace_id: str, artifact_id: str, *, context: dict | None = None, content: str | None = None) -> dict:
    body: dict = {}
    if context is not None:
        body["context"] = context
    if content is not None:
        body["content"] = content
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            artifact_url(MANTLE_URI, artifact_id),
            headers=_require_user_headers(),
            json=body,
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


def _parse_artifact_context(artifact: dict) -> dict:
    raw = artifact.get("context") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# Tool: extract_units — Semantic unit extraction
# ---------------------------------------------------------------------------

_ALLOWED_UNIT_KINDS = {"decision", "constraint", "action", "claim"}


@mcp.tool(
    description=(
        "Raises. No-models rule, universal and including BYOK."
    )
)
async def extract_units(
    workspace_id: str,
    source_artifact_id: str,
    artifact_artifact_ids: Optional[List[str]] = None,
    model: str = "gpt-4o-mini",
    max_units: int = 12,
) -> str:
    """
    Args:
        workspace_id: Workspace containing the source artifact.
        source_artifact_id: Artifact to extract units from.
        artifact_artifact_ids: Optional additional artifact IDs for context.
        model: Unused; retained for signature stability.
        max_units: Maximum number of units to extract.
    """
    # Mining decisions/constraints/actions/claims from text is model generation, which the
    # no-models rule forbids universally, including BYOK.
    raise NotImplementedError(
        "extract_units: no-models rule; grounded operators only."
    )


# ---------------------------------------------------------------------------
# Tool: attach_provenance — Evidence & source metadata
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Attach provenance metadata (source references) to existing workspace "
        "artifacts, writing into context.semantic.sources. mode='sources_only' "
        "is deterministic. mode='evidence' raises: no-models rule."
    )
)
async def attach_provenance(
    workspace_id: str,
    source_artifact_id: str,
    target_artifact_ids: Optional[List[str]] = None,
    target_artifact_id: Optional[str] = None,
    mode: str = "evidence",
    model: str = "gpt-4o-mini",
    max_evidence: int = 5,
) -> str:
    """
    Args:
        workspace_id: Workspace containing the artifacts.
        source_artifact_id: Artifact that is the source of provenance.
        target_artifact_ids: List of artifact IDs to attach provenance to.
        target_artifact_id: Single target artifact ID (alternative to list).
        mode: 'sources_only' (deterministic, works) or 'evidence' (tombstone — raises).
        model: Unused; retained for signature stability.
        max_evidence: Unused; retained for signature stability.
    """
    if not workspace_id or not source_artifact_id:
        return json.dumps({"error": "workspace_id and source_artifact_id are required"})

    ids: List[str] = []
    if isinstance(target_artifact_ids, list):
        ids.extend([str(x) for x in target_artifact_ids if str(x or "").strip()])
    if target_artifact_id:
        ids.append(str(target_artifact_id))
    ids = list(dict.fromkeys(ids))
    if not ids:
        return json.dumps({"error": "At least one target artifact ID required"})

    mode_norm = (mode or "evidence").strip().lower()
    if mode_norm not in {"sources_only", "evidence"}:
        return json.dumps({"error": "mode must be 'sources_only' or 'evidence'"})

    if mode_norm == "evidence":
        # Evidence-quote extraction is model generation, forbidden universally including BYOK.
        # The deterministic 'sources_only' mode (source-reference bookkeeping, no model call) works.
        raise NotImplementedError(
            "attach_provenance mode='evidence': model-based quote extraction "
            "removed 2026-07-22 — no-models rule; use mode='sources_only'."
        )

    try:
        source = await _get_workspace_artifact(workspace_id, source_artifact_id)
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"Failed to load source artifact: {exc}"})
    # Named separately: `MissingDelegationError` is a PermissionError, not an httpx error, and this tool
    # writes to caller-named artifacts — the refusal must be reported, not raised past the tool boundary.
    except MissingDelegationError as exc:
        return json.dumps({"error": f"attach_provenance refused: {exc}"})

    source_ctx = _parse_artifact_context(source)
    source_title = source_ctx.get("title")
    source_text = (source.get("content") or "").strip()

    source_ref: Dict[str, Any] = {"type": "workspace_artifact", "artifact_id": source_artifact_id}
    if source_title:
        source_ref["title"] = str(source_title)

    updated: List[str] = []
    skipped: List[Dict[str, Any]] = []

    for tid in ids:
        try:
            target = await _get_workspace_artifact(workspace_id, tid)
        except httpx.HTTPError as exc:
            skipped.append({"artifact_id": tid, "reason": f"target_fetch_failed: {exc}"})
            continue

        ctx = _parse_artifact_context(target)
        semantic = ctx.get("semantic") if isinstance(ctx.get("semantic"), dict) else {}

        # Dedupe sources
        sources = semantic.get("sources") if isinstance(semantic.get("sources"), list) else []
        sources.append(source_ref)
        seen_src: set[tuple] = set()
        deduped_sources: List[Dict[str, Any]] = []
        for s in sources:
            if not isinstance(s, dict):
                continue
            key = (str(s.get("type") or ""), str(s.get("artifact_id") or ""), str(s.get("uri") or ""))
            if key not in seen_src:
                seen_src.add(key)
                deduped_sources.append(s)
        semantic["sources"] = deduped_sources

        evidence_to_add: List[Dict[str, Any]] = []  # always empty: evidence mode raises above

        # Dedupe evidence
        existing_ev = semantic.get("evidence") if isinstance(semantic.get("evidence"), list) else []
        existing_ev.extend(evidence_to_add)
        seen_ev: set[tuple] = set()
        deduped_ev: List[Dict[str, Any]] = []
        for ev in existing_ev:
            if not isinstance(ev, dict):
                continue
            key = (str(ev.get("source_artifact_id") or ""), str(ev.get("quote") or ""), str(ev.get("claim") or ""))
            if key not in seen_ev:
                seen_ev.add(key)
                deduped_ev.append(ev)
        semantic["evidence"] = deduped_ev

        ctx["semantic"] = semantic
        agent_meta = ctx.get("agent") if isinstance(ctx.get("agent"), dict) else {}
        agent_meta.update({"name": "attach_provenance", "source_artifact_id": source_artifact_id, "mode": mode_norm})
        ctx["agent"] = agent_meta

        try:
            await _update_workspace_artifact(workspace_id, tid, context=ctx)
            updated.append(tid)
        except httpx.HTTPError as exc:
            skipped.append({"artifact_id": tid, "reason": f"update_failed: {exc}"})

    return json.dumps({
        "workspace_id": workspace_id,
        "source_artifact_id": source_artifact_id,
        "mode": mode_norm,
        "updated_artifact_ids": updated,
        "skipped": skipped,
    })


# ---------------------------------------------------------------------------
# Tool: run_chat_turn — tombstone
# ---------------------------------------------------------------------------
# This platform runs no agentic chat loop and no model-backed chat: the no-models rule is
# universal, including BYOK, since remote model APIs count as trained weights. The tool stays
# declared so clients get a loud failure instead of a 404.

@mcp.tool(description="Raises. No-models rule: this platform runs no model-backed chat.")
async def run_chat_turn(
    messages: str,
    workspace_id: Optional[str] = None,
    model: str = "gpt-4o-mini",
    connection_artifact_id: Optional[str] = None,
    mcp_server_ids: Optional[str] = None,
    chat_artifact_id: Optional[str] = None,
) -> str:
    """
    Args:
        messages: JSON-encoded array of message objects [{role, content}, ...].
        workspace_id: Active workspace ID (retained for signature stability).
        model: Unused; retained for signature stability.
        connection_artifact_id: Unused; retained for signature stability.
        mcp_server_ids: Unused; retained for signature stability.
        chat_artifact_id: Unused; retained for signature stability.
    """
    raise NotImplementedError(
        "run_chat_turn: no-models rule; grounded operators only."
    )


# ---------------------------------------------------------------------------
# UI Resources
# ---------------------------------------------------------------------------

@mcp.resource("ui://aria/vnd.agience.view.html")
async def view_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.view+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.view+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://aria/vnd.agience.chat.html")
async def chat_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.chat+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.chat+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting agience-server-aria � transport=%s", MCP_TRANSPORT)
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn
        uvicorn.run(create_server_app(), host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run()
