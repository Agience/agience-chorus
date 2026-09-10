"""
agience-server-lumen — MCP Server
====================================
Lumen (wisdom & inference — reasoning, learning, curriculum, consolidation,
illumination): synthesis, coordination, evaluation, training feedback.
A tekton — the wisdom/inference condensor in the chorus (the tekton standard
library); its tools are organons, invoked by condensation
(OPERATOR-ARCHITECTURE §12).

Lumen is the wisdom/inference tekton of chorus (a tekton is a chorus
member — the craftsman, the operators of one domain). It handles the
reasoning layer — synthesizing information from multiple sources,
coordinating multi-step workflows, evaluating outputs, and collecting
training feedback. It is the orchestration engine that ties retrieval,
analysis, and action into coherent results.

Pipeline position: Reasoning & workflow execution.

Tools
-----
  synthesize             — Grounded synthesis: retrieve (op.retrieve, mantle FTS) →
                            reason (op.reason where the input is quantitative) →
                            respond {answer, citations, refusal} — cited or refused
  run_workflow           — Execute a defined multi-step workflow
  execute_transform      — Dispatch a Transform artifact by its run.type (mcp-tool/transform-ref/workflow)
  chain_tasks            — Chain MCP tool calls sequentially via /artifacts/{server}/op/invoke
  schedule_action        — Stub: awaits a live scheduler/executor (nothing fires deferred actions)
  evaluate_output        — Stub: awaits a grounded verifier (a judge model would grade from inside; overlap ≠ quality)
  submit_feedback        — Record a human judgment as an append-only feedback artifact
  install_package        — Install a package artifact's contents and server deps into a workspace
  export_package         — Populate a package manifest's contents from workspace artifacts

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
  MCP_PORT=8088
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from prism.trust import (
    ServerAuth as _AgienceServerAuth,
    MissingDelegationError,
)

# op.reason is lumen's own organon — imported directly (persona-local; shared substrate lives in
# `crystal`).
import agience_chorus.lumen.reasoning as _op_reason  # noqa: E402 — persona-local organon (op.reason)

# Lumen never loads sage's module in-process. The retrieval call is a reach to sage's served
# `op.retrieve` (`_reach_retrieve`, below), inactive by default with an honest empty degrade — lumen
# stays deployable without sage's source on disk beside it, which is what persona isolation requires.

# ── the grounding budget: a wire constant, duplicated by value and never imported ──────────────────────
# These env vars are named `LUMEN_*` because the budget is lumen's — the finite context window of
# lumen's own observer. sage's `retrieval.py:34-35` reads the same env var names with the same
# fallback defaults, so the two personas cannot disagree at runtime without disagreeing on the env
# var itself: the env var is the single source, and only the fallback default is duplicated by value,
# identically, in both places (the pattern `ember/person.py::_USER_NS` sets for a value that must
# agree across a boundary that must not be imported). sage trims its own copy of the extract for its
# own purpose; `sage/retrieval.py:98-108` and `_grounded_body` below are near-verbatim today, a
# separate duplication from the budget constants.
GROUNDING_CHAR_BUDGET: int = int(os.getenv("LUMEN_GROUNDING_CHARS", "7000"))
PER_DOC_CHAR_CAP: int = int(os.getenv("LUMEN_GROUNDING_PER_DOC_CHARS", "1400"))

# ── the retrieval reach: dark by default ───────────────────────────────────────────────────────────────
# A host wires this by setting `server._RETRIEVE_REACH` to a callable `(query, token) -> [evidence dicts]`
# — normally one that places a need on `op.retrieve` over the ground plane (`sage.reach_provider`
# serves exactly that capability at `RETRIEVE_CAP`). Unset, the corpus leg does not run and reports
# that; it never fabricates evidence, and it does not depend on sage's file being next to lumen's.
_RETRIEVE_REACH = None

log = logging.getLogger("agience-server-lumen")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s - %(name)s - %(message)s")

MANTLE_URI: str = os.getenv("MANTLE_URI", "http://localhost:8081").rstrip("/")
ORIGIN_URI: str = os.getenv("ORIGIN_URI", "http://localhost:8080").rstrip("/")
#: The gateway. `POST /artifacts/{id}/op/{name}` is served by CRYSTAL, not Mantle — the
#: operation surface relocated there, and `mantle/main.py` states outright that there is no
#: second gateway in front of it. Three call sites below still addressed MANTLE_URI and got a
#: 404; corrected 2026-08-25. The deploy compose already defines CRYSTAL_URI.
CRYSTAL_URI: str = os.getenv("CRYSTAL_URI", "http://localhost:8085").rstrip("/")
LUMEN_CLIENT_ID: str = "agience-server-lumen"
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8088"))

_auth = _AgienceServerAuth(LUMEN_CLIENT_ID, MANTLE_URI)


# ---------------------------------------------------------------------------
# Auth wrappers (delegated to prism.trust.ServerAuth)
# ---------------------------------------------------------------------------


# Lumen has no function that resolves the persona's platform JWT for a caller-chosen resource. Every
# mantle call in this module is reached from an MCP tool with a caller-supplied `workspace_id` or
# `artifact_id`, so it uses the caller's own verified delegation — never the shared
# `chorus.private.pem` platform identity applied to a caller-chosen resource. If a genuinely
# principal-less path appears (one with no caller-supplied resource id, as ophan's Stripe webhook
# has), add an explicit `_platform_request` helper for that path rather than a flag on the
# fail-closed path below — a boolean cannot express "this path is exempt" to the call-graph check in
# `tests/test_no_service_identity_on_caller_ids.py`.


def _get_delegation_user_id() -> str:
    return _auth.get_delegation_user_id()


def _require_user_headers() -> dict[str, str]:
    """Headers carrying the caller's verified delegation JWT — fails closed.

    The only header helper in this module. Raises `MissingDelegationError`
    (`prism/trust/server_auth.py`) rather than falling back to lumen's
    platform JWT — there is no fallback to fall back to (see
    tests/test_no_service_identity_on_caller_ids.py).
    """
    return _auth.require_user_headers()


def _delegation_token() -> str:
    """The raw verified delegation JWT for this request, or "" when absent."""
    return _auth.request_user_token.get("")


mcp = FastMCP(
    "agience-server-lumen",
    instructions=(
        "You are Lumen, the Agience wisdom & inference server. "
        "Use Lumen to synthesize information from multiple sources, "
        "coordinate multi-step workflows, evaluate output quality, "
        "and collect training feedback for continuous improvement."
    ),
)

from mantle.clients.artifact_helpers import artifact_url, register_types_manifest
register_types_manifest(mcp, "lumen", __file__)


# ---------------------------------------------------------------------------
# Tool: synthesize
# ---------------------------------------------------------------------------

def _grounded_extract(evidence: list[dict]) -> tuple[str, list[str]]:
    """Assemble the grounded answer body from evidence, under the organon's budget.

    Walks evidence in rank order, caps each extract at the retrieval organon's
    PER_DOC_CHAR_CAP and stops at GROUNDING_CHAR_BUDGET — the same finite-context
    budget op.retrieve declares (no new constants here). Returns (text, cited ids).
    """
    blocks: list[str] = []
    cited: list[str] = []
    spent = 0
    for i, e in enumerate(evidence, 1):
        head = (e.get("title") or "").strip() or f"artifact {str(e.get('id', ''))[:8]}"
        body = (e.get("content") or "").strip()[:PER_DOC_CHAR_CAP]
        block = f"[{i}] {head}\n{body}".strip()
        if spent and spent + len(block) > GROUNDING_CHAR_BUDGET:
            break
        blocks.append(block)
        spent += len(block)
        if e.get("id"):
            cited.append(str(e["id"]))
    return "\n\n".join(blocks), cited


def _reason_over_input(input_text: str, findings: list[str]) -> tuple[Optional[str], Optional[dict]]:
    """The quantitative leg: op.reason over a numeric series pasted in the input.

    Returns (answer_fragment, reasoning_read). The fragment is None when there is
    no series to reason over, or when the regime is NON_COMPACT (that refusal is
    a computed finding, recorded in the read). The reasoning organon (`_op_reason`) is
    injected by the composition adapter; if the deployment did not wire it, that is
    reported as a finding rather than swallowed silently.
    """
    if _op_reason is None:  # the organon was not injected in this deployment
        findings.append(
            "op.reason unavailable in this deployment (organon not wired at assembly); "
            "the quantitative leg did not run"
        )
        return None, None

    try:
        X = _op_reason.parse_trajectory(input_text or "")
    except Exception as exc:
        findings.append(f"op.reason: trajectory parse failed ({type(exc).__name__})")
        return None, None
    if X is None:
        return None, None  # no numeric series to reason over — not a finding

    # The forecast horizon is the operator's own, read off its fitted spectrum
    # (`reasoning._operator_horizon`) rather than a fixed row count, so there is no horizon constant
    # to keep in sync with op.reason's own default; a frame that does not carry a proper compact
    # subspace is refused on the instrument's own terms, below.
    res = _op_reason.ReasoningRouter().reason([X], X, dt=1.0)
    read: dict[str, Any] = {
        "regime": res.regime,
        "complexity": int(res.complexity),
        "series_shape": [int(X.shape[0]), int(X.shape[1])],
    }
    if res.regime != _op_reason.DETERMINISTIC or res.forecast is None:
        # A computed refusal of the quantitative ask: the resolved-rank read
        # found no proper compact subspace — no exact answer exists.
        read["refusal"] = (
            f"non-compact: the resolved-rank read found K_signal={res.complexity} "
            "with no proper compact subspace, so no deterministic forecast exists "
            "for this series"
        )
        return None, read

    # fit_error is NaN by construction on this path (no in-sample error is measured), so the
    # projection is presented as unverified — the same honesty contract as op.reason's own grounding
    # message. The forecast is reported at the length it was computed at: `_operator_horizon` already
    # reads that length off the operator's own spectrum, so clipping it here would reintroduce a fixed
    # horizon constant. `reasoning._grounding_msg` states the identical rule for its own copy of this
    # report.
    import numpy as _np
    fc = _np.asarray(res.forecast)
    rows = "; ".join("[" + ", ".join(f"{v:.4g}" for v in r) + "]" for r in fc)
    read["forecast"] = fc.tolist()
    fragment = (
        "Deterministic-regime read of the numeric series in the input "
        f"(op.reason, K_signal={res.complexity}). UNVERIFIED projection — a linear "
        "operator was fitted and rolled forward with no in-sample error measured — "
        f"next {len(fc)} steps: {rows}"
    )
    return fragment, read


@mcp.tool(
    description=(
        "Synthesize an evidence-backed answer: retrieve→reason→respond. Grounds the "
        "input in the corpus via the retrieval organon (mantle FTS under the caller's "
        "grants) and/or explicitly cited artifacts, runs the deterministic reasoning "
        "organon when the input carries a numeric series, and returns "
        "{answer, citations, refusal} — cited or refused, never fabricated. No models."
    )
)
async def synthesize(
    input: str,
    artifact_ids: Optional[list[str]] = None,
    workspace_id: Optional[str] = None,
    model: str = "gpt-4o-mini",
) -> str:
    """
    Args:
        input: Question, prompt, or synthesis instruction.
        artifact_ids: Optional list of card IDs to use as explicit grounding context.
        workspace_id: Optional workspace for scoping cited-artifact fetches.
        model: Retained for signature stability; ignored — synthesis is grounded.
    """
    _ = model  # synthesis assembles its answer from grounded operators
    findings: list[str] = []   # computed facts about legs that could not run
    evidence: list[dict] = []
    reasoning_read: Optional[dict] = None

    token = _delegation_token()

    # (a) explicit grounding: fetch the cited artifacts. Caller-supplied ids ⇒
    #     the caller's own delegation, fail closed (never the service identity).
    if artifact_ids:
        try:
            headers = _require_user_headers()
        except MissingDelegationError as exc:
            findings.append(f"cited-artifact fetch refused: {exc}")
        else:
            async with httpx.AsyncClient() as client:
                for aid in artifact_ids:
                    url = (
                        artifact_url(MANTLE_URI, aid)
                        if workspace_id
                        else artifact_url(MANTLE_URI, aid)
                    )
                    try:
                        resp = await client.get(url, headers=headers, timeout=30)
                    except Exception as exc:
                        findings.append(f"artifact {aid}: fetch failed ({type(exc).__name__})")
                        continue
                    if resp.status_code != 200:
                        findings.append(f"artifact {aid}: HTTP {resp.status_code}")
                        continue
                    art = resp.json()
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

    # (b) corpus grounding: op.retrieve (mantle FTS) under the caller's grants.
    #     The organon requires the caller's own token — with none, the corpus
    #     leg cannot run and that fact is reported, not papered over.
    if token:
        reach_fn = _RETRIEVE_REACH
        if reach_fn is None:
            # Dark: no reach wired, so the corpus leg cannot run. Reported, never papered over — and
            # deliberately not a fallback to loading sage's module, a coupling §3.3 disallows.
            hits = []
            findings.append(
                "op.retrieve is not reachable from this process (no retrieval reach wired); the corpus "
                "grounding leg did not run and no evidence was invented")
        else:
            try:
                hits = reach_fn(input, token)
            except Exception as exc:  # the capability is fail-soft; belt and braces
                hits = []
                findings.append(f"op.retrieve raised {type(exc).__name__} (grounding skipped)")
            if hits is None:
                hits = []
        seen = {e["id"] for e in evidence}
        added = 0
        for h in hits:
            if h.get("id") in seen:
                continue
            evidence.append(h)
            added += 1
        if not hits:
            findings.append(
                "op.retrieve returned no evidence for this query (no committed "
                "artifact matched, or mantle search is unavailable — the organon "
                "is fail-soft and does not distinguish the two)"
            )
        else:
            findings.append(f"op.retrieve grounded {added} corpus artifact(s)")
    else:
        findings.append(
            "op.retrieve skipped: no verified user delegation on this request — "
            "corpus search runs only under the caller's own grants"
        )

    # (c) the quantitative leg: op.reason over a numeric series in the input.
    fragment, reasoning_read = _reason_over_input(input, findings)

    # (d) respond: grounded answer with citations, or a computed refusal.
    parts: list[str] = []
    citations: list[str] = []
    if fragment:
        parts.append(fragment)
    if evidence:
        extract, cited = _grounded_extract(evidence)
        if extract:
            parts.append(
                "Grounded evidence from the corpus (extracts, cited by artifact id):\n\n"
                + extract
            )
            citations = cited

    result: dict[str, Any] = {
        "answer": "\n\n".join(parts) if parts else None,
        "citations": citations,
        "refusal": None,
        "findings": findings,
    }
    if reasoning_read:
        result["reasoning"] = reasoning_read
    if not parts:
        # A computed refusal: every leg that ran came back empty, and every
        # leg that could not run is named above.
        result["refusal"] = {
            "reason": (
                "no grounded answer exists for this input: "
                f"{len(evidence)} evidence artifact(s), no deterministic read"
                + (
                    f"; quantitative leg refused ({reasoning_read['refusal']})"
                    if reasoning_read and reasoning_read.get("refusal")
                    else ""
                )
            ),
            "query": (input or "")[:500],
            "evidence_count": len(evidence),
            "findings": findings,
        }
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------

_CONDITION_OPS = {
    "eq":  lambda a, b: a == b,
    "ne":  lambda a, b: a != b,
    "gt":  lambda a, b: a is not None and b is not None and a > b,
    "gte": lambda a, b: a is not None and b is not None and a >= b,
    "lt":  lambda a, b: a is not None and b is not None and a < b,
    "lte": lambda a, b: a is not None and b is not None and a <= b,
}


def _evaluate_condition(condition: dict[str, Any], state_context: dict[str, Any]) -> bool:
    """Evaluate a workflow step condition against the State Artifact's context.

    Returns True if the step should execute, False if it should be skipped.
    Supported operators: eq, ne, gt, gte, lt, lte.
    """
    field = condition.get("field")
    if not field:
        return True  # no field specified = always execute

    value = state_context.get(field)

    for op_name, op_fn in _CONDITION_OPS.items():
        if op_name in condition:
            return op_fn(value, condition[op_name])

    # No recognised operator — default to execute
    return True


async def _get_artifact(client: httpx.AsyncClient, workspace_id: str, artifact_id: str) -> dict:
    """Fetch an artifact, trying the workspace first then collection batch lookup.

    LLM connection artifacts live in collections (not workspaces), so a
    workspace-only lookup would 404.  The fallback uses the global
    ``POST /artifacts/batch`` endpoint.
    """
    # Try workspace first (covers most artifacts)
    resp = await client.get(
        artifact_url(MANTLE_URI, artifact_id),
        headers=_require_user_headers(),
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()

    # Fallback: search collections by root_id batch
    batch_resp = await client.post(
        # Was `/collections/artifacts/batch` with `root_ids`, and both were wrong. Mantle serves
        # `/artifacts/batch` — there is no `collections` plane — and the body field is
        # `artifact_ids`. The 404 fell into the `status_code == 200` guard below, so this
        # fallback silently found nothing and the caller saw only the workspace miss.
        f"{MANTLE_URI}/artifacts/batch",
        headers=_require_user_headers(),
        json={"artifact_ids": [artifact_id]},
        timeout=30,
    )
    if batch_resp.status_code == 200:
        body = batch_resp.json()
        # `/artifacts/batch` ANSWERS `{items, total, has_more}` (P-6/P-7, 2026-08-25), not a
        # bare list. This tested `isinstance(results, list)`, so even with the path corrected it
        # would have found nothing and said nothing — the same envelope miss that broke the
        # astra UI. The bare list is still read, so an older node keeps working.
        results = body.get("items", []) if isinstance(body, dict) else (body or [])
        if results:
            return results[0]

    # Neither path found it — raise the original workspace error
    resp.raise_for_status()
    return resp.json()


async def _patch_artifact_context(
    client: httpx.AsyncClient,
    workspace_id: str,
    artifact_id: str,
    context_updates: dict[str, Any],
) -> None:
    """PATCH a workspace artifact's context with the given updates (merged)."""
    # Fetch current context to merge
    artifact = await _get_artifact(client, workspace_id, artifact_id)
    current_ctx = artifact.get("context", {})
    if isinstance(current_ctx, str):
        try:
            current_ctx = json.loads(current_ctx)
        except json.JSONDecodeError:
            current_ctx = {}

    current_ctx.update(context_updates)

    await client.patch(
        artifact_url(MANTLE_URI, artifact_id),
        headers=_require_user_headers(),
        json={"context": current_ctx},
        timeout=30,
    )


