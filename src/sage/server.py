"""
agience-server-sage — MCP Server
=====================================
Sage (knowledge — docs, retrieval, memory): discovering sources, gathering evidence,
ranking relevance, evidence-backed synthesis, hybrid search, and structured extraction.
A tekton — the knowledge condensor in the chorus (the tekton standard library); its tools are organons, invoked by condensation (OPERATOR-ARCHITECTURE §12).

Sage is the knowledge persona of chorus (operators, by domain). Interior server —
works entirely within the platform (no external credentials needed beyond the
Agience API key).

Tools
-----
  search                    - Hybrid search across workspaces and collections
  get_artifact                  - Fetch a card by ID
  browse_collections        - List and explore committed collections
  search_azure              - Tombstone: raises; Azure Search is a hosted, model-backed connector,
                              out of scope under the no-models rule
  index_to_azure            - Tombstone: raises; same no-models rule as search_azure
  research                  - Multi-step grounded research: op.retrieve → deepen hits → cited digest
  cite_sources              - Provenance receipt: per-card sha256/length/title, unresolved reported
  ask                       - Grounded Q&A: op.retrieve + cited cards → {answer, citations, refusal}
  extract_information       - Deterministic field extraction (JSON keys / 'field: value' lines)
  generate_meeting_insights - Stub: raises; NL synthesis is non-compact, the LLM leg is barred, and
                              keyword heuristics would fabricate structure

Auth (Phase C)
--------------
  Service identity loaded once by the chorus host (chorus.private.pem).
  Persona signs its own platform JWTs via _auth.sign_self_jwt() — no token
  exchange with Origin, no PLATFORM_INTERNAL_SECRET. Inbound delegation JWTs
  verified against Mantle's inline JWKS in the platform authority manifest.

  MANTLE_URI ⬩ Base URI of the Mantle backend

Transport
---------
  MCP_TRANSPORT=streamable-http
  MCP_HOST=0.0.0.0
  MCP_PORT=8084
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# No azure_search adapter: Azure Cognitive Search is semantic-search-as-a-service
# backed by hosted trained models (no-models rule).

log = logging.getLogger("agience-server-sage")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s - %(name)s - %(message)s")

MANTLE_URI: str = os.getenv("MANTLE_URI", "http://localhost:8081").rstrip("/")
SAGE_CLIENT_ID: str = "agience-server-sage"
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8084"))


# ---------------------------------------------------------------------------
# Shared authentication infrastructure (AgienceServerAuth)
# ---------------------------------------------------------------------------

from prism.trust import (
    ServerAuth as _AgienceServerAuth,
    MissingDelegationError,
)

# The retrieval organon (op.retrieve) grounds over mantle FTS. op.retrieve is sage's own
# capability (sole owner); the implementation lives with this persona (`sage/retrieval.py`) and is
# imported directly — persona-local code, drawing on the shared substrate in `crystal`. No shim
# injection.
import retrieval as _op_retrieve  # noqa: E402 — persona-local organon (op.retrieve)

_auth = _AgienceServerAuth(SAGE_CLIENT_ID, MANTLE_URI)


async def _headers() -> dict[str, str]:
    """Headers with Sage's own platform JWT (signed via the chorus service identity)."""
    return _auth.headers()


# Sage carries no `_user_headers()` fallback — same reasoning as astra and seraph: a "fall back to
# Sage's platform JWT" branch would fire exactly when verification or minting fails (the
# middleware stores an empty token), escalating a caller-chosen resource id to platform authority
# on the very requests that failed authentication. An unused authorization helper is still a
# loaded gun.


def _require_user_headers() -> dict[str, str]:
    """Headers carrying the caller's verified delegation JWT — fails closed.

    Tools acting on caller-supplied resource ids use this helper, never
    ``_headers``/``_user_headers`` (which fall back to the persona's platform
    JWT — see tests/test_no_service_identity_on_caller_ids.py).
    """
    return _auth.require_user_headers()


def _delegation_token() -> str:
    """The raw verified delegation JWT for this request, or "" when absent."""
    return _auth.request_user_token.get("")


def create_server_app():
    """Return the Sage ASGI app with verified middleware and startup hooks."""
    return _auth.create_app(mcp)


