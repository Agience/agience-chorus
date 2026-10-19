"""Invoking an LLM connection card calls the model it names, with the key it points at, on the
caller's own grant to that key, and only at the provider's own address.

2026-10-19: the card type existed (provider, model, a pointer to the key) but declared no working
operation, so nothing could reach a model a person had connected.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agience_chorus import _egress
from agience_chorus.lumen import connection as C

from .test_chain_and_feedback import MockResponse

_spec = importlib.util.spec_from_file_location("chorus_lumen_server_connection",
                                               Path(__file__).resolve().parent.parent / "server.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


def _card(**ctx):
    base = {"provider": "anthropic", "model": "claude-sonnet-5-5",
            "credentials_ref": {"secret_id": "sec-1", "resolution": "user_secret"}}
    return {"id": "conn-1", "content_type": C.CONNECTION_TYPE, "context": json.dumps({**base, **ctx})}


# ── the card ──────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ctx,why", [
    ({"provider": "google"}, "cannot be called"),
    ({"model": ""}, "no model"),
    ({"credentials_ref": {}}, "points at no key"),
    ({"endpoint": "https://collector.example.com/v1/messages"}, "not anthropic's own address"),
])
def test_a_card_that_cannot_be_called_says_why(ctx, why):
    with pytest.raises(C.ConnectionError_, match=why):
        C.read_card(_card(**ctx))


def test_the_providers_own_endpoint_is_accepted():
    assert C.read_card(_card(endpoint="https://api.anthropic.com/v1/messages"))["provider"] == "anthropic"


def test_a_platform_connection_is_an_ordinary_granted_card():
    """No resolution mode beside grants: the platform's connection is a card and a key it granted."""
    card = C.read_card(_card(credentials_ref={"secret_id": "sec-p", "resolution": "platform_secret"}))
    assert card["secret_id"] == "sec-p"


@pytest.mark.parametrize("messages,input,ok", [
    ([{"role": "user", "content": "hi"}], None, True),
    (json.dumps([{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]), None, True),
    (None, "hi", True),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}], None, False),
    ([{"role": "tool", "content": "x"}], None, False),
    (None, None, False),
])
def test_a_conversation_ends_with_a_user_turn(messages, input, ok):
    if ok:
        system, turns = C.messages_of(messages, input)
        assert turns[-1]["role"] == "user" and all(t["role"] != "system" for t in turns)
    else:
        with pytest.raises(C.ConnectionError_):
            C.messages_of(messages, input)


def test_each_provider_gets_its_own_request_shape():
    a = C.build(C.read_card(_card(system_prompt="You are Dana's assistant.")), "sk-a", "be brief",
                [{"role": "user", "content": "hi"}], max_tokens=99999)
    body = json.loads(a.body)
    assert a.url == "https://api.anthropic.com/v1/messages" and a.headers["x-api-key"] == "sk-a"
    assert body["system"] == "You are Dana's assistant.\n\nbe brief" and body["max_tokens"] == C.MAX_TOKENS_CAP
    o = C.build(C.read_card(_card(provider="openai", model="gpt-x")), "sk-o", "",
                [{"role": "user", "content": "hi"}])
    assert o.headers["Authorization"] == "Bearer sk-o"
    assert json.loads(o.body)["max_completion_tokens"] == C.DEFAULT_MAX_TOKENS


@pytest.mark.parametrize("provider,status,payload,expect", [
    ("anthropic", 200, {"content": [{"type": "text", "text": "Hello"}], "model": "m", "stop_reason": "end_turn"}, "Hello"),
    ("openai", 200, {"choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}]}, "Hi"),
    ("anthropic", 401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}, None),
])
def test_the_answer_is_read_or_its_error_named(provider, status, payload, expect):
    out = C.read_answer(provider, status, json.dumps(payload))
    if expect is None:
        assert out["error"].startswith(f"{provider} answered {status}") and "invalid x-api-key" in out["error"]
    else:
        assert out["text"] == expect


# ── the tool ──────────────────────────────────────────────────────────────────────────────────
class Store:
    def __init__(self, docs):
        self.docs, self.calls = docs, []

    def client(self):
        store = self

        class _C:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, **kw):
                store.calls.append((url, headers))
                doc = store.docs.get(url.rsplit("/", 1)[-1])
                return MockResponse(doc or {}, 200 if doc else 404)

            async def post(self, url, headers=None, json=None, **kw):
                store.calls.append((url, headers))
                assert url.endswith("/use"), url
                secret = url.rsplit("/", 2)[-2]
                doc = store.docs.get(secret)
                if not doc:
                    return MockResponse({}, 403)
                from prism.trust import sealing
                content = doc["content"] if isinstance(doc["content"], str) else _json.dumps(doc["content"])
                return MockResponse({"id": secret, "sealed": sealing.seal(
                    content.encode(), LUMEN_KEY.public_key(), kid="lumen-1",
                    context=f"{secret}|{(json or {}).get('for')}")})
        return _C


