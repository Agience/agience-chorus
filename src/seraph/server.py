"""
agience-server-seraph — MCP Server
====================================
Seraph (security & defense — audits, integrity, governance): access control, audit
trails, identity verification, policy compliance, cryptographic signing, and
Authorizer runtime (OAuth + Crypto).
A tekton — the security condensor in the chorus (the tekton standard library); its tools are organons, invoked by condensation (OPERATOR-ARCHITECTURE §12).

Seraph is the security & defense persona of chorus (operators, by domain).
Seraph is a platform-tier server — Core cannot connect to other servers
without Seraph resolving auth. Core's mcp_service carries an explicit
recursion guard that skips auth resolution when calling Seraph itself.

Seraph has two distinct roles:
  1. Credential application: resolves credentials to auth headers/tokens. A credential is an
     ordinary artifact and its value is the artifact's CONTENT, read under the caller's
     delegation and decrypted at rest by Mantle's envelope; Seraph never holds the
     DATA_ENCRYPTION_KEY or a second copy of the material. [was `/secrets/reveal`, a route that
     no longer exists — migrated 2026-08-26]
  2. Authorizer: knows OAuth providers (Google auth), handles OAuth flows.

Tools
-----
  provide_access_token      — Exchange stored refresh token for a fresh access token
  complete_authorizer_oauth — Complete OAuth code exchange and store refresh token
  resolve_llm_credentials   — Raises: no-models rule
  audit_access              — Query the access audit log
  check_permissions         — Check access grants
  grant_access              — Grant collection access
  revoke_access             — Revoke access
  verify_token              — Verify JWT or API key
  enforce_policy            — Evaluate policies
  list_policies             — List governance policies
  check_compliance          — Check compliance
  get_person_preferences    — Read the caller's preferences from Origin
  set_person_preferences    — Update the caller's preferences at Origin

Person management
------------------
  Verification is a contract; issuance is a service. Origin's issuance surface —
  OIDC, WebAuthn, OTP, JWKS, key custody, `/auth/clients`, `/setup`, `/internal/*`
  — stays a public HTTP service, because a tekton invocation needs a verified
  token and issuance is what mints one. Its management surface belongs here.

  That surface is one operation: person preferences. Passkey credential
  management and the whole `/system` router read as management but gate on
  `actor is None` — they refuse a delegation, and a seraph tekton is always a
  delegation. They stay at Origin. See `tests/test_person_preferences_seraph.py`.

Auth
----
  Service identity loaded once by the chorus host (chorus.private.pem).
  Persona signs its own platform JWTs via _auth.sign_self_jwt() — no token
  exchange with Origin, no PLATFORM_INTERNAL_SECRET.

  `_fetch_and_decrypt_secret` performs a live `GET /artifacts/{id}` and is reached from two
  registered tools — `complete_authorizer_bearer` and `provide_aws_credentials`. It POSTed
  `/secrets/reveal` until 2026-08-26; that route does not exist, so it had been returning `None`
  and every caller was taking its own failure branch.

  MANTLE_URI ⬩ Base URI of the Mantle backend
  ORIGIN_URI ⬩ Base URI of the identity authority (issuance). Reached over the
               wire — never imported; `chorus -> origin` is 0 and guarded.

Transport
---------
  MCP_TRANSPORT=streamable-http (default for Agience)
  MCP_HOST=0.0.0.0
  MCP_PORT=8089
"""

from __future__ import annotations

import json as _json
import logging
import os
import pathlib
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

log = logging.getLogger("agience-server-seraph")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s - %(name)s - %(message)s")

MANTLE_URI: str = os.getenv("MANTLE_URI", "http://localhost:8081").rstrip("/")
# Origin is reached over the wire, never imported. `chorus -> origin` is 0 by AST over non-test
# `src/` and guarded by `tests/test_chorus_does_not_import_origin.py`. The management tektons below
# hold Origin's identity, so they are exactly where that edge would come back if anyone reached for
# `from origin import ...`. Same env var, same default, as ophan and lumen use — one name for the
# identity authority across the repo.
ORIGIN_URI: str = os.getenv("ORIGIN_URI", "http://localhost:8080").rstrip("/")
SERAPH_CLIENT_ID: str = "agience-server-seraph"
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
MCP_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT: int = int(os.getenv("MCP_PORT", "8089"))


# ---------------------------------------------------------------------------
# Shared authentication infrastructure (AgienceServerAuth)
# ---------------------------------------------------------------------------

from prism.trust import ServerAuth as _AgienceServerAuth

_auth = _AgienceServerAuth(SERAPH_CLIENT_ID, MANTLE_URI)


def create_seraph_app():
    """Return the Seraph MCP ASGI app with verified middleware and startup hooks."""
    return _auth.create_app(mcp)


async def _headers() -> dict[str, str]:
    """Headers with Seraph's own platform JWT (signed via the chorus service identity)."""
    return _auth.headers()


# Seraph has no `_user_headers()` helper. Seraph is the security persona: it mutates grants, rotates
# API keys, verifies tokens, and resolves secret material — there is no operation here that should
# run on anything but the caller's own authority. A helper that falls back to Seraph's platform JWT
# when delegation is absent would escalate precisely when verification failed, since the middleware
# stores an empty token on a failed mint. Every call site here uses `_require_user_headers()`
# instead, which fails closed.


