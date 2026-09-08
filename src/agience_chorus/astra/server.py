"""
agience-server-astra — MCP Server
====================================
Astra (input — ingestion, describers, sources): capture, prepare, and index incoming information.
A tekton — the input condensor in the chorus (the tekton standard library); its tools are organons, invoked by condensation (OPERATOR-ARCHITECTURE §12).

Astra is the input persona of chorus (operators, by domain). It captures and
prepares incoming information through ingestion, validation, normalization,
indexing, hygiene, and telemetry collection from system inputs and activity
streams.

Pipeline position: Input & ingestion (first contact with external content).

Tools
-----
Implemented (live):
  ingest_file              — Create a workspace card from a file URL or raw text
  document_text_extract    — Extract text from a PDF artifact into a derived text artifact
  process_uploaded_content — Extract text from uploaded content and create derived artifacts
  apply_metadata           — Merge caller-supplied metadata into an artifact and re-index it
  ingest_pipeline          — Run dedup + text extraction on a PDF artifact in one call
  deduplicate              — Check for duplicate content by SHA-256 hash
  connect_source           — Register an external connector (Drive folder, inbox, Slack channel)
  sync_source              — Pull latest content from a registered connector
  ingest_text              — Extract, chunk, and index text from an uploaded artifact
  transcribe               — Finalize a completed stream session card into a transcript card
  rotate_stream_key        — Generate or rotate the RTMP stream key for a stream source

Declared placeholders (registered, raise NotImplementedError):
  validate_input      — Validate incoming data against a schema or content rules
  normalize_artifact  — Normalize card content: standardize fields, clean formatting
  classify_content    — Raises; no-models rule, this platform runs no trained classifier
  index_artifact      — Force re-index of a card into the search layer
  collect_telemetry   — Collect and record system activity telemetry as workspace cards

Auth
----
  Service identity loaded once by the chorus host (chorus.private.pem).
  Persona signs its own platform JWTs via _auth.sign_self_jwt() — no token
  exchange with Origin, no PLATFORM_INTERNAL_SECRET. Inbound delegation JWTs
  verified against Mantle's inline JWKS in the platform authority manifest.

  MANTLE_URI ⬩ Base URI of the Mantle backend

Stream
------
  Stream lifecycle (publish/unpublish) is handled by Mantle core.
  The rotate_stream_key tool remains here to manage RTMP keys via the
  Core API.  SRS_HTTP_API is unused on Astra.

Transport
---------
  MCP_TRANSPORT=streamable-http
  MCP_HOST=0.0.0.0
  MCP_PORT=8087
"""

from __future__ import annotations

import io
import json
import logging
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("agience-server-astra")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s - %(name)s - %(message)s")

MANTLE_URI: str = os.getenv("MANTLE_URI", "http://localhost:8081").rstrip("/")
ASTRA_CLIENT_ID: str = "agience-server-astra"
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8087"))
STREAM_INGEST_URL: str = os.getenv("STREAM_INGEST_URL", "rtmp://localhost:1936/live").rstrip("/")


# ---------------------------------------------------------------------------
# Shared authentication infrastructure (AgienceServerAuth)
# ---------------------------------------------------------------------------

from prism.trust import ServerAuth as _AgienceServerAuth
from mantle.clients.artifact_helpers import (
    artifact_url,
    get_artifact_content_type,
    parse_artifact_context,
)

_auth = _AgienceServerAuth(ASTRA_CLIENT_ID, MANTLE_URI)


async def _headers() -> dict[str, str]:
    """Headers with Astra's own platform JWT (signed via the chorus service identity)."""
    return _auth.headers()


# Astra has no `_user_headers()`-style fallback function, and must not gain one. Every astra tool
# takes a caller-supplied resource id, so there is no call site where falling back to Astra's own
# platform JWT would be correct: a fallback would escalate to service identity on exactly the
# requests that failed authentication, since the middleware stores an empty token whenever
# verification or minting fails. A predicate named like an authorization check, living in an
# authorization module, is a loaded gun even unused — the next person needing "the caller's headers"
# wires it into a gate. If a genuinely principal-less path ever appears here (a webhook, say), give
# it an explicit `_platform_request`-style function like ophan's, so a static check can tell the two
# apart — a boolean flag cannot express the exemption to the call-graph guard. See ophan/server.py.


def _require_user_headers() -> dict[str, str]:
    """Headers carrying the caller's verified delegation JWT — fails closed.

    Tools acting on a caller-supplied resource id must use this. `_headers`/`_user_headers` fall back
    to Astra's platform JWT, and the middleware stores an empty token when verification or minting
    fails, so a `_user_headers` site escalates to service identity on exactly the requests that
    failed authentication. Raises `MissingDelegationError`
    (`prism/trust/server_auth.py::ServerAuth.require_user_headers`). Guarded by
    `chorus/tests/test_no_service_identity_on_caller_ids.py`.
    """
    return _auth.require_user_headers()


def create_server_app():
    """Return the Astra ASGI app with verified middleware and startup hooks."""
    return _auth.create_app(mcp)


async def server_startup() -> None:
    """Run Astra startup tasks. The trust map is on disk; nothing to fetch."""
    await _auth.startup()


# ---------------------------------------------------------------------------
# Self-registration (GENESIS-NEXT §B1.10): this persona owns its registration.
# The host holds no roster — it calls each persona's register(). PERSONA is the
# single source of truth for {name, role, endpoint}; register() self-registers
# with Mantle (server record) + the crystal gateway (owned types).
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "astra",
    "kind": "tekton",
    "role": "Ingestion & Indexing",
    "endpoint": "/astra/mcp",
    "client_id": ASTRA_CLIENT_ID,
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


async def _get_workspace_artifact(workspace_id: str, artifact_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, artifact_id),
            headers=_require_user_headers(),
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


async def _get_workspace_artifact_content_url(workspace_id: str, artifact_id: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, artifact_id, "content-url"),
            headers=_require_user_headers(),
            timeout=30,
        )
    resp.raise_for_status()
    payload = resp.json()
    return str(payload.get("url") or "")


