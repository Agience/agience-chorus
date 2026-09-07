"""Tests the exchange agreement — value crosses between two Origins only through a signed agreement
(P7).

These cases construct the Origin artifacts they need as literal documents rather than importing
`origin/entity.py`: an Origin is a `vnd.agience.origin+json` on the wire, and a reader that can only be
tested by importing the writer's code is not exercising the artifact itself. Every document below is
the shape `origin/entity.py::origin_artifact` produces; if that shape changes, these cases must be
updated deliberately rather than following along silently.
"""
from __future__ import annotations

import pytest

try:                                              # works whether chorus/src or ophan/ is on the path
    from ophan import exchange as ex
except ImportError:
    import exchange as ex

ISSUER_CONTENT_TYPE = "application/vnd.agience.issuer+json"


# The in-memory store this suite runs against. Ember's `tests/_fakes.py` is not an importable surface
# for another repo's suite, so the two classes it needs are inlined here (they are 15 lines).
class _FakeArtifacts:
    def __init__(self):
        self.d = {}

    def put_artifact(self, doc):
        self.d[doc["id"]] = dict(doc)
        return doc

    def get_artifact(self, aid):
        a = self.d.get(aid)
        return dict(a) if a else None

    def list_artifacts(self, *, content_type=None, state=None, collection_id=None,
                       created_by=None, limit=None, skip=0):
        for a in self.d.values():
            if content_type and a.get("content_type") != content_type:
                continue
            if state and a.get("state") != state:
                continue
            yield dict(a)

    def put_many(self, docs, *, batch=500):
        n = 0
        for d in docs:
            self.put_artifact(d)
            n += 1
        return n


class _FakeStore:
    def __init__(self):
        self.artifacts = _FakeArtifacts()
        self.graph = None
        self.content = None
        self.keys_dir = None


def _put_origin(store, oid: str, *, issuer: str, economy: dict | None = None) -> str:
    """Write a `vnd.agience.origin+json` — the artifact, as it arrives over the wire."""
    store.artifacts.put_artifact({
        "id": oid,
        "content_type": ex.ORIGIN_CONTENT_TYPE,
        "state": "committed",
        "name": oid,
        "issuer": issuer,
        "policy": {},
        "economy": dict(economy or {}),
        "peers": [],
    })
    return oid


def _two_origins(s):
    out = []
    for oid, iss in (("urn:agience:origin:acme", "https://iss.acme/"),
                     ("urn:agience:origin:beta", "https://iss.beta/")):
        s.artifacts.put_artifact({"id": iss, "content_type": ISSUER_CONTENT_TYPE, "jwks": {}})
        out.append(_put_origin(s, oid, issuer=iss))
    return out[0], out[1]


# ── symmetric identity ────────────────────────────────────────────────────────────────────────────
def test_agreement_id_is_symmetric():
    assert ex.exchange_id("a", "b") == ex.exchange_id("b", "a")


def test_parties_stored_in_canonical_order():
    a = ex.exchange_artifact("zeta", "alpha")
    assert a["parties"] == sorted(a["parties"])                    # canonical, order-independent


def test_self_agreement_rejected():
    with pytest.raises(ValueError):
        ex.exchange_artifact("acme", "acme")                       # an origin does not peer with itself


def test_ophan_does_not_mint_origin_ids():
    """Ophan uses the origin ref exactly as given, never deriving its own slug from a bare name.
    Deriving one locally would be a second copy of the rule that decides what an Origin artifact is
    addressed by, free to drift from the rule `origin/entity.py` writes with. This asserts the party
    recorded is the string handed in, unchanged."""
    a = ex.exchange_artifact("urn:agience:origin:acme", "plain-name")
    assert set(a["parties"]) == {"urn:agience:origin:acme", "plain-name"}
    assert not any(p.startswith("urn:agience:origin:plain") for p in a["parties"])


# ── registration + resolution ─────────────────────────────────────────────────────────────────────
def test_register_and_resolve_between():
    s = _FakeStore()
    a, b = _two_origins(s)
    ex.register_exchange(s, a, b, allow={"content": True})
    got = ex.agreement_between(s, b, a)                            # resolvable from either side
    assert got is not None
    assert got["content_type"] == ex.EXCHANGE_CONTENT_TYPE


def test_no_agreement_returns_none_isolation_default():
    s = _FakeStore()
    a, b = _two_origins(s)
    assert ex.agreement_between(s, a, b) is None                   # unpeered ⇒ nothing crosses


# ── membrane: fail closed ─────────────────────────────────────────────────────────────────────────
def test_permits_denies_by_default():
    a = ex.exchange_artifact("acme", "beta")                       # no allow → nothing flows
    assert ex.permits(a, "content") is False


def test_permits_explicit_flow():
    a = ex.exchange_artifact("acme", "beta", allow={"content": True})
    assert ex.permits(a, "content") is True
    assert ex.permits(a, "operator") is False


def test_permits_wildcard_opens_membrane():
    a = ex.exchange_artifact("acme", "beta", allow={"*": True})
    assert ex.permits(a, "anything") is True


def test_permits_list_form():
    a = ex.exchange_artifact("acme", "beta", allow=["content", "operator"])
    assert ex.permits(a, "operator") is True
    assert ex.permits(a, "signal") is False


def test_permits_rejects_non_exchange_artifact():
    assert ex.permits({"content_type": "text/plain", "allow": {"*": True}}, "x") is False
    assert ex.permits(None, "x") is False


