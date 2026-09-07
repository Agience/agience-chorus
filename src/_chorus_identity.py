"""The chorus-wide test service identity — one home, registered by more than one conftest.

Persona tools sign outbound JWTs via `prism.trust.service_identity.sign_service_jwt`, which
raises if no identity is loaded. In production the chorus host lifespan calls
`init_service_identity("chorus")`; tests do not run the lifespan, so this materialises a
throwaway keypair and a minimal authority manifest, and restores `KEYS_DIR` afterwards.
"""
from __future__ import annotations

import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk




@pytest.fixture(scope="session", autouse=True)
def _chorus_test_identity(tmp_path_factory):
    keys_dir = tmp_path_factory.mktemp("chorus_keys")

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (keys_dir / "chorus.private.pem").write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    public_jwk = jwk.construct(public_pem, "RS256").to_dict()
    public_jwk["kid"] = "chorus-1"
    public_jwk["use"] = "sig"
    public_jwk["alg"] = "RS256"

    # Match the platform default issuer so any cross-suite test that compares
    # `manifest.issuer` against the platform's issuer keeps working. `prism.config` is the
    # canonical reader for `ORIGIN_URI` (falling back to the same localhost:8080 default), so
    # the fixture reads the environment through the SDK every service already stands on, and a
    # chorus test run does not need the identity service importable to make a keypair.
    from prism import config as _prism_config

    _issuer = os.getenv("AUTHORITY_ISSUER") or _prism_config.origin_uri()

    manifest = {
        "artifact_id": "00000000-0000-0000-0000-000000000001",
        "content_type": "application/vnd.agience.authority+json",
        "schema_version": 1,
        "issuer": _issuer,
        "trust_anchors": {
            "chorus": {"uri": "http://chorus.test", "jwks": {"keys": [public_jwk]}},
        },
    }
    (keys_dir / "authority.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    prior_keys_dir = os.environ.get("KEYS_DIR")
    os.environ["KEYS_DIR"] = str(keys_dir)

    from prism.trust import authority_trust as _at, service_identity as _si

    _si.reset_service_identity_for_tests()
    _at.reset_authority_manifest_for_tests()
    _si.init_service_identity("chorus")
    _at.load_authority_manifest()

    try:
        yield keys_dir
    finally:
        # Restore the environment and reset the singletons so later test files start clean.
        if prior_keys_dir is None:
            os.environ.pop("KEYS_DIR", None)
        else:
            os.environ["KEYS_DIR"] = prior_keys_dir
        _si.reset_service_identity_for_tests()
        _at.reset_authority_manifest_for_tests()



# Each persona imports its own organons locally; no persona declares organons. There is
# nothing to wire at test time — test setup matches deployment.
