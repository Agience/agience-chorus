"""A persona opens a sealed secret only on Origin's verdict, matched to its own delegation
(review 21, F1).

Mantle hands over the sealed copy, and a Mantle that is taken over would hand it over for anyone:
for a grant key it presented itself, or for a system delegation addressed to the persona. So the
persona acts only on a delegation Origin issued to it, proven by its own key, and opens the copy
only when Mantle's answer carries Origin's verdict for this persona, this subject, this delegation,
this credential and this card.

Tokens come from Origin's own issuers (`origin_issuer`); the sealed copy from prism's `sealing`.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agience_chorus import _secrets
from prism.trust import sealing

API = "https://api.example"
PERSON = "person-1"


def _jwk(key, kid):
    n = key.public_key().public_numbers()

    def b(i):
        return sealing._b64(i.to_bytes((i.bit_length() + 7) // 8, "big"))

    return {"kty": "RSA", "kid": kid, "n": b(n.n), "e": b(n.e)}


class _Resp:
    def __init__(self, body):
        self.status_code, self._body = 200, body

    def json(self):
        return self._body


class _Mantle:
    """A Mantle that answers every use with the sealed copy, whatever it was shown."""

    def __init__(self, body):
        self.body, self.sent = body, []

    async def post(self, url, headers=None, json=None, timeout=None):
        self.sent.append((url, headers, json))
        return _Resp(self.body(json) if callable(self.body) else self.body)


@pytest.fixture
def lumen_key(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(_secrets.service_identity, "load_persona_identity",
                        lambda persona: SimpleNamespace(private_key=key, kid="lumen-1"))
    return key


def _sealed(key):
    raw = json.dumps({"material": "sk-person-secret", "endpoints": [API]}).encode()
    return sealing.seal(raw, sealing.public_key_from_jwk(_jwk(key, "lumen-1")), kid="lumen-1",
                        context="cred-1")


def _use(body, bearer):
    return asyncio.run(_secrets.use_secret(
        _Mantle(body), "http://mantle.test", "cred-1", "card-1",
        {"Authorization": f"Bearer {bearer}"}, "lumen", endpoint=API + "/v1"))


def test_the_secret_opens_on_origin_s_verdict_for_this_delegation(lumen_key, origin_issuer):
    dlg = origin_issuer.delegation("lumen", PERSON)
    body = origin_issuer.answer("lumen", dlg, "cred-1", "card-1", _sealed(lumen_key), [API])
    assert _use(body, dlg) == "sk-person-secret"


def test_no_verdict_nothing_opens(lumen_key, origin_issuer):
    dlg = origin_issuer.delegation("lumen", PERSON)
    with pytest.raises(_secrets.SecretUnavailable):
        _use({"sealed": _sealed(lumen_key), "endpoints": [API]}, dlg)


@pytest.mark.parametrize("over", [
    {"credential_id": "cred-2"}, {"card_id": "card-2"}, {"subject": "someone-else"},
    {"delegation_jti": "another-jti"}, {"persona": "iris"},
])
def test_a_verdict_for_another_use_opens_nothing(lumen_key, origin_issuer, over):
    dlg = origin_issuer.delegation("lumen", PERSON)
    body = origin_issuer.answer("lumen", dlg, "cred-1", "card-1", _sealed(lumen_key), [API],
                                **over)
    with pytest.raises(_secrets.SecretUnavailable):
        _use(body, dlg)


def test_a_grant_key_opens_nothing_and_mantle_is_not_asked(lumen_key, origin_issuer):
    mantle = _Mantle({"sealed": _sealed(lumen_key), "endpoints": [API]})
    with pytest.raises(_secrets.SecretUnavailable):
        asyncio.run(_secrets.use_secret(mantle, "http://mantle.test", "cred-1", "card-1",
                                        {"Authorization": "Bearer agk_whatever"}, "lumen",
                                        endpoint=API))
    assert mantle.sent == []


def test_a_delegation_another_signer_asked_for_opens_nothing(lumen_key, origin_issuer):
    """The shared `chorus` identity's exchange, or another persona's, proves nothing about which
    persona acts; neither uses a secret."""
    for signer in ("chorus", "iris"):
        dlg = origin_issuer.delegation("lumen", PERSON, signer=signer)
        body = origin_issuer.answer("lumen", dlg, "cred-1", "card-1", _sealed(lumen_key), [API])
        with pytest.raises(_secrets.SecretUnavailable):
            _use(body, dlg)
