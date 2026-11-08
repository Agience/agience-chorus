"""Review 22, F2 and F3 at the persona: the verdict binds the sealed copy, the endpoint list and
this one use.

Mantle seals every credential, with the persona's public key from the manifest, so a Mantle taken
over could answer `/use` with a genuine verdict beside a copy it sealed itself (its own material,
its own endpoint list), and the persona would send the person's request on Mantle's credential.
The verdict now names the SHA-256 of the copy and of the list the credential's writer recorded at
Origin, and the persona's fresh nonce for the use; the persona refuses any mismatch.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agience_chorus import _secrets
from agience_chorus.tests.test_review21_a_persona_opens_a_secret_only_on_origin_s_verdict import (
    API, PERSON, _Mantle, _jwk, _sealed, lumen_key)  # noqa: F401
from prism.trust import sealing


def _use(body, dlg):
    return asyncio.run(_secrets.use_secret(
        _Mantle(body), "http://mantle.test", "cred-1", "card-1",
        {"Authorization": f"Bearer {dlg}"}, "lumen", endpoint=API + "/v1"))


def test_a_copy_mantle_sealed_itself_opens_nothing_on_a_genuine_verdict(lumen_key, origin_issuer):  # noqa: F811 (the shared key fixture)
    dlg = origin_issuer.delegation("lumen", PERSON)
    forged = sealing.seal(json.dumps({"material": "mantle-own-key", "endpoints": [API]}).encode(),
                          sealing.public_key_from_jwk(_jwk(lumen_key, "lumen-1")),
                          kid="lumen-1", context="cred-1")
    body = origin_issuer.answer("lumen", dlg, "cred-1", "card-1", _sealed(lumen_key), [API],
                                served=forged)
    with pytest.raises(_secrets.SecretUnavailable, match="sealed copy"):
        _use(body, dlg)


def test_an_endpoint_list_mantle_altered_opens_nothing(lumen_key, origin_issuer):  # noqa: F811 (the shared key fixture)
    dlg = origin_issuer.delegation("lumen", PERSON)
    writer = origin_issuer.answer("lumen", dlg, "cred-1", "card-1", _sealed(lumen_key), [API])
    with pytest.raises(_secrets.SecretUnavailable):
        _use(lambda req: {**writer(req), "endpoints": [API, "https://mantle.example"]}, dlg)


def test_a_verdict_for_another_nonce_opens_nothing(lumen_key, origin_issuer):  # noqa: F811 (the shared key fixture)
    """Review 22, F3: a verdict Mantle asked for on its own names a nonce the persona never sent."""
    dlg = origin_issuer.delegation("lumen", PERSON)
    copy = _sealed(lumen_key)
    body = {"sealed": copy, "endpoints": [API],
            "verdict": origin_issuer.verdict("lumen", dlg, "cred-1", "card-1", sealed=copy,
                                             endpoints=[API], nonce="m" * 32)}
    with pytest.raises(_secrets.SecretUnavailable, match="another use"):
        _use(body, dlg)


def test_the_writer_s_copy_opens(lumen_key, origin_issuer):  # noqa: F811 (the shared key fixture)
    dlg = origin_issuer.delegation("lumen", PERSON)
    assert _use(origin_issuer.answer("lumen", dlg, "cred-1", "card-1", _sealed(lumen_key),
                                     [API]), dlg) == "sk-person-secret"