async def server_startup() -> None:
    """Run Sage startup tasks. Trust map is on disk in Phase C; nothing to fetch."""
    await _auth.startup()
    # Starts the signal-native op.retrieve provider (ember runners reach it over the ground plane,
    # backed by the `content_search` BM25 tekton) only if a carrier is wired. Guarded/no-op by
    # default: the cross-process carrier + corpus store is a separate gated deploy step, so sage
    # boots dark here and the HTTP op.retrieve (`retrieval.py`) stays the live grounding path.
    try:
        import reach_provider as _reach_provider   # sage-local
        _rc = _reach_provider.serve_retrieve_if_configured()
        log.info("sage: op.retrieve reach provider %s",
                 "LIVE on the ground plane" if _rc is not None
                 else "dark (no carrier wired — gated follow-up)")
    except Exception as exc:  # provider wiring must never break startup
        log.info("sage: op.retrieve reach provider not started (%s)", type(exc).__name__)


# ---------------------------------------------------------------------------
# Self-registration (GENESIS-NEXT §B1.10): this persona owns its registration.
# The host holds no roster — it calls each persona's register(). PERSONA is the
# single source of truth for {name, role, endpoint}; register() self-registers
# with Mantle (server record) + the crystal gateway (owned types).
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "sage",
    "kind": "tekton",
    "role": "Research & Retrieval",
    "endpoint": "/sage/mcp",
    "client_id": SAGE_CLIENT_ID,
}

# No shim organons: op.retrieve is sage's own, imported locally above (`import retrieval`).


def register(register_fn) -> bool:
    """Self-register this persona (server + owned types). True on success."""
    return register_fn(
        name=PERSONA["name"],
        role=PERSONA["role"],
        endpoint=PERSONA["endpoint"],
        client_id=PERSONA["client_id"],
        server_file=__file__,
    )


mcp = FastMCP(
    "agience-server-sage",
    instructions=(
        "You are connected to Sage, the Agience research and retrieval server. "
        "Use Sage to search across workspaces and collections, fetch cards by ID, "
        "synthesise evidence-backed answers, and project cards into external search indexes."
    ),
)
from mantle.clients.artifact_helpers import artifact_url, register_types_manifest
register_types_manifest(mcp, "sage", __file__)

# ---------------------------------------------------------------------------
# Tool: corpus_search - the ranked path, in process, authorized per candidate
# ---------------------------------------------------------------------------
#
# `search` below asks mantle, which narrows on the blind-token SSE index. On a node whose corpus was
# seeded straight into the lattice that index holds nothing, so the question comes back empty however
# good the ranking is. This tool asks the corpus directly and orders it by what the question is
# ABOUT: `content_search.search` retrieves lexically, `ranking.rank` re-orders by measured reach
# standardised against the query's own null, and `ranking.cut_for` derives how many of them are the
# answer. Scored on 36 labelled questions over the live corpus, that path puts the subject first on
# 32 and inside the answer on all 36.
#
# EVERY ROW IS AUTHORIZED, one at a time. `check_access` is the tree's per-artifact primitive —
# "direct grant first, then walk origin edges upward checking propagated grants at each parent" —
# and it is the same check an ordinary artifact read goes through. Asking it per candidate is what
# lets this run on a collection the light cone cannot materialise: `stage.0.lexicon` holds 1,841,335
# members, `LightConeResolver.resolve` raises `EdgesTruncated` above its 1,000,000-edge cap, and
# `check_access` answers for an artifact inside it in three to eight milliseconds.
#
# It fails closed on an unauthenticated call, matching `_require_user_headers`: a tool acting on a
# caller's behalf never falls back to the persona's own identity, or it would answer with sage's
# reach instead of the caller's.

_CORPUS_STORE = None


def _corpus():
    """The lattice this node holds, opened once. `None` when there is none to open.

    Resolved from the environment (`EMBER_SQLITE_DIR`), which is what every service on a node is
    started with, so this reads the same store mantle and ember do rather than a second copy.
    """
    global _CORPUS_STORE
    if _CORPUS_STORE is None:
        from mantle.shard.local_store import open_store
        try:
            _CORPUS_STORE = open_store(ensure_schema=False)
        except Exception:
            # A persona can run on a node that holds no lattice — the store refuses rather than
            # creating one, which is right. The tool then reports an absence instead of raising:
            # "this node has no corpus" is an answer, and a traceback through an MCP call is not.
            return None
    return _CORPUS_STORE