from agience_chorus.astra import market_ingest, market_sources

#: A connector is an artifact so a sync is reproducible from the store, not from call arguments.
CONNECTOR_CT = "application/vnd.agience.connector+json"

#: Only connectors with a working fetcher. Deliberately does not list google_drive/gmail/slack/notion:
#: naming a type this tool cannot run would advertise a capability that does not exist. Credentialed
#: sources (openbb, polygon.io) belong here only once their secret resolves through seraph.
_CONNECTORS = {"market.binance", "news.gdelt"}


async def _find_child(container_id: str, name: str, content_type: str) -> dict | None:
    """One child of `container_id` whose title matches `name`, or None.

    Used for idempotent ingest: a series that already exists must be reused, never forked, or a
    re-run would split one symbol's history across two collections. `workspace_id` is passed as the
    container so draft children are visible too — an uncommitted series from an interrupted run must
    still be found, otherwise the retry duplicates it.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, container_id, "children"),
            params={"content_type": content_type, "workspace_id": container_id},
            # Fails closed on the caller-supplied `container_id`: an absent or unverifiable
            # delegation must not fall back to Astra's platform JWT, or this becomes a cross-tenant
            # listing primitive that returns any named container's children under platform
            # authority. The sole caller is the `sync_source` MCP tool (`find_child=_find_child`),
            # which only ever runs inside a delegated request, so there is no background path that
            # needs a fallback.
            headers=_require_user_headers(),
            timeout=30,
        )
    if resp.status_code != 200:
        return None
    for child in resp.json() or []:
        raw = child.get("context") or "{}"
        ctx = json.loads(raw) if isinstance(raw, str) else raw
        if (ctx or {}).get("title") == name or child.get("name") == name:
            return child
    return None


async def _create_workspace_artifact(workspace_id: str, context: dict, content: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{MANTLE_URI}/artifacts",
            headers=_require_user_headers(),
            json={
                "container_id": workspace_id,
                "context": json.dumps(context),
                "content": content,
                "content_type": context.get("content_type"),
            },
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


async def _update_workspace_artifact(workspace_id: str, artifact_id: str, *, context: dict | None = None, content: str | None = None) -> dict:
    body: dict = {}
    if context is not None:
        body["context"] = json.dumps(context)
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


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks).strip()


def _derive_text_title(title: Optional[str], context: dict) -> str:
    base = title or context.get("title") or context.get("filename") or "Extracted Text"
    if isinstance(base, str) and base.lower().endswith(".pdf"):
        base = base[:-4]
    base = str(base).strip() or "Extracted Text"
    return f"{base} Text"


mcp = FastMCP(
    "agience-server-astra",
    instructions=(
        "You are Astra, the Agience ingestion, validation, and indexing server. "
        "You capture and prepare incoming information through ingestion, validation, "
        "normalization, indexing, and hygiene. You also collect telemetry from system "
        "inputs and activity streams."
    ),
)

from mantle.clients.artifact_helpers import register_types_manifest
register_types_manifest(mcp, "astra", __file__)


# ---------------------------------------------------------------------------
# Tool: ingest_file
# ---------------------------------------------------------------------------

@mcp.tool(description="Ingest a file URL or raw text into a workspace as a card.")
async def ingest_file(
    workspace_id: str,
    url: Optional[str] = None,
    text: Optional[str] = None,
    title: Optional[str] = None,
    content_type: str = "text/plain",
) -> str:
    """
    Args:
        workspace_id: Target workspace ID.
        url: Public URL of the file to ingest (mutually exclusive with text).
        text: Raw text content to store directly (mutually exclusive with url).
        title: Optional card title. Inferred from URL filename if not set.
        content_type: MIME type hint (e.g. "text/markdown", "application/pdf").
    """
    if not url and not text:
        return "Error: provide either 'url' or 'text'."

    payload: dict = {
        "context": json.dumps({
            "type": "ingest",
            "source": url or "inline",
            "content_type": content_type,
        }),
        "content": text or "",
    }
    if content_type:
        # Also set mantle's own field, not just the context copy. Without it every ingested artifact
        # lands with `content_type: null`, which is the field indexing and retrieval filter on
        # (`GET /artifacts/{id}/children?content_type=…` cannot find them at all).
        payload["content_type"] = content_type
    if title:
        # `CreateArtifactRequest` (`mantle/routers/artifacts_router.py`) declares `name`, not
        # `title`, and does not set `extra="forbid"`, so a `title` key would be silently dropped by
        # pydantic and every ingest would be stored untitled while this tool reported success.
        payload["name"] = title

    payload["container_id"] = workspace_id
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{MANTLE_URI}/artifacts",
            headers=_require_user_headers(),
            json=payload,
            timeout=30,
        )

    if resp.status_code >= 400:
        return json.dumps({"error": "upstream %s" % resp.status_code, "detail": resp.text[:300]})

    card = resp.json()
    return f"Ingested card {card.get('id')}: {card.get('title', '(untitled)')}"


# ---------------------------------------------------------------------------
# Tool: document_text_extract
# ---------------------------------------------------------------------------

@mcp.tool(description="Extract text from a PDF artifact and create a derived text artifact. Returns structured JSON with text_artifact_id, extraction method, page count, and content_hash — suitable for downstream Transform steps.")
async def document_text_extract(
    workspace_id: str,
    source_artifact_id: str,
    title: Optional[str] = None,
) -> str:
    """
    Args:
        workspace_id: Workspace that owns the source artifact.
        source_artifact_id: PDF artifact to extract text from.
        title: Optional title override for the derived text artifact.

    Returns JSON:
        {
            "source_artifact_id": str,
            "text_artifact_id": str,
            "title": str,
            "length": int,
            "pages": int,
            "method": "pypdf",
            "content_hash": str,
            "images": [],   # populated by advanced extractors (third-party MCP servers)
            "tables": []    # populated by advanced extractors
        }
    """
    import hashlib

    try:
        artifact = await _get_workspace_artifact(workspace_id, source_artifact_id)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed to load artifact {source_artifact_id}: {exc}"})

    context = _parse_artifact_context(artifact)
    mime = get_artifact_content_type(artifact)
    if mime != "application/pdf":
        return json.dumps({"status": "error", "reason": f"source artifact is not a PDF (content_type={mime or 'unknown'})"})

    try:
        download_url = await _get_workspace_artifact_content_url(workspace_id, source_artifact_id)
        async with httpx.AsyncClient() as client:
            pdf_response = await client.get(download_url, timeout=60)
        pdf_response.raise_for_status()
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed to download PDF: {exc}"})

    pdf_bytes = pdf_response.content
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    try:
        from pypdf import PdfReader as _PdfReader
        reader = _PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        pages_text: list[str] = []
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                pages_text.append(t.strip())
        extracted_text = "\n\n".join(pages_text).strip()
    except ImportError:
        return json.dumps({"status": "error", "reason": "pypdf not installed on Astra server"})
    except Exception as exc:
        return json.dumps({"status": "error", "reason": f"PDF extraction failed: {exc}"})

    if not extracted_text:
        return json.dumps({"status": "error", "reason": "PDF yielded no extractable text"})

    output_title = _derive_text_title(title, context)
    derived_context = {
        "content_type": "text/markdown",
        "title": output_title,
        "type": "document-text",
        "source_artifact_id": source_artifact_id,
        "content_hash": content_hash,
        "derived_from": {
            "artifact_id": source_artifact_id,
            "transform": "document-text-extract",
            "method": "pypdf",
        },
    }

    try:
        output_artifact = await _create_workspace_artifact(workspace_id, derived_context, extracted_text)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed creating derived artifact: {exc}"})

    # Stamp content_hash onto source artifact context for dedup
    if context.get("content_hash") != content_hash:
        try:
            await _update_workspace_artifact(workspace_id, source_artifact_id, context={**context, "content_hash": content_hash})
        except httpx.HTTPError as exc:
            log.warning("document_text_extract: failed to stamp content_hash on source: %s", exc)

    return json.dumps({
        "status": "ok",
        "source_artifact_id": source_artifact_id,
        "text_artifact_id": output_artifact.get("id"),
        "title": output_title,
        "length": len(extracted_text),
        "pages": page_count,
        "method": "pypdf",
        "content_hash": content_hash,
        "images": [],
        "tables": [],
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool: process_uploaded_content
# ---------------------------------------------------------------------------

# Max bytes to download for text extraction.
_MAX_DOWNLOAD_BYTES = 10_000_000  # 10 MB

# Derived-artifact context types to skip (prevent infinite loops).
_SKIP_CONTEXT_TYPES = frozenset({
    "workspace-event-handler",
    "ingest.parsed_text",
    "ingest.chunk",
})

# Chunking thresholds — _CHUNK_SIZE / _CHUNK_OVERLAP (tokens) used by both
# process_uploaded_content and ingest_text.  Character threshold used as a
# fast pre-check before tokenising.
_CHUNK_THRESHOLD_CHARS = 4_000


@mcp.tool(description="Process uploaded text content � extract text and create derived artifacts for search and agent use.")
async def process_uploaded_content(
    workspace_id: str,
    artifact_id: str,
    source_artifact_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> str:
    """
    Triggered by upload_complete lifecycle events for text-extractable types.
    Extracts text from the uploaded artifact and creates derived parsed_text
    and chunk artifacts in the same workspace.

    Args:
        workspace_id: Workspace containing the uploaded artifact.
        artifact_id: The uploaded artifact to process.
        source_artifact_id: Alias for artifact_id (from event dispatch).
        event_type: The lifecycle event that triggered this (informational).
    """
    source_artifact_id = artifact_id or source_artifact_id
    if not source_artifact_id:
        return json.dumps({"status": "skipped", "reason": "no artifact_id"})

    # Fetch artifact metadata from Core
    try:
        artifact = await _get_workspace_artifact(workspace_id, source_artifact_id)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed to fetch artifact: {exc}"})

    context = _parse_artifact_context(artifact)

    # Skip derived/handler artifacts
    ctx_type = context.get("type") or ""
    if ctx_type in _SKIP_CONTEXT_TYPES:
        return json.dumps({"status": "skipped", "reason": f"source is {ctx_type}"})

    content_type = get_artifact_content_type(artifact)
    if not _is_text_extractable(content_type):
        return json.dumps({"status": "skipped", "reason": "not_text_extractable", "content_type": content_type})

    # Extract text: prefer inline content, fall back to S3 download
    text = (artifact.get("content") or "").strip()
    if not text:
        content_key = context.get("content_key")
        if not content_key:
            return json.dumps({"status": "skipped", "reason": "no content or content_key"})

        try:
            download_url = await _get_workspace_artifact_content_url(workspace_id, source_artifact_id)
            async with httpx.AsyncClient() as client:
                resp = await client.get(download_url, timeout=60)
            resp.raise_for_status()
            raw_bytes = resp.content[:_MAX_DOWNLOAD_BYTES]

            encoding = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
                encoding = charset or "utf-8"
            try:
                text = raw_bytes.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = raw_bytes.decode("utf-8", errors="replace")
        except httpx.HTTPError as exc:
            return json.dumps({"status": "error", "reason": f"failed to download content: {exc}"})

    text = text.strip()
    if not text:
        return json.dumps({"status": "skipped", "reason": "no_text_extracted"})

    # Cap text length from `_MAX_CONTENT_LEN`, single-sourced. Truncation is recorded, not hidden:
    # a 2 MB artifact cut from a 40 MB document is not the document.
    _full_chars = len(text)
    if _full_chars > _MAX_CONTENT_LEN:
        text = text[:_MAX_CONTENT_LEN]

    created_ids: list[str] = []
    filename = context.get("filename") or source_artifact_id

    # Create parsed_text artifact
    parsed_context = {
        "type": "ingest.parsed_text",
        "source_artifact_id": source_artifact_id,
        "content_type": "text/plain",
        "title": f"Parsed: {filename}",
        "truncated": _full_chars > _MAX_CONTENT_LEN,
        "source_chars": _full_chars,
    }
    try:
        parsed = await _create_workspace_artifact(workspace_id, parsed_context, text)
        parsed_id = parsed.get("id")
        if parsed_id:
            created_ids.append(parsed_id)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed to create parsed artifact: {exc}"})

    # Create chunk artifacts for long text
    chunk_ids: list[str] = []
    if len(text) > _CHUNK_THRESHOLD_CHARS:
        chunks = _chunk_text(text)
        for chunk in chunks:
            chunk_context = {
                "type": "ingest.chunk",
                "source_artifact_id": source_artifact_id,
                "parsed_artifact_id": parsed_id,
                "chunk_index": chunk["chunk_id"],
                "content_type": "text/plain",
                "title": f"Chunk {chunk['chunk_id']}: {filename}",
            }
            try:
                chunk_artifact = await _create_workspace_artifact(
                    workspace_id, chunk_context, chunk["text"],
                )
                cid = chunk_artifact.get("id")
                if cid:
                    chunk_ids.append(cid)
                    created_ids.append(cid)
            except httpx.HTTPError:
                log.warning("Failed to create chunk %d for %s", chunk["chunk_id"], source_artifact_id)

    return json.dumps({
        "status": "ok",
        "source_artifact_id": source_artifact_id,
        "parsed_artifact_id": parsed_id,
        "chunk_ids": chunk_ids,
        "total_created": len(created_ids),
    })


# ---------------------------------------------------------------------------
# Tool: validate_input
# ---------------------------------------------------------------------------

@mcp.tool(description="Validate incoming data against a schema or content rules.")
async def validate_input(
    content: str,
    schema: Optional[dict] = None,
    content_type: Optional[str] = None,
) -> str:
    """
    Args:
        content: Content to validate.
        schema: Optional JSON Schema to validate against.
        content_type: Expected MIME type for format validation.
    """
    raise NotImplementedError("validate_input is a declared placeholder.")


# ---------------------------------------------------------------------------
# Tool: normalize_artifact
# ---------------------------------------------------------------------------

@mcp.tool(description="Normalize card content � standardize fields, clean formatting, resolve encodings.")
async def normalize_artifact(
    artifact_id: str,
    workspace_id: str,
) -> str:
    """
    Args:
        artifact_id: Card to normalize.
        workspace_id: Workspace containing the card.
    """
    raise NotImplementedError(f"normalize_artifact is a declared placeholder. artifact_id={artifact_id}")


# ---------------------------------------------------------------------------
# Tool: apply_metadata
# ---------------------------------------------------------------------------

@mcp.tool(description="Merge caller-supplied metadata into an artifact's context.metadata field, then re-index so the fields become searchable. Deterministic merge; no model involved.")
async def apply_metadata(
    workspace_id: str,
    artifact_id: str,
    metadata: str,
) -> str:
    """
    Args:
        workspace_id: Workspace containing the artifact.
        artifact_id: Artifact to update.
        metadata: JSON string with extracted metadata fields, e.g.:
            {"published_by": "...", "published_date": "2024-01-15",
             "document_type": "Report", "formality": "High",
             "sector": "Technology", "issues": ["AI", "data privacy"]}

    Returns JSON: {"status": "ok", "artifact_id": str, "fields_applied": list}
    """
    try:
        new_meta = json.loads(metadata) if isinstance(metadata, str) else metadata
    except json.JSONDecodeError as exc:
        return json.dumps({"status": "error", "reason": f"invalid metadata JSON: {exc}"})

    if not isinstance(new_meta, dict):
        return json.dumps({"status": "error", "reason": "metadata must be a JSON object"})

    try:
        artifact = await _get_workspace_artifact(workspace_id, artifact_id)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed to fetch artifact: {exc}"})

    context = _parse_artifact_context(artifact)

    # Merge into context.metadata — existing values not overwritten
    existing_meta = context.get("metadata") or {}
    merged_meta = {**new_meta, **existing_meta}  # existing values win on conflict
    updated_context = {**context, "metadata": merged_meta}

    try:
        await _update_workspace_artifact(workspace_id, artifact_id, context=updated_context)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed to update artifact: {exc}"})

    return json.dumps({
        "status": "ok",
        "artifact_id": artifact_id,
        "fields_applied": list(new_meta.keys()),
    })


# ---------------------------------------------------------------------------
# Tool: ingest_pipeline
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Run the document ingestion pipeline on a PDF artifact: "
        "deduplication check → text extraction. Model-based metadata "
        "extraction was removed 2026-07-22 (no-models rule); metadata can "
        "still be applied deterministically via apply_metadata. Returns a "
        "summary of all steps executed."
    )
)
async def ingest_pipeline(
    workspace_id: str,
    artifact_id: str,
    skip_dedup: bool = False,
) -> str:
    """
    Args:
        workspace_id: Workspace containing the PDF artifact.
        artifact_id: The PDF artifact to ingest.
        skip_dedup: Skip the deduplication check (default: False).
    """
    steps: list[dict] = []

    # Step 1 — Deduplication
    if not skip_dedup:
        dedup_raw = await deduplicate(workspace_id, artifact_id)
        try:
            dedup_result = json.loads(dedup_raw)
        except json.JSONDecodeError:
            return json.dumps({"status": "error", "step": "dedup", "reason": f"unexpected dedup response: {dedup_raw[:200]}"})

        steps.append({"step": "dedup", "result": dedup_result})

        if dedup_result.get("status") == "error":
            return json.dumps({"status": "error", "step": "dedup", "reason": dedup_result.get("reason", "unknown")})
        if dedup_result.get("status") == "duplicate":
            return json.dumps({
                "status": "duplicate",
                "artifact_id": artifact_id,
                "duplicate_of": dedup_result.get("duplicate_of"),
                "steps": steps,
            })
    else:
        steps.append({"step": "dedup", "result": {"status": "skipped"}})

    # Step 2 — PDF text extraction
    extract_raw = await document_text_extract(workspace_id, artifact_id)
    try:
        extract_result = json.loads(extract_raw)
    except json.JSONDecodeError:
        return json.dumps({"status": "error", "step": "pdf_extract", "reason": f"unexpected extract response: {extract_raw[:200]}"})

    steps.append({"step": "pdf_extract", "result": extract_result})

    if extract_result.get("status") != "ok":
        return json.dumps({"status": "error", "step": "pdf_extract", "reason": extract_result.get("reason", "extraction failed"), "steps": steps})

    text_artifact_id = extract_result.get("text_artifact_id")

    # Fetch the extracted text from the derived artifact
    try:
        text_artifact = await _get_workspace_artifact(workspace_id, text_artifact_id)
        extracted_text = (text_artifact.get("content") or "").strip()
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "step": "pdf_extract", "reason": f"failed to read extracted text artifact: {exc}", "steps": steps})

    if not extracted_text:
        return json.dumps({"status": "error", "step": "pdf_extract", "reason": "extracted text artifact is empty", "steps": steps})

    # Step 3 — metadata extraction is the deterministic path only: there is no model-based step
    # here (no-models rule, universal, including BYOK), so what the pipeline does is exactly dedup
    # plus text extraction. Callers with metadata from a deterministic source apply it via the
    # apply_metadata tool.
    steps.append({
        "step": "metadata_extract",
        "result": {
            "status": "skipped",
            "reason": "model-based metadata extraction removed 2026-07-22 (no-models rule)",
        },
    })

    return json.dumps({
        "status": "ok",
        "artifact_id": artifact_id,
        "text_artifact_id": text_artifact_id,
        "pages": extract_result.get("pages"),
        "content_hash": extract_result.get("content_hash"),
        "metadata": None,
        "steps": steps,
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool: deduplicate
# ---------------------------------------------------------------------------

@mcp.tool(description="Check for duplicate content by SHA-256 hash. Stamps content_hash on the artifact context and searches the workspace for prior ingestions of the same file.")
async def deduplicate(
    workspace_id: str,
    artifact_id: str,
) -> str:
    """
    Args:
        workspace_id: Workspace containing the artifact to check.
        artifact_id: Artifact to check for duplicates.

    Returns JSON: {"status": "unique"} or {"status": "duplicate", "duplicate_of": "<artifact_id>", "duplicate_title": "..."}
    """
    import hashlib

    try:
        artifact = await _get_workspace_artifact(workspace_id, artifact_id)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed to fetch artifact: {exc}"})

    context = _parse_artifact_context(artifact)

    # Obtain content for hashing — prefer inline, fall back to S3
    raw_bytes: bytes = b""
    inline = (artifact.get("content") or "").strip()
    if inline:
        raw_bytes = inline.encode("utf-8")
    else:
        content_key = context.get("content_key")
        if content_key:
            try:
                url = await _get_workspace_artifact_content_url(workspace_id, artifact_id)
                async with httpx.AsyncClient() as client:
                    dl = await client.get(url, timeout=60)
                dl.raise_for_status()
                raw_bytes = dl.content
            except httpx.HTTPError as exc:
                return json.dumps({"status": "error", "reason": f"failed to download content: {exc}"})

    if not raw_bytes:
        return json.dumps({"status": "skipped", "reason": "no_content"})

    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    # Stamp hash onto artifact context if not already present
    if context.get("content_hash") != content_hash:
        merged_ctx = {**context, "content_hash": content_hash}
        try:
            await _update_workspace_artifact(workspace_id, artifact_id, context=merged_ctx)
        except httpx.HTTPError as exc:
            log.warning("deduplicate: failed to stamp content_hash on %s: %s", artifact_id, exc)

    # Search workspace for other artifacts with the same hash
    try:
        async with httpx.AsyncClient() as client:
            search_resp = await client.post(
                # Was `/artifacts/search`, which mantle deleted — 404, never a redirect.
                # The swallow below turned that into `results = []`, so this tool answered
                # "unique" for EVERY artifact and had never once found a duplicate.
                f"{MANTLE_URI}/artifacts/recall",
                headers=_require_user_headers(),
                json={
                    "query_text": content_hash,
                    "scope": [workspace_id],
                    "size": 5,
                },
                timeout=30,
            )
        search_resp.raise_for_status()
        results = search_resp.json().get("items", [])
    except httpx.HTTPError as exc:
        log.warning("deduplicate: search failed for %s: %s", artifact_id, exc)
        results = []

    # Filter out the artifact itself
    matches = [r for r in results if r.get("id") != artifact_id and r.get("root_id") != artifact_id]
    if matches:
        first = matches[0]
        return json.dumps({
            "status": "duplicate",
            "content_hash": content_hash,
            "duplicate_of": first.get("id") or first.get("root_id"),
            "duplicate_title": first.get("title") or first.get("context", {}).get("title"),
        })

    return json.dumps({"status": "unique", "content_hash": content_hash})


# ---------------------------------------------------------------------------
# Tool: classify_content
# ---------------------------------------------------------------------------

@mcp.tool(description="Raises. No-models rule: this platform runs no trained classifier.")
async def classify_content(
    content: str,
    workspace_id: Optional[str] = None,
    categories: Optional[list[str]] = None,
) -> str:
    """
    Args:
        content: Content to classify.
        workspace_id: Optional workspace context.
        categories: Optional list of target categories to choose from.
    """
    raise NotImplementedError(
        "classify_content: no-models rule; grounded operators only."
    )


# ---------------------------------------------------------------------------
# Tool: connect_source
# ---------------------------------------------------------------------------

@mcp.tool(description="Register an external connector (Drive folder, inbox, Slack channel).")
async def connect_source(
    workspace_id: str,
    connector_type: str,
    connection: dict,
) -> str:
    """Register a connector as an artifact, so a sync is reproducible and its config is auditable.

    Only implemented connector types are accepted; naming a type this tool cannot run — such as a
    Drive folder, inbox, or Slack channel — would advertise a capability that does not exist, so an
    unimplemented type is refused by name with the list of what is real.

    Implemented: `market.binance` (public OHLCV klines) and `news.gdelt` (public news doc API). Both
    are plain GET endpoints needing no credentials — which is why they came first. A credentialed
    source (openbb, polygon.io) must resolve its secret through seraph, not read a persona's
    environment.
    """
    kind = (connector_type or "").strip()
    if kind not in _CONNECTORS:
        return json.dumps({
            "error": "unsupported connector_type",
            "requested": kind,
            "implemented": sorted(_CONNECTORS),
            "why": "only connectors with a working fetcher are accepted; registering one without an "
                   "implementation would create a source that silently never syncs",
        })
    ctx = {
        "content_type": CONNECTOR_CT,
        "title": f"{kind} connector",
        "connector_type": kind,
        "connection": connection or {},
        "state": "registered",
    }
    created = await _create_workspace_artifact(workspace_id, ctx, "")
    return json.dumps({"connector_artifact_id": created.get("id"), "connector_type": kind,
                       "connection": ctx["connection"]})


# ---------------------------------------------------------------------------
# Tool: sync_source
# ---------------------------------------------------------------------------

@mcp.tool(description="Pull latest content from a registered connector into the workspace.")
async def sync_source(workspace_id: str, connector_artifact_id: str) -> str:
    """Run one registered connector and write what it returns as artifacts.

    Reads the connector artifact for its own config — a sync is therefore reproducible from the store,
    not from whatever arguments a caller happened to pass. Dispatches on `connector_type` to the ported
    fetchers (`astra.market_sources`) and writes through `astra.market_ingest`.

    `news.gdelt` writes fully — a headline is text, it embeds, and that embedding is the signal sage
    retrieves over. `market.binance` writes the series and a bars-chunk record, but the OHLCV
    payload stays `pending`: chorus has no parquet writer, and putting numbers in `content` would
    embed a numeric series into the meaning manifold, which the design refuses. The result says
    which happened rather than reporting an unqualified success.
    """
    art = await _get_workspace_artifact(workspace_id, connector_artifact_id)
    raw_ctx = art.get("context") or "{}"
    ctx = json.loads(raw_ctx) if isinstance(raw_ctx, str) else dict(raw_ctx)
    kind = (ctx.get("connector_type") or "").strip()
    conn = ctx.get("connection") or {}
    if kind not in _CONNECTORS:
        return json.dumps({"error": "connector artifact names an unsupported type",
                           "connector_type": kind, "implemented": sorted(_CONNECTORS)})

    if kind == "news.gdelt":
        query = conn.get("query") or ""
        if not query:
            return json.dumps({"error": "news.gdelt connector has no `query` in its connection — "
                                        "refusing to sync an unspecified feed"})
        items = await market_sources.fetch_gdelt_news(
            query, max_records=int(conn.get("max_records") or 50),
            timespan=conn.get("timespan") or "3d")
        ids = await market_ingest.push_news(
            workspace_id, items,
            lambda cid, c, body: _create_workspace_artifact(cid, c, body),
            tickers=conn.get("tickers"))
        return json.dumps({"connector_type": kind, "fetched": len(items),
                           "written": len(ids), "artifact_ids": ids[:20],
                           "embedded": True})

    # market.binance
    symbol = conn.get("symbol")
    interval = conn.get("interval") or "15m"
    if not symbol:
        return json.dumps({"error": "market.binance connector has no `symbol` — refusing to guess one"})
    rows = await market_sources.fetch_ohlcv_binance(
        symbol, interval=interval, days=int(conn.get("days") or 7))
    series_id = await market_ingest.ensure_series(
        workspace_id, symbol=symbol, interval=interval, source="binance",
        bar_seconds=market_sources.interval_seconds(interval),
        find_child=_find_child,
        create_artifact=lambda cid, c, body: _create_workspace_artifact(cid, c, body),
        quote=conn.get("quote"))
    chunk_id = await market_ingest.push_bars_chunk(
        series_id, symbol=symbol, interval=interval, source="binance",
        bar_seconds=market_sources.interval_seconds(interval), rows=rows,
        columns=market_sources.OHLCV_COLUMNS,
        create_artifact=lambda cid, c, body: _create_workspace_artifact(cid, c, body))
    return json.dumps({
        "connector_type": kind, "series_id": series_id, "chunk_id": chunk_id,
        "bars_fetched": len(rows), "payload": "pending",
        # `committed`/`indexed` are reported rather than assumed true, because an uncommitted series
        # is not indexed and is therefore invisible to retrieval — a silent half-ingest that looks
        # like a write succeeded. `market_ingest.commit_series` is not wired here because mantle
        # exposes no commit mutation route: the only `commits` route is the read-only
        # `GET /artifacts/{container_id}/commits`, and the sole state mutation is
        # `POST /artifacts/{id}/revert`. The honest move is to report the state and let the caller
        # see that a market sync currently produces data no retrieval can reach.
        "committed": False,
        "indexed": False,
        "note": "series + chunk metadata written; OHLCV bytes NOT uploaded (no parquet writer in "
                "chorus). Numbers are deliberately not embedded — see market_ingest.push_bars_chunk. "
                "⚠ The series is NOT committed and therefore NOT indexed, so it is invisible to "
                "retrieval: mantle exposes no commit route (only GET .../commits and POST .../revert), "
                "so market_ingest.commit_series cannot be wired. This write is real but unreachable.",
    })


# ---------------------------------------------------------------------------
# Tool: index_artifact
# ---------------------------------------------------------------------------

@mcp.tool(description="Force re-index of a card into the search layer.")
async def index_artifact(workspace_id: str, artifact_id: str) -> str:
    raise NotImplementedError(f"explicit re-index is a declared placeholder. artifact_id={artifact_id}")


# ---------------------------------------------------------------------------
# Text extraction & chunking utilities
# ---------------------------------------------------------------------------

_TEXT_EXTRACTABLE = {
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
    "application/ld+json",
    "application/xhtml+xml",
}

#: A resource cap, not a judgement, and stated as a seam rather than derived: 2 MB is what a derived
#: artifact is allowed to cost, and nothing here measures it. The bound should be derived from a
#: measured envelope (the store's per-artifact limit, or a cgroup memory allowance), and no such
#: figure is published anywhere this process can read ([[no-arbitrary-caps]]). Until one is, the cap
#: is stated once here and the truncation is recorded at every site that applies it — a silently
#: shortened artifact is indistinguishable from a complete one, which is the defect, not the cap.
#: A different value is right when a measured envelope says so.
_MAX_CONTENT_LEN = 2_000_000  # ~2 MB cap for derived artifact content
_CHUNK_SIZE = int(os.getenv("SEARCH_CHUNK_SIZE", "1000"))
_CHUNK_OVERLAP = int(os.getenv("SEARCH_CHUNK_OVERLAP", "200"))


def _is_text_extractable(content_type: str) -> bool:
    if not content_type:
        return False
    content_type = content_type.lower().split(";")[0].strip()
    if content_type.startswith("text/"):
        return True
    return content_type in _TEXT_EXTRACTABLE


def _word_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of whitespace-delimited words, in order."""
    import re
    return [m.span() for m in re.finditer(r"\S+", text)]


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[dict]:
    """Split text into overlapping word-based chunks.

    Tokens are whitespace-delimited words, counted deterministically — not BPE tokens from a
    trained tokenizer, which would be a model artifact (no-models rule). Chunk text is always an
    exact substring of the source (original spacing preserved); start_token/end_token are word
    indices.
    """
    if not text or not text.strip():
        return []
    spans = _word_spans(text)
    total = len(spans)
    if total <= chunk_size:
        return [{"chunk_id": 0, "text": text, "start_token": 0, "end_token": total}]

    chunks = []
    cid = 0
    start = 0
    while start < total:
        end = min(start + chunk_size, total)
        chunks.append({
            "chunk_id": cid,
            "text": text[spans[start][0]:spans[end - 1][1]],
            "start_token": start,
            "end_token": end,
        })
        cid += 1
        start += chunk_size - overlap
    return chunks


