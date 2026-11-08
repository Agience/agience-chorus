"""Origin's own issuers, under a throwaway key, for the tests of a persona's use of a secret.

A persona opens a sealed secret only on Origin's signed verdict, matched to the Origin delegation
it acts on (`prism.trust.use_verdict`, review 21). The tests need both tokens as Origin issues
them, so this fixture loads a throwaway key into the signing floor Origin itself signs with
(`prism.trust.key_manager`), anchors it as `origin` in the test authority manifest, and mints
through Origin's own functions: `issue_delegation_token` for a persona's server delegation,
`issue_system_delegation_token` for a platform purpose's, and `issue_use_verdict` for a verdict. Nothing is restored by hand: every change is a monkeypatch.
"""
from __future__ import annotations

import secrets
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture
def origin_issuer(monkeypatch):
    from prism.trust import authority_trust, key_manager

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(key_manager, "_private_key_pem", private)
    monkeypatch.setattr(key_manager, "_public_key_pem", public)
    monkeypatch.setattr(key_manager, "_key_id", "origin-test-1")

    manifest = authority_trust.get_authority_manifest()
    anchors = {**manifest.trust_anchors,
               "origin": {"jwks": {"keys": [key_manager.get_jwk_public()]}}}
    monkeypatch.setattr(authority_trust, "_manifest", authority_trust.AuthorityManifest(
        issuer=manifest.issuer, artifact_id=manifest.artifact_id, trust_anchors=anchors,
        bootstrap_token_hash=manifest.bootstrap_token_hash, raw=manifest.raw))

    from origin import config as origin_config
    from origin.services import auth_service

    monkeypatch.setattr(origin_config, "AUTHORITY_ISSUER", manifest.issuer)

    def delegation(persona: str, sub: str, *, signer: str = "") -> str:
        return auth_service.issue_delegation_token(
            f"agience-server-{persona}", sub, 300, signer=signer or persona,
            jti=secrets.token_hex(16))

    def system(persona: str, scope: str, sub: str, *, audience: str = "mantle") -> str:
        return auth_service.issue_system_delegation_token(
            sub, actor=f"agience-server-{persona}", signer=persona, scope=scope,
            audience=audience, jti=secrets.token_hex(16))

    def verdict(for_persona: str, dlg: str, credential: str, card: str, /, *, sealed=None,
                endpoints=None, nonce="", **over) -> str:
        """Origin's verdict for this use, naming the digests of the writer's `sealed` copy and
        `endpoints` list and the persona's `nonce` (review 22)."""
        from jose import jwt as jose_jwt

        from prism.trust import use_verdict
        claims = jose_jwt.get_unverified_claims(dlg)
        kw = dict(persona=for_persona, subject=claims["sub"], delegation_jti=claims["jti"],
                  credential_id=credential, card_id=card,
                  grants={"invoke_card": "g-1", "invoke_credential": "g-1", "read": "g-2"},
                  sealed_sha256=use_verdict.sealed_digest(sealed or {}),
                  endpoints_sha256=use_verdict.endpoints_digest(endpoints or []), nonce=nonce)
        kw.update(over)
        return auth_service.issue_use_verdict(**kw)

    def answer(for_persona: str, dlg: str, credential: str, card: str, sealed: dict,
               endpoints: list, /, *, served=None, **over):
        """Mantle's answer to `/use`, as a function of the request it answers: the `served` copy
        (the writer's `sealed` unless given) and Origin's verdict for the writer's copy and the
        request's nonce."""
        def body(request: dict) -> dict:
            return {"sealed": served if served is not None else sealed, "endpoints": endpoints,
                    "verdict": verdict(for_persona, dlg, credential, card, sealed=sealed,
                                       endpoints=endpoints, nonce=(request or {}).get("nonce"),
                                       **over)}
        return body

    return SimpleNamespace(delegation=delegation, system=system, verdict=verdict, answer=answer)