@mcp.tool(description=(
    "Search this node's corpus and rank by what the question is about, not by term overlap. "
    "Returns only artifacts the caller may read."))
async def corpus_search(query: str, limit: int = 10) -> str:
    import json as _json

    caller = _auth.get_delegation_user_id()
    if not caller or caller == "anonymous":
        return _json.dumps({
            "error": "unauthenticated",
            "detail": "corpus_search answers under the caller's own grants; this request carries "
                      "no verified delegation, and answering with the persona's reach would "
                      "report sage's access as yours."})

    try:
        from sage import content_search as _cs
    except ImportError:
        import content_search as _cs                      # (sage/ on path)
    from mantle.search import ranking as _ranking
    import mantle.services.dependencies as _deps

    store = _corpus()
    if store is None:
        return _json.dumps({
            "error": "no_corpus",
            "detail": "this node holds no lattice to search; corpus_search answers from the "
                      "node's own store and there is none here."})
    pool = _cs.search(store, query, k=_cs._POOL) or []
    if not pool:
        return "No results found."
    ranked, account, _reached = _ranking.rank(pool, query, store)
    cut = _ranking.cut_for(ranked, query=query, store=store)

    db = next(_deps.get_store_db())
    auth = _deps.AuthContext(principal_id=caller, principal_type="user", user_id=caller)

    lines, shown, refused = [], 0, 0
    for aid, _ct, score in ranked[:cut]:
        try:
            _deps.check_access(auth, aid, "read", db)
        except Exception:
            refused += 1
            continue                                      # not the caller's to see
        art = store.artifacts.get_artifact(aid)
        title = (art or {}).get("title") or aid
        lines.append("[%s] %s  (%+.2f)" % (aid, title, -float(score)))
        shown += 1
        if shown >= max(1, int(limit)):
            break

    if not lines:
        return ("No results you may read. %d candidate(s) matched and were refused."
                % refused) if refused else "No results found."
    footer = "\n\n%d shown of %d in the answer%s; ordering=%s" % (
        shown, cut, (", %d refused" % refused) if refused else "", account.get("reach"))
    return "\n".join(lines) + footer


# ---------------------------------------------------------------------------
# Tool: search - delegates to platform /search
# ---------------------------------------------------------------------------

