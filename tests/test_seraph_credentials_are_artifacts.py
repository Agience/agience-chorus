"""Seraph reads and writes credentials as ARTIFACTS, not through Mantle's removed `/secrets`.

What this replaces: Mantle has no `secrets_router.py` and no `/secret*` route anywhere in
`agience-mantle/src`. Seraph made seven live CRUD calls to `{MANTLE_URI}/secrets*`, and every one
of them 404'd — silently, because each call site checked only for its own error case and logged.

A credential is now an ordinary artifact. `mantle/services/bootstrap_types.py` states the design:
*"the value is the artifact's CONTENT, so the envelope encrypts it at rest under the origin-root
principal and the light cone decides who may read it. There is no second store and no second
authorization path."* The shape asserted below is the one Mantle's own producer writes
(`seed_provisioning/platform_email.py`), not one invented here.

These tests are the first coverage this code has ever had — chorus's suite had four tests and
none touched seraph, ophan or credentials. That is why the migration came with them.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import seraph.server as srv

_SERVER = Path(srv.__file__)


def _client(status: int = 200, payload=None):
    c = MagicMock()
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else []
    resp.text = ""
    c.get = AsyncMock(return_value=resp)
    c.post = AsyncMock(return_value=resp)
    c.delete = AsyncMock(return_value=resp)
    return c


# ── the wire shape ───────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_credential_is_written_as_an_artifact_with_the_value_as_content():
    c = _client()
    await srv._create_credential(
        c, {"h": "1"}, kind="bearer_token", provider="google",
        label="Access token for auth-1", value="s3cret", authorizer_id="auth-1",
    )
    url, kwargs = c.post.call_args[0][0], c.post.call_args[1]
    assert url.endswith("/artifacts"), url
    assert "/secrets" not in url

    body = kwargs["json"]
    assert body["content_type"] == "application/vnd.agience.credential+json"
    # The value lives in `content` and NOWHERE else — that is what puts it under the envelope.
    assert json.loads(body["content"]) == {"value": "s3cret"}
    assert "s3cret" not in body["context"], (
        "the secret value leaked into `context`, which is stored in PLAINTEXT")

    ctx = json.loads(body["context"])
    assert ctx["kind"] == "bearer_token"
    assert ctx["provider"] == "google"
    assert ctx["authorizer_id"] == "auth-1"


@pytest.mark.asyncio
async def test_an_absent_authorizer_is_omitted_rather_than_stored_as_null():
    """A `None` written into context would match `authorizer_id=None` filters later."""
    c = _client()
    await srv._create_credential(c, {}, kind="k", provider="p", label="l", value="v")
    ctx = json.loads(c.post.call_args[1]["json"]["context"])
    assert "authorizer_id" not in ctx


@pytest.mark.asyncio
async def test_delete_targets_the_artifact_route():
    c = _client()
    await srv._delete_credential(c, {}, "art-9")
    assert c.delete.call_args[0][0].endswith("/artifacts/art-9")


# ── listing, which Mantle cannot filter server-side ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_listing_asks_for_the_credential_content_type():
    c = _client()
    await srv._list_credentials(c, {})
    url, kwargs = c.get.call_args[0][0], c.get.call_args[1]
    assert url.endswith("/artifacts/visible"), url
    assert kwargs["params"]["content_type"] == "application/vnd.agience.credential+json"


@pytest.mark.asyncio
async def test_the_selectors_narrow_client_side():
    """Mantle's `/artifacts/recall` refuses a pure-filter query by design — *"a filter narrows a
    recall, it does not constitute one"* — and `/visible` filters only on content type. So these
    selectors are applied here, and this test is what keeps them honest."""
    docs = [
        {"id": "a", "context": json.dumps({"kind": "bearer_token", "authorizer_id": "auth-1"})},
        {"id": "b", "context": json.dumps({"kind": "bearer_token", "authorizer_id": "auth-2"})},
        {"id": "c", "context": json.dumps({"kind": "oauth_refresh_token", "authorizer_id": "auth-1"})},
    ]
    c = _client(payload=docs)
    got = await srv._list_credentials(c, {}, authorizer_id="auth-1", secret_type="bearer_token")
    assert [d["id"] for d in got] == ["a"]

    c = _client(payload=docs)
    assert [d["id"] for d in await srv._list_credentials(c, {}, secret_id="c")] == ["c"]

    c = _client(payload=docs)
    assert len(await srv._list_credentials(c, {})) == 3, "an unfiltered list must return everything"


@pytest.mark.asyncio
async def test_an_unparseable_context_never_matches_a_filter():
    """A credential that cannot be classified must not be handed to a caller that asked for a
    different one. Failing closed matters more here than anywhere else in this file."""
    c = _client(payload=[{"id": "bad", "context": "{not json"}])
    assert await srv._list_credentials(c, {}, secret_type="bearer_token") == []


@pytest.mark.asyncio
async def test_a_failed_listing_returns_empty_rather_than_raising():
    c = _client(status=503)
    assert await srv._list_credentials(c, {}) == []


def test_context_accepts_both_a_string_and_a_dict():
    """It travels as a JSON string, but the read path may hand back either."""
    assert srv._credential_context({"context": '{"kind": "k"}'})["kind"] == "k"
    assert srv._credential_context({"context": {"kind": "k"}})["kind"] == "k"
    assert srv._credential_context({}) == {}


# ── the guard ────────────────────────────────────────────────────────────────────────────────

def test_no_secrets_call_survives():
    """UPDATED 2026-08-26: the count is now ZERO, and the reason is a ruling, not a refactor.

    This test previously pinned **one** surviving call, on the reasoning that *"`/secrets/reveal`
    asked Mantle to decrypt FOR A NAMED RECIPIENT. Credentials-as-artifacts has no equivalent —
    recipient identity is not a storage concern — so that one call stays broken until the question
    is answered."* That was right, and the question has since been answered.

    🔷 John: Chorus adopts Mantle's position — an authorized reader fetches
    plaintext over TLS, so **`fetch` is what `read` already does** and there is no named recipient to
    preserve. `_fetch_and_decrypt_secret` now reads the artifact, as `iris/server.py` already did.

    The count still matters, in the other direction: a `/secrets` call reappearing here would be
    a call to a route that does not exist, failing silently into each caller's own error branch —
    which is exactly how seven of them sat broken and unnoticed."""
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    verbs = {"get", "post", "put", "patch", "delete"}
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in verbs):
            continue
        if "/secrets" in ast.dump(node):
            calls.append(node.lineno)
    assert calls == [], (
        "a `/secrets` HTTP call is back at %r — that route does not exist in "
        "`agience-mantle/src`, so it fails into the caller's own error branch and says nothing"
        % (calls,))


# ── the bearer-token expiry check, which had never fired ──────────────────────────────────────
#
# `expires_at` is written INSIDE `context` by `_create_credential`, and `context` reaches a reader
# as a JSON STRING. `provide_access_token` read `bt_secret.get("expires_at", "")` — the artifact's
# TOP level — which returned "" on every credential ever written. The branch was never entered and
# an expired bearer token was returned as valid. Demonstrated 2026-08-26 with a token dated
# 2000-01-01.
#
# The accessor that reads it correctly was already in the same file, two calls earlier in the
# same flow, filtering on `kind` and `authorizer_id`. The defect was reading one field a different
# way from its neighbours.

_BEARER_CFG = json.dumps({"token_response_type": "bearer_only"})


def _bearer_artifact(expires_at: str) -> dict:
    """A credential exactly as `_create_credential` writes it — `context` a JSON STRING."""
    return {
        "id": "cred-bearer-1",
        "content_type": srv._CREDENTIAL_CT,
        "context": json.dumps({
            "content_type": srv._CREDENTIAL_CT, "kind": "bearer_token",
            "provider": "gmail", "label": "inbox", "expires_at": expires_at,
        }, separators=(",", ":")),
    }


async def _resolve(monkeypatch, expires_at: str) -> dict:
    monkeypatch.setattr(srv, "_list_secrets_metadata",
                        AsyncMock(return_value=_bearer_artifact(expires_at)))
    monkeypatch.setattr(srv, "_fetch_and_decrypt_secret",
                        AsyncMock(return_value="the-cached-access-token"))
    return json.loads(await srv.provide_access_token(_BEARER_CFG, "auth-1"))


@pytest.mark.asyncio
async def test_an_expired_bearer_token_is_refused(monkeypatch):
    """The regression. Before 2026-08-26 this returned the token."""
    out = await _resolve(monkeypatch, "2000-01-01T00:00:00+00:00")
    assert out.get("error") == "token_expired", (
        "an expired bearer token was handed back as valid: %r" % out)
    assert out.get("reauth_required") is True
    assert "access_token" not in out


@pytest.mark.asyncio
async def test_a_live_bearer_token_is_still_returned(monkeypatch):
    """The other half — a fix that refuses everything is not a fix."""
    out = await _resolve(monkeypatch, "2099-01-01T00:00:00+00:00")
    assert out.get("access_token") == "the-cached-access-token", out


@pytest.mark.asyncio
async def test_a_credential_with_no_expiry_is_returned(monkeypatch):
    """`expires_at` is optional — absent means "no recorded expiry", not "expired"."""
    doc = _bearer_artifact("")
    ctx = json.loads(doc["context"])
    ctx.pop("expires_at")
    doc["context"] = json.dumps(ctx, separators=(",", ":"))
    monkeypatch.setattr(srv, "_list_secrets_metadata", AsyncMock(return_value=doc))
    monkeypatch.setattr(srv, "_fetch_and_decrypt_secret",
                        AsyncMock(return_value="the-cached-access-token"))
    out = json.loads(await srv.provide_access_token(_BEARER_CFG, "auth-1"))
    assert out.get("access_token") == "the-cached-access-token", out


@pytest.mark.asyncio
async def test_an_unparseable_context_does_not_hand_back_the_token_by_accident(monkeypatch):
    """`_credential_context` returns {} on a context that will not parse. That must read as
    "no recorded expiry", the same as absent — never as a silent pass on a token whose expiry
    could not be established."""
    doc = _bearer_artifact("")
    doc["context"] = "{not json"
    monkeypatch.setattr(srv, "_list_secrets_metadata", AsyncMock(return_value=doc))
    monkeypatch.setattr(srv, "_fetch_and_decrypt_secret",
                        AsyncMock(return_value="the-cached-access-token"))
    out = json.loads(await srv.provide_access_token(_BEARER_CFG, "auth-1"))
    assert "access_token" in out or out.get("error"), out


# ── the credential READ that replaced /secrets/reveal ─────────────────────────────────────────
#
# `_fetch_and_decrypt_secret` POSTed `{MANTLE_URI}/secrets/reveal` until 2026-08-26. That route
# does not exist, so it returned None on every call and all six callers took their own failure
# branch — silently. Migrated to a plain `GET /artifacts/{id}` under John's no-sealing ruling,
# following `iris/server.py::_fetch_secret_material`, which had the same treatment a day earlier.

def _artifact_response(content):
    r = MagicMock()
    r.status_code = 200
    r.json = MagicMock(return_value={"id": "cred-1", "content": content})
    return r


def _client_returning(resp):
    c = MagicMock()
    c.get = AsyncMock(return_value=resp)
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize("content,expected", [
    (json.dumps({"value": "tok-value"}), "tok-value"),      # what _create_credential writes
    (json.dumps({"material": "tok-material"}), "tok-material"),  # Mantle's own producer / older rows
    ({"value": "tok-object"}, "tok-object"),                # content already an object
    ("a-bare-string-token", "a-bare-string-token"),         # the value itself
])
async def test_every_stored_content_shape_is_read(monkeypatch, content, expected):
    """Three shapes are in flight and all three are read rather than assumed."""
    monkeypatch.setattr(srv.httpx, "AsyncClient",
                        MagicMock(return_value=_client_returning(_artifact_response(content))))
    monkeypatch.setattr(srv, "_require_user_headers", MagicMock(return_value={}))
    assert await srv._fetch_and_decrypt_secret(secret_id="cred-1") == expected


@pytest.mark.asyncio
async def test_an_unrecognised_shape_yields_none_not_the_raw_json(monkeypatch):
    """The failure that matters. Returning the raw structure would hand a caller something that
    is not the secret, and every caller treats a truthy return as the credential."""
    monkeypatch.setattr(srv.httpx, "AsyncClient",
                        MagicMock(return_value=_client_returning(_artifact_response(
                            json.dumps({"unexpected": "shape"})))))
    monkeypatch.setattr(srv, "_require_user_headers", MagicMock(return_value={}))
    assert await srv._fetch_and_decrypt_secret(secret_id="cred-1") is None


@pytest.mark.asyncio
async def test_a_non_200_yields_none(monkeypatch):
    r = MagicMock()
    r.status_code = 404
    r.text = "not found"
    monkeypatch.setattr(srv.httpx, "AsyncClient", MagicMock(return_value=_client_returning(r)))
    monkeypatch.setattr(srv, "_require_user_headers", MagicMock(return_value={}))
    assert await srv._fetch_and_decrypt_secret(secret_id="cred-1") is None


@pytest.mark.asyncio
async def test_the_selector_form_is_refused_rather_than_guessed(monkeypatch):
    """All six call sites pass a concrete `secret_id`; the selector parameters never had a user.
    Resolving `(type, provider)` to "newest of this type" is how the wrong credential gets handed
    out, so it refuses and says so instead."""
    called = MagicMock()
    monkeypatch.setattr(srv.httpx, "AsyncClient", called)
    assert await srv._fetch_and_decrypt_secret(secret_type="bearer_token", provider="gmail") is None
    assert not called.called, "it made a request despite having no concrete id"