def _require_user_headers() -> dict[str, str]:
    """Headers carrying the caller's verified delegation JWT — fails closed.

    Tools acting on a caller-supplied resource id must use this, never `_headers`. `_headers`
    resolves to Seraph's own platform JWT, and the middleware stores an empty token whenever
    verification or minting fails — so a `_headers` site would escalate to service identity on
    exactly the requests that failed authentication, and Mantle would then apply platform authority
    to a resource the caller chose.

    This matters most in seraph: seraph is the persona that mutates grants, so an escalated call
    would not be a read of someone else's data but a write to the authorization system itself. Same
    body as `sage/server.py`'s equivalent; guarded by
    `chorus/tests/test_no_service_identity_on_caller_ids.py`.
    """
    return _auth.require_user_headers()


# ---------------------------------------------------------------------------
# Secret resolution helpers
# ---------------------------------------------------------------------------


async def _fetch_and_decrypt_secret(
    secret_id: str | None = None,
    authorizer_id: str | None = None,
    secret_type: str | None = None,
    provider: str | None = None,
) -> str | None:
    """Resolve a credential's value with a plain artifact READ.

    Migrated 2026-08-26 under John's no-sealing ruling. This POSTed `{MANTLE_URI}/secrets/reveal`,
    and that route does not exist — there is no `secrets_router.py` and no `/secret*` route anywhere
    in `agience-mantle/src`. It returned `None` on every call, so every caller below took its
    own failure branch. `iris/server.py::_fetch_secret_material` received the same treatment on
    2026-08-25 and is the worked precedent.

    A credential is an ordinary artifact: the value is its CONTENT, the light cone decides who may
    read it, and *"`fetch` is what `read` already does"*. The delegation still authorizes — Mantle
    maps it to a user principal and the read is that user's read.

    The selector parameters have no callers. All six call sites pass a concrete `secret_id`;
    `authorizer_id` / `secret_type` / `provider` were never used, and the old body only logged a
    warning that `authorizer_id` would widen the selector ambiguously. They are kept in the
    signature so this is a body change and not a call-site change, and refused explicitly rather
    than silently resolved — guessing which credential a caller meant is how the wrong one gets
    handed out.
    """
    if not secret_id:
        log.error("a credential read needs a concrete secret_id; got authorizer_id=%r type=%r "
                  "provider=%r. Selecting by (type, provider) is not implemented and must not be "
                  "guessed at.", authorizer_id, secret_type, provider)
        return None

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, secret_id),
            headers=_require_user_headers(),
        )
    if resp.status_code != 200:
        log.error("credential read failed: %s %s", resp.status_code, resp.text[:200])
        return None

    content = (resp.json() or {}).get("content")
    #: Three shapes are in flight and all three are read rather than assumed. `_create_credential`
    #: writes `{"value": ...}`; Mantle's own producer and older rows may carry `{"material": ...}`;
    #: and a bare string is the value itself. A shape this does not recognise yields None, which
    #: every caller already handles — never the raw JSON, which would be handed on as if it were
    #: the secret.
    if isinstance(content, str):
        try:
            content = _json.loads(content)
        except (TypeError, ValueError):
            return content or None
    if isinstance(content, dict):
        return content.get("value") or content.get("material") or None
    return None



# ── credentials as artifacts ─────────────────────────────────────────────────────────────────
#
# Mantle's `/secrets` surface no longer exists. There is no `secrets_router.py` and no
# `/secret*` route anywhere in `agience-mantle/src`; every call below used to 404. A credential is
# now an ordinary artifact — `mantle/services/bootstrap_types.py` states the design: *"the value is
# the artifact's CONTENT, so the envelope encrypts it at rest under the origin-root principal and
# the light cone decides who may read it. There is no second store and no second authorization
# path."* The shape below is copied from the one live producer,
# `mantle/services/seed_provisioning/platform_email.py`, rather than invented.
#
# Filtering is client-side, and that is forced. Seraph selects credentials by `authorizer_id` and
# by type — a pure-filter query. Mantle's `/artifacts/recall` refuses one by design (*"a filter
# narrows a recall, it does not constitute one"* — 400), and `/artifacts/visible` filters only on
# `content_type`. So the list is fetched by content type and narrowed here. The set is one user's
# credentials, so it is small; if it stops being small, the fix is a query surface in Mantle, not a
# bigger page here.
_CREDENTIAL_CT = "application/vnd.agience.credential+json"


def _credential_context(doc: dict) -> dict:
    """The plaintext metadata off a credential artifact.

    `context` is a JSON STRING over the wire (every field on Mantle's create/update request model
    is `Optional[str]`), but the read path may hand back either, so both are accepted. A context
    that will not parse yields `{}` — a credential that cannot be classified must not match a
    filter and be handed to the wrong caller.
    """
    raw = doc.get("context")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = _json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _list_credentials(
    client,
    headers: dict,
    *,
    secret_id: str | None = None,
    authorizer_id: str | None = None,
    secret_type: str | None = None,
) -> list[dict]:
    """Credential artifacts the caller may read, narrowed by the selectors Seraph uses."""
    resp = await client.get(
        f"{MANTLE_URI}/artifacts/visible",
        params={"content_type": _CREDENTIAL_CT, "limit": 1000},
        headers=headers,
    )
    if resp.status_code != 200:
        log.error("Failed to list credentials: %s %s", resp.status_code, resp.text[:200])
        return []
    body = resp.json() or {}
    #: `/artifacts/visible` returns `{items, total, has_more}` since 2026-08-25 (P-6/P-7).
    #: The bare list is still read so a client pointed at an older node keeps working.
    docs = body.get("items", []) if isinstance(body, dict) else body
    out: list[dict] = []
    for doc in docs or []:
        if secret_id and doc.get("id") != secret_id:
            continue
        ctx = _credential_context(doc)
        if secret_type and ctx.get("kind") != secret_type:
            continue
        if authorizer_id and ctx.get("authorizer_id") != authorizer_id:
            continue
        out.append(doc)
    return out


