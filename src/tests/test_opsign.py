"""Operator signing and admission — verify what you reached, then decide whether to run it.

Moved here from `agience-ember/tests/test_opsign.py`: these exercise operators through ember's
runner and need a sha-verified operator payload present. The payloads are chorus's,
built from chorus source; ember is the engine that runs them, so the test belongs
beside the operators. Tests in that file needing no payload stayed in ember.
"""
from __future__ import annotations
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from prism.trust import opsign
from ember import genesis as g
from _fakes import _FakeStore
@pytest.fixture()
def keys(tmp_path):
    priv, pub = opsign.authority_key(tmp_path, create=True)
    return priv, pub
def _op(**over):
    d = {"id": "op.t.x", "kind": "composition", "spec": {"steps": [{"op": "op.a"}]},
         "requires": ["compute.basic"], "effects": {"writes": False}}
    d.update(over)
    return d


def test_define_operator_signs_when_a_keys_dir_exists(tmp_path):
    s = _FakeStore()
    s.keys_dir = tmp_path
    g.bootstrap(s)
    r = g.invoke(s, "op.operator.define", {"id": "op.t.signed", "kind": "composition",
                                           "spec": {"steps": [{"op": "op.consistency"}]}})["result"]
    # Signing is what this invariant is about, so signing is what is asserted. No `spec_hash` is
    # stamped: `crystal/evolution.py` and `opsign.sign_operator` both leave it off, because a
    # second, weaker content address (digesting only kind+spec) beside an Ed25519 signature that
    # covers a superset would need migrating whenever its canonicalizer changed.
    #
    # `define_operator` reaches `evolution` through `ember.runtime.runner` — the bundle — rather
    # than through `crystal` directly, so an assertion on a stamped field here measures whatever
    # bundle happens to be shipped rather than the source it names.
    assert r["signed"] is True
    doc = s.artifacts.get_artifact("op.t.signed")
    assert opsign.verify_operator(doc)[0] is True


def test_an_unsignable_publish_reports_it_rather_than_pretending(tmp_path):
    """With no keys dir there is no key to sign with, so the result says `signed: False` and carries
    a note. An unsigned publish that said nothing would look identical to a signed one at every
    later step."""
    s = _FakeStore()                                   # no keys_dir
    g.bootstrap(s)
    r = g.invoke(s, "op.operator.define", {"id": "op.t.unsigned", "kind": "composition",
                                           "spec": {"steps": [{"op": "op.consistency"}]}})["result"]
    assert r["signed"] is False
    assert r["signature_note"]
    assert opsign.verify_operator(s.artifacts.get_artifact("op.t.unsigned"))[0] is False


def test_redefining_resigns_and_the_old_signature_does_not_carry(tmp_path):
    s = _FakeStore()
    s.keys_dir = tmp_path
    g.bootstrap(s)
    g.invoke(s, "op.operator.define", {"id": "op.t.v", "kind": "composition",
                                       "spec": {"steps": [{"op": "op.consistency"}]}})
    first = dict(s.artifacts.get_artifact("op.t.v"))
    g.invoke(s, "op.operator.define", {"id": "op.t.v", "kind": "composition",
                                       "spec": {"steps": [{"op": "op.health"}]}})
    second = s.artifacts.get_artifact("op.t.v")
    assert second["signature"] != first["signature"], "the spec changed but the signature did not"
    # The content address is computed rather than stored: `evolution.spec_hash()` answers the
    # behaviour question on demand. The signature above already covers {id, kind, spec, requires,
    # effects}, a superset of what a stored digest would hold, so this is the narrower of the two
    # checks and is here because it names the address directly.
    from crystal.evolution import spec_hash
    assert spec_hash(second) != spec_hash(first), "the spec changed but the computed address did not"
    assert opsign.verify_operator(second)[0] is True