@mcp.tool(description="Lexical BM25 search across workspaces and collections.")
async def search(
    query: str,
    workspace_id: Optional[str] = None,
    limit: int = 10,
) -> str:
    # This targeted `POST /search/query`, and mantle has no `search` plane. The comment
    # here cited `mantle/routers/search_router.py:24-31` by line number — that FILE no longer
    # exists; mantle's routers are artifacts, events, git, grants, mcp, oci and system.
    # A citation with line numbers reads as verified and this one had simply gone stale.
    #
    # The primitive is `POST /artifacts/recall` with `candidates: true` — the narrowed,
    # unranked, unhydrated set, which is what this tool wants. `scope` is unchanged: a list of
    # container ids, and `workspace_id` still maps onto it.
    payload: dict[str, Any] = {"query_text": query, "candidates": True}
    if workspace_id:
        payload["scope"] = [workspace_id]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{MANTLE_URI}/artifacts/recall",
            # Fails closed: mantle's own docstring says "Auth = the calling user; candidates are
            # filtered to that user's light-cone inside the accessor" — so a platform JWT here would
            # hand back a light-cone that is not the caller's.
            headers=_require_user_headers(),
            json=payload,
            timeout=30,
        )
    if resp.status_code >= 400:
        return json.dumps({"error": "upstream %s" % resp.status_code, "detail": resp.text[:300]})

    # `limit` is applied client-side below, deliberately: it is not `candidate_budget`, which is how
    # many candidates the ranker considers (server default 200) rather than how many rows to
    # display, and conflating them would quietly change ranking quality when a caller asked for
    # fewer lines.
    #
    # The response is `accessor.candidates(...)` (`search_router.py:83`); the `id`/`title`/
    # `content_type` shape the loop below renders has not been exercised against a live encrypted
    # index (`build_sse_search_accessor` returns 503 without Oracle/S3/the lattice), so the
    # rendering below is not asserted against a real response — inventing the field names to assert
    # against would be fitting rather than verifying. Verifying it needs a live index, which this
    # environment does not have.
    results = resp.json()
    if not results:
        return "No results found."
    lines = []
    for r in results[:limit]:
        lines.append(f"[{r.get('id')}] {r.get('title', '(untitled)')} � {r.get('content_type', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_artifact
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tool: web_retrieve - fetch a web page / paper, extract text, persist as an
# artifact so it enters the corpus (indexed, retrievable). The intake side of
# the knowledge flywheel: external knowledge -> owned artifact -> grounding.
# ---------------------------------------------------------------------------
from web_extract import html_to_text, looks_like_html


@mcp.tool(description="Fetch a web page or paper by URL, extract its readable text (script, style, "
                     "noscript, head, nav, footer, svg, template and aside are dropped), and persist it as a "
                     "text/markdown artifact in the given workspace (stamped with operator "
                     "provenance and the source URL). Returns the new artifact id.")
async def web_retrieve(url: str, workspace_id: str, title: Optional[str] = None) -> str:
    if not url.startswith(("http://", "https://")):
        return "Error: url must be http(s)."
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "Agience/1.0 (Sage web_retrieve)"})
        except Exception as e:
            return f"Error fetching {url}: {type(e).__name__}"
    if resp.status_code >= 400:
        return json.dumps({"error": "fetch returned %s" % resp.status_code})
    ctype = resp.headers.get("content-type", "").lower()
    body = resp.text
    text = html_to_text(body) if looks_like_html(ctype, body) else body
    text = text[:200000]
    if not text.strip():
        return "Error: no extractable text at that URL."
    import json as _json
    context = {"content_type": "text/markdown", "title": title or url,
               "operator": "sage:web_retrieve", "source_url": url}
    async with httpx.AsyncClient() as client:
        cr = await client.post(
            f"{MANTLE_URI}/artifacts", headers=_require_user_headers(),
            json={"container_id": workspace_id, "content": text, "content_type": "text/markdown",
                  "context": _json.dumps(context)}, timeout=30)
    if cr.status_code >= 400:
        return f"Fetched {len(text)} chars but persist failed: {cr.status_code} � {cr.text[:200]}"
    art = cr.json() if cr.text else {}
    return (f"Retrieved {len(text)} chars from {url}; saved as artifact "
            f"{art.get('id')} (operator=sage:web_retrieve).")


@mcp.tool(description="Fetch a card by ID. Returns full card content and context.")
async def get_artifact(artifact_id: str, workspace_id: Optional[str] = None) -> str:
    # The id is encoded as ONE path segment. This corpus's ids carry characters that mean
    # something in a URL — every canon id has a `#`, and `canon:best-practices#intro` interpolated
    # into an f-string becomes the path `/artifacts/canon:best-practices` with `#intro` split off
    # as a fragment the server never receives. No artifact exists at the truncated id, so the
    # request 404s — every canon id, and only canon ids. `corpus_search` returns exactly these, so
    # search and fetch have to agree about what one is.
    #
    # `workspace_id` chose between two identical branches and is unused by the route; it stays in
    # the signature because callers pass it.
    url = artifact_url(MANTLE_URI, artifact_id)
    async with httpx.AsyncClient() as client:
        # User-data access -> delegation headers (rooted to the caller), not the persona's bare
        # service identity, so Mantle applies the caller's own grants. Fails closed:
        # `_require_user_headers()` raises rather than falling back when no delegation is verified.
        resp = await client.get(url, headers=_require_user_headers(), timeout=15)
    if resp.status_code >= 400:
        return json.dumps({"error": "upstream %s" % resp.status_code, "detail": resp.text[:300]})
    return json.dumps(resp.json(), indent=2)


# ---------------------------------------------------------------------------
# Tool: browse_collections
# ---------------------------------------------------------------------------

