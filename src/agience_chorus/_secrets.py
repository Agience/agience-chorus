"""A persona's use of a secret: released by Mantle for one card, sealed to this persona's own key,
opened here at the point of use.

A key and an authorizer's secret are one thing, a credential artifact. Whoever holds `invoke` on it
may have it used for them; nobody but the persona that serves the card it is used for ever holds it
in clear, and only for the call. Mantle releases it (`POST /artifacts/{id}/use`) only to a persona
that proved who it is (a delegation the persona obtained signing with its own enrolled key), when
the caller holds Invoke on it and the persona's own principal holds Read on it. The copy was sealed
to the persona's key when the credential was written, bound to the credential's id
(`prism.trust.sealing`); the persona opens it here with its own key. That the card names this
credential is the persona's own reading of the card.

Mantle's yes is not enough (review 21, F1): a Mantle that is taken over would hand the copy over
for a grant key it presented itself, or for a system delegation addressed to the persona. So the
persona acts only on a delegation Origin issued to it, proven by its own key (`act.iss`), and opens
the copy only when Mantle's answer carries Origin's signed verdict for this persona, the
delegation's subject and `jti`, this credential and this card (`prism.trust.use_verdict`), for
the sealed copy and endpoint list the credential's writer recorded at Origin, and for the fresh
nonce the persona sent for this one use (review 22): a copy Mantle sealed itself, or a verdict
Mantle asked for on its own, opens nothing. A grant
key uses no secret, and Mantle is not even asked.

Where the secret may go is the credential's own (review 10, R1): it names the endpoints it may be
sent to (`allowed_endpoints`), fixed by whoever wrote it, who holds Admin on it by creation. That
list is sealed to the persona with the secret, so neither Mantle nor a caller can alter it, and
`/use` returns the same list beside the sealed copy. Invoke lets a caller have the credential used
for them; it never lets them choose where it goes. A copy that names no endpoint is sent nowhere.
"""
from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlsplit

from prism.trust import sealing, service_identity, use_verdict


class SecretUnavailable(PermissionError):
    """The secret cannot be used for this call. The message is safe to return; it carries no secret."""


#: How many rounds of percent-decoding an endpoint path may take to settle.
_DECODE_ROUNDS = 8


def _origin_and_path(url: str):
    """`((scheme, host, port), path)` as a sender reaches it, or None for an endpoint a sender could
    read another way (review 11): surrounding whitespace, control characters or a backslash
    anywhere, a user part (`user@host`), a host that is not plain ASCII, or a path that does not
    normalise. The path is percent-decoded and its `.` and `..` segments resolved."""
    import posixpath
    from urllib.parse import unquote

    raw = str(url or "")
    if (raw != raw.strip() or "\\" in raw
            or any(ord(c) < 0x21 or ord(c) == 0x7F for c in raw)):
        return None
    p = urlsplit(raw)
    if "@" in (p.netloc or "") or p.username is not None or p.password is not None:
        return None
    host = p.hostname or ""
    if not host or not host.isascii():
        return None
    scheme = (p.scheme or "").lower()
    try:
        port = p.port or {"https": 443, "http": 80}.get(scheme)
    except ValueError:
        return None
    # Decoded until stable (review 12): a path decoded once can still carry an encoded `..`
    # (`%252e%252e`) that a server decoding again reads as a parent segment. One that has not
    # settled within a few rounds is refused.
    path = p.path or "/"
    for _ in range(_DECODE_ROUNDS):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    else:
        return None
    if "\\" in path or any(ord(c) < 0x20 for c in path):
        return None
    norm = posixpath.normpath(path) if path not in ("", "/") else "/"
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    if path.endswith("/") and norm != "/":
        norm += "/"
    return (scheme, host.lower(), port), norm


def endpoint_allowed(endpoint: str, allowed: List[str]) -> bool:
    """Is `endpoint` one the credential names: the same scheme, host and port, and a normalised
    path at or under the named one, on a path boundary."""
    got = _origin_and_path(endpoint)
    if got is None:
        return False
    origin, path = got
    if origin[0] not in ("https", "http") or not origin[1]:
        return False
    for entry in allowed or ():
        named = _origin_and_path(entry)
        if named is None or named[0] != origin:
            continue
        base = named[1].rstrip("/")
        if not base or path == base or path.startswith(base + "/"):
            return True
    return False


async def use_secret(client: Any, mantle_uri: str, secret_id: str, card_id: str, headers: dict,
                     persona: str, *, endpoint: Optional[str]) -> str:
    """The secret `secret_id`, released for `card_id`, opened with `persona`'s own key, for
    `endpoint` only: refused unless the credential itself names that endpoint."""
    from mantle.clients.artifact_helpers import artifact_url

    own = service_identity.load_persona_identity(persona)
    if own is None or own.private_key is None:
        raise SecretUnavailable(f"{persona} holds no key of its own, so no secret can be sealed to it")
    raw = str((headers or {}).get("Authorization") or "")
    bearer = raw[7:].strip() if raw[:7].lower() == "bearer " else ""
    try:
        delegation = use_verdict.persona_delegation(bearer, persona)
    except use_verdict.VerdictRefused as exc:
        raise SecretUnavailable(str(exc)) from None
    import secrets as _secrets_mod
    nonce = _secrets_mod.token_hex(16)        # this one use's, signed into Origin's verdict
    resp = await client.post(artifact_url(mantle_uri, secret_id, "use"), headers=headers,
                             json={"for": card_id, "nonce": nonce}, timeout=15)
    if resp.status_code != 200:
        raise SecretUnavailable(
            f"the secret cannot be used on your grant ({resp.status_code}): it needs your Invoke "
            f"on the card and its secret, and {persona}'s own Read on the secret")
    answer = resp.json() or {}
    try:
        use_verdict.verify(answer.get("verdict") or "", persona=persona, delegation=delegation,
                           credential_id=str(secret_id), card_id=str(card_id),
                           sealed=answer.get("sealed") or {},
                           endpoints=list(answer.get("endpoints") or []), nonce=nonce)
    except use_verdict.VerdictRefused as exc:
        raise SecretUnavailable(str(exc)) from None
    try:
        plain = sealing.open_sealed(answer.get("sealed") or {}, own.private_key,
                                    kid=own.kid, context=str(secret_id))
    except sealing.SealError as exc:
        raise SecretUnavailable(str(exc)) from None
    value = plain.decode("utf-8")
    material, endpoints = value.strip(), None
    if value.lstrip().startswith("{"):
        import json
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            material = str(parsed.get("material") or parsed.get("value") or "").strip()
            endpoints = parsed.get("endpoints")
    # The credential's own content may wrap the value (`{"value": ...}`), as written.
    if material.lstrip().startswith("{"):
        import json
        try:
            inner = json.loads(material)
        except ValueError:
            inner = None
        if isinstance(inner, dict):
            material = str(inner.get("material") or inner.get("value") or "").strip()
    if not isinstance(endpoints, list) or not endpoints:
        raise SecretUnavailable(
            f"credential {secret_id} names no endpoint it may be sent to, so it is sent nowhere; "
            "its Admin writes it again with `allowed_endpoints`")
    bound = answer.get("endpoints")
    if sorted(map(str, bound or [])) != sorted(map(str, endpoints)):
        raise SecretUnavailable(f"the endpoints Mantle returned for credential {secret_id} "
                                "differ from the ones sealed with it; nothing is sent")
    if not endpoint or not endpoint_allowed(endpoint, [str(e) for e in endpoints]):
        raise SecretUnavailable(f"credential {secret_id} does not name {endpoint or 'this endpoint'}"
                                " as one it may be sent to")
    return material