async def _create_credential(
    client,
    headers: dict,
    *,
    kind: str,
    provider: str,
    label: str,
    value: str,
    authorizer_id: str | None = None,
    expires_at: str | None = None,
):
    """Write one credential. The VALUE is the artifact's content and nothing else holds it."""
    context: dict[str, object] = {
        "content_type": _CREDENTIAL_CT,
        "kind": kind,
        "provider": provider,
        "label": label,
    }
    if authorizer_id:
        context["authorizer_id"] = authorizer_id
    if expires_at:
        context["expires_at"] = expires_at
    return await client.post(
        f"{MANTLE_URI}/artifacts",
        headers=headers,
        json={
            "content_type": _CREDENTIAL_CT,
            # A JSON object rather than the bare token, matching the `+json` suffix and the
            # producer in Mantle, so a second field can be added later without readers having to
            # tell two encodings apart.
            "content": _json.dumps({"value": value}, separators=(",", ":")),
            "context": _json.dumps(context, separators=(",", ":")),
            "name": label,
        },
    )


async def _delete_credential(client, headers: dict, artifact_id: str):
    return await client.delete(f"{MANTLE_URI}/artifacts/{artifact_id}", headers=headers)


async def _list_secrets_metadata(
    secret_id: str | None = None,
    authorizer_id: str | None = None,
    secret_type: str | None = None,
) -> dict | None:
    """Fetch secret metadata (no plaintext) from Core using the delegation JWT."""
    params: dict[str, str] = {}
    if secret_id:
        params["id"] = secret_id
    if authorizer_id:
        params["authorizer_id"] = authorizer_id
    if secret_type:
        params["type"] = secret_type

    headers = _require_user_headers()
    async with httpx.AsyncClient(timeout=10) as client:
        found = await _list_credentials(
            client, headers,
            secret_id=secret_id, authorizer_id=authorizer_id, secret_type=secret_type,
        )
    return found[0] if found else None


# Seraph has no `_fetch_secret_via_op` helper. The Chorus op-dispatch route it would have posted to
# (`/artifacts/{id}/op/fetch`) does not exist; mantle carries a guard
# (`test_op_dispatch_route_is_gone.py`) to keep it that way. Nor is the live path
# `/secrets/reveal` any more — that route is gone too. It is a plain `GET /artifacts/{id}`; see
# `_fetch_and_decrypt_secret` above.


async def _store_or_rotate_bearer_token(
    authorizer_artifact_id: str,
    provider: str,
    access_token: str,
    expires_in: int | None,
) -> None:
    """Delete any existing bearer_token for this authorizer and store the new one.

    Called both after a fresh OAuth2 code exchange and after a refresh-token
    exchange so that ``_resolve_auth_headers`` always finds a cached token.
    """
    from datetime import datetime, timezone, timedelta

    expires_at = ""
    if expires_in:
        try:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            ).isoformat()
        except (ValueError, TypeError):
            pass

    headers = _require_user_headers()
    async with httpx.AsyncClient(timeout=10) as client:
        # Delete any cached bearer token already held for this authorizer
        for sec in await _list_credentials(
            client, headers,
            authorizer_id=authorizer_artifact_id, secret_type="bearer_token",
        ):
            await _delete_credential(client, headers, sec["id"])

        # Store the fresh token
        await _create_credential(
            client, headers,
            kind="bearer_token",
            provider=provider,
            label=f"Access token for {authorizer_artifact_id}",
            value=access_token,
            authorizer_id=authorizer_artifact_id,
            expires_at=expires_at or None,
        )


mcp = FastMCP(
    "agience-server-seraph",
    instructions=(
        "You are Seraph, the security, governance, and trust guardian of the Agience platform. "
        "You enforce access policies, maintain audit trails, verify identities, ensure policy "
        "compliance, and protect the integrity of knowledge through cryptographic signing. "
        "Treat every access control decision as consequential � revoke first, escalate later."
    ),
)
from mantle.clients.artifact_helpers import artifact_url, register_types_manifest
register_types_manifest(mcp, "seraph", __file__)

# ---------------------------------------------------------------------------
# Authorizer tools
# ---------------------------------------------------------------------------

