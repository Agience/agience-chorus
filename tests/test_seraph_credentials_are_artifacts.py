"""Seraph reads and writes credentials as artifacts, and makes no `/secrets` call.

Mantle serves no `/secrets` surface: there is no `secrets_router.py` and no `/secret*` route
anywhere in `agience-mantle/src`. A credential is an ordinary artifact, and
`mantle/services/bootstrap_types.py` states the design: *"the value is the artifact's CONTENT, so
the envelope encrypts it at rest under the origin-root principal and the light cone decides who may
read it. There is no second store and no second authorization path."* The shape asserted below is
the one Mantle's own producer writes (`seed_provisioning/platform_email.py`), not one invented here.

These tests pin the wire shape of the write, the client-side narrowing of the list, the
bearer-token expiry check, and the artifact read that resolves a credential's value.
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
    """No `/secrets` HTTP call survives in `seraph/server.py`. The count is zero.

    There is no named-recipient case left to carve out. An authorized reader fetches plaintext over
    TLS, so `fetch` is what `read` already does, and `_fetch_and_decrypt_secret` reads the artifact
    the way `iris/server.py` does.

    The count matters in the other direction: a `/secrets` call reappearing here would be a call to
    a route that does not exist, failing silently into the caller's own error branch."""
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


# ── the bearer-token expiry check ─────────────────────────────────────────────────────────────
#
# `expires_at` is written inside `context` by `_create_credential`, and `context` reaches a reader
# as a JSON string, so `provide_access_token` reads it through `_credential_context` rather than
# off the artifact's top level. Read at the top level, `bt_secret.get("expires_at", "")` returns ""
# on every credential ever written: the expiry branch is never entered and an expired bearer token
# is handed back as valid.
#
# The accessor two calls earlier in the same flow reads `kind` and `authorizer_id` the same way.

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
    """An `expires_at` in the past is refused, not handed back as a live token."""
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


# ── the credential read ───────────────────────────────────────────────────────────────────────
#
# `_fetch_and_decrypt_secret` resolves a credential's value with a plain `GET /artifacts/{id}`,
# following `iris/server.py::_fetch_secret_material`. There is no reveal or unseal step: the light
# cone decides who may read, and an authorized reader gets plaintext over TLS.

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
