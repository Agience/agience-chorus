"""`crystal.market` — the declaration, and the boundaries it is only worth having if it holds.

A crystal is data, so most of what could go wrong is a claim that is merely untrue rather than a
crash: a facet that gates on a type, a capability the persona should not hold, a tekton count that
hides where the waveform becomes an artifact. Each test below states the property it pins.

This filename must stay unique across chorus: pytest substitutes duplicate basenames silently.
"""
import pytest

from crystal.crystal_model import crystal_sha, validate
from agience_chorus.ophan import crystal_market as cm


def test_the_declaration_validates():
    """A crystal that fails its own contract must not be importable at all. The module asserts this
    at import; this pins it independently so a removed assert is visible."""
    assert validate(cm.MARKET) == []


def test_it_declares_no_network_capability():
    """This crystal must never acquire a network capability. It is about market data, which makes
    "give it its own fetcher" a persistent temptation, but that would put a second world-touching
    path inside the arithmetic persona, bypassing the single place SSRF and GET-locking are enforced
    (`astra/fetch.py`). Ingestion belongs to astra; bars reach here through the store."""
    required = {r for o in cm.MARKET["organons"] for r in o.get("requires", [])}
    assert not any(r.startswith("net.") for r in required), (
        "crystal.market acquired a network capability — ingestion belongs to astra")
    assert required == {"store.read", "compute.local"}


def test_it_never_declares_a_store_write():
    """This crystal reads and condenses; astra's ingest owns every write. A `store.write` here would
    make two personas able to author market artifacts, and provenance would stop being a single path."""
    required = {r for o in cm.MARKET["organons"] for r in o.get("requires", [])}
    assert "store.write" not in required


def test_exactly_one_tekton_because_there_is_one_type_crossing():
    """The tekton count is a claim, not a convenience. Framing (`co_register`) is alignment — it
    changes no type and decides nothing. The condensation is the read: the single moment an ordered
    waveform becomes a typed, signable artifact. A second tekton here would assert a second crossing
    of the waveform-provenance boundary, and there is not one."""
    assert len(cm.MARKET["tektons"]) == 1
    assert cm.MARKET["tektons"][0]["name"] == "op.market"


def test_the_tekton_domain_is_not_finance():
    """Nothing about this condensation is specific to markets — a macro series, a sensor array and a
    fleet of embers couple through the identical read. Naming the domain `market` would invite a
    finance-shaped special case into a generic condensation."""
    assert cm.MARKET["tektons"][0]["domain"] == "co-movement"


def test_price_and_news_are_separate_in_facets():
    """A price-only read is a real read; a news-only read has nothing to be a read of. One merged
    conduit would hide that asymmetry, and a caller could not tell which input was optional."""
    facets = {f["name"]: f for f in cm.MARKET["facets"]}
    assert facets["bars"]["direction"] == "in"
    assert facets["news"]["direction"] == "in"


def test_the_read_facet_is_out_only():
    """A structural read is a statement about signal and must never re-enter as signal — the same
    discriminator that keeps `prism.instrument.Read` separate from `Instrument`. `both` here would
    let a read be fed back in as evidence, which is self-reinforcement
    ([[developmental-learning-not-self-reinforcement]])."""
    facets = {f["name"]: f for f in cm.MARKET["facets"]}
    assert facets["read"]["direction"] == "out"
    assert "content_type" not in facets["read"]


def test_content_types_are_hints_and_the_crystal_still_validates_without_them():
    """The binding between conduits is the waveform. A facet's `content_type` is a discovery hint,
    never a gate — a typed gate at a conduit is the step-I/O pipeline contract the propagation rule
    forbids, and validation must succeed with the hints stripped to prove it."""
    stripped = dict(cm.MARKET, facets=[{k: v for k, v in f.items() if k != "content_type"}
                                       for f in cm.MARKET["facets"]])
    assert validate(stripped) == []


def test_the_artifact_is_content_addressed_and_refuses_tampering():
    """The sha covers the declaration, so an edited crystal is a different crystal rather than the
    same one with new contents."""
    art = cm.market_artifact()
    assert art["content_type"] == "application/vnd.agience.crystal+json"
    tampered = dict(cm.MARKET, organons=cm.MARKET["organons"] + [
        {"name": "op.exfiltrate", "requires": ["net.request"]}])
    assert crystal_sha(tampered) != crystal_sha(cm.MARKET)


def test_a_sealed_crystal_is_refused():
    """This is the control for every facet assertion above: it confirms `validate` actually rejects a
    malformed declaration rather than accepting anything, which every prior assertion depends on. A
    crystal with no facet is sealed glass and must be refused."""
    assert validate(dict(cm.MARKET, facets=[])) != []