async def provide_access_token(
    authorizer_config: str,
    authorizer_artifact_id: str,
) -> str:
    """Decrypt the client secret, fetch the stored refresh token, exchange for access token.

    Args:
        authorizer_config: JSON string of the Authorizer artifact's content
            (contains client_id, client_secret_id, token_endpoint, scopes, sender_address).
        authorizer_artifact_id: Artifact ID of the Authorizer artifact.

    User identity is carried at the transport layer via the delegation JWT set
    by Core before calling this tool.  No bearer token should be passed as an
    argument.
    """
    try:
        config = _json.loads(authorizer_config) if isinstance(authorizer_config, str) else authorizer_config
    except Exception:
        return _json.dumps({"error": "Invalid authorizer_config JSON"})

    # Bearer-only authorizers: return stored access token directly (no refresh flow)
    token_response_type = config.get("token_response_type", "standard")
    requires_client_credentials = config.get("requires_client_credentials", True)

    if token_response_type == "bearer_only" or not requires_client_credentials:
        bt_secret = await _list_secrets_metadata(
            authorizer_id=authorizer_artifact_id,
            secret_type="bearer_token",
        )
        if not bt_secret:
            return _json.dumps({
                "error": "token_expired",
                "reauth_required": True,
                "message": "No bearer token found. User must re-authenticate.",
            })

        access_token = await _fetch_and_decrypt_secret(secret_id=bt_secret["id"])
        if not access_token:
            return _json.dumps({"error": "Failed to decrypt bearer token"})

        # Check expiry
        #: Read through `_credential_context`, NOT off the artifact's top level. `expires_at` is
        #: written INSIDE `context` by `_create_credential`, and `context` reaches us as a JSON
        #: STRING. `bt_secret.get("expires_at")` therefore returned "" on every credential ever
        #: written, the branch below was never entered, and an expired bearer token was handed back
        #: as valid — demonstrated 2026-08-26 with a token dated 2000-01-01. The accessor two
        #: calls earlier in this same flow already reads it correctly for `kind`/`authorizer_id`.
        expires_at = _credential_context(bt_secret).get("expires_at", "")
        if expires_at:
            from datetime import datetime, timezone
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_dt < datetime.now(timezone.utc):
                    return _json.dumps({
                        "error": "token_expired",
                        "reauth_required": True,
                        "message": "Bearer token has expired. User must re-authenticate.",
                    })
            except Exception:
                pass  # can't parse expiry, return token anyway

        return _json.dumps({"access_token": access_token})

    # Standard OAuth2 refresh flow
    client_id = config.get("client_id")
    client_secret_id = config.get("client_secret_id")
    token_endpoint = config.get("token_endpoint")
    scopes = config.get("scopes", "")
    sender_address = config.get("sender_address", "")

    if not all([client_id, client_secret_id, token_endpoint]):
        return _json.dumps({"error": "authorizer_config missing required fields (client_id, client_secret_id, token_endpoint)"})

    # 1. Decrypt client_secret via JWE
    client_secret = await _fetch_and_decrypt_secret(secret_id=client_secret_id)
    if not client_secret:
        return _json.dumps({"error": "Client secret not found or failed to decrypt"})

    # 2. Fetch the refresh token (stored with authorizer_id reference)
    rt_secret = await _list_secrets_metadata(
        authorizer_id=authorizer_artifact_id,
        secret_type="oauth_refresh_token",
    )
    if not rt_secret:
        return _json.dumps({"error": "No refresh token found for this authorizer. Connect the account first."})
    refresh_token = await _fetch_and_decrypt_secret(secret_id=rt_secret["id"])
    if not refresh_token:
        return _json.dumps({"error": "Failed to decrypt refresh token"})

    # 3. Exchange refresh token for access token
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "scope": scopes,
            },
        )

    if resp.status_code != 200:
        return _json.dumps({"error": f"Token exchange failed: {resp.status_code} {resp.text[:200]}"})

    token_data = resp.json()
    access_token = token_data.get("access_token")
    provider = config.get("provider", "google")

    # If a new refresh token was returned, rotate the stored one
    new_refresh = token_data.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        headers = _require_user_headers()
        async with httpx.AsyncClient(timeout=10) as client:
            await _delete_credential(client, headers, rt_secret["id"])
            await _create_credential(
                client, headers,
                kind="oauth_refresh_token",
                provider=provider,
                label=f"Refresh token for {sender_address or authorizer_artifact_id}",
                value=new_refresh,
                authorizer_id=authorizer_artifact_id,
            )

    # Cache the new access token
    if access_token:
        await _store_or_rotate_bearer_token(
            authorizer_artifact_id=authorizer_artifact_id,
            provider=provider,
            access_token=access_token,
            expires_in=token_data.get("expires_in"),
        )

    return _json.dumps({"access_token": access_token, "sender_address": sender_address})


async def complete_authorizer_oauth(
    authorizer_config: str,
    authorizer_artifact_id: str,
    authorization_code: str,
    code_verifier: str,
    redirect_uri: str,
) -> str:
    """Exchange an OAuth authorization code for tokens and store the refresh token.

    Args:
        authorizer_config: JSON content of the Authorizer artifact.
        authorizer_artifact_id: Artifact ID of the Authorizer.
        authorization_code: The OAuth authorization code from the callback.
        code_verifier: The PKCE code verifier.
        redirect_uri: The redirect URI used in the original authorization request.

    User identity is carried at the transport layer via the delegation JWT.
    """
    try:
        config = _json.loads(authorizer_config) if isinstance(authorizer_config, str) else authorizer_config
    except Exception:
        return _json.dumps({"error": "Invalid authorizer_config JSON"})

    client_id = config.get("client_id")
    client_secret_id = config.get("client_secret_id")
    token_endpoint = config.get("token_endpoint")
    provider = config.get("provider", "google")

    if not all([client_id, client_secret_id, token_endpoint]):
        return _json.dumps({"error": "authorizer_config missing required fields"})

    # Decrypt client_secret via JWE
    client_secret = await _fetch_and_decrypt_secret(secret_id=client_secret_id)
    if not client_secret:
        return _json.dumps({"error": "Client secret not found or failed to decrypt"})

    # Exchange authorization code for tokens
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )

    if resp.status_code != 200:
        return _json.dumps({"error": f"Token exchange failed: {resp.status_code} {resp.text[:200]}"})

    token_data = resp.json()
    refresh_token = token_data.get("refresh_token")

    if not refresh_token:
        return _json.dumps({"error": "No refresh_token in token response. Ensure offline access is requested."})

    # Store refresh token as a secret with authorizer_id delegation
    async with httpx.AsyncClient(timeout=10) as client:
        store_resp = await _create_credential(
            client, _require_user_headers(),
            kind="oauth_refresh_token",
            provider=provider,
            label=f"OAuth refresh for {authorizer_artifact_id}",
            value=refresh_token,
            authorizer_id=authorizer_artifact_id,
        )

    if store_resp.status_code >= 400:
        return _json.dumps({"error": f"Failed to store refresh token: {store_resp.text[:200]}"})

    # Cache the initial access token so the first tool call works without an
    # extra round-trip to provide_access_token.
    initial_access_token = token_data.get("access_token")
    if initial_access_token:
        await _store_or_rotate_bearer_token(
            authorizer_artifact_id=authorizer_artifact_id,
            provider=provider,
            access_token=initial_access_token,
            expires_in=token_data.get("expires_in"),
        )

    return _json.dumps({"status": "connected", "authorizer_artifact_id": authorizer_artifact_id})