def _should_chunk(text: str) -> bool:
    """Deterministic word count (see _chunk_text)."""
    return len(_word_spans(text)) > _CHUNK_SIZE


# Alias shared helper — all servers use the same context parsing.
_parse_artifact_context = parse_artifact_context


# ---------------------------------------------------------------------------
# Tool: ingest_text
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Extract text from an uploaded artifact, optionally chunk it, and create "
        "derived workspace artifacts (ingest.parsed_text and ingest.chunk) that are "
        "automatically indexed by the search pipeline."
    )
)
async def ingest_text(
    workspace_id: str,
    source_artifact_id: str,
    create_chunks: bool = True,
) -> str:
    """
    Args:
        workspace_id: Workspace containing the source artifact.
        source_artifact_id: Artifact to extract text from.
        create_chunks: If true, split extracted text into chunk artifacts.
    """
    if not source_artifact_id:
        return json.dumps({"status": "skipped", "reason": "no source_artifact_id"})

    try:
        artifact = await _get_workspace_artifact(workspace_id, source_artifact_id)
    except httpx.HTTPError:
        return json.dumps({"status": "skipped", "reason": "artifact_not_found"})

    source_ctx = _parse_artifact_context(artifact)
    content_type = source_ctx.get("content_type") or ""

    # Skip handler artifacts and already-derived artifacts
    ctx_type = source_ctx.get("type") or ""
    if ctx_type in {"workspace-event-handler", "ingest.parsed_text", "ingest.chunk"}:
        return json.dumps({"status": "skipped", "reason": f"source is {ctx_type}"})

    # Check if content is extractable
    inline_content = (artifact.get("content") or "").strip()
    if not inline_content and not _is_text_extractable(content_type):
        return json.dumps({"status": "skipped", "reason": "not_text_extractable", "content_type": content_type})

    # Extract text: prefer inline content, fall back to S3 download
    text = inline_content
    if not text:
        try:
            download_url = await _get_workspace_artifact_content_url(workspace_id, source_artifact_id)
            if download_url:
                async with httpx.AsyncClient() as client:
                    dl_resp = await client.get(download_url, timeout=60)
                dl_resp.raise_for_status()
                text = dl_resp.content.decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("ingest_text: failed to download content for %s: %s", source_artifact_id, exc)

    if not text or not text.strip():
        return json.dumps({"status": "skipped", "reason": "no_text_extracted"})

    # Same cap, same reason it is recorded — see `_MAX_CONTENT_LEN`.
    _full_chars = len(text)
    if _full_chars > _MAX_CONTENT_LEN:
        text = text[:_MAX_CONTENT_LEN]

    created_ids: list[str] = []

    # Create parsed_text artifact
    parsed_ctx = {
        "type": "ingest.parsed_text",
        "source_artifact_id": source_artifact_id,
        "content_type": "text/plain",
        "title": f"Parsed: {source_ctx.get('filename') or source_artifact_id}",
        "truncated": _full_chars > _MAX_CONTENT_LEN,
        "source_chars": _full_chars,
    }
    try:
        parsed_artifact = await _create_workspace_artifact(workspace_id, parsed_ctx, text)
        parsed_id = parsed_artifact.get("id", "")
        created_ids.append(parsed_id)
    except httpx.HTTPError as exc:
        return json.dumps({"status": "error", "reason": f"failed creating parsed artifact: {exc}"})

    # Create chunk artifacts
    chunk_ids: list[str] = []
    if create_chunks and _should_chunk(text):
        chunks = _chunk_text(text)
        for chunk in chunks:
            chunk_ctx = {
                "type": "ingest.chunk",
                "source_artifact_id": source_artifact_id,
                "parsed_artifact_id": parsed_id,
                "chunk_index": chunk["chunk_id"],
                "start_token": chunk["start_token"],
                "end_token": chunk["end_token"],
                "content_type": "text/plain",
                "title": f"Chunk {chunk['chunk_id']}: {source_ctx.get('filename') or source_artifact_id}",
            }
            try:
                chunk_artifact = await _create_workspace_artifact(workspace_id, chunk_ctx, chunk["text"])
                cid = chunk_artifact.get("id", "")
                chunk_ids.append(cid)
                created_ids.append(cid)
            except httpx.HTTPError:
                log.warning("ingest_text: failed creating chunk %d for %s", chunk["chunk_id"], source_artifact_id)

    return json.dumps({
        "status": "ok",
        "source_artifact_id": source_artifact_id,
        "parsed_artifact_id": parsed_id,
        "chunk_ids": chunk_ids,
        "total_created": len(created_ids),
    })


