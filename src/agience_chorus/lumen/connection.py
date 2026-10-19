"""An LLM connection card, invoked: one call to the model its owner connected.

The card (`vnd.agience.llm-connection+json`) names a provider, a model, and where its key is kept
(`credentials_ref.secret_id`, a credential artifact). Invoking it is a deliberate act on that card,
so the call, the model and who made it are on record; nothing in Lumen's answer path calls a model
on its own.

The key is a credential artifact. It is released for this one call through Mantle's `use` route,
which answers a platform persona acting for someone who holds `invoke` on the key: a connection
shared with a team, or the platform's own granted to everyone, is usable by them without its key
being readable by them, and never returns to the caller. The request goes out through the
shared egress guard, to the provider's own address only. A card's `endpoint` is editable by anyone
who can edit the card, and the request carries the key, so an endpoint that is not the provider's
is refused rather than followed.

This module builds the request and reads the answer; it does no I/O.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

CONNECTION_TYPE = "application/vnd.agience.llm-connection+json"
#: The most a reply may run to unless the caller asks for less. The egress guard bounds the wait at
#: 30 seconds, so the default reply is kept to what a model writes well inside it.
DEFAULT_MAX_TOKENS = 1024
MAX_TOKENS_CAP = 4096

#: Each provider this node can call, at its own address. Azure, Google and local models are not
#: here: each needs a request shape or an address (a private network, for local) this node does not
#: reach yet, and a card naming one is told so.
PROVIDERS: Dict[str, str] = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
}


class ConnectionError_(ValueError):
    """The card, or what it was asked, cannot be called. The message is safe to return."""


@dataclass(frozen=True)
class Request:
    url: str
    headers: Dict[str, str]
    body: bytes


def _context(doc: dict) -> dict:
    ctx = doc.get("context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except ValueError:
            ctx = {}
    return ctx if isinstance(ctx, dict) else {}


def read_card(doc: dict) -> Dict[str, Any]:
    """What the card says: provider, model, secret id, system prompt, endpoint. Refuses a card that
    cannot be called."""
    if doc.get("content_type") != CONNECTION_TYPE:
        raise ConnectionError_("this card is not an LLM connection")
    ctx = _context(doc)
    provider = str(ctx.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise ConnectionError_(
            f"provider {provider or '(none)'!r} cannot be called from this node; "
            f"one of {', '.join(sorted(PROVIDERS))}")
    model = str(ctx.get("model") or "").strip()
    if not model:
        raise ConnectionError_("the card names no model")
    # A platform connection is not a special case: it is a card and a key the platform granted.
    ref = ctx.get("credentials_ref") or {}
    secret_id = str(ref.get("secret_id") or "").strip()
    if not secret_id:
        raise ConnectionError_("the card points at no key (credentials_ref.secret_id)")
    endpoint = str(ctx.get("endpoint") or "").strip()
    if endpoint and urlparse(endpoint).netloc.lower() != urlparse(PROVIDERS[provider]).netloc:
        raise ConnectionError_(
            f"the card's endpoint is not {provider}'s own address; the request carries the key, so it "
            "goes to the provider only")
    return {"provider": provider, "model": model, "secret_id": secret_id,
            "system_prompt": str(ctx.get("system_prompt") or "").strip()}


def messages_of(messages: Any = None, input: Optional[str] = None) -> tuple[str, List[Dict[str, str]]]:
    """(system text, the conversation) from `messages` ([{role, content}] or a JSON string of it)
    or a single `input`. System turns are lifted out; the rest must alternate as the caller sent."""
    if isinstance(messages, str) and messages.strip():
        try:
            messages = json.loads(messages)
        except ValueError:
            raise ConnectionError_("messages is not JSON") from None
    turns: List[Dict[str, str]] = []
    system: List[str] = []
    for m in messages or []:
        if not isinstance(m, dict):
            raise ConnectionError_("each message is {role, content}")
        role, content = str(m.get("role") or ""), m.get("content")
        if not isinstance(content, str):
            raise ConnectionError_("a message's content is text")
        if role == "system":
            system.append(content)
        elif role in ("user", "assistant"):
            turns.append({"role": role, "content": content})
        else:
            raise ConnectionError_(f"no role {role!r}; user, assistant or system")
    if input:
        turns.append({"role": "user", "content": str(input)})
    if not turns or turns[-1]["role"] != "user":
        raise ConnectionError_("nothing to answer: the conversation ends without a user turn")
    return "\n\n".join(system), turns


def build(card: Dict[str, Any], key: str, system: str, turns: List[Dict[str, str]],
          max_tokens: Optional[int] = None) -> Request:
    """The provider's request for this conversation."""
    if not key:
        raise ConnectionError_("the card's key is empty")
    limit = max(1, min(int(max_tokens or DEFAULT_MAX_TOKENS), MAX_TOKENS_CAP))
    system = "\n\n".join(s for s in (card.get("system_prompt"), system) if s)
    provider, url = card["provider"], PROVIDERS[card["provider"]]
    if provider == "anthropic":
        body: Dict[str, Any] = {"model": card["model"], "max_tokens": limit, "messages": turns}
        if system:
            body["system"] = system
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        msgs = ([{"role": "system", "content": system}] if system else []) + turns
        body = {"model": card["model"], "messages": msgs,
                ("max_completion_tokens" if provider == "openai" else "max_tokens"): limit}
        headers = {"Authorization": f"Bearer {key}"}
    headers["Content-Type"] = "application/json"
    return Request(url, headers, json.dumps(body).encode())


def read_answer(provider: str, status: int, text: str) -> Dict[str, Any]:
    """The reply, or `{"error": ...}` naming what the provider said. Never echoes a header."""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {}
    if status >= 400 or not isinstance(data, dict):
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else (err if isinstance(err, str) else "")
        return {"error": f"{provider} answered {status}" + (f": {str(msg)[:300]}" if msg else "")}
    if provider == "anthropic":
        reply = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        stop = data.get("stop_reason")
    else:
        choice = (data.get("choices") or [{}])[0]
        reply = ((choice.get("message") or {}).get("content")) or ""
        stop = choice.get("finish_reason")
    return {"text": reply, "model": data.get("model"), "stop_reason": stop, "usage": data.get("usage") or {}}