async def _dispatch_child_transform(
    client: httpx.AsyncClient,
    workspace_id: str,
    transform_id: str,
    extra_params: dict[str, Any],
) -> dict:
    """Invoke a child Transform via POST /artifacts/{id}/op/invoke.

    This is the canonical artifact-invoke path. The operation_dispatcher
    reads the transform's type.json, enforces grants, and routes to the
    right handler (direct MCP tool for run.type=mcp-tool, or back to
    lumen:execute_transform for workflow/llm/transform-ref types).
    """
    body: dict[str, Any] = {
        "workspace_id": workspace_id,
        "params": extra_params or {},
    }
    resp = await client.post(
        artifact_url(CRYSTAL_URI, transform_id, "op", "invoke"),
        headers=_require_user_headers(),
        json=body,
        timeout=300,  # pipeline steps can be long-running
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Tool: run_workflow
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Execute a multi-step workflow defined by a Transform artifact. "
        "Reads steps from the artifact's run block, evaluates conditions "
        "against a State Artifact, dispatches each step via the platform, "
        "and handles bounded retry loops."
    )
)
async def run_workflow(
    workflow_artifact_id: str,
    workspace_id: Optional[str] = None,
    params: Optional[str] = None,
) -> str:
    """
    Args:
        workflow_artifact_id: ID of the workflow Transform artifact.
        workspace_id: Workspace containing the workflow and state artifacts.
        params: JSON string of additional parameters (must include state_artifact_id).
    """
    # Every failure return in this tool is a JSON object (`{"error": ...}`), matching the JSON
    # `execute_transform` returns on every other branch of its `run.type == "workflow"` delegation —
    # a caller doing `json.loads` gets a parseable result whether the workflow was refused or ran.
    if not workspace_id:
        return json.dumps({"error": "workspace_id is required for workflow execution."})

    extra: dict[str, Any] = {}
    if params:
        try:
            extra = json.loads(params)
        except json.JSONDecodeError:
            return json.dumps({"error": f"params is not valid JSON: {params[:200]}"})

    state_artifact_id = extra.get("state_artifact_id")

    async with httpx.AsyncClient() as client:
        # 1. Fetch the workflow Transform artifact
        try:
            workflow_artifact = await _get_artifact(client, workspace_id, workflow_artifact_id)
        except httpx.HTTPStatusError as exc:
            return json.dumps({"error": f"failed to fetch workflow artifact "
                                        f"{workflow_artifact_id}: {exc.response.status_code}"})
        except MissingDelegationError as exc:
            return json.dumps({"error": str(exc)})

        ctx = workflow_artifact.get("context", {})
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except json.JSONDecodeError:
                return json.dumps({"error": "workflow artifact has invalid JSON context."})

        # Find the run block
        run = (
            ctx.get("run")
            or (ctx.get("transform") or {}).get("run")
            or (ctx.get("order") or {}).get("run")
        )
        if not run or run.get("type") != "workflow":
            return json.dumps({"error": f"artifact {workflow_artifact_id} is not a workflow "
                                        f"(run.type={run.get('type') if run else 'missing'})."})

        steps = run.get("steps") or []
        retry_config = run.get("retry")

        if not steps:
            return "Workflow has no steps."

        # 2. Execute steps
        results: list[dict[str, Any]] = []
        retry_count = 0
        retries_performed = 0

        async def _execute_steps_from(start_index: int) -> str | None:
            """Execute steps starting from start_index. Returns error string or None."""
            for i in range(start_index, len(steps)):
                step = steps[i]
                step_name = step.get("name", f"step_{i}")
                child_transform_id = step.get("transform_id")

                if not child_transform_id:
                    return json.dumps({"error": f"step {i} ({step_name}) is missing transform_id."})

                # Evaluate condition if present
                condition = step.get("condition")
                if condition and state_artifact_id:
                    try:
                        state_art = await _get_artifact(client, workspace_id, state_artifact_id)
                        state_ctx = state_art.get("context", {})
                        if isinstance(state_ctx, str):
                            state_ctx = json.loads(state_ctx)
                    except Exception:
                        state_ctx = {}

                    if not _evaluate_condition(condition, state_ctx):
                        log.info("Workflow step %d (%s) skipped � condition not met", i, step_name)
                        results.append({"step": i, "name": step_name, "status": "skipped"})
                        continue

                # Update state artifact with current step info
                if state_artifact_id:
                    try:
                        await _patch_artifact_context(client, workspace_id, state_artifact_id, {
                            "status": "running",
                            "current_step": step_name,
                            "step_index": i,
                        })
                    except Exception as exc:
                        log.warning("Failed to update state artifact step info: %s", exc)

                # Build params for child dispatch
                child_params = dict(extra)
                step_mapping = step.get("input_mapping") or {}
                for k, v in step_mapping.items():
                    if isinstance(v, str) and v.startswith("$."):
                        resolved = extra.get(v[2:])
                        if resolved is not None:
                            child_params[k] = resolved
                    else:
                        child_params[k] = v

                # Dispatch child transform
                log.info("Workflow step %d (%s) � dispatching transform %s", i, step_name, child_transform_id)
                try:
                    result = await _dispatch_child_transform(
                        client, workspace_id, child_transform_id, child_params,
                    )
                    results.append({"step": i, "name": step_name, "status": "completed", "result": result})
                except httpx.HTTPStatusError as exc:
                    error_msg = f"Step {i} ({step_name}) failed: HTTP {exc.response.status_code}"
                    try:
                        error_msg += f" � {exc.response.text[:300]}"
                    except Exception:
                        pass
                    results.append({"step": i, "name": step_name, "status": "error", "error": error_msg})

                    # Update state with error
                    if state_artifact_id:
                        try:
                            await _patch_artifact_context(client, workspace_id, state_artifact_id, {
                                "status": "error",
                                "error": error_msg,
                            })
                        except Exception:
                            pass
                    # The state artifact keeps the human-readable string; the tool return is JSON
                    # (see the note at the top of run_workflow) — this is the branch that fires on a
                    # real step failure, the one a caller most needs to be able to parse.
                    return json.dumps({"error": error_msg, "step": i, "name": step_name})
                except Exception as exc:
                    error_msg = f"Step {i} ({step_name}) failed: {exc}"
                    results.append({"step": i, "name": step_name, "status": "error", "error": error_msg})
                    if state_artifact_id:
                        try:
                            await _patch_artifact_context(client, workspace_id, state_artifact_id, {
                                "status": "error",
                                "error": error_msg,
                            })
                        except Exception:
                            pass
                    return json.dumps({"error": error_msg, "step": i, "name": step_name})

            return None  # success

        # Initial execution from step 0
        error = await _execute_steps_from(0)
        if error:
            return error

        # 3. Retry logic
        if retry_config and state_artifact_id:
            on_field = retry_config.get("on_field")
            max_retries = retry_config.get("max_retries", 0)
            restart_from = retry_config.get("restart_from_step", 0)

            # Read initial retry_count from state (may have been set by a previous run)
            try:
                state_art = await _get_artifact(client, workspace_id, state_artifact_id)
                state_ctx = state_art.get("context", {})
                if isinstance(state_ctx, str):
                    state_ctx = json.loads(state_ctx)
                retry_count = state_ctx.get("retry_count", 0)
            except Exception:
                pass

            while retry_count < max_retries:
                # Re-fetch state to check retry condition
                try:
                    state_art = await _get_artifact(client, workspace_id, state_artifact_id)
                    state_ctx = state_art.get("context", {})
                    if isinstance(state_ctx, str):
                        state_ctx = json.loads(state_ctx)
                except Exception:
                    break

                should_retry = state_ctx.get(on_field)
                if not should_retry:
                    break

                retry_count += 1
                retries_performed += 1
                log.info("Workflow retry %d/%d � restarting from step %d", retry_count, max_retries, restart_from)

                # Update retry_count in state
                try:
                    await _patch_artifact_context(client, workspace_id, state_artifact_id, {
                        "retry_count": retry_count,
                    })
                except Exception as exc:
                    log.warning("Failed to update retry_count in state: %s", exc)

                error = await _execute_steps_from(restart_from)
                if error:
                    return error

        # 4. Mark completed
        if state_artifact_id:
            try:
                await _patch_artifact_context(client, workspace_id, state_artifact_id, {
                    "status": "completed",
                    "error": None,
                })
            except Exception as exc:
                log.warning("Failed to mark state as completed: %s", exc)

        completed = sum(1 for r in results if r.get("status") == "completed")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        return f"Workflow completed: {completed} steps executed, {skipped} skipped, {retries_performed} retries."