@mcp.tool(description="Complete a bearer-token-only authorization code exchange (no refresh token)")
async def complete_authorizer_bearer(
    authorizer_config: str,
    authorizer_artifact_id: str,
    authorization_code: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,
) -> str:
    """Exchange an authorization code for a bearer token (no refresh token flow).

    For providers that return only an access_token with no refresh token
    (e.g. JarvisGPT). The access token is stored as a secret with an
    expiry timestamp; when it expires the user must re-authenticate.

    Args:
        authorizer_config: JSON content of the Authorizer artifact.
        authorizer_artifact_id: Artifact ID of the Authorizer.
        authorization_code: The authorization code from the callback.
        redirect_uri: The redirect URI used in the original request.
        code_verifier: Optional PKCE code verifier.

    User identity is carried at the transport layer via the delegation JWT.
    """
    try:
        config = _json.loads(authorizer_config) if isinstance(authorizer_config, str) else authorizer_config
    except Exception:
        return _json.dumps({"error": "Invalid authorizer_config JSON"})

    token_endpoint = config.get("token_endpoint")
    if not token_endpoint:
        return _json.dumps({"error": "authorizer_config missing token_endpoint"})

    client_id = config.get("client_id")
    provider = config.get("provider", "external")

    # Build token exchange payload
    token_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": redirect_uri,
    }
    if client_id:
        token_data["client_id"] = client_id
    if code_verifier:
        token_data["code_verifier"] = code_verifier

    # Optionally decrypt client secret via Core
    client_secret_id = config.get("client_secret_id")
    if client_secret_id:
        decrypted_cs = await _fetch_and_decrypt_secret(secret_id=client_secret_id)
        if decrypted_cs:
            token_data["client_secret"] = decrypted_cs

    # Exchange authorization code for access token
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_endpoint, data=token_data)

    if resp.status_code != 200:
        return _json.dumps({"error": f"Token exchange failed: {resp.status_code} {resp.text[:200]}"})

    result = resp.json()
    access_token = result.get("access_token")
    if not access_token:
        return _json.dumps({"error": "No access_token in token response"})

    await _store_or_rotate_bearer_token(
        authorizer_artifact_id=authorizer_artifact_id,
        provider=provider,
        access_token=access_token,
        expires_in=result.get("expires_in"),
    )

    return _json.dumps({
        "status": "connected",
        "authorizer_artifact_id": authorizer_artifact_id,
    })


# ---------------------------------------------------------------------------
# LLM credential resolution
# ---------------------------------------------------------------------------

@mcp.tool(
    description=(
        "Raises. No-models rule, universal and including BYOK: this platform "
        "hands out no model API keys."
    )
)
async def resolve_llm_credentials(
    credentials_ref: str,
) -> str:
    """Resolve LLM credentials from a connection artifact's credentials_ref.

    Args:
        credentials_ref: JSON string of the credentials_ref object from the LLM Connection
            artifact context (contains secret_id, secret_type, provider, resolution).

    User identity is carried at the transport layer via the delegation JWT.
    """
    raise NotImplementedError(
        "resolve_llm_credentials: no-models rule; this platform resolves no "
        "model API keys."
    )


# ---------------------------------------------------------------------------
# AWS credential decryption
# ---------------------------------------------------------------------------

@mcp.tool(description="Decrypt and return AWS credentials for a credential artifact")
async def provide_aws_credentials(
    credential_artifact_id: str,
    workspace_id: str,
) -> str:
    """Fetch an AWS credentials artifact, decrypt the secret access key, and return both credentials.

    The credential artifact is a plain application/json artifact whose context
    stores aws_access_key_id and a reference (secret_id) to the encrypted
    aws_secret_access_key held as a Seraph-managed secret.

    Args:
        credential_artifact_id: Artifact ID of the application/json credential artifact.
        workspace_id: Workspace containing the credential artifact.
    """
    # 1. Fetch the credential artifact to get context fields.
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            artifact_url(MANTLE_URI, credential_artifact_id),
            # Fails closed on a caller-supplied credential artifact id. This tool resolves AWS
            # credentials; under the platform JWT a caller naming any credential artifact would have
            # it fetched under platform authority — the worst possible place for a fallback.
            headers=_require_user_headers(),
        )
    if resp.status_code != 200:
        return _json.dumps({"error": f"Failed to fetch credential artifact: {resp.status_code}"})

    artifact = resp.json()
    ctx = artifact.get("context", {})
    if isinstance(ctx, str):
        try:
            ctx = _json.loads(ctx)
        except Exception:
            return _json.dumps({"error": "Invalid credential artifact context"})

    aws_access_key_id = ctx.get("aws_access_key_id")
    secret_id = ctx.get("secret_id")
    aws_region = ctx.get("aws_region", "us-east-1")

    if not aws_access_key_id or not secret_id:
        return _json.dumps({"error": "Credential artifact missing aws_access_key_id or secret_id"})

    # 2. Decrypt the secret access key using the stored delegation context or
    # the server's own platform credentials.
    aws_secret_access_key = await _fetch_and_decrypt_secret(secret_id=secret_id)
    if not aws_secret_access_key:
        return _json.dumps({"error": "AWS secret access key not found or could not be decrypted"})

    # 3. Return credentials (transient � not stored or logged).
    return _json.dumps({
        "aws_access_key_id": aws_access_key_id,
        "aws_secret_access_key": aws_secret_access_key,
        "aws_region": aws_region,
    })