# ── the economy constants come off the artifact (D2) ──────────────────────────────────────────────
def test_governed_constant_reads_the_origin_artifact():
    """The positive control for the two refusal cases below: without it, a returned `None` would not
    be evidence the reader can read anything at all."""
    s = _FakeStore()
    _put_origin(s, "urn:agience:origin:acme", issuer="https://iss.acme/",
                economy={"facilitation_fee": 0.04})
    assert ex.governed_constant(s, "urn:agience:origin:acme", "facilitation_fee") == 0.04


def test_a_missing_origin_artifact_refuses_rather_than_defaulting():
    """A missing artifact is an honest refusal, never a silent default."""
    s = _FakeStore()                                               # nothing registered at all
    assert ex.governed_constant(s, "urn:agience:origin:ghost", "facilitation_fee") is None
    assert ex.governing_authority(s, "urn:agience:origin:ghost") is None


def test_a_wrong_content_type_is_not_an_origin():
    """A document at the right id with the wrong type must not be read as an Origin — otherwise any
    artifact could govern the economy by sitting on the right key."""
    s = _FakeStore()
    s.artifacts.put_artifact({"id": "urn:agience:origin:acme", "content_type": "text/plain",
                              "economy": {"facilitation_fee": 0.99}, "issuer": "https://evil/"})
    assert ex.governed_constant(s, "urn:agience:origin:acme", "facilitation_fee") is None
    assert ex.governing_authority(s, "urn:agience:origin:acme") is None


def test_an_ungoverned_constant_is_none_not_zero():
    s = _FakeStore()
    _put_origin(s, "urn:agience:origin:acme", issuer="https://iss.acme/")   # economy = {}
    got = ex.governed_constant(s, "urn:agience:origin:acme", "facilitation_fee")
    assert got is None and got != 0.0


def test_a_boolean_is_not_a_constant():
    """`isinstance(True, int)` is True in Python, so a `true` in the economy block would otherwise
    read as a governed 1.0."""
    s = _FakeStore()
    _put_origin(s, "urn:agience:origin:acme", issuer="https://iss.acme/",
                economy={"facilitation_fee": True})
    assert ex.governed_constant(s, "urn:agience:origin:acme", "facilitation_fee") is None


# ── fees: recorded, else Origin-governed ──────────────────────────────────────────────────────────
def test_fee_uses_recorded_value():
    s = _FakeStore()
    a, b = _two_origins(s)
    agr = ex.exchange_artifact(a, b, fee_a=0.03)
    assert ex.fee_for(s, agr, a) == 0.03


def test_an_ungoverned_fee_is_NONE_and_never_zero():
    """`facilitation_fee` is governable with no inherited value, so there is no default to fall back
    to: the honest answer when nobody has set a fee is `None`.

    The second assertion is the point: `None` must not become `0.0`. A governed fee of zero is a
    decision; an absent fee is nobody having decided, and those two must stay distinguishable."""
    s = _FakeStore()
    a, b = _two_origins(s)
    agr = ex.exchange_artifact(a, b)                               # no fee recorded, none governed
    fee = ex.fee_for(s, agr, a)
    assert fee is None, "an ungoverned fee answered %r — a default has been invented" % (fee,)
    assert fee != 0.0 and not isinstance(fee, float)


def test_fee_uses_origin_override():
    s = _FakeStore()
    iss = "https://iss.acme/"
    s.artifacts.put_artifact({"id": iss, "content_type": ISSUER_CONTENT_TYPE})
    a = _put_origin(s, "urn:agience:origin:acme", issuer=iss, economy={"facilitation_fee": 0.02})
    b = _put_origin(s, "urn:agience:origin:beta", issuer=iss)
    agr = ex.exchange_artifact(a, b)
    assert ex.fee_for(s, agr, a) == 0.02                          # reads the origin's governed constant


# ── cross-issuer trust ────────────────────────────────────────────────────────────────────────────
def test_trusts_issuer_prefers_agreement_pin():
    s = _FakeStore()
    a, b = _two_origins(s)
    agr = ex.exchange_artifact(a, b, issuers={a: "https://pinned.acme/"})
    assert ex.trusts_issuer(s, agr, a) == "https://pinned.acme/"


def test_trusts_issuer_falls_back_to_origin_authority():
    s = _FakeStore()
    a, b = _two_origins(s)
    agr = ex.exchange_artifact(a, b)                               # no pin
    assert ex.trusts_issuer(s, agr, a) == "https://iss.acme/"     # off the Origin artifact


def test_trusts_issuer_none_when_unknown():
    s = _FakeStore()
    agr = ex.exchange_artifact("ghosta", "ghostb")                # origins never registered
    assert ex.trusts_issuer(s, agr, "ghosta") is None            # never guesses an authority


# ── validity: fail closed ─────────────────────────────────────────────────────────────────────────
def test_valid_agreement():
    s = _FakeStore()
    a, b = _two_origins(s)
    agr = ex.exchange_artifact(a, b)
    assert ex.valid(s, agr) is True


def test_invalid_when_a_party_has_no_authority():
    s = _FakeStore()
    a, _ = _two_origins(s)
    agr = ex.exchange_artifact(a, "urn:agience:origin:ghost")     # ghost has no issuer
    assert ex.valid(s, agr) is False


def test_valid_rejects_non_exchange():
    s = _FakeStore()
    assert ex.valid(s, {"content_type": "text/plain", "parties": ["a", "b"]}) is False