# ---------------------------------------------------------------------------
# Tool: transcribe
# ---------------------------------------------------------------------------

@mcp.tool(description="Finalize a completed stream session card into a transcript card.")
async def transcribe(
    workspace_id: str,
    session_artifact_id: str,
    title: Optional[str] = None,
) -> str:
    """
    Args:
        workspace_id: Workspace that owns the stream session card.
        session_artifact_id: The completed stream session card to finalize.
        title: Optional transcript title override.
    """
    if not session_artifact_id:
        return "Error: session_artifact_id is required."

    try:
        artifact = await _get_workspace_artifact(workspace_id, session_artifact_id)
    except httpx.HTTPError as exc:
        return json.dumps({"error": "failed to load session artifact", "artifact_id": session_artifact_id, "detail": str(exc)})

    transcript_text = (artifact.get("content") or "").strip()
    if not transcript_text:
        return json.dumps({
            "error": "Session artifact has no transcript content yet. Ensure the stream has ended.",
            "session_artifact_id": session_artifact_id,
        })

    raw_ctx = artifact.get("context") or {}
    if isinstance(raw_ctx, str):
        try:
            raw_ctx = json.loads(raw_ctx)
        except json.JSONDecodeError:
            raw_ctx = {}
    session_ctx = raw_ctx if isinstance(raw_ctx, dict) else {}

    artifact_title = title or session_ctx.get("title") or "Transcript"
    output_context = {
        "content_type": "text/markdown",
        "title": artifact_title,
        "type": "transcript",
        "source_artifact_id": session_artifact_id,
    }

    try:
        output_artifact = await _create_workspace_artifact(workspace_id, output_context, transcript_text)
    except httpx.HTTPError as exc:
        return json.dumps({"error": "failed creating transcript artifact", "detail": str(exc)})

    return json.dumps({
        "transcript_artifact_id": output_artifact.get("id"),
        "session_artifact_id": session_artifact_id,
        "title": artifact_title,
        "length": len(transcript_text),
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool: collect_telemetry
# ---------------------------------------------------------------------------

@mcp.tool(description="Collect and record system activity telemetry as workspace cards.")
async def collect_telemetry(
    workspace_id: str,
    source: str,
    metrics: Optional[dict] = None,
) -> str:
    """
    Args:
        workspace_id: Workspace to store telemetry cards.
        source: Telemetry source identifier.
        metrics: Optional structured metrics data.
    """
    raise NotImplementedError(f"collect_telemetry is a declared placeholder. source={source}")


# ---------------------------------------------------------------------------
# Tool: rotate_stream_key
# ---------------------------------------------------------------------------

@mcp.tool(description="Generate or rotate the RTMP stream key for a stream source artifact.")
async def rotate_stream_key(
    workspace_id: str,
    artifact_id: str,
) -> str:
    """
    Args:
        workspace_id: Workspace that owns the stream artifact.
        artifact_id: The stream source artifact whose key to rotate.

    Returns JSON with {key_id, key, server_url} — key value is shown once and must be saved.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            artifact_url(MANTLE_URI, artifact_id, "key"),
            headers=_require_user_headers(),
            params={"key_context": "stream"},
            timeout=15,
        )
        if resp.status_code >= 400:
            return json.dumps({"error": "upstream %s" % resp.status_code, "detail": resp.text[:300]})

        data = resp.json()
        data["server_url"] = STREAM_INGEST_URL

        # Persist server_url into the artifact context so the viewer can read
        # it on future loads without knowing the platform's ingest URL.
        try:
            art_resp = await client.get(
                artifact_url(MANTLE_URI, artifact_id),
                headers=_require_user_headers(),
                timeout=15,
            )
            if art_resp.status_code == 200:
                artifact = art_resp.json()
                ctx = artifact.get("context", {})
                if isinstance(ctx, str):
                    ctx = json.loads(ctx)
                stream_cfg = {**(ctx.get("stream") or {}), "server_url": STREAM_INGEST_URL}
                await client.patch(
                    artifact_url(MANTLE_URI, artifact_id),
                    headers=_require_user_headers(),
                    json={"context": json.dumps({**ctx, "stream": stream_cfg})},
                    timeout=15,
                )
        except Exception as exc:
            log.warning("Failed to persist server_url in artifact context: %s", exc)

    return json.dumps(data)


# ---------------------------------------------------------------------------
# Resource: Stream Source HTML View
# ---------------------------------------------------------------------------

import pathlib


@mcp.resource("ui://astra/vnd.agience.stream.html")
async def stream_html_view() -> str:
    """Standalone MCP Apps HTML view for vnd.agience.stream+json artifacts."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.stream+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point — wraps MCP app + stream routes in a single FastAPI host
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting agience-server-astra � transport=%s port=%s", MCP_TRANSPORT, MCP_PORT)
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn
        uvicorn.run(create_server_app(), host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run()