# ---------------------------------------------------------------------------
# Security & governance tool stubs
# ---------------------------------------------------------------------------

@mcp.tool(description="Query the access audit log for a resource")
async def audit_access(
    resource_id: str,
    limit: int = 50,
    result: Optional[str] = None,
) -> str:
    """An artifact's own access history — who touched it, when, allowed or denied.

    Wired to mantle's `GET /artifacts/{id}/access-log`, which requires `admin` on the artifact and is
    itself witnessed through the same `check_access` gate — so reading the audit is audited.

    There is no `user_id` filter. "Show me everything this person touched" is a cross-resource
    surveillance query, and mantle's audit is scoped per-artifact behind an admin check for that
    reason; a person-scoped audit needs its own server-side design and its own authorization, not a
    client-side fan-out from a persona.

    `result` filters to `allowed` or `denied` (server-side).
    """
    headers = _require_user_headers()
    params: dict = {"limit": max(1, min(int(limit), 1000))}
    if result in ("allowed", "denied"):
        params["result"] = result
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(artifact_url(MANTLE_URI, resource_id, "access-log"),
                                params=params, headers=headers)
    if resp.status_code != 200:
        log.error("audit_access refused: %s %s", resp.status_code, resp.text[:200])
        return _json.dumps({"error": "access log unavailable (admin on the artifact required)",
                            "status": resp.status_code, "resource_id": resource_id})
    return _json.dumps(resp.json())


@mcp.tool(description="Check what a person or API key can access")
async def check_permissions(
    resource_id: str,
    action: str = "read",
) -> str:
    """The caller's effective verdict for one CRUDEASIO action on one resource.

    Asks, never derives. Mantle's `/grants/my-access` is explicit that effective access is a
    light-cone computation that "must never be re-derived client-side" — it delegates to the same
    audited `check_access` chokepoint every enforcing route uses, so this verdict cannot drift from
    the verdict at the data path, and each probe is witnessed in the access audit.

    There is no `subject` parameter: a persona cannot ask "what can *that* person do" — that would be
    an enumeration oracle over someone else's access. The server answers only for the authenticated
    caller, carried by the delegation JWT. Listing a resource's grants is a separate, admin-gated call
    (`/grants?resource_id=…`).
    """
    headers = _require_user_headers()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{MANTLE_URI}/grants/my-access",
            params={"resource_id": resource_id, "action": action},
            headers=headers,
        )
    if resp.status_code != 200:
        log.error("check_permissions failed: %s %s", resp.status_code, resp.text[:200])
        return _json.dumps({"error": "permission check failed",
                            "status": resp.status_code, "resource_id": resource_id})
    # Denial and nonexistence both return allowed=false — no existence oracle. Passed through as-is.
    return _json.dumps(resp.json())


