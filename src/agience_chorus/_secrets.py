"""A persona's use of a secret: released by Mantle for one card, sealed to this persona's own key,
opened here at the point of use.

A key and an authorizer's secret are one thing, a credential artifact. Whoever holds `invoke` on it
may have it used for them; nobody but the persona that serves the card it is used for ever holds it
in clear, and only for the call. Mantle releases it (`POST /artifacts/{id}/use`) only to a persona
that proved who it is — a delegation the persona obtained signing with its own enrolled key — and
only sealed to that key (`prism.trust.sealing`), bound to the secret and the card.
"""
from __future__ import annotations

from typing import Any

from prism.trust import sealing, service_identity


class SecretUnavailable(PermissionError):
    """The secret cannot be used for this call. The message is safe to return; it carries no secret."""


async def use_secret(client: Any, mantle_uri: str, secret_id: str, card_id: str, headers: dict,
                     persona: str) -> str:
    """The secret `secret_id`, released for `card_id` and opened with `persona`'s own key."""
    from mantle.clients.artifact_helpers import artifact_url

    own = service_identity.load_persona_identity(persona)
    if own is None or own.private_key is None:
        raise SecretUnavailable(f"{persona} holds no key of its own, so no secret can be sealed to it")
    resp = await client.post(artifact_url(mantle_uri, secret_id, "use"), headers=headers,
                             json={"for": card_id}, timeout=15)
    if resp.status_code != 200:
        raise SecretUnavailable(
            f"the secret cannot be used on your grant ({resp.status_code}): it needs invoke on the "
            f"card and its secret, through a person's own sign-in")
    try:
        plain = sealing.open_sealed((resp.json() or {}).get("sealed") or {}, own.private_key,
                                    kid=own.kid, context=f"{secret_id}|{card_id}")
    except sealing.SealError as exc:
        raise SecretUnavailable(str(exc)) from None
    value = plain.decode("utf-8")
    # The credential type carries the value directly; older credentials wrap it.
    if value.lstrip().startswith("{"):
        import json
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return str(parsed.get("material") or parsed.get("value") or "").strip()
        except ValueError:
            pass
    return value.strip()
