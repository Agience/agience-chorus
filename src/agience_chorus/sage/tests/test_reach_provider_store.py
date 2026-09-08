"""The real sage provider over the local carrier: ember reaches sage's `op.retrieve` and the evidence
returns through a persisted mantle lattice store, not the in-memory `LoopbackFabric`.

`test_reach_provider.py` proves the same reach over `LoopbackFabric` (live, same-object, same-process).
This file swaps the transport for `beam.carriers.StoreCarrier` — a carrier that persists every need /
evidence envelope as a lattice artifact — and drives the store-and-forward round-trip with two
independent reactors sharing one real lattice store:

  - provider = sage, stood up exactly as production would (`reach_provider.serve_retrieve`), but
    carrier-only (`fabric=None`) so its provider is pump-driven — the offline / store-and-forward path.
  - requester = ember (`ember.runtime.reach.reactor`), fallback'd onto the same `StoreCarrier`, placing
    the need an Apache runner places. Ember imports no chorus; it reaches over the wire (`prism`) only.

Both derive the ground key from one `root_secret`, so the persisted evidence opens for the requester
and the circuit completes — through the store, correlated by provenance (`root == handle`), no
`reply_to`.

A two-process run needs only a serve-loop cadence added on top of this: a poller invoking
`sage.pump(carrier)` and `req.pump(carrier)` on an interval (and `StoreCarrier` pointed at a shared DB
file / `S3Carrier` at the mesh bucket) instead of the explicit in-test drive. The wire is what is
proven here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare `import reach_provider`

from agience_chorus import _persona  # noqa: E402

# `sys.modules` is keyed by name and process-global, so a bare `import reach_provider` /
# `import manifest` means whichever persona imported it first — and several personas own a
# module by each of those names. `_persona.load` loads this persona's copy under the unique name
# `<persona>.<module>`, so substitution is impossible.
reach_provider = _persona.load("reach_provider", __file__)

import ember.runtime.reach as er  # noqa: E402  (the Apache runner side — imports no chorus)
from prism.carriers import CARRIER_LEAF_CT, StoreCarrier  # noqa: E402
from prism.reach import EVIDENCE_CT, NEED_CT  # noqa: E402
from mantle.db import open_lattice  # noqa: E402

DOCS = [
    {"id": "d.hamlet", "title": "Hamlet", "content": "Hamlet is a tragedy written by William Shakespeare."},
    {"id": "d.newton", "title": "Principia", "content": "Isaac Newton described the laws of motion and gravity."},
    {"id": "d.gravity", "title": "Gravity", "content": "Gravity is the attraction between masses, per Newton."},
]


def _ground(tmp_path):
    """A real lattice store — the shared ground the reach round-trips through."""
    L = open_lattice(str(tmp_path / "ground.db"), origin="node-71")
    L.artifacts.ensure_schema()
    return L


def _offers(offers):
    """An injected light-cone fn: `principal -> {caps}` (grants without a live grant store)."""
    return lambda _store, principal: offers.get(principal, set())


def _wire(tmp_path, offers, *, root=b"genesis-fleet-root", ground="ground"):
    store = _ground(tmp_path)
    carrier = StoreCarrier(store)
    reach_fn = _offers(offers)
    # sage: the real provider, carrier-only (fabric=None) → pump-driven store-and-forward.
    sage = reach_provider.serve_retrieve(store, root_secret=root, fabric=None, docs=DOCS,
                                         ground=ground, reach=reach_fn)
    # ember: the runner requester, fallback'd onto the same StoreCarrier.
    req = er.reactor(store, "ember", root_secret=root, fabric=None, fallback=carrier, ground=ground,
                     reach=reach_fn)
    return store, carrier, sage, req


# ── delivery + persistence + provenance + real shape ──────────────────────────────────────────────────
def test_ember_reaches_sage_op_retrieve_through_a_persisted_store(tmp_path):
    store, carrier, sage, ember = _wire(tmp_path, {"sage": {"op.retrieve"}})

    need = {"query": "who wrote Hamlet?"}
    handle = ember.reach(need, to="op.retrieve")         # need persisted to the lattice
    assert ember.evidence(handle) is None                # store-and-forward: silent until the server serves

    sage.pump(carrier)                                   # sage's serve loop: poll needs, discharge evidence
    ember.pump(carrier)                                  # ember's ground pickup off the store

    evidence = ember.evidence(handle)
    oracle = reach_provider.local_retrieve(need["query"], DOCS)
    assert evidence == oracle                            # delivery + real shape: exactly sage's own hits
    assert evidence[0]["id"] == "d.hamlet"
    assert all(set(h) == {"id", "title", "content", "score"} for h in evidence)

    # persistence: the transport was the lattice — a need and an evidence landed as real artifacts.
    kinds = sorted(d["leaf"]["content_type"]
                   for d in store.artifacts.list_artifacts(content_type=CARRIER_LEAF_CT))
    assert NEED_CT in kinds and EVIDENCE_CT in kinds
    assert store.artifacts.get_artifact(handle) is not None      # need artifact id == the reach handle

    # provenance: evidence references the need; ember correlates on the store, no return address.
    prov = ember.provenance(handle)
    assert prov and prov[0]["in_reply_to"] == handle and prov[0]["root"] == handle
    assert prov[0]["origin"] == "sage" and prov[0]["cap"] == "op.retrieve"


# ── isolation: a requester keyed off a different fleet root gets nothing off the same store ───────────
def test_a_different_root_key_gets_nothing_off_the_store(tmp_path):
    store, carrier, sage, ember = _wire(tmp_path, {"sage": {"op.retrieve"}})
    handle = ember.reach({"query": "Hamlet"}, to="op.retrieve")
    sage.pump(carrier)
    ember.pump(carrier)
    assert ember.evidence(handle)[0]["id"] == "d.hamlet"         # fleet-root holder → gets the answer

    # a snoop reading the same store but keyed off a different root never derives the ground key.
    snoop = er.reactor(store, "ember", root_secret=b"a-different-root", fabric=None, fallback=carrier,
                       reach=_offers({"ember": set()}))
    snoop.pump(carrier)
    assert snoop.bands(handle) == []                             # opaque: isolation is cryptographic


# ── inactive-by-default is preserved: no wiring → the provider stays dark (honest null) ───────────────
def test_provider_stays_dark_without_wiring():
    assert reach_provider.serve_retrieve_if_configured() is None