@mcp.tool(description="Grant access to a collection for a person or team")
async def grant_access(
    collection_id: str,
    grantee: str,
    role: str = "viewer",
    grantee_type: str = "invite",
) -> str:
    """Grant `role` on a collection, as an `invite` by default.

    Default is `invite` deliberately: mantle requires only can_share for an invite but can_admin for
    a direct user→user grant, because a direct grant bypasses the claim/identity flow. Defaulting to
    the weaker, identity-verifying path is the honest default; pass `grantee_type="user"` explicitly
    to make the stronger request, and mantle will refuse it unless the caller really is an admin.

    Authorization is Mantle's — this tool never decides, it asks. A refusal comes back as the
    server's status, not as a local judgement.
    """
    # Fails closed on a caller-supplied `collection_id`. A fallback to Seraph's platform JWT here
    # would let an unauthenticated request mint a grant on a collection of its choosing under
    # platform authority. Grant minting is the most privileged write in the system; there is no
    # defensible fallback for it.
    headers = _require_user_headers()
    body = {"resource_id": collection_id, "grantee_type": grantee_type, "role": role,
            "target_entity": grantee,
            "target_entity_type": "email" if "@" in grantee else "person"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{MANTLE_URI}/grants", headers=headers, json=body)
    if resp.status_code not in (200, 201):
        log.error("grant_access refused: %s %s", resp.status_code, resp.text[:200])
        return _json.dumps({"error": "grant refused by mantle", "status": resp.status_code,
                            "detail": resp.text[:300]})
    return _json.dumps(resp.json())


@mcp.tool(description="Revoke access to a collection")
async def revoke_access(
    collection_id: str,
    grantee: str,
) -> str:
    """Revoke every grant this grantee holds on the collection.

    Two calls by necessity: mantle revokes by grant id (`DELETE /grants/{id}`), and a grantee may
    hold several grants on one resource, so the set is listed first and each revoked. Listing is
    admin-gated server-side, so a non-admin caller is refused at the list step rather than partially
    revoking.

    Reports per-grant outcomes rather than a single boolean. A partial revoke — some grants removed,
    one refused — is a real state; collapsing it to "ok" would leave access in place while reporting
    success.
    """
    # Fails closed, same reasoning as `grant_access`. Revocation is worse to escalate: the docstring
    # above relies on "listing is admin-gated server-side" to refuse a non-admin, but under a
    # platform-JWT fallback the caller would be effectively admin, so that gate would open and the
    # revoke would proceed. A tool that removes someone's access runs only on the caller's own
    # authority.
    headers = _require_user_headers()
    async with httpx.AsyncClient(timeout=10) as client:
        listed = await client.get(f"{MANTLE_URI}/grants",
                                  params={"resource_id": collection_id}, headers=headers)
        if listed.status_code != 200:
            log.error("revoke_access could not list grants: %s %s",
                      listed.status_code, listed.text[:200])
            return _json.dumps({"error": "cannot list grants (admin required)",
                                "status": listed.status_code, "revoked": []})
        targets = [g for g in listed.json()
                   if grantee in (g.get("grantee_id"), g.get("target_entity"), g.get("name"))]
        results = []
        for g in targets:
            gid = g.get("id") or g.get("grant_id")
            r = await client.delete(f"{MANTLE_URI}/grants/{gid}", headers=headers)
            results.append({"grant_id": gid, "status": r.status_code,
                            "revoked": r.status_code in (200, 204)})
    return _json.dumps({"resource_id": collection_id, "grantee": grantee,
                        "matched": len(targets), "results": results,
                        "all_revoked": bool(results) and all(x["revoked"] for x in results)})


# `rotate_api_key` was removed 2026-08-26, and it had never worked.
#
# It read, re-issued and revoked against `GET|POST|DELETE {MANTLE_URI}/api-keys[/{id}]` — a plane
# mantle does not serve. Its first call 404'd, the tool returned its own
# "cannot read the existing key — refusing to rotate" branch, and an operator was told the
# rotation was refused for safety rather than that the endpoint was gone.
#
# Removed rather than repointed, and the tool's own docstring is the argument. Mantle's
# surviving key surface is `/grants/keys`, whose contract is PER-RESOURCE CRUDEASIO
# (`can_read`, `can_update`, … plus `resource_id`, `role`, `expires_at`). The old one was
# SCOPE-based (`scopes[]`, `resource_filters`, `client_id`/`host_id`/`server_id`/`agent_id`).
# There is no mechanical mapping between them — and this tool existed precisely to stop a
# rotation silently re-scoping a key: *"guessing here would quietly widen access during a
# security operation"*. Inventing that mapping is the thing it was written to refuse.
#
# Rotating a grant key is `POST /grants/keys` + `DELETE /grants/keys/{key_id}`, and what the
# replacement should carry is an authorization decision, not a translation. Left for that
# decision rather than approximated here.


@mcp.tool(description="Verify a JWT against the platform JWKS and return which class it is, plus claims")
async def verify_token(
    token: str,
) -> str:
    """Verify a token and say what it is — not merely that it is "valid".

    The platform issues several distinct token classes and they authorize different things: a
    delegation JWT (a user acting through a server), an origin delegation, a plain user JWT, and a
    core/service JWT. **"Valid" on its own is not a usable answer — valid as what?** A caller that
    treats a service token as a user token has been told the truth and still gets it wrong. So this
    reports the class that verified, and returns claims only for that class.

    Verification uses the same `_auth` verifiers the enforcing paths use (which check against origin's
    published JWKS), so a verdict here cannot drift from a verdict at an enforcing route.

    Reports failure without a per-class reason. Saying which check failed and how would help shape a
    forgery attempt; "did not verify as any known class" is the sufficient answer. API keys are not
    accepted here — they are not JWTs, are checked by a different mechanism, and treating them as
    tokens would blur two authorization paths.
    """
    checks = (
        ("delegation", _auth.verify_delegation_jwt),
        ("origin_delegation", _auth.verify_origin_delegation),
        ("user", _auth.verify_user_jwt),
        ("core", _auth.verify_core_jwt),
    )
    for name, fn in checks:
        try:
            claims = fn(token)
        except Exception:                    # a verifier that raises is a refusal, not a crash
            continue
        if claims:
            return _json.dumps({"valid": True, "token_class": name, "claims": claims})
    return _json.dumps({
        "valid": False,
        "token_class": None,
        "detail": "did not verify as any known token class "
                  "(delegation | origin_delegation | user | core)",
    })


@mcp.tool(description="Evaluate a request or card against active system policies")
async def enforce_policy(
    resource_id: str,
    action: str,
    context: Optional[str] = None,
) -> str:
    """Check whether a proposed action on a resource is allowed by current policies."""
    raise NotImplementedError("enforce_policy is a declared placeholder.")


@mcp.tool(description="List active governance policies")
async def list_policies(
    scope: Optional[str] = None,
) -> str:
    """Return active policies, optionally filtered by scope (e.g. 'collection', 'workspace')."""
    raise NotImplementedError("list_policies is a declared placeholder.")


@mcp.tool(description="Check compliance of a resource or workflow against governance rules")
async def check_compliance(
    resource_id: str,
    workspace_id: Optional[str] = None,
) -> str:
    """Assess whether a resource or workflow meets all applicable compliance requirements."""
    raise NotImplementedError("check_compliance is a declared placeholder.")


# ---------------------------------------------------------------------------
# Person management (Origin)
#
# Verification is a contract; issuance is a service. That line decides which of Origin's surfaces
# may live here:
#
#   * Issuance stays a public HTTP service — OIDC (`/auth/authorize|callback|token|userinfo`,
#     `/.well-known/*`), WebAuthn ceremonies, OTP, password/email flows, `/internal/*` delegation
#     minting, `/oracle` key custody, `/auth/clients` (it mints client secrets), and `/setup`
#     (first-boot, runs before any token exists). A tekton invocation needs a verified token, and
#     issuance is what mints one; a tekton that issued tokens would need a token to call itself.
#
#   * Two surfaces that read as management still do not live here. `passkey_router.list/delete
#     credentials` and all of `platform_router` (settings + users) gate on `principal_type == "user"
#     AND actor is None` — they refuse a delegation, because a delegated machine token must not
#     manage authentication factors or rewrite platform settings. A seraph tekton is a delegated
#     machine token (`act.sub == agience-server-seraph`), so exposing them here would require
#     weakening Origin's gate. They stay where they are.
#
# What is left after both cuts is person preferences, and only that. It needs no issuance internal —
# just a verified token and the person the token names.
# ---------------------------------------------------------------------------

async def _origin_preferences(method: str, payload: dict | None = None) -> str:
    """One wire path for both preference tools.

    Uses `_require_user_headers()` and nothing else. It raises `MissingDelegationError` when no
    verified delegation is in context; these tools never fall through to `_headers()`, which resolves
    to Seraph's own platform JWT. Origin's `/auth/me/*` routes resolve the person from the token
    (`get_person` -> `auth.user_id`), so a platform-JWT fallback would not read "nobody's
    preferences" — it would read whatever person Seraph's service identity resolves to. A preferences
    read that silently returns the wrong person's settings looks like a working tool.
    """
    headers = _require_user_headers()
    url = f"{ORIGIN_URI}/auth/me/preferences"
    async with httpx.AsyncClient(timeout=10) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        else:
            resp = await client.patch(url, headers=headers, json=payload or {})
    if resp.status_code != 200:
        log.error("origin %s /auth/me/preferences refused: %s %s",
                  method, resp.status_code, resp.text[:200])
        return _json.dumps({"error": "preferences unavailable",
                            "status": resp.status_code})
    return _json.dumps(resp.json())


@mcp.tool(description="Read the calling person's stored preferences from Origin")
async def get_person_preferences() -> str:
    """The caller's own preferences — never a person named in an argument.

    There is deliberately no `person_id` parameter. Origin derives the person from the delegation's
    `sub`, so this tool cannot be pointed at someone else's settings; adding the argument would
    create exactly the enumeration oracle `check_permissions` above refuses to be.
    """
    return await _origin_preferences("GET")


@mcp.tool(description="Update the calling person's preferences in Origin (shallow merge)")
async def set_person_preferences(preferences: str) -> str:
    """Merges into the stored preferences and returns the merged result.

    Shallow merge, not replace — this mirrors `origin.person_service.update_preferences` exactly,
    and the distinction is load-bearing: a caller sending one key must not blank the others. The
    merge happens server-side at Origin; doing it here would put the same rule in two repos with a
    drift gate between them, and read-modify-write from a client would lose a concurrent update.
    This tool only forwards.
    """
    try:
        parsed = _json.loads(preferences) if isinstance(preferences, str) else preferences
    except Exception:
        return _json.dumps({"error": "Invalid preferences JSON"})
    if not isinstance(parsed, dict):
        return _json.dumps({"error": "preferences must be a JSON object"})
    return await _origin_preferences("PATCH", parsed)


# ---------------------------------------------------------------------------
# UI Resources
# ---------------------------------------------------------------------------

@mcp.resource("ui://seraph/vnd.agience.key.html")
async def key_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.key+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.key+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://seraph/vnd.agience.authority.html")
async def authority_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.authority+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.authority+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://seraph/vnd.agience.authorizer.html")
async def authorizer_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.authorizer+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.authorizer+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


@mcp.resource("ui://seraph/vnd.agience.signature.html")
async def signature_viewer_html() -> str:
    """Serve the viewer HTML for vnd.agience.signature+json."""
    view_path = pathlib.Path(__file__).parent / "ui" / "application" / "vnd.agience.signature+json" / "view.html"
    return view_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Standard server interface (used by _host and standalone)
# ---------------------------------------------------------------------------

def create_server_app():
    """Return the Seraph ASGI app with verified middleware and startup hooks."""
    return create_seraph_app()


async def server_startup() -> None:
    """Run Seraph startup tasks. Trust map is on disk in Phase C; nothing to fetch."""
    await _auth.startup()


# ---------------------------------------------------------------------------
# Self-registration (GENESIS-NEXT §B1.10): this persona owns its registration.
# The host holds no roster — it calls each persona's register(). PERSONA is the
# single source of truth for {name, role, endpoint}; register() self-registers
# with Mantle (server record) + the crystal gateway (owned types).
# ---------------------------------------------------------------------------
PERSONA = {
    "name": "seraph",
    "kind": "tekton",
    "role": "Security & Governance",
    "endpoint": "/seraph/mcp",
    "client_id": SERAPH_CLIENT_ID,
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
    log.info("Starting agience-server-seraph � transport=%s port=%s", MCP_TRANSPORT, MCP_PORT)
    if MCP_TRANSPORT == "streamable-http":
        import uvicorn
        uvicorn.run(create_server_app(), host=MCP_HOST, port=MCP_PORT)
    else:
        mcp.run()