# ---------------------------------------------------------------------------
# Tool: execute_transform — Transform artifact execution
# ---------------------------------------------------------------------------

_MAX_TRANSFORM_DEPTH = 10


def _resolve_input_mapping(mapping: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Resolve '$.field' and '$.field[N]' references in mapping against params."""
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, str) and value.startswith("$."):
            path = value[2:]
            if "[" in path:
                field, rest = path.split("[", 1)
                try:
                    idx = int(rest.rstrip("]"))
                except ValueError:
                    idx = 0
                raw = params.get(field)
                resolved = raw[idx] if isinstance(raw, list) and len(raw) > idx else None
            else:
                resolved = params.get(path)
            if resolved is not None:
                result[key] = resolved
        else:
            result[key] = value
    return result


@mcp.tool(
    description=(
        "Execute a Transform artifact. Reads the artifact's run block and dispatches "
        "based on run.type: 'mcp-tool' calls an MCP tool directly, 'transform-ref' "
        "delegates to another Transform artifact, 'workflow' runs the multi-step "
        "workflow engine."
    )
)
async def execute_transform(
    workspace_id: str,
    transform_id: str,
    params: Optional[str] = None,
    depth: int = 0,
) -> str:
    """
    Args:
        workspace_id: Workspace containing the Transform artifact.
        transform_id: ID of the Transform artifact to execute.
        params: JSON string of additional parameters (e.g. artifact IDs, input values).
        depth: Internal recursion depth guard — do not set manually.
    """
    if not workspace_id or not transform_id:
        return json.dumps({"error": "workspace_id and transform_id are required"})

    if depth >= _MAX_TRANSFORM_DEPTH:
        return json.dumps({"error": f"Transform recursion depth exceeded (max {_MAX_TRANSFORM_DEPTH})"})

    invoke_params: dict[str, Any] = {}
    if params:
        try:
            invoke_params = json.loads(params)
        except json.JSONDecodeError:
            return json.dumps({"error": f"params is not valid JSON: {params[:200]}"})

    invoke_params["workspace_id"] = workspace_id
    invoke_params["transform_id"] = transform_id

    # Fetch the transform artifact
    async with httpx.AsyncClient() as client:
        try:
            transform_artifact = await _get_artifact(client, workspace_id, transform_id)
        except httpx.HTTPStatusError as exc:
            return json.dumps({"error": f"Transform artifact not found: {transform_id} (HTTP {exc.response.status_code})"})

    # Parse context
    raw_ctx = transform_artifact.get("context", {})
    if isinstance(raw_ctx, str):
        try:
            raw_ctx = json.loads(raw_ctx)
        except json.JSONDecodeError:
            return json.dumps({"error": "Transform artifact has invalid JSON context"})
    ctx = raw_ctx if isinstance(raw_ctx, dict) else {}

    # Inject artifact metadata so input_mapping can reference them
    invoke_params["_artifact_id"] = transform_id
    invoke_params["_artifact_content"] = transform_artifact.get("content")

    run = (
        ctx.get("run")
        or (ctx.get("transform") or {}).get("run")
        or (ctx.get("order") or {}).get("run")
    )
    if not run:
        return json.dumps({"error": "Transform artifact has no 'run' block"})

    run_type = run.get("type")

    # --- mcp-tool: call an MCP tool on a named server ---
    if run_type == "mcp-tool":
        # Server name from artifact context (e.g. "astra"). The platform
        # router resolves short names to UUIDs via the server registry, so
        # POST /artifacts/{server}/op/invoke works with either form.
        server = run.get("server")
        if not server:
            return json.dumps({"error": "Transform run block is missing 'server'"})

        tool = run.get("tool")
        if not tool:
            return json.dumps({"error": "Transform run block is missing 'tool'"})

        input_mapping = run.get("input_mapping") or {}
        tool_args = _resolve_input_mapping(input_mapping, invoke_params)

        # Dispatch via the artifact-native invoke path.
        # POST /artifacts/{server}/op/invoke accepts both server names and UUIDs.
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    artifact_url(CRYSTAL_URI, server, "op", "invoke"),
                    headers=_require_user_headers(),
                    json={
                        "name": tool,
                        "arguments": tool_args,
                        "workspace_id": workspace_id,
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                return json.dumps(resp.json(), indent=2)
            except httpx.HTTPStatusError as exc:
                return json.dumps({"error": f"Tool execution failed: HTTP {exc.response.status_code} — {exc.response.text[:300]}"})
    # --- transform-ref: delegate to another Transform artifact ---
    elif run_type in {"transform-ref", "order-ref"}:
        child_transform_id = run.get("transform_id")
        if not child_transform_id:
            return json.dumps({"error": "transform-ref run block is missing 'transform_id'"})

        child_params = dict(invoke_params)
        input_mapping = run.get("input_mapping") or {}
        mapped = _resolve_input_mapping(input_mapping, invoke_params)
        child_params.update(mapped)
        child_params["transform_id"] = child_transform_id

        return await execute_transform(
            workspace_id=workspace_id,
            transform_id=child_transform_id,
            params=json.dumps({k: v for k, v in child_params.items() if not k.startswith("_")}),
            depth=depth + 1,
        )

    # --- workflow: delegate to run_workflow ---
    elif run_type == "workflow":
        workflow_params = {k: v for k, v in invoke_params.items()
                          if k not in ("transform_id", "_artifact_id", "_artifact_content")
                          and not k.startswith("_")}
        return await run_workflow(
            workflow_artifact_id=transform_id,
            workspace_id=workspace_id,
            params=json.dumps(workflow_params) if workflow_params else None,
        )

    # --- llm: a transform step runs inside the answer path, which stays grounded ---
    elif run_type == "llm":
        # Transforms with run.type == "llm" fail loudly rather than silently
        # skipping the step.
        raise NotImplementedError(
            "Transform run type 'llm': model dispatch removed 2026-07-22. A "
            "transform step executes inside Lumen's answer path, and that path is "
            "grounded operators over the artifact graph. Reach a model deliberately "
            "through its own tekton, where the call is explicit and the provenance "
            "records that a caller chose it."
        )

    elif run_type == "webhook":
        raise NotImplementedError("Transform run type 'webhook' is a declared placeholder; the spec is open.")

    else:
        return json.dumps({"error": f"Unknown Transform run type: {run_type!r}"})


# ---------------------------------------------------------------------------
# Tool: chain_tasks
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Chain multiple MCP tool calls sequentially via the platform's artifact-invoke "
        "path. Each step is {server, tool, arguments}; the literal string \"$prev\" in "
        "an argument value is replaced by the previous step's result. Runs under the "
        "caller's delegation (fails closed without one). Returns all step results and "
        "the final output; aborts on the first failed step."
    )
)
async def chain_tasks(
    steps: str,
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        steps: JSON array of step definitions, each with 'server', 'tool', 'arguments'.
        workspace_id: Workspace context for the chain.
    """
    try:
        step_list = json.loads(steps)
    except json.JSONDecodeError:
        return json.dumps({"error": f"steps is not valid JSON: {steps[:200]}"})
    if not isinstance(step_list, list) or not step_list:
        return json.dumps({"error": "steps must be a non-empty JSON array"})

    # The chain dispatches to caller-chosen servers/tools — the caller's own
    # delegation only, never the persona's platform identity.
    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": str(exc)})

    results: list[dict[str, Any]] = []
    prev: Any = None
    async with httpx.AsyncClient() as client:
        for i, step in enumerate(step_list):
            if not isinstance(step, dict) or not step.get("server") or not step.get("tool"):
                return json.dumps({
                    "error": f"step {i} must be an object with 'server' and 'tool'",
                    "results": results,
                })
            args = dict(step.get("arguments") or {})
            # Feed the previous step's output forward: "$prev" placeholders.
            for k, v in args.items():
                if v == "$prev":
                    args[k] = prev
            body: dict[str, Any] = {"name": step["tool"], "arguments": args}
            if workspace_id:
                body["workspace_id"] = workspace_id
            try:
                resp = await client.post(
                    artifact_url(CRYSTAL_URI, step["server"], "op", "invoke"),
                    headers=headers,
                    json=body,
                    timeout=120,
                )
                resp.raise_for_status()
                prev = resp.json()
            except httpx.HTTPStatusError as exc:
                results.append({
                    "step": i, "server": step["server"], "tool": step["tool"],
                    "status": "error",
                    "error": f"HTTP {exc.response.status_code} — {exc.response.text[:300]}",
                })
                return json.dumps({
                    "error": f"chain aborted at step {i} ({step['server']}:{step['tool']})",
                    "results": results,
                }, indent=2)
            except Exception as exc:
                results.append({
                    "step": i, "server": step["server"], "tool": step["tool"],
                    "status": "error", "error": f"{type(exc).__name__}: {exc}",
                })
                return json.dumps({
                    "error": f"chain aborted at step {i} ({step['server']}:{step['tool']})",
                    "results": results,
                }, indent=2)
            results.append({
                "step": i, "server": step["server"], "tool": step["tool"],
                "status": "completed", "result": prev,
            })
    return json.dumps({
        "steps_executed": len(results),
        "results": results,
        "final": prev,
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool: schedule_action
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Schedule a deferred action for future execution. "
        "Creates a task card that will be executed at the specified time or interval."
    )
)
async def schedule_action(
    workspace_id: str,
    action: str,
    cron: str = "0 8 * * 1",
    params: Optional[str] = None,
) -> str:
    """
    Args:
        workspace_id: Workspace for the task card.
        action: Action identifier or tool name to execute.
        cron: Cron expression for schedule (default: Mondays at 08:00).
        params: JSON string of action parameters.
    """
    # No component in the platform fires deferred actions: chorus has no timer loop and ember's
    # ScheduleWakeup never fires. Creating a task card here would advertise deferred execution
    # that nothing in the platform performs.
    raise NotImplementedError(
        f"schedule_action awaits a live scheduler/executor — no platform component "
        f"fires deferred actions, so a task card would never run. action={action}, cron={cron}"
    )


# ---------------------------------------------------------------------------
# Tool: evaluate_output
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Evaluate the quality and accuracy of generated output. "
        "Scores content against criteria like relevance, completeness, "
        "coherence, and factual accuracy."
    )
)
async def evaluate_output(
    content: str,
    criteria: Optional[str] = None,
    reference: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        content: The generated output to evaluate.
        criteria: Optional JSON string of evaluation criteria and weights.
        reference: Optional reference/ground-truth text to compare against.
        workspace_id: Optional workspace context.
    """
    # Quality/accuracy judgment needs an oracle — execution results, agreement with verified
    # triples, or human confirmation (the verification-mass loop). A judge model would grade this
    # answer path from inside it, which is the thing the path exists to avoid; and lexical-overlap
    # scores are bookkeeping, not capability
    # (metrics-are-not-capability): reporting them as "quality" would be a fabricated evaluation.
    # Human judgments are recorded via submit_feedback instead.
    raise NotImplementedError(
        "evaluate_output awaits a grounded verifier (execution / oracle agreement / "
        "human confirmation); an LLM judge is barred and lexical overlap is not a "
        "quality measurement. Use submit_feedback to record human judgments."
    )


# ---------------------------------------------------------------------------
# Tool: submit_feedback
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Submit evaluation feedback on an artifact. Records the judgment as an "
        "append-only feedback artifact (a confirmation event in the verification-"
        "mass loop: human sentiment is the oracle that raises or lowers a triple's "
        "effective mass). Requires the caller's delegation; the submitter identity "
        "is derived from the verified delegation, never client-asserted."
    )
)
async def submit_feedback(
    artifact_id: str,
    rating: Optional[int] = None,
    feedback: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> str:
    """
    Args:
        artifact_id: ID of the card being evaluated.
        rating: Numeric quality rating (1-5).
        feedback: Free-text feedback or correction.
        workspace_id: Optional workspace context.
    """
    if rating is None and not (feedback or "").strip():
        return json.dumps({"error": "nothing to record: provide a rating and/or feedback text"})
    if rating is not None and not (1 <= rating <= 5):
        # 1-5 is this tool's declared interface (see Args), not a derived bound.
        return json.dumps({"error": f"rating must be within the declared 1-5 scale, got {rating}"})

    # Caller-supplied artifact_id ⇒ the caller's own delegation, fail closed.
    try:
        headers = _require_user_headers()
    except MissingDelegationError as exc:
        return json.dumps({"error": str(exc)})

    submitted_by = _get_delegation_user_id()
    body = {
        "subject_artifact_id": artifact_id,
        "rating": rating,
        "feedback": (feedback or "").strip() or None,
    }
    context = {
        "content_type": "application/vnd.agience.feedback+json",
        "title": f"feedback on {artifact_id}",
        "operator": "lumen:submit_feedback",
        "subject_artifact_id": artifact_id,
        "source": "human",           # the human oracle — a confirmation event
        "submitted_by": submitted_by,
    }
    payload: dict[str, Any] = {
        "content": json.dumps(body),
        "content_type": "application/vnd.agience.feedback+json",
        "context": json.dumps(context),
    }
    if workspace_id:
        payload["container_id"] = workspace_id

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{MANTLE_URI}/artifacts", headers=headers, json=payload, timeout=30,
            )
        except Exception as exc:
            return json.dumps({"error": f"feedback persist failed: {type(exc).__name__}"})
    if resp.status_code >= 400:
        return json.dumps({"error": f"feedback persist failed: HTTP {resp.status_code} — {resp.text[:300]}"})
    created = resp.json() if resp.text else {}
    return json.dumps({
        "recorded": True,
        "feedback_artifact_id": created.get("id"),
        "subject_artifact_id": artifact_id,
        "rating": rating,
        "submitted_by": submitted_by,
    }, indent=2)


# ---------------------------------------------------------------------------
# Resource: Transform HTML View
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tool: install_package
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Install a package into a target workspace. "
        "Reads the package manifest, resolves MCP server dependencies "
        "(creating missing server artifacts), copies content artifacts "
        "into the workspace, and rewrites package-scoped references to "
        "local IDs. Dispatched from the package type's invoke operation."
    )
)
async def install_package(
    transform_id: str,
    workspace_id: Optional[str] = None,
    target_workspace_id: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """Install the package artifact ``transform_id`` into ``target_workspace_id``.

    ``transform_id`` is the package manifest artifact ID (named that way
    because it's what the operation dispatcher injects as the invoke
    subject). ``target_workspace_id`` defaults to ``workspace_id`` if
    omitted.
    """
    target_ws = target_workspace_id or workspace_id
    if not target_ws:
        return json.dumps({"error": "target_workspace_id (or workspace_id) required"})

    async with httpx.AsyncClient() as client:
        # 1. Fetch the package manifest.
        pkg = await _get_artifact(client, workspace_id or target_ws, transform_id)
        pkg_ctx = pkg.get("context") or {}
        if isinstance(pkg_ctx, str):
            try:
                pkg_ctx = json.loads(pkg_ctx)
            except json.JSONDecodeError:
                return json.dumps({"error": "Package context is not valid JSON"})

        pkg_block = pkg_ctx.get("package") or {}
        if not pkg_block:
            return json.dumps({"error": "Artifact is not a package (missing context.package)"})

        pkg_id = pkg_block.get("id") or "unknown"
        pkg_version = pkg_block.get("version") or "0.0.0"
        contents = pkg_block.get("contents") or []
        deps = (pkg_block.get("dependencies") or {}).get("servers") or []
        linking = (pkg_block.get("install") or {}).get("linking") or []

        plan: dict[str, Any] = {
            "package_id": pkg_id,
            "package_version": pkg_version,
            "target_workspace_id": target_ws,
            "servers": {"existing": [], "would_create": [], "created": []},
            "artifacts": {"ref_map": {}, "created": []},
            "rewrites_applied": 0,
        }

        # 2. Resolve server dependencies. Check each required server and
        #    record whether we'd create it or it already exists.
        existing_servers = await _list_workspace_servers(client, target_ws)
        existing_by_name = {s.get("name"): s for s in existing_servers if s.get("name")}

        for dep in deps:
            name = dep.get("name")
            if not name:
                continue
            if name in existing_by_name:
                plan["servers"]["existing"].append(name)
                continue
            if dry_run:
                plan["servers"]["would_create"].append(name)
                continue
            try:
                created = await _create_server_artifact(client, target_ws, dep)
                plan["servers"]["created"].append({
                    "name": name,
                    "artifact_id": created.get("id"),
                })
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to create server dependency %s: %s", name, exc)
                plan["servers"]["created"].append({"name": name, "error": str(exc)})

        # 3. Copy content artifacts into the target workspace, building a
        #    ref_map from package-scoped ref -> new local artifact_id.
        ref_map: dict[str, str] = {}
        for entry in contents:
            ref = entry.get("artifact_ref")
            src_id = entry.get("artifact_id")
            if not ref or not src_id:
                continue
            if dry_run:
                ref_map[ref] = f"<pending:{src_id}>"
                continue
            try:
                new_id = await _copy_artifact_to_workspace(
                    client, src_id, target_ws, role=entry.get("role"),
                )
                ref_map[ref] = new_id
                plan["artifacts"]["created"].append({
                    "ref": ref, "role": entry.get("role"), "artifact_id": new_id,
                })
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to copy artifact %s: %s", src_id, exc)
                plan["artifacts"]["created"].append({
                    "ref": ref, "role": entry.get("role"), "error": str(exc),
                })

        plan["artifacts"]["ref_map"] = ref_map

        # 4. Apply link rewriting so imported artifacts reference each other
        #    by new local ID rather than package-scoped URI.
        if not dry_run:
            for rule in linking:
                from_ref = rule.get("from_ref")
                if from_ref not in ref_map:
                    continue
                new_id = ref_map[from_ref]
                rewrites = rule.get("rewrite") or []
                for r in rewrites:
                    path = r.get("path")
                    value_template = r.get("value") or ""
                    # Single supported pattern: ${workspace_artifact_id(<ref>)}
                    # resolves to the freshly-copied artifact ID for that ref.
                    resolved = _resolve_rewrite_value(value_template, ref_map)
                    if path and resolved is not None:
                        try:
                            await _patch_artifact_path(
                                client, target_ws, new_id, path, resolved,
                            )
                            plan["rewrites_applied"] += 1
                        except Exception as exc:  # noqa: BLE001
                            log.warning(
                                "Rewrite failed (%s.%s): %s", new_id, path, exc,
                            )

        plan["status"] = "dry_run" if dry_run else "installed"
        return json.dumps(plan, indent=2)


async def _list_workspace_servers(
    client: httpx.AsyncClient, workspace_id: str,
) -> list[dict]:
    """List MCP server artifacts already in the target workspace."""
    try:
        resp = await client.get(
            artifact_url(MANTLE_URI, workspace_id, "children"),
            headers=_require_user_headers(),
            params={"content_type": "application/vnd.agience.mcp-server+json"},
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        artifacts = data if isinstance(data, list) else data.get("artifacts", [])
        out: list[dict] = []
        for a in artifacts:
            ctx = a.get("context") or {}
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except json.JSONDecodeError:
                    ctx = {}
            out.append({"id": a.get("id"), "name": ctx.get("name"), "context": ctx})
        return out
    except Exception:
        return []


async def _create_server_artifact(
    client: httpx.AsyncClient, workspace_id: str, dep: dict,
) -> dict:
    """Create a vnd.agience.mcp-server+json artifact from a package dep entry."""
    ctx = {
        "name": dep.get("name"),
        "transport": dep.get("transport", "http"),
    }
    if dep.get("endpoint"):
        ctx["endpoint"] = dep["endpoint"]
    if dep.get("repo_url"):
        ctx["repo_url"] = dep["repo_url"]
    payload = {
        "content_type": "application/vnd.agience.mcp-server+json",
        "context": ctx,
        "workspace_id": workspace_id,
    }
    resp = await client.post(
        f"{MANTLE_URI}/artifacts",
        headers=_require_user_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


async def _copy_artifact_to_workspace(
    client: httpx.AsyncClient,
    source_id: str,
    target_workspace_id: str,
    role: Optional[str] = None,
) -> str:
    """Copy a source artifact's content + context into a new artifact in the target workspace.

    Returns the new artifact ID. Adds ``package_role`` to the copy's
    context for traceability.
    """
    # Fetch via collection-batch so we can read from either workspace or
    # published collection.
    # Same three faults as the fallback above, and this one was missed on the first pass:
    # there is no `collections` plane, the field is `artifact_ids`, and the response is the
    # `{items, …}` envelope rather than a bare list. This copy `raise_for_status`es, so
    # it failed loudly where the other failed silently — which is why only one of the two
    # was noticed.
    batch = await client.post(
        f"{MANTLE_URI}/artifacts/batch",
        headers=_require_user_headers(),
        json={"artifact_ids": [source_id]},
        timeout=30,
    )
    batch.raise_for_status()
    body = batch.json()
    results = body.get("items", []) if isinstance(body, dict) else (body or [])
    if not results:
        raise ValueError(f"Source artifact {source_id} not found")
    source = results[0]

    ctx = source.get("context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except json.JSONDecodeError:
            ctx = {}
    if role:
        ctx["package_role"] = role

    payload = {
        "content_type": source.get("content_type"),
        "context": ctx,
        "content": source.get("content") or "",
        "workspace_id": target_workspace_id,
    }
    resp = await client.post(
        f"{MANTLE_URI}/artifacts",
        headers=_require_user_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("id")


def _resolve_rewrite_value(template: str, ref_map: dict[str, str]) -> Optional[str]:
    """Resolve ``${workspace_artifact_id(<ref>)}`` tokens in a rewrite value.

    Returns None if the template references a ref that's not in ref_map.
    """
    import re
    match = re.match(
        r"^\$\{workspace_artifact_id\(([^)]+)\)\}$", template.strip(),
    )
    if not match:
        # Literal value; passthrough.
        return template
    ref = match.group(1).strip().strip("'\"")
    return ref_map.get(ref)


async def _patch_artifact_path(
    client: httpx.AsyncClient,
    workspace_id: str,
    artifact_id: str,
    path: str,
    value: Any,
) -> None:
    """Set a dotted path inside an artifact's context to *value* (PATCH merge)."""
    artifact = await _get_artifact(client, workspace_id, artifact_id)
    ctx = artifact.get("context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except json.JSONDecodeError:
            ctx = {}

    # Walk the dotted path, creating dicts as needed.
    parts = path.split(".")
    node: dict = ctx
    for key in parts[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[parts[-1]] = value

    await client.patch(
        artifact_url(MANTLE_URI, artifact_id),
        headers=_require_user_headers(),
        json={"context": ctx},
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Tool: export_package
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Populate a package manifest from workspace contents. "
        "Walks the named workspace (or subset by artifact_ids), generates "
        "stable package-scoped references, and updates the package artifact's "
        "context.package.contents + dependencies.servers. Dispatched from "
        "the package type's export operation."
    )
)
async def export_package(
    transform_id: str,
    workspace_id: Optional[str] = None,
    artifact_ids: Optional[list[str]] = None,
) -> str:
    """Populate package ``transform_id`` with contents from ``workspace_id``.

    Only inspects draft + committed artifacts in the workspace; archived
    artifacts are skipped. Server dependencies are inferred from each
    transform artifact's ``server`` relationship edge.
    """
    ws = workspace_id
    if not ws:
        return json.dumps({"error": "workspace_id required"})

    async with httpx.AsyncClient() as client:
        # 1. Read the package manifest.
        pkg = await _get_artifact(client, ws, transform_id)
        pkg_ctx = pkg.get("context") or {}
        if isinstance(pkg_ctx, str):
            try:
                pkg_ctx = json.loads(pkg_ctx)
            except json.JSONDecodeError:
                return json.dumps({"error": "Package context is not valid JSON"})
        pkg_block = pkg_ctx.get("package") or {}
        pkg_id = pkg_block.get("id")
        if not pkg_id:
            return json.dumps({"error": "Package is missing context.package.id"})

        # 2. List workspace artifacts (filtered if artifact_ids given).
        artifacts = await _list_workspace_artifacts(client, ws)
        if artifact_ids:
            wanted = set(artifact_ids)
            artifacts = [a for a in artifacts if a.get("id") in wanted]

        # 3. Build contents[] and dependencies.servers[].
        contents: list[dict[str, Any]] = []
        server_names: set[str] = set()

        for a in artifacts:
            aid = a.get("id")
            ctype = a.get("content_type") or ""
            if ctype == "application/vnd.agience.package+json":
                continue  # don't include the package itself in its own contents
            ctx = a.get("context") or {}
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except json.JSONDecodeError:
                    ctx = {}

            role = _infer_package_role(ctype, ctx)
            slug = ctx.get("slug") or (ctx.get("title") or aid).lower().replace(" ", "-")
            contents.append({
                "artifact_ref": f"agience://packages/{pkg_id}/{role}/{slug}",
                "artifact_id": aid,
                "role": role,
                "content_type": ctype,
                "slug": slug,
            })

            # Harvest server dependencies from the transform's context.
            # Per Step 1.6, typed relationships live on the artifact's context
            # rather than as separate Arango edges. Transform context carries
            # `run.server_artifact_id` (the canonical field that
            # operation_dispatcher already prefers).
            if ctype == "application/vnd.agience.transform+json":
                run_block = ctx.get("run") or (ctx.get("order") or {}).get("run") or {}
                if isinstance(run_block, dict):
                    server_id = run_block.get("server_artifact_id") or run_block.get("server")
                    if isinstance(server_id, str) and server_id:
                        server_names.add(server_id)

        # 4. Merge into the existing package context (preserve publisher,
        #    version, etc. that the author set manually).
        pkg_block["contents"] = contents
        deps = pkg_block.setdefault("dependencies", {})
        existing_deps = deps.get("servers") or []
        existing_ids = {d.get("artifact_id") for d in existing_deps if d.get("artifact_id")}
        for server_id in sorted(server_names):
            if server_id not in existing_ids:
                existing_deps.append({"artifact_id": server_id})
        deps["servers"] = existing_deps

        pkg_ctx["package"] = pkg_block

        # 5. Write back to the package artifact.
        await client.patch(
            artifact_url(MANTLE_URI, transform_id),
            headers=_require_user_headers(),
            json={"context": pkg_ctx},
            timeout=30,
        )

        return json.dumps({
            "status": "exported",
            "package_id": pkg_id,
            "contents_count": len(contents),
            "server_deps_count": len(existing_deps),
        }, indent=2)


async def _list_workspace_artifacts(
    client: httpx.AsyncClient, workspace_id: str,
) -> list[dict]:
    resp = await client.get(
        artifact_url(MANTLE_URI, workspace_id, "children"),
        headers=_require_user_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("artifacts", [])


def _infer_package_role(content_type: str, context: dict) -> str:
    """Infer a package role string from content type + context."""
    if content_type == "application/vnd.agience.transform+json":
        return "transform"
    if content_type == "application/vnd.agience.mcp-server+json":
        return "server"
    if content_type == "application/vnd.agience.prompts+json":
        return "prompt"
    if content_type.startswith("text/markdown"):
        return "docs"
    ctx_type = context.get("type")
    if ctx_type == "prompt":
        return "prompt"
    if ctx_type == "docs":
        return "docs"
    return "artifact"


# ---------------------------------------------------------------------------
# Resources: HTML Views
# ---------------------------------------------------------------------------

@mcp.resource("ui://lumen/vnd.agience.transform.html")
async def transform_html_view() -> str:
    """Standalone MCP Apps HTML view for vnd.agience.transform+json artifacts."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.transform+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://lumen/vnd.agience.evaluation.html")
async def evaluation_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.evaluation+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.evaluation+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://lumen/vnd.agience.llm-connection.html")
async def llm_connection_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.llm-connection+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.llm-connection+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://lumen/vnd.agience.prompt.html")
async def prompt_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.prompt+json.

    The platform adopts Lumen's richer overlay for the prompt type: the facet
    content-types build auto-derives `resource_uri: ui://lumen/vnd.agience.prompt.html`
    from this view.html, so it must be served here for McpAppHost to load it.
    """
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.prompt+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Standard server interface (used by _host and standalone)
# ---------------------------------------------------------------------------

def create_server_app():
    """Return the Lumen ASGI app with verified middleware and startup hooks."""
    return _auth.create_app(mcp)


async def server_startup() -> None:
    """Run Lumen startup tasks. The trust map is on disk; nothing to fetch."""
    await _auth.startup()
    # Stands lumen up as the conversation-tekton provider (op.respond/op.act/op.learn/op.thought)
    # over the ground plane, so other nodes can reach it. Dark by default — with no carrier wired,
    # the provider does not start and ember honestly refuses op.respond rather than fabricating one;
    # wiring a live carrier is a separate deploy step. This never breaks boot.
    try:
        import agience_chorus.lumen.reach_provider as _reach_provider   # lumen-local
        _rc = _reach_provider.serve_respond_if_configured()
        # This log names its transport explicitly because there are two independent ones: the host
        # wires an in-process responder so aria's chat can answer (logged separately by
        # `personas.py` as "conversation carrier wired -> lumen op.respond"), while this is the
        # ground-plane provider that lets other nodes reach this lumen over the mesh. The two can
        # report opposite states in the same boot without contradicting each other.
        log.info("lumen: op.respond MESH provider %s",
                 "LIVE on the ground plane" if _rc is not None
                 else "dark — no ground-plane carrier (the in-process chat responder is separate "
                      "and wired by the host; this is the mesh-facing half, a gated follow-up)")
    except Exception as exc:  # provider wiring must never break startup
        log.info("lumen: op.respond reach provider not started (%s)", type(exc).__name__)


# ---------------------------------------------------------------------------
# Self-registration (GENESIS-NEXT §B1.10): this persona owns its registration.
# The host holds no roster — it calls each persona's register(). PERSONA is the
# single source of truth for {name, role, endpoint}; register() self-registers
# with Mantle (server record) + the crystal gateway (owned types).
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "lumen",
    "kind": "tekton",
    "role": "Wisdom & Inference",
    "endpoint": "/lumen/mcp",
    "client_id": LUMEN_CLIENT_ID,
}

# The organons this tekton uses, wired in at assembly by the composition adapter (module-attr <- op).
# The tekton declares what it needs; the adapter resolves the impl and injects it — so this file
# imports no crystal (a tekton is an impartial part; crystal collects/assembles it).
# No shim organons: op.reason is local (`import reasoning`), op.retrieve is reached from sage (above).


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
    log.info("Starting agience-server-lumen � transport=%s port=%s", MCP_TRANSPORT, MCP_PORT)
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn
        uvicorn.run(create_server_app(), host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run()
