"""A persona opens the copy of a credential Mantle hands it, sealed to its own key when the
credential was written and bound to the credential's id (`mantle.services.credential_sealing`).

The persona opened it under the context `"<secret>|<card>"`, which no copy was ever sealed under,
so every use failed. It opens it as it was sealed: under the credential's id.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agience_chorus import _secrets
from prism.trust import sealing


def _jwk(key, kid):
    n = key.public_key().public_numbers()
    b = lambda i: sealing._b64(i.to_bytes((i.bit_length() + 7) // 8, "big"))  # noqa: E731
    return {"kty": "RSA", "kid": kid, "n": b(n.n), "e": b(n.e)}


class _Resp:
    def __init__(self, body):
        self.status_code, self._body = 200, body

    def json(self):
        return self._body


class _Client:
    def __init__(self, body):
        self.body, self.sent = body, []

    async def post(self, url, headers=None, json=None, timeout=None):
        self.sent.append((url, json))
        return _Resp(self.body(json) if callable(self.body) else self.body)


def test_the_persona_opens_the_copy_sealed_to_it_for_the_credential(monkeypatch, origin_issuer):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = b'{"material": "sk-team-secret", "endpoints": ["https://api.example"]}'
    sealed = sealing.seal(payload, sealing.public_key_from_jwk(_jwk(key, "lumen-1")),
                          kid="lumen-1", context="cred-1")
    monkeypatch.setattr(_secrets.service_identity, "load_persona_identity",
                        lambda persona: SimpleNamespace(private_key=key, kid="lumen-1"))
    dlg = origin_issuer.delegation("lumen", "person-1")
    client = _Client(origin_issuer.answer("lumen", dlg, "cred-1", "card-1", sealed,
                                          ["https://api.example"]))
    got = asyncio.run(_secrets.use_secret(client, "http://mantle.test", "cred-1", "card-1",
                                          {"Authorization": f"Bearer {dlg}"}, "lumen",
                                          endpoint="https://api.example/v1"))
    assert got == "sk-team-secret"
    assert client.sent[0][1]["for"] == "card-1" and len(client.sent[0][1]["nonce"]) >= 16


def test_a_copy_sealed_for_another_credential_does_not_open(monkeypatch, origin_issuer):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sealed = sealing.seal(b"sk-other", sealing.public_key_from_jwk(_jwk(key, "lumen-1")),
                          kid="lumen-1", context="cred-2")
    monkeypatch.setattr(_secrets.service_identity, "load_persona_identity",
                        lambda persona: SimpleNamespace(private_key=key, kid="lumen-1"))
    with pytest.raises(_secrets.SecretUnavailable):
        dlg = origin_issuer.delegation("lumen", "person-1")
        asyncio.run(_secrets.use_secret(
            _Client(origin_issuer.answer("lumen", dlg, "cred-1", "card-1", sealed, [])),
            "http://mantle.test", "cred-1", "card-1", {"Authorization": f"Bearer {dlg}"},
            "lumen", endpoint="https://api.example"))
