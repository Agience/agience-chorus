"""
agience-server-ophan — MCP Server
====================================
Ophan (economics — value, consent+stake, licensing): energy accounting, settlement,
licensing, entitlements, and the subscription/commercial-operations surface.
A tekton — the economics condensor in the chorus (the tekton standard library); its tools are
organons, invoked by condensation (OPERATOR-ARCHITECTURE §12).

Ophan is the economics persona of chorus (operators, by domain) — the economic
operations layer. It measures an artifact's energy (standing heat, cooled to
the current frame) and computes settlement between the governing Origin and
the producer; it issues, renews, revokes, and reports on licenses and
entitlements; and it carries the subscription surface (activation and plan
changes, plus outbound payment tools that carry no execution path yet). Value
transfers, crypto/fiat rails, double-entry bookkeeping, reconciliation,
budgeting, and performance metrics are not this domain — no payment or chain
rails exist anywhere in the workspace.

Tools
-----
The registered surface, and nothing else:

  get_energy          — standing heat cooled to the current frame (value decays unless re-witnessed)
  settle_energy       — a flat Origin fee, conservation checked, computes only; moves nothing
  resolve_license_posture — read the effective licensing posture for a subject
  issue_license       — create and sign a license artifact from entitlement inputs
  renew_license       — extend or replace an existing license artifact
  revoke_license      — revoke a license and record the compliance event
  review_installation — inspect installation and activation state
  record_usage_snapshot — ingest aggregate metering or usage snapshots
  run_licensing_report — produce licensing or entitlement report cards
  create_checkout_session / create_portal_session / create_vu_topup — registered, but raise (see the
    Stripe outbound-writes note above the three tools)
  activate_subscription / update_subscription — subscription state

Ophan meters no model invocation: the platform's no-models rule applies to this persona too,
including BYOK. `check_llm_allowance` and `record_llm_usage` are unregistered tombstones that raise
if called directly, matching seraph's `resolve_llm_credentials` shape.

Stripe credentials are resolved from stored secrets under a delegation, never read from the
persona's process environment — the same rule astra follows by not building credentialed market
fetchers directly (`astra/market_sources.py`). `STRIPE_WEBHOOK_SECRET` is resolved by
`_resolve_stripe_webhook_secret()`, which raises rather than returning `None`: a missing secret is a
503 that names the reason, never a signature check that silently goes unverified.

Outbound writes to Stripe (`create_checkout_session`, `create_portal_session`, `create_vu_topup`)
raise. External operators in this platform are GET-only, and a write-capable reach is meant to go
through an organon declaring `net.request`, gated by the discharge grant — the pattern astra
enforces structurally in `astra/fetch.py`. The organon that would carry these three calls is
specified in `_archive/OPHAN-STRIPE-TEKTON.md` and is not wired yet, so the tools stay registered —
a caller gets an addressed raise rather than an unknown tool — while raising unconditionally.

`_PLAN_LIMITS`, `VU_TOPUP_PACK_SIZE`, and the `STRIPE_PRICE_ID_*` env reads are hand-authored price
and limit tables: values decided in a deploy file or code constant rather than derived from a
governed artifact (the entitlement card, the settled exchange rate at the screen).

Auth (Phase C)
--------------
  Service identity loaded once by the chorus host (chorus.private.pem).
  Persona signs its own platform JWTs via _auth.sign_self_jwt() — no token
  exchange with Origin, no PLATFORM_INTERNAL_SECRET. Inbound delegation JWTs
  verified against Mantle's inline JWKS in the platform authority manifest.

  MANTLE_URI ⬩ Base URI of the Mantle backend

Transport
---------
  MCP_TRANSPORT=streamable-http (default for Agience)
  MCP_HOST=0.0.0.0
  MCP_PORT=8090
"""

from __future__ import annotations

from contextvars import ContextVar
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import httpx
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("agience-server-ophan")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s - %(name)s - %(message)s")

# Canonical param names: MANTLE_URI (backend) + ORIGIN_URI (identity).
MANTLE_URI: str = os.getenv("MANTLE_URI", "http://localhost:8081").rstrip("/")
ORIGIN_URI: str = os.getenv("ORIGIN_URI", "http://localhost:8080").rstrip("/")
OPHAN_CLIENT_ID: str = "agience-server-ophan"

# The platform email operator artifact (provisioned by Mantle's platform_email
# from GMAIL_OAUTH_* env). Its id is derived deterministically from the shared
# instance namespace — uuid5(instance_namespace, "platform/platform-email-sender")
# — so Ophan can address it for op/invoke without a slug→id lookup.
_PLATFORM_EMAIL_OPERATOR_DERIVATION = "platform/platform-email-sender"
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8090"))

# Neither `STRIPE_SECRET_KEY` nor `STRIPE_WEBHOOK_SECRET` is read from the environment. A secret in a
# persona's environment is held by the process, so its custody is the deployment's rather than the
# store's — there is no owner, no grant, no delegation and no audit on the read, and a bare truthiness
# check on it turns "the platform forgot to mount the secret" into the same quiet state as "billing is
# not configured". astra follows the same rule by not building credentialed market fetchers directly
# (`astra/market_sources.py`): credentials in this platform are resolved from stored secrets under a
# delegation, not read from a persona's environment.
#
# `STRIPE_SECRET_KEY` has no consumer in this module: it fed only the outbound Stripe writes, which
# raise (see the three creation tools below), so a credential with no permitted use is not resolvable
# at all. `STRIPE_WEBHOOK_SECRET` still has a legitimate consumer — inbound signature verification —
# and is resolved by `_resolve_stripe_webhook_secret()`, which raises rather than returning `None`.
#
# The price ids below are not secrets (a Stripe price id is public), so they stay on env — but they
# are a hand-authored price table: three configured rates whose values are decided in a deploy file.
# They should be derived from the licensing/entitlement artifact that governs a plan
# (`ENTITLEMENT_CARD_MIME`), so the offer and the price are one governed object, not a code constant
# plus an env var that can disagree.
STRIPE_PRICE_ID_PRO: str | None = os.getenv("STRIPE_PRICE_ID_PRO")
STRIPE_PRICE_ID_POWER: str | None = os.getenv("STRIPE_PRICE_ID_POWER")
STRIPE_PRICE_ID_VU_TOPUP: str | None = os.getenv("STRIPE_PRICE_ID_VU_TOPUP")

SUBSCRIPTION_CARD_MIME = "application/vnd.agience.subscription+json"

LICENSE_CARD_MIME = "application/vnd.agience.license+json"
ENTITLEMENT_CARD_MIME = "application/vnd.agience.entitlement+json"
INSTALLATION_CARD_MIME = "application/vnd.agience.license-installation+json"
USAGE_CARD_MIME = "application/vnd.agience.license-usage+json"
EVENT_CARD_MIME = "application/vnd.agience.license-event+json"
ORGANIZATION_CARD_MIME = "application/vnd.agience.organization+json"
KNOWN_LICENSING_ENTITLEMENTS = {
    "host_standard",
    "white_label_branding",
    "relay_distribution",
    "oem_distribution",
    "licensing_operations",
    "delegated_licensing_operations",
}
ADVANCED_OPERATIONS_ENTITLEMENTS = {"licensing_operations", "delegated_licensing_operations"}
_CURRENT_OPERATOR_CLAIMS: ContextVar[dict[str, Any] | None] = ContextVar(
    "ophan_current_operator_claims",
    default=None,
)


class OphanToolError(RuntimeError):
    """Raised when an Ophan tool cannot complete a request safely."""


# ---------------------------------------------------------------------------
# Shared authentication infrastructure (AgienceServerAuth)
# ---------------------------------------------------------------------------

from prism.trust import ServerAuth as _AgienceServerAuth

_auth = _AgienceServerAuth(OPHAN_CLIENT_ID, MANTLE_URI)


async def _headers() -> dict[str, str]:
    """Headers with Ophan's own platform JWT (signed via the chorus service identity)."""
    return _auth.headers()


# ---------------------------------------------------------------------------
# Platform email (webhook/background sends) — act AS the operator-rooted system
# principal via the Origin system-delegation exchange, then invoke the platform
# email operator. Every send carries the full Authority/Host/Server/User chain
# (the exchange mints it); the customer's secret is never exposed.
# ---------------------------------------------------------------------------

async def _origin_headers() -> dict[str, str]:
    """Ophan's platform JWT addressed to Origin (aud=origin) — for /internal calls."""
    return _auth.headers(audience="origin")


def _platform_email_operator_id() -> str:
    """Derive the platform email operator artifact id from the shared instance
    namespace (matches Mantle's provisioner). Empty if the namespace is absent."""
    import uuid as _uuid

    from prism.trust.service_identity import get_instance_namespace

    ns = get_instance_namespace()
    return str(_uuid.uuid5(ns, _PLATFORM_EMAIL_OPERATOR_DERIVATION)) if ns else ""


async def _obtain_system_delegation(client: httpx.AsyncClient, purpose: str = "platform-mail") -> str:
    """Exchange Ophan's platform identity for a delegation as the platform system
    principal (Origin gates the purpose→subject; Ophan cannot pick the subject)."""
    resp = await client.post(
        f"{ORIGIN_URI}/internal/system-delegation",
        headers=await _origin_headers(),
        json={"purpose": purpose},
        timeout=15,
    )
    resp.raise_for_status()
    return (resp.json() or {}).get("token", "")