from cryptography.hazmat.primitives.asymmetric import rsa as _rsa  # noqa: E402
import json as _json  # noqa: E402

LUMEN_KEY = _rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def person(monkeypatch):
    from prism.trust import service_identity
    monkeypatch.setattr(service_identity, "load_persona_identity", lambda name: service_identity.ServiceIdentity(
        name=name, kid=f"{name}-1", private_key=LUMEN_KEY) if name == "lumen" else None)
    tok = L._auth.request_user_token.set("delegation-for-me")
    try:
        yield
    finally:
        L._auth.request_user_token.reset(tok)


@pytest.mark.asyncio
async def test_invoking_the_card_sends_the_conversation_with_its_key_and_returns_the_reply(person):
    store = Store({"conn-1": _card(), "sec-1": {"id": "sec-1", "content": json.dumps({"value": "sk-secret"})}})
    sent = {}

    def fake_post(url, body, *, headers=None, timeout=None):
        sent.update(url=url, body=json.loads(body), headers=headers)
        return _egress.Response(url, 200, "application/json",
                                json.dumps({"content": [{"type": "text", "text": "Four."}], "model": "m",
                                            "usage": {"output_tokens": 2}}).encode(), False, {})

    with patch.object(L.httpx, "AsyncClient", store.client()), patch.object(_egress, "post", fake_post):
        out = json.loads(await L.invoke_connection("conn-1", input="2+2?"))
    assert out["text"] == "Four." and out["connection_id"] == "conn-1" and out["provider"] == "anthropic"
    assert sent["url"] == C.PROVIDERS["anthropic"] and sent["headers"]["x-api-key"] == "sk-secret"
    assert sent["body"]["messages"] == [{"role": "user", "content": "2+2?"}]
    assert all(h["Authorization"] == "Bearer delegation-for-me" for _, h in store.calls), \
        "the card and its key are reached on the caller's own grant"
    assert store.calls[-1][0].endswith("/artifacts/sec-1/use"), "the key is released for use, not read"
    assert "sk-secret" not in json.dumps(out), "the key never returns to the caller"


@pytest.mark.asyncio
async def test_a_caller_who_cannot_use_the_key_is_refused_before_anything_is_sent(person):
    store = Store({"conn-1": _card()})
    with patch.object(L.httpx, "AsyncClient", store.client()), \
            patch.object(_egress, "post", side_effect=AssertionError("nothing is sent")):
        out = json.loads(await L.invoke_connection("conn-1", input="hi"))
    assert "cannot be used on your grant" in out["error"]


@pytest.mark.asyncio
async def test_an_unreachable_provider_is_an_error_not_a_reply(person):
    store = Store({"conn-1": _card(), "sec-1": {"id": "sec-1", "content": "sk-plain"}})

    def refused(*a, **kw):
        raise _egress.EgressError("request failed: TimeoutError")

    with patch.object(L.httpx, "AsyncClient", store.client()), patch.object(_egress, "post", refused):
        out = json.loads(await L.invoke_connection("conn-1", input="hi"))
    assert "could not be reached" in out["error"]


@pytest.mark.asyncio
async def test_a_persona_holding_no_key_of_its_own_is_released_nothing(person, monkeypatch):
    from prism.trust import service_identity
    monkeypatch.setattr(service_identity, "load_persona_identity", lambda name: None)
    store = Store({"conn-1": _card(), "sec-1": {"id": "sec-1", "content": "sk-plain"}})
    with patch.object(L.httpx, "AsyncClient", store.client()), \
            patch.object(_egress, "post", side_effect=AssertionError("nothing is sent")):
        out = json.loads(await L.invoke_connection("conn-1", input="hi"))
    assert "holds no key of its own" in out["error"]
    assert not [u for u, _ in store.calls if u.endswith("/use")], "no release is even asked for"
