# agience-server-seraph

Status: **Live** — 10 of 14 registered tools are implemented; 4 raise (see Tool Surface).

**Domain**: Security, Governance & Trust — access control, audit trails, identity verification, policy compliance, cryptographic signing

---

## Responsibility

Seraph is the guardian layer of the Agience platform. It enforces access policies, maintains a tamper-evident audit trail of all security events, verifies identities and tokens, ensures governance policy compliance, and enables cryptographic signing of knowledge artifacts.

---

## Tool Surface

Every row below is derived from the `@mcp.tool` registrations in `server.py`, not maintained by
hand. Ten tools are live; four are declared placeholders that raise `NotImplementedError`.

Seraph's management surface over Origin is limited to person preferences (`get_person_preferences`,
`set_person_preferences`). Passkey credential management and the whole `/system` router (settings)
are not exposed here: both gate on `principal_type == "user" AND actor is None`, deliberately
refusing a delegation, and a seraph tekton is always a delegation (`act.sub ==
agience-server-seraph`). Everything else on Origin is issuance rather than management: OIDC, WebAuthn,
OTP, password/email flows, JWKS, `/oracle` key custody, `/auth/clients` (it mints client secrets),
`/setup`, and `/internal/*` delegation minting.

Implemented (live):

| Tool | Description |
|---|---|
| `complete_authorizer_bearer` | Complete a bearer-token-only authorization code exchange (no refresh token) |
| `provide_aws_credentials` | Decrypt and return AWS credentials for a credential artifact |
| `audit_access` | Query the access audit log for a resource |
| `check_permissions` | Check what a person or API key can access |
| `grant_access` | Grant access to a collection for a person or team |
| `revoke_access` | Revoke access to a collection |
| `verify_token` | Verify a JWT against the platform JWKS and return whether it is a valid access token, and of which class |
| `get_person_preferences` | Read the calling person's stored preferences from Origin |
| `set_person_preferences` | Update the calling person's preferences in Origin (shallow merge) |

Declared placeholders (registered, raise `NotImplementedError`):

| Tool | Description |
|---|---|
| `resolve_llm_credentials` | Raises. No-models rule, universal and including BYOK: this platform hands out no model API keys |
| `enforce_policy` | Evaluate a request or card against active system policies |
| `list_policies` | List active governance policies |
| `check_compliance` | Check compliance of a resource or workflow against governance rules |

`provide_aws_credentials` returns a decrypted AWS secret access key, gated on
`_require_user_headers()`. `resolve_llm_credentials` raises — this platform hands out no model API
keys (no-models rule, universal and including BYOK).

`verify_token` returns only `valid` and `token_class`, never the claims. A token carrying
`token_type` (Origin's refresh, email-verification and password-reset tokens) is not an access token
and does not verify. API keys are not accepted, since they are not JWTs.

`complete_authorizer_bearer` reads the Authorizer's config from the stored artifact
(`authorizer_artifact_id`, under the caller's delegation) and takes no config argument. Its
`token_endpoint` must be in `agience_chorus._egress.OAUTH_TOKEN_ENDPOINTS`; any other is refused.

## Auth

The real auth mechanism is a self-issued platform JWT signed with the chorus service identity;
`AGIENCE_API_KEY` and `AGIENCE_API_URI` are not read anywhere in `server.py`.

| Env var | Description |
|---|---|
| `MANTLE_URI` | **Required.** Base URI of the Mantle backend (defaults to `http://localhost:8081`) |
| `ORIGIN_URI` | Base URI of the identity authority (defaults to `http://localhost:8080`). Read by the person-management tektons. Origin is reached over the wire — `chorus → origin` is 0 imports and guarded by `src/tests/test_chorus_does_not_import_origin.py` |
| `MCP_HOST` / `MCP_PORT` / `MCP_TRANSPORT` | MCP server bind host, port and transport |
| `LOG_LEVEL` | Logging level |

Derived from `server.py`; `.well-known/mcp.json` is generated from the same source.

---

## Quick Start

```bash
pip install -e .
export MANTLE_URI=http://localhost:8081
python server.py
```

---

## Target Repo

`github.com/Agience/agience-server-seraph` (public)