async def _resolve_person_email(client: httpx.AsyncClient, person_id: str) -> str:
    """Look up a person's email via Origin's internal person endpoint (platform-gated)."""
    resp = await client.get(
        f"{ORIGIN_URI}/internal/persons/{person_id}",
        headers=await _origin_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        return ""
    return (resp.json() or {}).get("email", "")


def _receipt_html(plan: str) -> str:
    return (
        "<html><body style='font-family:sans-serif;'>"
        f"<h2>Your Agience {plan} plan is active</h2>"
        "<p>Thanks for subscribing. Your plan is now active and your limits have "
        "been updated. You can manage billing anytime from Settings.</p>"
        "<p style='color:#888;font-size:12px;'>— Agience</p>"
        "</body></html>"
    )


def _usage_warning_html(overages: dict) -> str:
    rows = "".join(
        f"<tr><td style='padding:4px 8px;font-weight:bold;'>{k}</td>"
        f"<td style='padding:4px 8px;'>{v}</td></tr>"
        for k, v in (overages.items() if isinstance(overages, dict) else [])
    )
    return (
        "<html><body style='font-family:sans-serif;'>"
        "<h2>Usage approaching your plan limits</h2>"
        "<p>Some of your usage indicators are over the threshold for your plan:</p>"
        "<table border='1' cellpadding='0' cellspacing='0' style='border-collapse:collapse;'>"
        f"{rows}</table>"
        "<p>Consider upgrading or topping up from Settings to avoid interruption.</p>"
        "<p style='color:#888;font-size:12px;'>— Agience</p>"
        "</body></html>"
    )


async def _send_account_email(person_id: str, subject: str, body_html: str) -> None:
    """Best-effort platform email to a person, sent AS the system principal.

    Resolves the recipient's address, obtains a system delegation, and invokes the
    platform email operator under it. Non-fatal: a send failure never breaks the
    caller (e.g. a Stripe webhook must still succeed)."""
    if not person_id:
        return
    try:
        op_id = _platform_email_operator_id()
        if not op_id:
            log.warning("platform email skipped: cannot resolve operator id (no instance namespace)")
            return
        async with httpx.AsyncClient() as client:
            email = await _resolve_person_email(client, person_id)
            if not email:
                log.warning("platform email skipped: no address for person %s", person_id)
                return
            delegation = await _obtain_system_delegation(client)
            if not delegation:
                log.warning("platform email skipped: no system delegation obtained")
                return
            resp = await client.post(
                artifact_url(MANTLE_URI, op_id, "op", "invoke"),
                headers={"Authorization": f"Bearer {delegation}", "Content-Type": "application/json"},
                json={"params": {"to": email, "subject": subject, "body_html": body_html}},
                timeout=30,
            )
            resp.raise_for_status()
            log.info("platform email sent to %s (person %s)", email, person_id)
    except Exception:
        log.warning("platform email send failed for person %s", person_id, exc_info=True)


# ---------------------------------------------------------------------------
# Stripe webhook secret — resolved from a stored secret, never from the environment
# ---------------------------------------------------------------------------

#: This path is dead and this tool cannot succeed — measured 2026-08-26.
#:
#: `POST /secrets/reveal` was mantle's delegated stored-secret read. Mantle serves no `secrets`
#: plane: its top-level segments are .well-known, artifacts, auth, docs, events, git, grants,
#: mcp, status, system, v2 and version. The line below used to cite
#: `mantle/routers/secrets_router.py:286` — that FILE does not exist either; mantle's routers are
#: artifacts, events, git, grants, mcp, oci and system. A citation with a line number reads as
#: verified, and this one kept a dead call looking deliberate.
#:
#: It fails closed and loud, which is why it is recorded here rather than removed: the 404
#: raises `OphanToolError` naming the status, so Stripe webhook verification REFUSES rather than
#: passing something unverified. Broken, not dangerous.
#:
#: WHAT A REPLACEMENT NEEDS, so the next person does not start from scratch: secrets are
#: artifacts now, and seraph already reads them — `GET /artifacts/visible` narrowed by
#: `content_type=application/vnd.agience.credential+json`, then the artifact's content. What
#: is NOT established from here is whether THIS secret is stored in that shape, under which
#: selector — `(type, provider)` is what this call sends and a credential artifact carries its
#: own context. That is a fact about the store, not about this file, and guessing it would put
#: a silent wrong answer where a loud refusal now stands.
#:
#: The JWE flow is inoperative too —
#: `prism/trust/server_auth.py::ServerAuth.decrypt_jwe` raises `NotImplementedError`, so seraph's
#: `_fetch_and_decrypt_secret` cannot decrypt anything (its `except Exception` swallows the raise and
#: returns None). Resolving the webhook secret through the JWE path would silently yield None instead
#: of the secret.
_SECRET_REVEAL_PATH = "/secrets/reveal"

#: What the stored secret is called. A `(type, provider)` selector rather than an id, because the id is
#: per-instance and a persona must not carry instance state in code.
_STRIPE_WEBHOOK_SECRET_TYPE = "stripe_webhook_secret"
_STRIPE_PROVIDER = "stripe"

#: The Origin purpose this read needs. `platform-stripe` is not in
#: `origin/routers/auth_router.py:_SYSTEM_DELEGATION_PURPOSES` (only `platform-mail` and
#: `platform-llm` are), so `_obtain_system_delegation` currently returns 403 for it: the purpose is
#: what bounds the delegation, and inventing an unbounded one here — or reusing `platform-mail`, whose
#: scope is `platform.email.send` — would widen a platform authority from inside a persona. Origin owns
#: that vocabulary.
_STRIPE_DELEGATION_PURPOSE = "platform-stripe"


async def _resolve_stripe_webhook_secret() -> str:
    """The Stripe webhook signing secret, read from the stored secret. Raises — never returns `None`.

    This function raises on every call in the current tree, and the webhook handler turns that into
    a 503 that names the reason. It drives the real path — it is not a stub — but two platform pieces
    it depends on do not exist yet, and both are outside ophan:

      (a) `origin`: no `platform-stripe` system-delegation purpose, so the principal-less webhook path
          cannot obtain a delegation at all (403 "Unknown system delegation purpose").
      (b) `mantle`: `/secrets/reveal` requires `aud == act.sub` (the token was issued to the presenter),
          but `issue_system_delegation_token` stamps `aud` from the purpose table (`"mantle"`), never
          the requesting service. So even with (a) added, a system delegation is rejected as
          "token audience does not match presenter". One of the two must move, and which one is a
          platform decision, not a persona's.

    This must never fall back to an unverified path: a missing signing secret and a forged signature
    would otherwise be the same observable outcome. A payments webhook that cannot verify stays a
    named 503 rather than a quiet 400. See `_archive/OPHAN-STRIPE-TEKTON.md` §5.
    """
    try:
        async with httpx.AsyncClient() as client:
            delegation = await _obtain_system_delegation(client, purpose=_STRIPE_DELEGATION_PURPOSE)
            if not delegation:
                raise OphanToolError("Origin returned no token for the stripe system delegation.")
            resp = await client.post(
                f"{MANTLE_URI}{_SECRET_REVEAL_PATH}",
                headers={"Authorization": f"Bearer {delegation}", "Content-Type": "application/json"},
                json={"type": _STRIPE_WEBHOOK_SECRET_TYPE, "provider": _STRIPE_PROVIDER},
                timeout=15,
            )
            if resp.status_code != 200:
                raise OphanToolError(
                    f"stored-secret read refused: {resp.status_code} — {resp.text[:200]}"
                )
            material = (resp.json() or {}).get("material") or ""
    except OphanToolError:
        raise
    except Exception as exc:  # noqa: BLE001 — every failure surfaces as the same named error
        raise OphanToolError(
            f"could not reach the stored-secret path for the Stripe webhook secret: {exc}"
        ) from exc

    if not material:
        raise OphanToolError(
            f"no material for the '{_STRIPE_WEBHOOK_SECRET_TYPE}' secret artifact "
            f"(provider={_STRIPE_PROVIDER})."
        )
    return material


async def server_startup() -> None:
    """Run Ophan startup tasks. Trust map is on disk in Phase C; nothing to fetch."""
    await _auth.startup()


# ---------------------------------------------------------------------------
# Self-registration (GENESIS-NEXT §B1.10): this persona owns its registration.
# The host holds no roster — it calls each persona's register(). PERSONA is the
# single source of truth for {name, role, endpoint}; register() self-registers
# with Mantle (server record) + the crystal gateway (owned types).
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "ophan",
    "kind": "tekton",
    "role": "Economic Operations",
    "endpoint": "/ophan/mcp",
    "client_id": OPHAN_CLIENT_ID,
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


def _profiles_root() -> Path:
    """The licensing profile registry — delegated to `licensing`, which is the one place that knows it.

    `licensing._profiles_root()` returns `ophan/policy/`, where the real profiles live
    (`standard.json`, `managed-host.json`, `community-self-host.json`, …), with a documented
    `LICENSING_POLICY_ROOT` override for mounted config.
    """
    import licensing  # deferred: the module is persona-local (see the `import licensing` note below)
    return licensing._profiles_root()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _future_iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


@lru_cache(maxsize=1)
def _licensing_service():
    """Return the licensing module — lives next to this file in src/ophan/.

    Returned via a function (rather than top-level import) so this file's import
    chain stays tolerant when the host loads it via importlib's
    `spec_from_file_location` and the persona's directory hasn't been added to
    sys.path yet (see `src/server.py`'s persona-load loop).
    """
    here = Path(__file__).resolve().parent
    here_str = str(here)
    if here_str not in sys.path:
        sys.path.insert(0, here_str)
    import licensing  # noqa: E402 — see docstring

    return licensing


# Licensing scope helpers — the canonical definitions live in prism, so a persona reads the shape of a
# `licensing:entitlement:<name>` string without importing the AGPL identity service. What a scope
# means is a contract; `origin.scopes` keeps only the fastapi-coupled enforcement and re-exports the
# rest from here.
from prism.trust.scopes import (
    extract_licensing_entitlements as _extract_licensing_entitlements,
)


def _normalize_entitlements(values: Optional[list[str]]) -> set[str]:
    return {item.strip() for item in (values or []) if item and item.strip()}


def _resource_filter_values(resource_filters: Any, key: str) -> list[str]:
    if not isinstance(resource_filters, dict):
        return []
    raw = resource_filters.get(key)
    if raw == "*":
        return ["*"]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if item and str(item).strip()]


def _current_operator_claims() -> dict[str, Any]:
    claims = _CURRENT_OPERATOR_CLAIMS.get()
    if not claims:
        raise OphanToolError(
            "This operation requires a verified operator token with licensing authorization."
        )
    return claims


def _set_current_operator_claims_for_test(claims: Optional[dict[str, Any]]) -> object:
    return _CURRENT_OPERATOR_CLAIMS.set(claims)


def _reset_current_operator_claims_for_test(token: object) -> None:
    _CURRENT_OPERATOR_CLAIMS.reset(token)


def _require_workspace_access(claims: dict[str, Any], workspace_id: str, action: str) -> None:
    allowed = _resource_filter_values(claims.get("resource_filters"), "workspaces")
    if not allowed or "*" in allowed:
        return
    if workspace_id in allowed:
        return
    raise OphanToolError(
        f"{action} is gated. The verified operator token cannot access workspace '{workspace_id}'."
    )


def _resolve_operator_entitlements(workspace_id: str, action: str) -> set[str]:
    claims = _current_operator_claims()
    _require_workspace_access(claims, workspace_id, action)

    scopes = _as_string_list(claims.get("scopes"))
    entitlements = _extract_licensing_entitlements(scopes)
    return {item for item in entitlements if item in KNOWN_LICENSING_ENTITLEMENTS}


def _current_operator_summary(workspace_id: str, action: str) -> dict[str, Any]:
    claims = _current_operator_claims()
    return {
        "subject_id": claims.get("sub"),
        "client_id": claims.get("client_id"),
        "api_key_id": claims.get("api_key_id"),
        "authorized_entitlements": sorted(_resolve_operator_entitlements(workspace_id, action)),
    }


def _verify_operator_token(token: str) -> Optional[dict[str, Any]]:
    """Verify an operator JWT using Core's JWKS (fetched at startup)."""
    return _auth.verify_core_jwt(token)


def _extract_bearer_token(scope: dict[str, Any]) -> Optional[str]:
    for raw_name, raw_value in scope.get("headers") or []:
        if raw_name.decode("latin-1").lower() != "authorization":
            continue
        value = raw_value.decode("latin-1")
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        return token.strip()
    return None