@mcp.tool(description="List committed collections accessible to the current user.")
async def browse_collections(limit: int = 20) -> str:
    """List the collections this caller can reach.

    There is no collections router in mantle. A collection is an artifact with child edges
    (`CreateArtifactRequest`'s own docstring: "A collection is just an artifact with child edges,
    so there's one create path"), so a separate collections endpoint would be a second answer to a
    question the artifact surface already answers. The live equivalent is `GET /artifacts/visible`.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{MANTLE_URI}/artifacts/visible",
            headers=_require_user_headers(),
            timeout=15,
        )
    if resp.status_code >= 400:
        return json.dumps({"error": "upstream %s" % resp.status_code, "detail": resp.text[:300]})
    _body = resp.json()
    #: `/artifacts/visible` returns `{items, total, has_more}` since 2026-08-25 (P-6/P-7).
    #: The bare list is still read so a client pointed at an older node keeps working.
    cols = _body.get("items", []) if isinstance(_body, dict) else _body
    if not cols:
        return "No collections found."
    # `limit` is applied here, client-side, not sent: `/artifacts/visible` declares only
    # `content_type` and `action` (`artifacts_router.py:297-311`), and FastAPI ignores an undeclared
    # query param, so a `params={"limit": limit}` sent to it would be silently dropped.
    shown = cols[:limit] if isinstance(cols, list) else cols
    body = "\n".join(f"[{c.get('id')}] {c.get('name', '(unnamed)')}" for c in shown)
    if isinstance(cols, list) and len(cols) > limit:
        # Say what was dropped. A truncated list that reads as complete is how a partial answer becomes
        # a decision — the same rule the gates here follow about never capping silently.
        body += "\n… %d more not shown (limit=%d)" % (len(cols) - limit, limit)
    return body


# ---------------------------------------------------------------------------
# Tool: search_azure — tombstone: raises under the no-models rule
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Raises. No-models rule: retrieval runs on the platform's own index. "
        "Use the `search` tool."
    )
)
async def search_azure(
    query: str,
    connection: dict,
    top: int = 10,
) -> str:
    """
    Args:
        query: Search query string.
        connection: Unused; retained for signature stability.
        top: Max results to return.
    """
    raise NotImplementedError(
        "search_azure: no-models rule; use the platform's own search tool."
    )


# ---------------------------------------------------------------------------
# Tool: index_to_azure — tombstone: raises under the no-models rule
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Raises. No-models rule: source-of-truth and the retrieval index both "
        "stay in the platform."
    )
)
async def index_to_azure(
    workspace_id: str,
    connection: dict,
    artifact_ids: Optional[list[str]] = None,
) -> str:
    """
    Args:
        workspace_id: Source workspace.
        connection: Unused; retained for signature stability.
        artifact_ids: Optional list of specific card IDs (unused; retained for signature stability).
    """
    raise NotImplementedError(
        "index_to_azure: no-models rule; the platform index is the retrieval surface."
    )


# ---------------------------------------------------------------------------
# Grounded Q&A + research (retrieve → extract → cite-or-refuse; no models)
# ---------------------------------------------------------------------------

def _grounded_extract(evidence: list[dict]) -> tuple[str, list[str]]:
    """Assemble the grounded answer body from evidence, under the retrieval
    organon's declared finite-context budget (PER_DOC_CHAR_CAP /
    GROUNDING_CHAR_BUDGET — no new constants). Returns (text, cited ids)."""
    blocks: list[str] = []
    cited: list[str] = []
    spent = 0
    for i, e in enumerate(evidence, 1):
        head = (e.get("title") or "").strip() or f"artifact {str(e.get('id', ''))[:8]}"
        body = (e.get("content") or "").strip()[: _op_retrieve.PER_DOC_CHAR_CAP]
        block = f"[{i}] {head}\n{body}".strip()
        if spent and spent + len(block) > _op_retrieve.GROUNDING_CHAR_BUDGET:
            break
        blocks.append(block)
        spent += len(block)
        if e.get("id"):
            cited.append(str(e["id"]))
    return "\n\n".join(blocks), cited


async def _fetch_artifact_json(client: httpx.AsyncClient, headers: dict, aid: str,
                               ws: Optional[str] = None) -> Optional[dict]:
    """GET one artifact with the supplied headers — auth is decided by the caller, never in here.

    `ws` is accepted and ignored: a workspace-scoped path (`/workspaces/{ws}/artifacts/{aid}`) is
    not a mounted route in this mantle. An artifact is addressed by its own id and access is the
    grant light-cone, so there is no second path to choose between; keeping the parameter avoids
    touching the callers, and a caller still passing it is not wrong, just uninformative. Left as an
    explicit `del` rather than dropped from the signature so the next reader sees that the argument
    is deliberately inert rather than accidentally unused.
    """
    del ws
    url = artifact_url(MANTLE_URI, aid)
    try:
        resp = await client.get(url, headers=headers, timeout=30)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


@mcp.tool(
    description=(
        "Multi-step grounded research: (1) search the corpus via the retrieval organon "
        "(mantle FTS under the caller's grants), (2) deepen each hit by fetching its "
        "full content, (3) assemble a budgeted evidence digest with citations. Returns "
        "{answer, citations, refusal, steps} — cited or refused, never fabricated."
    )
)
async def research(query: str, workspace_id: Optional[str] = None) -> str:
    steps: list[str] = []
    token = _delegation_token()
    if not token:
        # Computed: the corpus is searched under the caller's own grants only; with no verified
        # delegation there is nothing to search as, and the missing leg is named in the response.
        return json.dumps({
            "answer": None, "citations": [], "steps": steps,
            "refusal": {
                "reason": "no verified user delegation on this request — corpus "
                          "search runs only under the caller's own grants",
                "query": query[:500],
            },
        }, indent=2)

    # Step 1 — search (op.retrieve: FTS, committed state, budgeted top-k).
    if workspace_id:
        # Honest scope note: op.retrieve does not take a container scope — the
        # search runs over the caller's full light-cone, not just this workspace.
        steps.append(
            f"note: workspace scoping ({workspace_id}) is not plumbed through "
            "op.retrieve — searched the caller's full light-cone"
        )
    hits = _op_retrieve.retrieve(query, token, MANTLE_URI)
    steps.append(f"op.retrieve: {len(hits)} hit(s) for the query")
    if not hits:
        return json.dumps({
            "answer": None, "citations": [], "steps": steps,
            "refusal": {
                "reason": "op.retrieve returned no evidence for this query (no "
                          "committed artifact matched, or mantle search is "
                          "unavailable — the organon is fail-soft and does not "
                          "distinguish the two)",
                "query": query[:500],
                "evidence_count": 0,
            },
        }, indent=2)

    # Step 2 — deepen: search hits carry truncated content; fetch each hit's
    # full artifact under the caller's delegation.
    headers = _require_user_headers()
    deepened = 0
    async with httpx.AsyncClient() as client:
        for h in hits:
            aid = h.get("id")
            if not aid:
                continue
            art = await _fetch_artifact_json(client, headers, aid)
            if art and art.get("content"):
                h["content"] = art["content"]
                deepened += 1
    steps.append(f"deepened {deepened}/{len(hits)} hit(s) to full content")

    # Step 3 — assemble the digest under the organon's grounding budget.
    extract, cited = _grounded_extract(hits)
    steps.append(f"digest assembled from {len(cited)} source(s)")
    return json.dumps({
        "answer": "Evidence digest (extracts, cited by artifact id):\n\n" + extract,
        "citations": cited,
        "steps": steps,
        "refusal": None,
    }, indent=2)


@mcp.tool(
    description=(
        "Produce a provenance receipt for a synthesised answer: for each cited card, "
        "fetch it under the caller's delegation and record id, title, content type, "
        "content length and content sha256 (the content-address — agreement computed). "
        "Missing cards are reported as unresolved, never silently dropped."
    )
)
async def cite_sources(artifact_ids: list[str], answer: str) -> str:
    if not artifact_ids:
        return json.dumps({"error": "artifact_ids is empty — nothing to cite"})
    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": str(exc)})

    import hashlib
    sources: list[dict[str, Any]] = []
    unresolved: list[str] = []
    async with httpx.AsyncClient() as client:
        for aid in artifact_ids:
            art = await _fetch_artifact_json(client, headers, aid)
            if art is None:
                unresolved.append(aid)
                continue
            content = art.get("content") or ""
            ctx = art.get("context") or {}
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except json.JSONDecodeError:
                    ctx = {}
            sources.append({
                "artifact_id": art.get("id") or aid,
                "title": ctx.get("title") or art.get("title") or "",
                "content_type": art.get("content_type") or "",
                "content_length": len(content),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            })
    return json.dumps({
        "answer_sha256": hashlib.sha256((answer or "").encode("utf-8")).hexdigest(),
        "sources": sources,
        "unresolved": unresolved,
        "complete": not unresolved,
    }, indent=2)


@mcp.tool(
    description=(
        "Ask a question with optional card context: grounds the question via the "
        "retrieval organon (mantle FTS under the caller's grants) and/or the given "
        "cards, and returns {answer, citations, refusal} — an evidence extract with "
        "citations, or an honest computed refusal. No models."
    )
)
async def ask(
    question: str,
    workspace_id: Optional[str] = None,
    artifact_ids: Optional[list[str]] = None,
) -> str:
    """
    Args:
        question: Natural language question.
        workspace_id: Optional workspace to scope cited-card fetches.
        artifact_ids: Optional list of card IDs to use as grounding context.
    """
    findings: list[str] = []
    evidence: list[dict] = []
    token = _delegation_token()

    # Explicit grounding cards — caller-supplied ids ⇒ caller's delegation only.
    if artifact_ids:
        try:
            headers = _require_user_headers()
        except MissingDelegationError as exc:
            findings.append(f"cited-card fetch refused: {exc}")
        else:
            async with httpx.AsyncClient() as client:
                for aid in artifact_ids:
                    art = await _fetch_artifact_json(client, headers, aid, workspace_id)
                    if art is None:
                        findings.append(f"card {aid}: not fetchable under the caller's grants")
                        continue
                    ctx = art.get("context") or {}
                    if isinstance(ctx, str):
                        try:
                            ctx = json.loads(ctx)
                        except json.JSONDecodeError:
                            ctx = {}
                    evidence.append({
                        "id": art.get("id") or aid,
                        "title": ctx.get("title") or art.get("title") or "",
                        "content": art.get("content") or "",
                    })

    # Corpus grounding via op.retrieve.
    if token:
        hits = _op_retrieve.retrieve(question, token, MANTLE_URI)
        seen = {e["id"] for e in evidence}
        evidence.extend(h for h in hits if h.get("id") not in seen)
        if not hits:
            findings.append(
                "op.retrieve returned no evidence (no committed artifact matched, "
                "or mantle search is unavailable — the organon is fail-soft and "
                "does not distinguish the two)"
            )
    else:
        findings.append(
            "op.retrieve skipped: no verified user delegation on this request — "
            "corpus search runs only under the caller's own grants"
        )

    if not evidence:
        return json.dumps({
            "answer": None, "citations": [],
            "refusal": {
                "reason": "no grounded evidence exists for this question",
                "question": question[:500],
                "evidence_count": 0,
                "findings": findings,
            },
        }, indent=2)

    extract, cited = _grounded_extract(evidence)
    return json.dumps({
        "answer": "Grounded evidence (extracts, cited by artifact id):\n\n" + extract,
        "citations": cited,
        "refusal": None,
        "findings": findings,
    }, indent=2)


# Lexical field matcher: a JSON-Schema property name is matched against
# "key: value" / "key = value" lines (optionally bulleted or bolded), with
# underscores/hyphens/spaces in the name treated as interchangeable.
import re as _re


def _field_pattern(name: str) -> "_re.Pattern[str]":
    key = r"[\s_\-]+".join(_re.escape(part) for part in _re.split(r"[\s_\-]+", name) if part)
    return _re.compile(
        rf"^\s*(?:[-*]\s*)?(?:\*\*)?{key}(?:\*\*)?\s*[:=]\s*(.+?)\s*$",
        _re.IGNORECASE | _re.MULTILINE,
    )


@mcp.tool(
    description=(
        "Extract structured fields from a card's content, deterministically: JSON "
        "content is read by key; text content is scanned for 'field: value' lines "
        "matching the schema's property names. Fields that cannot be grounded in the "
        "content are returned in 'missing' — never guessed. No models."
    )
)
async def extract_information(
    artifact_id: str,
    workspace_id: str,
    schema: dict,
) -> str:
    """
    Args:
        artifact_id: ID of the card whose content to parse.
        workspace_id: Workspace the card belongs to.
        schema: JSON Schema describing the fields to extract.
    """
    properties = (schema or {}).get("properties") or {}
    if not properties:
        return json.dumps({"error": "schema has no 'properties' — nothing to extract"})

    # Caller-supplied resource ids ⇒ the caller's own delegation, fail closed.
    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": str(exc)})

    async with httpx.AsyncClient() as client:
        art = await _fetch_artifact_json(client, headers, artifact_id, workspace_id)
    if art is None:
        return json.dumps({"error": f"card {artifact_id} not fetchable under the caller's grants"})

    content = art.get("content") or ""
    extracted: dict[str, Any] = {}
    methods: dict[str, str] = {}

    # Leg 1 — structured content: JSON object keys are read directly.
    doc = None
    try:
        doc = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass
    if isinstance(doc, dict):
        for name in properties:
            if name in doc:
                extracted[name] = doc[name]
                methods[name] = "json-key"

    # Leg 2 — semi-structured text: deterministic 'field: value' line scan.
    for name in properties:
        if name in extracted:
            continue
        m = _field_pattern(name).search(content)
        if m:
            extracted[name] = m.group(1)
            methods[name] = "lexical-line"

    missing = [n for n in properties if n not in extracted]
    required_missing = [n for n in (schema.get("required") or []) if n in missing]
    result: dict[str, Any] = {
        "artifact_id": art.get("id") or artifact_id,
        "extracted": extracted,
        "methods": methods,
        "missing": missing,
    }
    if not extracted:
        # Computed refusal: nothing in the content grounds any requested field.
        result["refusal"] = {
            "reason": "no requested field is grounded in the card's content "
                      "(neither as a JSON key nor as a 'field: value' line); "
                      "free-text inference is not performed (no-models rule)",
            "fields_requested": sorted(properties),
        }
    elif required_missing:
        result["incomplete"] = {
            "reason": "required fields not grounded in the content",
            "required_missing": required_missing,
        }
    return json.dumps(result, indent=2, default=str)


@mcp.tool(
    description=(
        "Raises. Meeting summarization awaits a grounded summarization operator; the "
        "model leg is barred by the no-models rule. Use `ask` or `research` against the "
        "transcript card."
    )
)
async def generate_meeting_insights(
    artifact_id: str,
    workspace_id: str,
    format: str = "markdown",
) -> str:
    """
    Args:
        artifact_id: ID of the transcript card to analyse.
        workspace_id: Workspace the card belongs to.
        format: Output format - 'markdown' (default) or 'json'.
    """
    # Summary, action items and coaching are open-ended natural-language synthesis — the
    # non-compact edge of the Koopman boundary, where no deterministic operator exists. The LLM leg
    # is barred (no-models rule), and a keyword/heuristic extractor would force arbitrary structure
    # onto the transcript (word lists deciding what counts as an "action"). Use `ask`/`research` to
    # ground questions against the transcript card instead.
    raise NotImplementedError(
        "generate_meeting_insights awaits a grounded summarization capability — "
        "NL synthesis is non-compact (no deterministic operator), the LLM leg is "
        "barred, and a keyword heuristic would fabricate structure. "
        f"artifact_id={artifact_id!r}"
    )


# ---------------------------------------------------------------------------
# UI Resources
# ---------------------------------------------------------------------------

@mcp.resource("ui://sage/vnd.agience.research.html")
async def research_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.research+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.research+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://sage/vnd.agience.resource.html")
async def resource_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.resource+json.

    The platform adopts Sage's richer overlay for the resource type: facet's
    content-types build auto-derives `resource_uri: ui://sage/vnd.agience.resource.html`
    from this view.html, so it must be served here for McpAppHost to load it.
    """
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.resource+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting agience-server-sage � transport=%s", MCP_TRANSPORT)
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn
        uvicorn.run(create_server_app(), host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run()