async def _send_unauthorized(send: Any, message: str) -> None:
    body = json.dumps({"jsonrpc": "2.0", "error": {"code": -32001, "message": message}}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def create_server_app() -> Any:
    """Return the Ophan ASGI app with operator token verification.

    Note: ophan uses operator token verification (not delegation JWT middleware)
    because ophan tools require operator-scoped claims for entitlement checks.
    AgienceServerAuth instance handles JWKS fetch and server key registration.

    Also mounts /webhooks/stripe for raw Stripe webhook delivery (no auth — Stripe
    signature verification handles authentication internally).
    """
    mcp_app = streamable_http_app()

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path == "/webhooks/stripe" and scope.get("method", "").upper() == "POST":
                await _handle_stripe_webhook_http(scope, receive, send)
                return
        await mcp_app(scope, receive, send)

    return app


def streamable_http_app() -> Any:
    """Wrap the MCP ASGI app with optional operator token extraction.

    Auth is permissive at the transport level — if a valid operator JWT is
    present it is verified and stored in ``_CURRENT_OPERATOR_CLAIMS``;
    otherwise the request proceeds without claims.  Individual tools gate
    access via ``_current_operator_claims()`` which raises if claims are
    absent.

    This matches the other persona servers' pattern and allows MCP protocol
    calls (e.g. type discovery at startup) to succeed without a token.
    """
    inner_app = mcp.streamable_http_app()

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await inner_app(scope, receive, send)
            return

        token = _extract_bearer_token(scope)
        if token:
            claims = _verify_operator_token(token)
            if claims:
                context_token = _CURRENT_OPERATOR_CLAIMS.set(claims)
                try:
                    await inner_app(scope, receive, send)
                finally:
                    _CURRENT_OPERATOR_CLAIMS.reset(context_token)
                return

        await inner_app(scope, receive, send)

    return app


def _parse_json_argument(raw: Optional[str], field_name: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OphanToolError(f"{field_name} must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise OphanToolError(f"{field_name} must decode to a JSON object.")
    return parsed


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item)]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _organization_card_index(cards: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    index: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for card in cards:
        artifact_id = card.get("id")
        if artifact_id is None:
            continue
        index[str(artifact_id)] = (card, _parse_artifact_context(card))
    return index


def _organization_context_from_index(
    index: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    organization_artifact_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    item = index.get(str(organization_artifact_id))
    if item is None:
        raise OphanToolError(f"No organization card found for id '{organization_artifact_id}'.")
    card, context = item
    if context.get("content_type") != ORGANIZATION_CARD_MIME:
        raise OphanToolError(f"Card '{organization_artifact_id}' is not an organization card.")
    return card, context


def _profile_policy_id(profile_name: str) -> Optional[str]:
    refs = _as_string_list(_load_profile(profile_name).get("policy_refs"))
    return refs[0] if refs else None


def _organization_display_name(context: dict[str, Any], fallback_id: str) -> str:
    identity = _as_dict(context.get("identity"))
    return str(
        identity.get("display_name")
        or identity.get("legal_name")
        or context.get("title")
        or fallback_id
    )


def _resolve_public_license_posture(
    organization_artifact_id: str,
    organization_context: dict[str, Any],
    profile_name: str,
    profile_definition: dict[str, Any],
    index: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    identity = _as_dict(organization_context.get("identity"))
    licensing = _as_dict(organization_context.get("licensing"))
    packaging = _as_dict(licensing.get("packaging"))
    compliance = _as_dict(licensing.get("compliance"))

    entity_kind = str(identity.get("entity_kind") or "").strip().lower()
    if not entity_kind:
        raise OphanToolError("Organization card is missing 'identity.entity_kind'.")

    packaging_flags = {
        "managed_service": _coerce_bool(packaging.get("offers_managed_service")),
        "hosted_service": _coerce_bool(packaging.get("offers_hosted_service")),
        "oem": _coerce_bool(packaging.get("offers_oem")),
        "embedded": _coerce_bool(packaging.get("offers_embedded")),
        "white_label": _coerce_bool(packaging.get("offers_white_label")),
    }

    # AGPL compliance flags from organization card
    proprietary_modifications = _coerce_bool(compliance.get("proprietary_modifications"))
    closed_source_service = _coerce_bool(compliance.get("closed_source_service"))
    source_disclosed = _coerce_bool(compliance.get("source_disclosed"))

    profile_control_class = str(profile_definition.get("license_class") or "")
    commercial_by_profile = profile_control_class in {"white-label", "oem-embedded", "relay-client"} or profile_name == "managed-host"

    reasons: list[str] = []

    # Track 1 � Copyleft trigger: proprietary modifications or closed-source service without source disclosure
    if commercial_by_profile:
        reasons.append(f"Profile '{profile_name}' is a commercial distribution mode.")
    if proprietary_modifications and not source_disclosed:
        reasons.append("Organization uses proprietary modifications without disclosing source (AGPL copyleft opt-out).")
    if closed_source_service and not source_disclosed:
        reasons.append("Organization offers a closed-source managed service without disclosing source (AGPL copyleft opt-out).")

    # Track 2 � Trademark trigger: white-label always requires commercial license
    if packaging_flags["white_label"]:
        reasons.append("Organization declares white-label packaging (trademark license required regardless of AGPL compliance).")

    # Other packaging flags that imply commercial use
    for flag_name in ("managed_service", "hosted_service", "oem", "embedded"):
        if packaging_flags[flag_name]:
            reasons.append(f"Organization declares {flag_name.replace('_', ' ')} packaging in its organization card.")

    requires_license = bool(reasons)
    resolved_profile = profile_name
    resolved_policy_id = _profile_policy_id(profile_name)
    control_class = profile_control_class
    if not requires_license and profile_name in {"standard", "community-self-host"}:
        resolved_profile = "community-self-host"
        resolved_policy_id = _profile_policy_id("community-self-host")
        control_class = "community-self-host"
        reasons.append("Organization is AGPL-compliant with no white-label use; qualifies for community self-host.")

    return {
        "status": "ok",
        "organization_artifact_id": organization_artifact_id,
        "organization_name": _organization_display_name(organization_context, organization_artifact_id),
        "entity_kind": entity_kind,
        "input_profile": profile_name,
        "resolved_profile": resolved_profile,
        "resolved_policy_id": resolved_policy_id,
        "control_class": control_class,
        "requires_license": requires_license,
        "decision": "commercial" if requires_license else "community",
        "reasons": reasons,
        "compliance": {
            "proprietary_modifications": proprietary_modifications,
            "closed_source_service": closed_source_service,
            "source_disclosed": source_disclosed,
            "packaging": packaging_flags,
        },
    }


async def _resolve_license_posture_from_workspace(
    workspace_id: str,
    organization_artifact_id: str,
    profile_name: str,
) -> dict[str, Any]:
    cards = await _list_workspace_artifacts(workspace_id)
    index = _organization_card_index(cards)
    _card, context = _organization_context_from_index(index, organization_artifact_id)
    profile_definition = _load_profile(profile_name)
    result = _resolve_public_license_posture(
        organization_artifact_id,
        context,
        profile_name,
        profile_definition,
        index,
    )
    result["workspace_id"] = workspace_id
    return result


def _license_branding_mode(control_class: Optional[str], branding_scope: list[str], features: dict[str, Any]) -> Optional[str]:
    if control_class == "white-label":
        return "white-label"
    if branding_scope:
        return "white-label"
    if bool(features.get("allow_white_label")):
        return "white-label"
    return None


def _artifact_digest(payload: dict[str, Any]) -> str:
    return _licensing_service().digest_signed_payload(payload)


def _issue_signed_license_artifact(**kwargs: Any) -> dict[str, Any]:
    try:
        return _licensing_service().issue_license_artifact(**kwargs)
    except RuntimeError as exc:
        raise OphanToolError(str(exc)) from exc


def _issue_signed_activation_lease(**kwargs: Any) -> dict[str, Any]:
    try:
        return _licensing_service().issue_activation_lease(**kwargs)
    except RuntimeError as exc:
        raise OphanToolError(str(exc)) from exc


def _get_signed_license_artifact(context: dict[str, Any]) -> dict[str, Any]:
    artifact = context.get("signed_artifact")
    if not isinstance(artifact, dict):
        raise OphanToolError("License card does not contain a signed_artifact payload.")
    return artifact


@lru_cache(maxsize=32)
def _load_profile(profile_name: str) -> dict[str, Any]:
    path = _profiles_root() / f"{profile_name}.json"
    if not path.exists():
        raise OphanToolError(f"Unknown profile '{profile_name}'.")
    return json.loads(path.read_text(encoding="utf-8"))


def _profile_required_entitlements(profile_name: str) -> set[str]:
    return set(_load_profile(profile_name).get("required_entitlements", []))


def _profile_license_class(profile_name: str) -> Optional[str]:
    return _load_profile(profile_name).get("license_class")


def _profile_surface(profile_name: str) -> Optional[str]:
    return _load_profile(profile_name).get("product_surface")


def _require_any_licensing_entitlement(granted: set[str], action: str) -> None:
    if granted & KNOWN_LICENSING_ENTITLEMENTS:
        return
    raise OphanToolError(
        f"{action} is gated. The verified operator token does not grant any licensing entitlements."
    )


def _require_entitlements(granted: set[str], required: set[str], action: str) -> None:
    missing = sorted(required - granted)
    if missing:
        raise OphanToolError(
            f"{action} is gated. Missing required entitlements: {', '.join(missing)}."
        )


def _require_user_headers() -> dict[str, str]:
    """Headers carrying the caller's verified delegation JWT. Fails closed.

    Raises `MissingDelegationError` (`prism/trust/server_auth.py::ServerAuth.require_user_headers`)
    rather than falling back to ophan's platform JWT.
    """
    return _auth.require_user_headers()


async def _platform_request(method: str, path: str,
                            payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """A mantle call on ophan's own platform identity — for genuinely principal-less paths only.

    Kept as a separate function rather than a `user=False` flag on `_request`, so a static check that
    scans for a resource-id parameter alongside a service-identity call can tell the two apart: a
    boolean cannot express "this path is exempt" the way two distinct functions can. `_request`
    provably never reaches the platform JWT; only call sites that genuinely need it call this one.

    Use only where there is no delegated caller to fail closed on: the Stripe webhook / payment path.
    Never for anything reached from an MCP tool with a caller-supplied resource id.
    """
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method, f"{MANTLE_URI}{path}", headers=await _headers(), json=payload, timeout=60,
        )
    if response.status_code >= 400:
        raise OphanToolError(f"Platform request failed: {response.status_code} — {response.text[:300]}")
    return response.json() if response.text else {}


async def _request(method: str, path: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """One mantle call, fail-closed on the caller's delegation. No platform-identity fallback exists.

    Every caller-id call in this module funnels through here, and there is deliberately no opt-out
    parameter: the principal-less path is the separate `_platform_request` function, so that a static
    check scanning for a resource-id parameter alongside a service-identity call can tell the two
    apart. See its docstring.
    """
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            f"{MANTLE_URI}{path}",
            headers=_require_user_headers(),
            json=payload,
            timeout=60,
        )
    if response.status_code >= 400:
        raise OphanToolError(f"Platform request failed: {response.status_code} � {response.text[:300]}")
    if not response.text:
        return {}
    return response.json()


# There is no `/workspaces/*` route in this mantle: `main.py` includes secrets, downloads, artifacts,
# gate, search, issuers, grants, api_keys, platform, servers and events, and no workspaces router.
# A workspace is instead an ordinary artifact, and membership is a child edge — "an artifact in
# workspace W" is an artifact created with `container_id=W`. These three helpers are the one path
# every licensing, subscription and billing tool in this module writes through.
#
# `context` is passed to `_request` as a JSON string: `CreateArtifactRequest.context` and
# `UpdateArtifactRequest.context` are declared `Optional[str]`, not a dict.
async def _create_workspace_artifact(workspace_id: str, context: dict[str, Any], content: str) -> dict[str, Any]:
    return await _request(
        "POST",
        "/artifacts",
        {
            # `container_id` is the membership edge — the CRUDEASIO *Add* — and is how a workspace is
            # expressed now that it is an ordinary container artifact.
            "container_id": workspace_id,
            "context": json.dumps(context) if isinstance(context, (dict, list)) else context,
            "content": content,
        },
    )


async def _update_workspace_artifact(
    workspace_id: str,
    artifact_id: str,
    *,
    context: Optional[dict[str, Any]] = None,
    content: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if context is not None:
        payload["context"] = context
    if content is not None:
        payload["content"] = content
    # `workspace_id` is not part of the path: an artifact is addressed by its own id, and access is the
    # grant light-cone, not the container it happens to sit in. The parameter stays in the signature so
    # the ten callers do not all have to change, and because a caller naming the workspace it believes
    # the artifact lives in is still meaningful provenance for the error path.
    del workspace_id                       # not routed on — see the note above
    return await _request("PATCH", f"/artifacts/{artifact_id}", payload)


async def _list_workspace_artifacts(workspace_id: str) -> list[dict[str, Any]]:
    # A workspace is a container artifact, so "its artifacts" are its children. `workspace_id` is passed
    # again as the query param on purpose: that is what makes draft children visible, and a draft is
    # workspace-private, so omitting it silently hides uncommitted rows (which is how a retry ends up
    # duplicating an interrupted write).
    response = await _request("GET", f"/artifacts/{workspace_id}/children?workspace_id={workspace_id}")
    # `/children` returns a bare list; a dict with an `items` list is accepted too rather than guessed
    # at, because an unexpected shape here silently becomes "this workspace is empty", and an empty
    # list is exactly the answer that makes a licensing tool mint a duplicate instead of finding the
    # existing artifact.
    if isinstance(response, list):
        return response
    items = response.get("items") if isinstance(response, dict) else None
    if isinstance(items, list):
        return items
    return []


def _parse_artifact_context(card: dict[str, Any]) -> dict[str, Any]:
    raw = card.get("context")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


async def _find_workspace_artifact(
    workspace_id: str,
    *,
    content_type: str,
    identity_key: str,
    identity_value: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for card in await _list_workspace_artifacts(workspace_id):
        context = _parse_artifact_context(card)
        if context.get("content_type") != content_type:
            continue
        if context.get(identity_key) == identity_value:
            return card, context
    raise OphanToolError(
        f"No card found in workspace '{workspace_id}' for {identity_key}='{identity_value}'."
    )


def _title_from_prefix(prefix: str, identifier: str) -> str:
    return f"{prefix} {identifier}"


def _summarize_limits(limits: dict[str, Any]) -> str:
    if not limits:
        return "No explicit limits recorded."
    return ", ".join(f"{key}={value}" for key, value in sorted(limits.items()))


def _artifact_id_from_response(response: dict[str, Any]) -> Optional[str]:
    return response.get("id") or response.get("card", {}).get("id")


mcp = FastMCP(
    "agience-server-ophan",
    instructions=(
        "You are Ophan, the economic operations layer of the Agience platform. "
        "You execute and record value transfers, maintain double-entry ledgers, reconcile "
        "accounts, track market data, measure resource usage and performance, manage "
        "budgets, and operate licensing and commercial entitlement workflows. Every financial or "
        "licensing action must be recorded as an auditable card. "
        "Treat financial credentials with extreme care � always retrieve them per-request "
        "from the platform secrets service."
    ),
)

from mantle.clients.artifact_helpers import artifact_url, register_types_manifest
register_types_manifest(mcp, "ophan", __file__)


# ---------------------------------------------------------------------------
# Value — the energy economy (UNIVERSAL-ECONOMICS §12)
# ---------------------------------------------------------------------------
#
# The platform's value model is energy, not fiat or crypto rails: there are no payment or chain rails
# anywhere in the workspace. Energy accrues to an artifact, cools by the 2nd law (`exp(-dt/tau)`), and
# settles with a flat Origin fee — flat because a percentage is economic rent, while a flat fee
# shrinks as a fraction of value as value grows. A rate is measured at the screen, never configured,
# and each Origin is its own currency.
#
# The laws are pure and stdlib-only, and live in `prism`, so the server and the leaf compute the same
# answer for who gets paid. Ophan applies them directly rather than asking a service: this is not
# re-deriving a decision client-side, it is running the one shared law.

from prism import demurrage as _demurrage          # noqa: E402
from prism import settlement as _settlement        # noqa: E402


def _frame_of(artifact: dict[str, Any], now_frame: Optional[int]) -> int:
    """The 2nd-law clock is a frame, not a wall clock — one frame = one change-feed step (mesh `_seq`),
    the same monotone axis `mass.age_frames` counts. Wall-clock time here would make energy depend on
    how long a node happened to be switched on."""
    if now_frame is not None:
        return int(now_frame)
    seq = artifact.get("_seq")
    if seq is None:
        raise OphanToolError(
            "cannot read the current frame (`_seq`) from the artifact, and no `now_frame` was given. "
            "Energy is a function of frames elapsed; guessing one would fabricate a value."
        )
    return int(seq)


@mcp.tool(description="Read an artifact's energy, realised value, and thermal state (the 2nd-law economy)")
async def get_energy(
    artifact_id: str,
    now_frame: Optional[int] = None,
) -> str:
    """Energy, earned value and temperature for one artifact.

    - `energy`  — standing heat cooled to the current frame (`exp(-dt/tau)`); value decays unless
      re-witnessed. This is the 2nd law, not a policy.
    - `earned`  — the realised-value integral through the last-settled frame; the settlement basis.
    - `temperature` — the thermal classification (hot/warm/cold) derived from the same reading.

    All three are read from the artifact's own stored heat/frame/rest-mass, so this is a measurement,
    never a quote.
    """
    artifact = await _request("GET", f"/artifacts/{artifact_id}")
    now = _frame_of(artifact, now_frame)
    return json.dumps({
        "artifact_id": artifact_id,
        "frame": now,
        "energy": _demurrage.energy(artifact, now),
        "earned": _demurrage.earned(artifact, now),
        "temperature": _demurrage.temperature(artifact, now),
    })


@mcp.tool(description="Compute the settlement split for an artifact's earned value (flat Origin fee)")
async def settle_energy(
    artifact_id: str,
    fee: float,
    now_frame: Optional[int] = None,
) -> str:
    """How an artifact's earned energy divides between the governing Origin and the producer.

    The Origin's cut is flat, never a percentage — that is the anti-rent design, not a tunable.
    The only bound is conservation: the Origin cannot take energy that was never earned
    (`min(fee, earned)`), which is the 1st law rather than an arbitrary cap.

    Computes only; moves nothing. There is no payment rail in this platform — it reports the split
    that settlement would produce.
    """
    artifact = await _request("GET", f"/artifacts/{artifact_id}")
    now = _frame_of(artifact, now_frame)
    earned = _demurrage.earned(artifact, now)
    split = _settlement.facilitation_split(earned, fee=float(fee))
    # `Split`'s own docstring says conservation is checkable — so check it rather than trust it.
    # A split that does not conserve is a minting bug, and reporting it as a payout would launder one.
    conserved = abs((split.to_producer + split.to_origin) - split.earned) < 1e-9
    if not conserved:
        raise OphanToolError(
            "settlement did not conserve: to_producer + to_origin != earned "
            "(%r + %r != %r) — refusing to report a payout that creates or destroys energy"
            % (split.to_producer, split.to_origin, split.earned))
    return json.dumps({
        "artifact_id": artifact_id, "frame": now,
        "earned": split.earned,
        "to_origin": split.to_origin,        # flat facilitation fee, min(fee, earned)
        "to_producer": split.to_producer,
        "conserved": conserved,
        "note": "computed only — no value was moved; this platform has no payment rail",
    })


@mcp.tool(description="Resolve whether an organization is AGPL-compliant (community self-host) or needs a commercial license")
async def resolve_license_posture(
    workspace_id: str,
    organization_artifact_id: str,
    profile: str = "standard",
) -> str:
    try:
        claims = _current_operator_claims()
        _require_workspace_access(claims, workspace_id, "resolve_license_posture")
        return _json_result(await _resolve_license_posture_from_workspace(workspace_id, organization_artifact_id, profile))
    except OphanToolError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(description="Create and sign a license artifact from entitlement inputs or approved policy parameters")
async def issue_license(
    workspace_id: str,
    policy_id: str,
    account_id: str,
    profile: str,
    organization_artifact_id: Optional[str] = None,
    expires_at: Optional[str] = None,
    runtime_role: str = "standard",
    branding_scope: Optional[list[str]] = None,
    limits: Optional[str] = None,
    features: Optional[str] = None,
    downstream_customer: Optional[str] = None,
) -> str:
    try:
        posture: Optional[dict[str, Any]] = None
        if organization_artifact_id:
            posture = await _resolve_license_posture_from_workspace(workspace_id, organization_artifact_id, profile)
            if not posture["requires_license"]:
                return _json_result(
                    {
                        "status": "not_required",
                        "workspace_id": workspace_id,
                        "organization_artifact_id": organization_artifact_id,
                        "account_id": account_id,
                        "posture": posture,
                    }
                )
            if profile == "community-self-host":
                raise OphanToolError(
                    "Organization requires a commercial license; use the commercial 'standard' profile instead of 'community-self-host'."
                )

        granted = _resolve_operator_entitlements(workspace_id, "issue_license")
        operator = _current_operator_summary(workspace_id, "issue_license")
        required = ADVANCED_OPERATIONS_ENTITLEMENTS | _profile_required_entitlements(profile)
        _require_entitlements(granted, required, "issue_license")

        profile_definition = _load_profile(profile)
        issued_at = _now_iso()
        entitlement_id = f"ent_{uuid4().hex[:12]}"
        license_id = f"lic_{uuid4().hex[:12]}"
        effective_expires_at = expires_at or _future_iso(365)
        parsed_limits = _parse_json_argument(limits, "limits")
        parsed_features = _parse_json_argument(features, "features")
        control_class = _profile_license_class(profile)
        product_surface = _profile_surface(profile)
        license_entitlements = sorted(_profile_required_entitlements(profile))
        effective_branding_scope = branding_scope or []
        signed_artifact = _issue_signed_license_artifact(
            license_id=license_id,
            entitlement_id=entitlement_id,
            account_id=account_id,
            issued_at=issued_at,
            not_before=issued_at,
            expires_at=effective_expires_at,
            policy_id=policy_id,
            runtime_roles=[runtime_role],
            distribution_profiles=[profile],
            product_surface=product_surface,
            branding_mode=_license_branding_mode(control_class, effective_branding_scope, parsed_features),
            branding_scope=effective_branding_scope,
            state="active",
            offline_allowed=bool(profile_definition.get("offline_supported", True)),
            require_activation=True,
            require_reporting=True,
            offline_lease_days=30 if profile_definition.get("offline_supported", True) else None,
            enforcement_profile=control_class,
            limits=parsed_limits,
            features=parsed_features,
            reporting={
                "dimensions": _as_string_list(profile_definition.get("meter_dimensions")),
                "snapshot_interval_hours": 24,
            },
            entitlements=license_entitlements,
            attributes={
                "downstream_customer": downstream_customer,
            }
            if downstream_customer
            else {},
            extensions={
                "issued_by": "ophan",
                "profile": profile,
            },
        )

        entitlement_context = {
            "type": "entitlement",
            "title": _title_from_prefix("Entitlement", entitlement_id),
            "content_type": ENTITLEMENT_CARD_MIME,
            "entitlement_id": entitlement_id,
            "account_id": account_id,
            "policy_id": policy_id,
            "profile": profile,
            "runtime_roles": [runtime_role],
            "state": "active",
            "required_entitlements": license_entitlements,
            "operator": operator,
            "branding_scope": effective_branding_scope,
            "downstream_customer": downstream_customer,
            "issued_at": issued_at,
            "expires_at": effective_expires_at,
        }
        entitlement_content = (
            f"Entitlement {entitlement_id} for account {account_id} under policy {policy_id}. "
            f"Profile {profile}; required entitlements: {', '.join(license_entitlements) or 'none'}."
        )
        entitlement_artifact = await _create_workspace_artifact(workspace_id, entitlement_context, entitlement_content)

        license_context = {
            "type": "license",
            "title": _title_from_prefix("License", license_id),
            "content_type": LICENSE_CARD_MIME,
            "license_id": license_id,
            "entitlement_id": entitlement_id,
            "account_id": account_id,
            "policy_id": policy_id,
            "control_class": control_class,
            "product_surface": product_surface,
            "runtime_roles": [runtime_role],
            "distribution_profiles": [profile],
            "branding_scope": effective_branding_scope,
            "state": "active",
            "issued_at": issued_at,
            "not_before": issued_at,
            "expires_at": effective_expires_at,
            "artifact_status": "issued",
            "artifact_ref": f"ophan://licenses/{license_id}",
            "artifact_hash": _artifact_digest(signed_artifact),
            "signed_artifact": signed_artifact,
            "limits": parsed_limits,
            "features": parsed_features,
            "entitlements": license_entitlements,
            "downstream_customer": downstream_customer,
        }
        license_content = (
            f"License {license_id} is active for account {account_id}. "
            f"Profile {profile}; limits: {_summarize_limits(parsed_limits)}."
        )
        license_artifact = await _create_workspace_artifact(workspace_id, license_context, license_content)

        event_context = {
            "type": "license-event",
            "title": _title_from_prefix("Licensing Event", f"issued-{license_id}"),
            "content_type": EVENT_CARD_MIME,
            "event_type": "license_issued",
            "severity": "info",
            "account_id": account_id,
            "license_id": license_id,
            "entitlement_id": entitlement_id,
            "policy_id": policy_id,
            "profile": profile,
            "created_at": issued_at,
        }
        event_content = (
            f"Issued license {license_id} for account {account_id} under profile {profile}."
        )
        event_artifact = await _create_workspace_artifact(workspace_id, event_context, event_content)

        return _json_result(
            {
                "status": "issued",
                "workspace_id": workspace_id,
                "license_id": license_id,
                "entitlement_id": entitlement_id,
                **({"posture": posture} if posture else {}),
                "artifact": signed_artifact,
                "created_cards": {
                    "entitlement_artifact_id": _artifact_id_from_response(entitlement_artifact),
                    "license_artifact_id": _artifact_id_from_response(license_artifact),
                    "event_artifact_id": _artifact_id_from_response(event_artifact),
                },
                "required_entitlements": sorted(required),
            }
        )
    except OphanToolError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(description="Extend, replace, or reissue an existing license artifact")
async def renew_license(
    workspace_id: str,
    license_id: str,
    expires_at: Optional[str] = None,
) -> str:
    try:
        granted = _resolve_operator_entitlements(workspace_id, "renew_license")
        _require_entitlements(granted, ADVANCED_OPERATIONS_ENTITLEMENTS, "renew_license")

        card, context = await _find_workspace_artifact(
            workspace_id,
            content_type=LICENSE_CARD_MIME,
            identity_key="license_id",
            identity_value=license_id,
        )
        renewed_at = _now_iso()
        existing_artifact = _get_signed_license_artifact(context)
        updated_expires_at = expires_at or _future_iso(365)
        renewal_count = int(context.get("renewal_count", 0)) + 1
        signed_artifact = _issue_signed_license_artifact(
            license_id=license_id,
            entitlement_id=str(context.get("entitlement_id") or ""),
            account_id=str(context.get("account_id") or ""),
            issued_at=renewed_at,
            not_before=renewed_at,
            expires_at=updated_expires_at,
            policy_id=str(context.get("policy_id") or existing_artifact["product"]["policy_id"]),
            runtime_roles=_as_string_list(context.get("runtime_roles")) or _as_string_list(existing_artifact["product"].get("runtime_roles")),
            distribution_profiles=_as_string_list(context.get("distribution_profiles")) or _as_string_list(existing_artifact["product"].get("distribution_profiles")),
            product_surface=context.get("product_surface") or existing_artifact["product"].get("product_surface"),
            branding_mode=(existing_artifact.get("branding") or {}).get("mode"),
            branding_scope=_as_string_list(context.get("branding_scope")) or _as_string_list((existing_artifact.get("branding") or {}).get("scope")),
            state="active",
            offline_allowed=bool(existing_artifact.get("controls", {}).get("offline_allowed", True)),
            require_activation=bool(existing_artifact.get("controls", {}).get("require_activation", True)),
            require_reporting=bool(existing_artifact.get("controls", {}).get("require_reporting", True)),
            offline_lease_days=existing_artifact.get("controls", {}).get("offline_lease_days"),
            enforcement_profile=existing_artifact.get("controls", {}).get("enforcement_profile") or context.get("control_class"),
            limits=_as_dict(context.get("limits")) or _as_dict(existing_artifact.get("limits")),
            features=_as_dict(context.get("features")) or _as_dict(existing_artifact.get("features")),
            reporting=_as_dict(existing_artifact.get("reporting")),
            entitlements=_as_string_list(context.get("entitlements")) or _as_string_list(existing_artifact.get("entitlements")),
            attributes=_as_dict(existing_artifact.get("attributes")),
            extensions={
                **_as_dict(existing_artifact.get("extensions")),
                "renewed_at": renewed_at,
                "renewal_count": renewal_count,
            },
        )
        updated_context = {
            **context,
            "state": "active",
            "expires_at": updated_expires_at,
            "last_renewed_at": renewed_at,
            "renewal_count": renewal_count,
            "artifact_status": "issued",
            "artifact_hash": _artifact_digest(signed_artifact),
            "signed_artifact": signed_artifact,
        }
        updated_content = (
            f"License {license_id} renewed. New expiry {updated_context['expires_at']}."
        )
        updated_artifact = await _update_workspace_artifact(
            workspace_id,
            card["id"],
            context=updated_context,
            content=updated_content,
        )
        event_context = {
            "type": "license-event",
            "title": _title_from_prefix("Licensing Event", f"renewed-{license_id}"),
            "content_type": EVENT_CARD_MIME,
            "event_type": "license_renewed",
            "severity": "info",
            "license_id": license_id,
            "account_id": context.get("account_id"),
            "created_at": renewed_at,
        }
        event_artifact = await _create_workspace_artifact(
            workspace_id,
            event_context,
            f"Renewed license {license_id}; expires {updated_context['expires_at']}.",
        )
        return _json_result(
            {
                "status": "renewed",
                "workspace_id": workspace_id,
                "license_id": license_id,
                "license_artifact_id": _artifact_id_from_response(updated_artifact),
                "event_artifact_id": _artifact_id_from_response(event_artifact),
                "expires_at": updated_context["expires_at"],
                "artifact": signed_artifact,
            }
        )
    except OphanToolError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(description="Revoke a license and record the resulting compliance event")
async def revoke_license(
    workspace_id: str,
    license_id: str,
    reason: Optional[str] = None,
) -> str:
    try:
        granted = _resolve_operator_entitlements(workspace_id, "revoke_license")
        _require_entitlements(granted, ADVANCED_OPERATIONS_ENTITLEMENTS, "revoke_license")

        card, context = await _find_workspace_artifact(
            workspace_id,
            content_type=LICENSE_CARD_MIME,
            identity_key="license_id",
            identity_value=license_id,
        )
        revoked_at = _now_iso()
        revoke_reason = reason or "No reason provided."
        existing_artifact = _get_signed_license_artifact(context)
        signed_artifact = _issue_signed_license_artifact(
            license_id=license_id,
            entitlement_id=str(context.get("entitlement_id") or ""),
            account_id=str(context.get("account_id") or ""),
            issued_at=str(context.get("issued_at") or revoked_at),
            not_before=str(context.get("not_before") or revoked_at),
            expires_at=str(context.get("expires_at") or revoked_at),
            policy_id=str(context.get("policy_id") or existing_artifact["product"]["policy_id"]),
            runtime_roles=_as_string_list(context.get("runtime_roles")) or _as_string_list(existing_artifact["product"].get("runtime_roles")),
            distribution_profiles=_as_string_list(context.get("distribution_profiles")) or _as_string_list(existing_artifact["product"].get("distribution_profiles")),
            product_surface=context.get("product_surface") or existing_artifact["product"].get("product_surface"),
            branding_mode=(existing_artifact.get("branding") or {}).get("mode"),
            branding_scope=_as_string_list(context.get("branding_scope")) or _as_string_list((existing_artifact.get("branding") or {}).get("scope")),
            state="revoked",
            offline_allowed=bool(existing_artifact.get("controls", {}).get("offline_allowed", True)),
            require_activation=bool(existing_artifact.get("controls", {}).get("require_activation", True)),
            require_reporting=bool(existing_artifact.get("controls", {}).get("require_reporting", True)),
            offline_lease_days=existing_artifact.get("controls", {}).get("offline_lease_days"),
            enforcement_profile=existing_artifact.get("controls", {}).get("enforcement_profile") or context.get("control_class"),
            limits=_as_dict(context.get("limits")) or _as_dict(existing_artifact.get("limits")),
            features=_as_dict(context.get("features")) or _as_dict(existing_artifact.get("features")),
            reporting=_as_dict(existing_artifact.get("reporting")),
            entitlements=_as_string_list(context.get("entitlements")) or _as_string_list(existing_artifact.get("entitlements")),
            attributes=_as_dict(existing_artifact.get("attributes")),
            extensions={
                **_as_dict(existing_artifact.get("extensions")),
                "revoked_at": revoked_at,
                "revoke_reason": revoke_reason,
            },
        )
        updated_context = {
            **context,
            "state": "revoked",
            "revoked_at": revoked_at,
            "revoke_reason": revoke_reason,
            "artifact_status": "revoked",
            "artifact_hash": _artifact_digest(signed_artifact),
            "signed_artifact": signed_artifact,
        }
        updated_artifact = await _update_workspace_artifact(
            workspace_id,
            card["id"],
            context=updated_context,
            content=f"License {license_id} was revoked. Reason: {revoke_reason}",
        )
        event_context = {
            "type": "license-event",
            "title": _title_from_prefix("Licensing Event", f"revoked-{license_id}"),
            "content_type": EVENT_CARD_MIME,
            "event_type": "license_revoked",
            "severity": "warning",
            "license_id": license_id,
            "account_id": context.get("account_id"),
            "reason": revoke_reason,
            "created_at": revoked_at,
        }
        event_artifact = await _create_workspace_artifact(
            workspace_id,
            event_context,
            f"Revoked license {license_id}. Reason: {revoke_reason}",
        )
        return _json_result(
            {
                "status": "revoked",
                "workspace_id": workspace_id,
                "license_id": license_id,
                "license_artifact_id": _artifact_id_from_response(updated_artifact),
                "event_artifact_id": _artifact_id_from_response(event_artifact),
                "artifact": signed_artifact,
            }
        )
    except OphanToolError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(description="Inspect installation state, activation status, and lease freshness")
async def review_installation(
    workspace_id: str,
    install_id: Optional[str] = None,
    instance_id: Optional[str] = None,
    device_id: Optional[str] = None,
    license_id: Optional[str] = None,
    profile: Optional[str] = None,
) -> str:
    try:
        granted = _resolve_operator_entitlements(workspace_id, "review_installation")
        _require_any_licensing_entitlement(granted, "review_installation")

        cards = await _list_workspace_artifacts(workspace_id)
        installation_artifacts: list[dict[str, Any]] = []
        matched_artifact: Optional[dict[str, Any]] = None
        matched_context: Optional[dict[str, Any]] = None
        for card in cards:
            context = _parse_artifact_context(card)
            if context.get("content_type") != INSTALLATION_CARD_MIME:
                continue
            installation_artifacts.append({"card": card, "context": context})
            if install_id and context.get("install_id") == install_id:
                matched_artifact, matched_context = card, context
            if instance_id and context.get("instance_id") == instance_id:
                matched_artifact, matched_context = card, context
            if device_id and context.get("device_id") == device_id:
                matched_artifact, matched_context = card, context

        if not any([install_id, instance_id, device_id]):
            return _json_result(
                {
                    "status": "ok",
                    "workspace_id": workspace_id,
                    "count": len(installation_artifacts),
                    "installations": [
                        {
                            "artifact_id": item["card"].get("id"),
                            "install_id": item["context"].get("install_id"),
                            "license_id": item["context"].get("license_id"),
                            "profile": item["context"].get("profile"),
                            "compliance_state": item["context"].get("compliance_state"),
                            "lease_expires_at": item["context"].get("lease_expires_at"),
                        }
                        for item in installation_artifacts
                    ],
                }
            )

        reviewed_at = _now_iso()
        if matched_artifact and matched_context:
            activation_lease = None
            if matched_context.get("license_id") and matched_context.get("profile"):
                _, linked_license_context = await _find_workspace_artifact(
                    workspace_id,
                    content_type=LICENSE_CARD_MIME,
                    identity_key="license_id",
                    identity_value=str(matched_context["license_id"]),
                )
                signed_artifact = _get_signed_license_artifact(linked_license_context)
                preflight = _licensing_service().preflight_license(str(matched_context["profile"]), signed_artifact)
                if not preflight.verification.valid or not preflight.compatibility.allowed:
                    raise OphanToolError(
                        f"Cannot issue activation lease for install '{matched_context.get('install_id')}'."
                    )
                runtime_role = str(
                    matched_context.get("runtime_role")
                    or _load_profile(str(matched_context["profile"])).get("runtime_role")
                    or signed_artifact["product"]["runtime_roles"][0]
                )
                offline_lease_days = signed_artifact.get("controls", {}).get("offline_lease_days") or 30
                lease_expires_at = _future_iso(int(offline_lease_days))
                activation_lease = _issue_signed_activation_lease(
                    lease_id=f"lease_{uuid4().hex[:12]}",
                    license_id=str(matched_context["license_id"]),
                    install_id=str(matched_context.get("install_id") or matched_artifact["id"]),
                    runtime_role=runtime_role,
                    issued_at=reviewed_at,
                    not_before=reviewed_at,
                    lease_expires_at=lease_expires_at,
                    instance_id=matched_context.get("instance_id"),
                    device_id=matched_context.get("device_id"),
                    profile=str(matched_context["profile"]),
                    heartbeat_interval_hours=24 if signed_artifact.get("controls", {}).get("require_reporting", True) else None,
                    reporting=_as_dict(signed_artifact.get("reporting")),
                    attributes={"workspace_id": workspace_id},
                    extensions={"issued_by": "ophan"},
                )

            updated_context = {
                **matched_context,
                "last_reviewed_at": reviewed_at,
                "compliance_state": matched_context.get("compliance_state", "active"),
                **(
                    {
                        "last_validated_at": reviewed_at,
                        "lease_expires_at": activation_lease["lease_expires_at"],
                        "activation_lease_ref": f"ophan://leases/{activation_lease['lease_id']}",
                        "activation_lease_hash": _artifact_digest(activation_lease),
                        "activation_lease": activation_lease,
                    }
                    if activation_lease
                    else {}
                ),
            }
            updated_artifact = await _update_workspace_artifact(
                workspace_id,
                matched_artifact["id"],
                context=updated_context,
                content=(
                    f"Installation {updated_context.get('install_id', matched_artifact['id'])} reviewed at {reviewed_at}."
                ),
            )
            return _json_result(
                {
                    "status": "reviewed",
                    "workspace_id": workspace_id,
                    "installation_artifact_id": _artifact_id_from_response(updated_artifact),
                    "install_id": updated_context.get("install_id"),
                    "compliance_state": updated_context.get("compliance_state"),
                    **({"activation_lease": activation_lease} if activation_lease else {}),
                }
            )

        created_install_id = install_id or f"inst_{uuid4().hex[:12]}"
        activation_lease = None
        effective_profile = profile
        if license_id:
            _, linked_license_context = await _find_workspace_artifact(
                workspace_id,
                content_type=LICENSE_CARD_MIME,
                identity_key="license_id",
                identity_value=license_id,
            )
            signed_artifact = _get_signed_license_artifact(linked_license_context)
            if not effective_profile:
                effective_profile = (_as_string_list(linked_license_context.get("distribution_profiles")) or _as_string_list(signed_artifact["product"].get("distribution_profiles")) or [None])[0]
            if effective_profile:
                preflight = _licensing_service().preflight_license(str(effective_profile), signed_artifact)
                if not preflight.verification.valid or not preflight.compatibility.allowed:
                    raise OphanToolError(
                        f"Cannot issue activation lease for install '{created_install_id}'."
                    )
                runtime_role = str(
                    _load_profile(str(effective_profile)).get("runtime_role")
                    or signed_artifact["product"]["runtime_roles"][0]
                )
                offline_lease_days = signed_artifact.get("controls", {}).get("offline_lease_days") or 30
                activation_lease = _issue_signed_activation_lease(
                    lease_id=f"lease_{uuid4().hex[:12]}",
                    license_id=license_id,
                    install_id=created_install_id,
                    runtime_role=runtime_role,
                    issued_at=reviewed_at,
                    not_before=reviewed_at,
                    lease_expires_at=_future_iso(int(offline_lease_days)),
                    instance_id=instance_id,
                    device_id=device_id,
                    profile=str(effective_profile),
                    heartbeat_interval_hours=24 if signed_artifact.get("controls", {}).get("require_reporting", True) else None,
                    reporting=_as_dict(signed_artifact.get("reporting")),
                    attributes={"workspace_id": workspace_id},
                    extensions={"issued_by": "ophan"},
                )
            else:
                raise OphanToolError("A licensed installation review requires a profile.")

        installation_context = {
            "type": "license-installation",
            "title": _title_from_prefix("Installation", created_install_id),
            "content_type": INSTALLATION_CARD_MIME,
            "install_id": created_install_id,
            "license_id": license_id,
            "instance_id": instance_id,
            "device_id": device_id,
            "profile": effective_profile,
            "runtime_role": (
                activation_lease["runtime_role"]
                if activation_lease
                else "standard"
            ),
            "compliance_state": "active" if license_id else "needs-license",
            "last_validated_at": reviewed_at,
            "lease_expires_at": activation_lease["lease_expires_at"] if activation_lease else _future_iso(30),
            "last_reviewed_at": reviewed_at,
            **(
                {
                    "activation_lease_ref": f"ophan://leases/{activation_lease['lease_id']}",
                    "activation_lease_hash": _artifact_digest(activation_lease),
                    "activation_lease": activation_lease,
                }
                if activation_lease
                else {}
            ),
        }
        installation_artifact = await _create_workspace_artifact(
            workspace_id,
            installation_context,
            f"Installation {created_install_id} reviewed at {reviewed_at}.",
        )
        return _json_result(
            {
                "status": "observed",
                "workspace_id": workspace_id,
                "installation_artifact_id": _artifact_id_from_response(installation_artifact),
                "install_id": created_install_id,
                "compliance_state": installation_context["compliance_state"],
                **({"activation_lease": activation_lease} if activation_lease else {}),
            }
        )
    except OphanToolError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(description="Ingest or reconcile aggregate licensing and metering snapshots")
async def record_usage_snapshot(
    workspace_id: str,
    snapshot_artifact_id: Optional[str] = None,
    snapshot_payload: Optional[str] = None,
    account_id: Optional[str] = None,
    license_id: Optional[str] = None,
) -> str:
    try:
        granted = _resolve_operator_entitlements(workspace_id, "record_usage_snapshot")
        _require_any_licensing_entitlement(granted, "record_usage_snapshot")
        payload = _parse_json_argument(snapshot_payload, "snapshot_payload")
        captured_at = payload.get("captured_at") or _now_iso()
        usage_id = payload.get("usage_id") or f"usage_{uuid4().hex[:12]}"
        usage_context = {
            "type": "license-usage",
            "title": _title_from_prefix("Usage Snapshot", usage_id),
            "content_type": USAGE_CARD_MIME,
            "usage_id": usage_id,
            "account_id": account_id or payload.get("account_id"),
            "license_id": license_id or payload.get("license_id"),
            "captured_at": captured_at,
            "reporting_period": payload.get("reporting_period"),
            "usage": payload.get("usage", {}),
            "allowances": payload.get("allowances", {}),
            "source_artifact_id": snapshot_artifact_id,
            "state": "recorded",
        }
        usage_artifact = await _create_workspace_artifact(
            workspace_id,
            usage_context,
            f"Usage snapshot {usage_id} recorded at {captured_at}.",
        )

        created_cards = {"usage_artifact_id": _artifact_id_from_response(usage_artifact)}
        overages = payload.get("overages")
        if isinstance(overages, dict) and overages:
            event_context = {
                "type": "license-event",
                "title": _title_from_prefix("Licensing Event", f"usage-{usage_id}"),
                "content_type": EVENT_CARD_MIME,
                "event_type": "usage_threshold_warning",
                "severity": "warning",
                "license_id": usage_context.get("license_id"),
                "account_id": usage_context.get("account_id"),
                "created_at": captured_at,
                "details": overages,
            }
            event_artifact = await _create_workspace_artifact(
                workspace_id,
                event_context,
                f"Usage snapshot {usage_id} recorded overage indicators: {json.dumps(overages, sort_keys=True)}",
            )
            created_cards["event_artifact_id"] = _artifact_id_from_response(event_artifact)

            # Usage warning — sent AS the operator-rooted system principal
            # (best-effort) to the account holder.
            account_id = usage_context.get("account_id")
            if account_id:
                await _send_account_email(
                    str(account_id), "Agience usage warning", _usage_warning_html(overages)
                )

        return _json_result(
            {
                "status": "recorded",
                "workspace_id": workspace_id,
                "usage_id": usage_id,
                "created_cards": created_cards,
            }
        )
    except OphanToolError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(description="Produce entitlement, installation, renewal, or overage report cards")
async def run_licensing_report(
    workspace_id: str,
    report_type: str = "entitlements",
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> str:
    try:
        granted = _resolve_operator_entitlements(workspace_id, "run_licensing_report")
        _require_entitlements(granted, ADVANCED_OPERATIONS_ENTITLEMENTS, "run_licensing_report")

        cards = await _list_workspace_artifacts(workspace_id)
        family = {
            ENTITLEMENT_CARD_MIME: "entitlements",
            LICENSE_CARD_MIME: "licenses",
            INSTALLATION_CARD_MIME: "installations",
            USAGE_CARD_MIME: "usage_snapshots",
            EVENT_CARD_MIME: "events",
        }
        counts = {value: 0 for value in family.values()}
        active_licenses = 0
        revoked_licenses = 0
        warnings = 0
        for card in cards:
            context = _parse_artifact_context(card)
            content_type = context.get("content_type")
            bucket = family.get(content_type)
            if bucket:
                counts[bucket] += 1
            if content_type == LICENSE_CARD_MIME and context.get("state") == "active":
                active_licenses += 1
            if content_type == LICENSE_CARD_MIME and context.get("state") == "revoked":
                revoked_licenses += 1
            if content_type == EVENT_CARD_MIME and context.get("severity") == "warning":
                warnings += 1

        generated_at = _now_iso()
        markdown = "\n".join(
            [
                f"# Licensing Report — {report_type}",
                "",
                f"Generated: {generated_at}",
                f"Window: {since or 'beginning'} to {until or 'now'}",
                "",
                "## Summary",
                f"- Active licenses: {active_licenses}",
                f"- Revoked licenses: {revoked_licenses}",
                f"- Warning events: {warnings}",
                "",
                "## Card Counts",
                *[f"- {label.replace('_', ' ').title()}: {count}" for label, count in counts.items()],
            ]
        )
        report_context = {
            "type": "licensing-report",
            "title": f"Licensing Report — {report_type}",
            "content_type": "text/markdown",
            "report_type": report_type,
            "generated_at": generated_at,
            "since": since,
            "until": until,
            "counts": counts,
            "active_licenses": active_licenses,
            "revoked_licenses": revoked_licenses,
            "warning_events": warnings,
        }
        report_artifact = await _create_workspace_artifact(workspace_id, report_context, markdown)
        return _json_result(
            {
                "status": "generated",
                "workspace_id": workspace_id,
                "report_type": report_type,
                "report_artifact_id": _artifact_id_from_response(report_artifact),
                "summary": report_context,
            }
        )
    except OphanToolError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# LLM usage metering — tombstones
# ---------------------------------------------------------------------------
#
# The no-models rule is universal and explicitly includes BYOK, so ophan meters no model invocation.
# A metering surface for a forbidden capability keeps its path alive economically — a billing surface
# argues that invocations happen, that tokens are the unit, and that a `provider` is a real parameter.
# The apparatus these two functions would meter does not exist in this platform, so neither does the
# metering.
#
# The shape matches seraph's `resolve_llm_credentials` (`seraph/server.py:597`): a tombstone that
# raises, naming the rule and what is absent, so an exercised path fails loudly rather than quietly
# succeeding. One deliberate difference: seraph's tombstone keeps its `@mcp.tool` registration because
# it has a real caller (lumen's `invoke_llm`) that needs an addressed raise. These two have no caller
# anywhere in the tree, so they are unregistered as well as tombstoned — keeping `@mcp.tool` would go
# on advertising two LLM metering tools in `tools/list`. The functions are kept, rather than deleted
# outright, so that a re-add is a conflict rather than a blank line, and so
# `src/ophan/tests/test_no_llm_metering.py` can assert they raise and are unregistered.


async def check_llm_allowance(
    user_id: str,
    tier: str = "free",
    estimated_tokens: int = 0,
) -> str:
    """Tombstone (no-models rule, universal, including BYOK). Raises."""
    del user_id, tier, estimated_tokens
    raise NotImplementedError(
        "check_llm_allowance: no-models rule; this platform meters no model invocation."
    )


async def record_llm_usage(
    user_id: str,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    workspace_id: Optional[str] = None,
) -> str:
    """Tombstone (no-models rule, universal, including BYOK). Raises."""
    del user_id, provider, model, input_tokens, output_tokens, workspace_id
    raise NotImplementedError(
        "record_llm_usage: no-models rule; this platform consumes no model tokens."
    )


# ---------------------------------------------------------------------------
# SaaS Billing (Stripe) — plan definitions, checkout, sync
# ---------------------------------------------------------------------------

# `_PLAN_LIMITS` is a hand-authored table of nine numbers that decide what every customer may hold —
# a typed-in value, the same configured-rate shape the energy block above states the law against:
# rates are measured at the screen, never configured.
#
# It should be derived from the entitlement artifact (`ENTITLEMENT_CARD_MIME`) that a plan issues.
# `activate_subscription` currently writes `limits` into that artifact from this dict — the dependency
# runs backwards. The entitlement is the governed object (issued, signed, revocable and versioned);
# these limits should be read from it, so that changing what a plan grants is an artifact change with
# provenance rather than a code deploy, and `_sync_limits_to_core` pushes what was granted rather than
# what a constant says. Three call sites read this dict today: `_sync_limits_to_core`,
# `_add_vu_to_core` and `activate_subscription`.
_PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free":  {"max_workspaces": 1,  "max_artifacts": 500,    "vu_limit": 100},
    "pro":   {"max_workspaces": 3,  "max_artifacts": 10_000, "vu_limit": 2_000},
    "power": {"max_workspaces": 10, "max_artifacts": 100_000, "vu_limit": 10_000},
}

# VUs granted per purchased top-up pack — a typed-in 500 that converts money into value units, i.e.
# an exchange rate authored in code. It should be derived from the settled exchange: the top-up's
# price is on the Stripe price artifact, and the VU it buys should come from the measured VU rate at
# the screen (`exchange.py` / the energy surface), not from a constant that silently redefines the
# currency. Read once, by `_dispatch_stripe_event`.
VU_TOPUP_PACK_SIZE = 500


# A Stripe API credential has no permitted use in this module — the three outbound creation tools
# raise rather than call the vendor SDK — so none is resolved here.


def _price_id_to_plan(price_id: str) -> str:
    """Reverse-map a Stripe price ID to a plan key."""
    if price_id == STRIPE_PRICE_ID_PRO:
        return "pro"
    if price_id == STRIPE_PRICE_ID_POWER:
        return "power"
    return "free"


async def _sync_limits_to_core(person_id: str, plan: str) -> None:
    """Push numeric limits to Core's entitlement cache. The one sync channel."""
    limits = _PLAN_LIMITS.get(plan, _PLAN_LIMITS["free"])
    try:
        # _platform_request: this runs from the Stripe webhook path, which has no delegated caller —
        # there is no principal to fail closed on. `/internal/gate/*` is a platform-internal surface.
        await _platform_request("POST", "/internal/gate/set-limits", {
            "person_id": person_id,
            **limits,
        })
    except Exception as exc:
        log.error("Failed to sync limits to Core for person=%s plan=%s: %s", person_id, plan, exc)


async def _add_vu_to_core(person_id: str, vu_amount: int) -> None:
    """Additively increase the VU limit for a person (top-up). Reads current limits first."""
    try:
        # _platform_request: top-up runs from the webhook/payment path — no delegated caller.
        usage_data = await _platform_request("GET", f"/internal/gate/usage/{person_id}")
        limits = usage_data.get("limits", _PLAN_LIMITS["free"])
        current_vu = limits.get("vu_limit") or _PLAN_LIMITS["free"]["vu_limit"]
        await _platform_request("POST", "/internal/gate/set-limits", {
            "person_id": person_id,
            "max_workspaces": limits.get("max_workspaces"),
            "max_artifacts": limits.get("max_artifacts"),
            "vu_limit": current_vu + vu_amount,
        })
        log.info("Added %s VU credits for person=%s (new limit=%s)", vu_amount, person_id, current_vu + vu_amount)
    except Exception as exc:
        log.error("Failed to add VU credits for person=%s amount=%s: %s", person_id, vu_amount, exc)


# ---------------------------------------------------------------------------
# Stripe session creation — outbound writes, raised pending the tekton
# ---------------------------------------------------------------------------
#
# These three tools raise. Each would otherwise issue an outbound HTTP write to api.stripe.com
# (`stripe.checkout.Session.create` twice, `stripe.billing_portal.Session.create` once) via a bare
# vendor SDK call inside a persona server, on a credential read from the process environment.
#
# External operators in this platform are GET-only, and astra makes that structural rather than
# conventional (`astra/fetch.py`): the method is hard-locked at `Request(url, method="GET")` with no
# code path that sends a body and no parameter that can change the verb; scheme and host are
# re-validated on every redirect hop; responses are size- and time-capped. Everything world-touching
# there is an organon — a registered operator artifact declaring the capability it needs — so it
# passes the prism junction and the discharge gate. These three tools have none of that: no organon,
# no declared capability, no gate, and so nothing that a prism could withhold or a grant could deny.
# `net.request` (outbound HTTP any-method, write-capable, a higher trust rung) exists in the
# capability vocabulary (`prism/capabilities.py`) precisely so a write-capable reach is something an
# environment grants — calling from inside the persona routes around that decision entirely.
#
# A correct tekton is a cross-repo change touching a security gate: the organon and its manifest are
# ophan's, the capability rung is prism's, `can_discharge` is crystal's, and the grant is ember's
# light-cone. `CAPABILITY-AS-ARTIFACT.md` records that `can_discharge` is currently a bare
# capability-subset test with no reference to grants, so the gate this would hang from is itself
# mid-migration. The full design — organon id, capability, gate, and every call site that moves — is
# written at `_archive/OPHAN-STRIPE-TEKTON.md`.
#
# The tools stay registered rather than deleted (unlike the LLM tombstones above) because they have
# live callers — the billing UI calls all three — and a caller that gets "unknown tool" learns
# nothing, whereas a raise carries the reason and the pointer.

_STRIPE_WRITE_REFUSAL = (
    "refused: this is an outbound WRITE to an external service made from a persona server. External "
    "operators are GET-only and write-capable reaches go through an ORGANON declaring `net.request`, "
    "gated by the discharge grant — see agience-pharos/working/OPHAN-STRIPE-TEKTON.md (organon "
    "`op.pay.session`). "
    "Removed 2026-07-30 on John's ruling 'bring it into a tekton'."
)


@mcp.tool(
    description=(
        "REFUSES — Stripe Checkout Session creation is an outbound write and must go through the "
        "op.pay.session organon (net.request + discharge gate). Raises; creates nothing."
    )
)
async def create_checkout_session(
    plan: str,
    person_id: str,
    email: Optional[str] = None,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> str:
    """Raises. Starting a Stripe subscription checkout via `checkout.Session.create` needs the
    organon described in the module note above, which is not wired yet.

    Args:
        plan: Target plan key ('pro' or 'power').
        person_id: The person upgrading.
        email: Pre-fill email on checkout page.
        success_url: Redirect after successful checkout.
        cancel_url: Redirect on cancel.
    """
    del plan, person_id, email, success_url, cancel_url
    raise OphanToolError(f"create_checkout_session {_STRIPE_WRITE_REFUSAL}")


@mcp.tool(
    description=(
        "REFUSES — Stripe billing-portal session creation is an outbound write and must go through the "
        "op.pay.session organon (net.request + discharge gate). Raises; creates nothing."
    )
)
async def create_portal_session(
    stripe_customer_id: str,
    return_url: Optional[str] = None,
) -> str:
    """Raises. Opening the Stripe billing portal via `billing_portal.Session.create` needs the
    organon described in the module note above, which is not wired yet.

    Args:
        stripe_customer_id: The Stripe customer ID.
        return_url: URL to redirect after portal session.
    """
    del stripe_customer_id, return_url
    raise OphanToolError(f"create_portal_session {_STRIPE_WRITE_REFUSAL}")


@mcp.tool(
    description=(
        "REFUSES — VU top-up checkout is an outbound write and must go through the op.pay.session "
        "organon (net.request + discharge gate). Raises; creates nothing and charges nothing."
    )
)
async def create_vu_topup(
    person_id: str,
    stripe_customer_id: Optional[str] = None,
    quantity: int = 1,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> str:
    """Raises. A one-time VU credit purchase via `checkout.Session.create` needs the organon
    described in the module note above, which is not wired yet.

    Args:
        person_id: The person buying credits.
        stripe_customer_id: Existing Stripe customer ID (optional).
        quantity: Number of VU packs to buy.
        success_url: Redirect after payment.
        cancel_url: Redirect on cancel.
    """
    del person_id, stripe_customer_id, quantity, success_url, cancel_url
    raise OphanToolError(f"create_vu_topup {_STRIPE_WRITE_REFUSAL}")


@mcp.tool(description="Activate a subscription after Stripe checkout. Creates artifacts and syncs limits to Core.")
async def activate_subscription(
    person_id: str,
    plan: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
) -> str:
    """Record a new subscription activation.

    Creates entitlement + subscription + event artifacts in the user's inbox,
    then syncs numeric limits to Core's gate.

    Args:
        person_id: The person whose subscription was activated.
        plan: Plan key ('pro' or 'power').
        stripe_customer_id: Stripe customer ID.
        stripe_subscription_id: Stripe subscription ID.
    """
    issued_at = _now_iso()
    limits = _PLAN_LIMITS.get(plan, _PLAN_LIMITS["free"])

    # 1. Entitlement artifact
    entitlement_context = {
        "content_type": ENTITLEMENT_CARD_MIME,
        "type": "entitlement",
        "entitlement_id": f"ent_{uuid4().hex[:12]}",
        "account_id": person_id,
        "plan": plan,
        "status": "active",
        "limits": limits,
        "issued_at": issued_at,
    }
    await _create_workspace_artifact(person_id, entitlement_context, f"SaaS {plan} plan entitlement activated.")

    # 2. Subscription artifact
    sub_context = {
        "content_type": SUBSCRIPTION_CARD_MIME,
        "type": "subscription",
        "subscription_id": f"sub_{uuid4().hex[:12]}",
        "account_id": person_id,
        "plan": plan,
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "status": "active",
        "activated_at": issued_at,
    }
    await _create_workspace_artifact(person_id, sub_context, f"Stripe subscription for {plan} plan.")

    # 3. Event artifact
    event_context = {
        "content_type": EVENT_CARD_MIME,
        "type": "license-event",
        "event_type": "subscription_activated",
        "account_id": person_id,
        "plan": plan,
        "timestamp": issued_at,
        "severity": "info",
    }
    await _create_workspace_artifact(person_id, event_context, f"Subscription activated: {plan} plan.")

    # 4. Sync limits to Core
    await _sync_limits_to_core(person_id, plan)

    return _json_result({"status": "activated", "person_id": person_id, "plan": plan})


@mcp.tool(description="Update a subscription (plan change or cancellation). Syncs new limits to Core.")
async def update_subscription(
    person_id: str,
    new_plan: str,
) -> str:
    """Handle a subscription plan change or cancellation.

    Args:
        person_id: The person whose subscription changed.
        new_plan: New plan key ('free' for cancellation, 'pro', 'power').
    """
    event_context = {
        "content_type": EVENT_CARD_MIME,
        "type": "license-event",
        "event_type": "subscription_updated",
        "account_id": person_id,
        "new_plan": new_plan,
        "timestamp": _now_iso(),
        "severity": "info",
    }
    await _create_workspace_artifact(person_id, event_context, f"Subscription updated to {new_plan}.")
    await _sync_limits_to_core(person_id, new_plan)
    return _json_result({"status": "updated", "person_id": person_id, "plan": new_plan})


async def _dispatch_stripe_event(event_type: str, event_data: str) -> str:
    """Internal Stripe event dispatcher — called only from _handle_stripe_webhook_http.

    Not exposed as an MCP tool to prevent unauthorized invocation by MCP clients.
    The HTTP endpoint validates the Stripe-Signature before calling this.
    """
    data = json.loads(event_data) if isinstance(event_data, str) else event_data

    if event_type == "checkout.session.completed":
        person_id = data.get("metadata", {}).get("person_id")
        plan = data.get("metadata", {}).get("plan_key", "pro")
        if not person_id:
            return _json_result({"status": "skipped", "reason": "No person_id in metadata"})

        # VU top-up (one-time payment) — actually increment the limit in Core
        if data.get("mode") == "payment" and data.get("metadata", {}).get("topup") == "vu":
            quantity = int(data.get("metadata", {}).get("topup_quantity", "1"))
            vu_added = quantity * VU_TOPUP_PACK_SIZE
            await _add_vu_to_core(person_id, vu_added)
            return _json_result({"status": "vu_topup_applied", "person_id": person_id, "vu_added": vu_added})

        # Subscription checkout
        stripe_customer_id = data.get("customer")
        stripe_subscription_id = data.get("subscription")
        result = await activate_subscription(
            person_id=person_id,
            plan=plan,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
        )
        # Receipt — sent AS the operator-rooted system principal (best-effort).
        await _send_account_email(
            person_id, "Your Agience subscription is active", _receipt_html(plan)
        )
        return result

    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        person_id = data.get("metadata", {}).get("person_id")
        if not person_id:
            return _json_result({"status": "skipped", "reason": "No person_id in metadata"})

        if event_type == "customer.subscription.deleted":
            return await update_subscription(person_id=person_id, new_plan="free")

        # Determine new plan from price
        items = data.get("items", {}).get("data", [])
        plan = "free"
        if items:
            price_id = items[0].get("price", {}).get("id", "")
            plan = _price_id_to_plan(price_id)
        return await update_subscription(person_id=person_id, new_plan=plan)

    return _json_result({"status": "ignored", "event_type": event_type})


# There is no tool in this module that reads `/internal/gate/usage/{person_id}` for a caller-supplied
# `person_id` on ophan's own platform JWT — that would be a cross-tenant billing oracle, since
# `/internal/gate/*` is a platform-internal surface and need not authorize a delegation JWT at all.
# `/internal/gate/usage/` appears at exactly one site in this module, `_add_vu_to_core`, which reads a
# person's current limits only in order to add to them, is reachable only from the signature-verified
# Stripe webhook, and returns nothing to any caller. A user-facing usage view needs a route that
# authorizes a delegated caller for their own person and returns only that person's data — a mantle
# change, not a persona workaround.


# ---------------------------------------------------------------------------
# Stripe webhook HTTP endpoint (outside MCP — raw ASGI)
# ---------------------------------------------------------------------------

# In-memory idempotency set — deduplicates Stripe retries within a process lifetime.
# Capped to prevent unbounded growth; evicted on cap (rare for well-behaved webhooks).
_processed_stripe_events: set[str] = set()
_PROCESSED_EVENTS_MAX = 10_000


async def _handle_stripe_webhook_http(scope: dict, receive: Any, send: Any) -> None:
    """Handle POST /webhooks/stripe — validates Stripe-Signature and dispatches."""
    body_parts = []
    while True:
        msg = await receive()
        body_parts.append(msg.get("body", b""))
        if not msg.get("more_body", False):
            break
    body = b"".join(body_parts)

    # Extract Stripe-Signature header
    sig_header = None
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"stripe-signature":
            sig_header = header_value.decode("utf-8")
            break

    # A missing signature and a missing secret are distinct outcomes: no signature is a 400 (the
    # caller's fault), and no resolvable secret is a 503 naming the missing platform piece (ours) —
    # so an unconfigured webhook is never indistinguishable from a malformed request.
    if not sig_header:
        resp_body = json.dumps({"error": "Missing Stripe-Signature header"}).encode()
        await send({"type": "http.response.start", "status": 400,
                     "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(resp_body)).encode())]})
        await send({"type": "http.response.body", "body": resp_body})
        return

    try:
        webhook_secret = await _resolve_stripe_webhook_secret()
    except Exception as exc:  # noqa: BLE001 — loud, and never a fallback to an unverified dispatch
        log.error("Stripe webhook REFUSED — signing secret unresolvable: %s", exc)
        resp_body = json.dumps({
            "error": "Stripe webhook signing secret is not resolvable from stored secrets",
            "reason": str(exc),
            "refused": "no event is dispatched without a verified signature",
        }).encode()
        await send({"type": "http.response.start", "status": 503,
                     "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(resp_body)).encode())]})
        await send({"type": "http.response.body", "body": resp_body})
        return

    try:
        # `Webhook.construct_event` is a local HMAC comparison over the request body — it makes no
        # network call, so this is not an outbound reach and needs no organon. `_stripe.api_key` is
        # not set here: it is not needed for verification, and setting it would leave a write-capable
        # client configured on the inbound path.
        import stripe as _stripe
        event = _stripe.Webhook.construct_event(body, sig_header, webhook_secret)
    except Exception as exc:
        resp_body = json.dumps({"error": f"Webhook verification failed: {exc}"}).encode()
        await send({"type": "http.response.start", "status": 400,
                     "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(resp_body)).encode())]})
        await send({"type": "http.response.body", "body": resp_body})
        return

    # Idempotency check — skip already-processed events (handles Stripe retries)
    event_id = event.get("id", "")
    if event_id and event_id in _processed_stripe_events:
        resp_body = json.dumps({"status": "already_processed", "event_id": event_id}).encode()
        await send({"type": "http.response.start", "status": 200,
                     "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(resp_body)).encode())]})
        await send({"type": "http.response.body", "body": resp_body})
        return

    if event_id:
        if len(_processed_stripe_events) >= _PROCESSED_EVENTS_MAX:
            _processed_stripe_events.clear()
        _processed_stripe_events.add(event_id)

    # Dispatch to internal handler (not an MCP tool — Stripe-Signature already verified above)
    try:
        result = await _dispatch_stripe_event(
            event_type=event["type"],
            event_data=json.dumps(event["data"]["object"]),
        )
        resp_body = result.encode() if isinstance(result, str) else json.dumps(result).encode()
    except Exception as exc:
        log.exception("Stripe webhook processing error")
        resp_body = json.dumps({"error": str(exc)}).encode()

    await send({"type": "http.response.start", "status": 200,
                 "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(resp_body)).encode())]})
    await send({"type": "http.response.body", "body": resp_body})


# ---------------------------------------------------------------------------
# UI Resources
# ---------------------------------------------------------------------------

@mcp.resource("ui://ophan/billing-settings.html")
async def billing_settings_html() -> str:
    """Serve the billing settings page for the platform shell."""
    view_path = Path(__file__).parent / "ui" / "billing" / "billing-settings.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.account.html")
async def account_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.account+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.account+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.entitlement.html")
async def entitlement_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.entitlement+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.entitlement+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.invoice.html")
async def invoice_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.invoice+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.invoice+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.license.html")
async def license_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.license+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.license+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.license-event.html")
async def license_event_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.license-event+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.license-event+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.license-installation.html")
async def license_installation_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.license-installation+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.license-installation+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.license-usage.html")
async def license_usage_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.license-usage+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.license-usage+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.market.html")
async def market_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.market+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.market+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.portfolio.html")
async def portfolio_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.portfolio+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.portfolio+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://ophan/vnd.agience.transaction.html")
async def transaction_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.transaction+json."""
    view_path = Path(__file__).parent / "ui" / "application" / "vnd.agience.transaction+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Starting agience-server-ophan � transport=%s port=%s", MCP_TRANSPORT, MCP_PORT)
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn
        uvicorn.run(create_server_app(), host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run()
