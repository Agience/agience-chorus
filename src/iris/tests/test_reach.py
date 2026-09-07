"""Signal-native reach (`prism.reach`; there is no `iris/comms/reach.py` re-export shim), tested to
`pharos/genesis/TEST-ARCHITECTURE.md` — named invariants proven over a generated world-space against an
independent oracle, an adversarial roster that must fail safely, and a multi-node partition→heal. A reach is
not a blocking RPC and carries no return address: a need signal is placed, it propagates to whatever provider
resolves it (lightning — live if up, store-and-forward otherwise), the provider discharges the evidence onto
the shared ground plane, and the requester — connected to the same ground — picks it up, correlating by
provenance (the evidence references the need). Not "it ran": every assertion is one of

  (1) delivery    — a need reaches exactly the providers of the capability it is addressed to.
  (2) provenance  — the evidence artifact references the need (`in_reply_to`/`root` == the reach handle); the
                    requester finds its answer by following provenance on the ground, no carried address.
  (3) ground      — the return needs only a shared ground connection: a requester not connected to the
                    provider's ground opens nothing; a non-provider never opens the need (key-gated).
  (4) idempotence — re-delivery / re-pump yields no duplicate evidence (content-addressed artifacts).
  (5) degrade     — a reach resolves over a live fabric and, offline, over a bare carrier + reconcile.
  (6) membrane    — a signal stays intact along its path; each tekton absorbs its band and transmits the
                    residual (same `root`), and the union of bands reconstructs the incident (conservation).

The oracle is computed directly from the membership relation (not from the plane's `reaches`), so the test
cannot be fooled by the plane and the test sharing a bug. See `agience-pharos/genesis/SIGNAL-PROTOCOL.md`.
"""
from __future__ import annotations

import inspect
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → the local `comms` package

from prism.carriers import InMemoryCarrier, reconcile  # noqa: E402
from prism.plane import HLC, Keyring, Lightcone  # noqa: E402
from prism.reach import GROUND, Absorption, Provider, Reactor, Requester, reach  # noqa: E402
from prism.streams import LoopbackFabric  # noqa: E402

SEEDS = range(120)   # the generated world-space (each seed = a reproducible world + reach script)


# ── the world harness: providers offering capabilities, requesters placing needs, one shared ground ───
class World:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.keyring = Keyring(b"reach-root-%d" % seed)
        self.caps = ["op.cap%d" % i for i in range(self.r.randint(1, 4))]
        self.providers = ["prov%d" % i for i in range(self.r.randint(1, 4))]
        self.requesters = ["req%d" % i for i in range(self.r.randint(1, 3))]
        # the membership relation: which provider offers which capability (the ground truth for the oracle).
        self.offers = {p: set(self.r.sample(self.caps, self.r.randint(0, len(self.caps))))
                       for p in self.providers}
        self.lc = Lightcone()
        for c in self.caps:
            self.lc.define_group(c)
        for p, cs in self.offers.items():
            for c in cs:
                self.lc.join(p, c)                       # offering a capability = reaching its address
        self.needs = []
        for i in range(self.r.randint(1, 8)):
            self.needs.append({"req": self.r.choice(self.requesters), "cap": self.r.choice(self.caps),
                               "need": {"q": "n%d" % i, "i": i}})
        self._n = 0

    def clk(self) -> int:                                # one shared, strictly-increasing clock
        self._n += 1
        return self._n

    @staticmethod
    def handler(cap):
        """A deterministic capability: evidence is a pure function of (cap, need). Every provider of a
        capability computes the same evidence, so the answer is well-defined regardless of who resolves."""
        return lambda need, _c=cap: {"cap": _c, "hits": [_c, need]}

    def providers_of(self, cap) -> set:
        """The independent oracle — who resolves a need to `cap` = the providers that offer it, read
        straight from the membership relation (not via the plane's `reaches`)."""
        return {p for p, cs in self.offers.items() if cap in cs}


def _all_handled(reactor: Reactor) -> set:
    seen = set()
    for prov in reactor._providers:                      # merge every capability this persona serves
        seen |= set(prov.handled)
    return seen


def _run_fabric(w: World):
    """Live path: a Reactor per persona on one loopback fabric, all grounded on the default ground plane;
    providers serve, requesters reach; evidence discharges onto the ground and the requester picks it up —
    a synchronous propagation cascade (place need → provider fires → discharge → requester picks up)."""
    fabric = LoopbackFabric()
    reactors = {}
    for p in w.providers:
        rc = Reactor(p, keyring=w.keyring, lightcone=w.lc, fabric=fabric, hlc=HLC(p, clock=w.clk))
        for c in w.offers[p]:
            rc.serve(c, w.handler(c))
        reactors[p] = rc
    for q in w.requesters:
        reactors[q] = Reactor(q, keyring=w.keyring, lightcone=w.lc, fabric=fabric, hlc=HLC(q, clock=w.clk))
    results = []
    for nd in w.needs:
        handle = reactors[nd["req"]].reach(nd["need"], to=nd["cap"])
        ev = reactors[nd["req"]].evidence(handle)
        handled = {p for p in w.providers if handle in _all_handled(reactors[p])}
        results.append((nd, handle, ev, handled))
    return reactors, results


# ── L1 — invariants over the generated world-space (live fabric) ──────────────────────────────────────
def test_need_reaches_exactly_the_capability_providers():           # invariant 1 + 3
    for seed in SEEDS:
        w = World(seed)
        _reactors, results = _run_fabric(w)
        for nd, _handle, _ev, handled in results:
            oracle = w.providers_of(nd["cap"])
            assert handled == oracle, "seed %d cap %s: reached %s != oracle %s" % (
                seed, nd["cap"], sorted(handled), sorted(oracle))


def test_evidence_returns_through_the_ground_referencing_the_need():  # invariant 2
    for seed in SEEDS:
        w = World(seed)
        reactors, results = _run_fabric(w)
        for nd, handle, ev, _handled in results:
            if w.providers_of(nd["cap"]):
                assert ev == w.handler(nd["cap"])(nd["need"])        # the answer, picked up off the ground
                prov = reactors[nd["req"]].provenance(handle)
                assert prov and all(r["root"] == handle for r in prov)          # every band references the need
                assert prov[0]["in_reply_to"] == handle                        # single hop → answers the need
            else:
                assert ev is None                                              # no provider → silence stays silence
                assert reactors[nd["req"]].provenance(handle) == []


def test_correlation_by_provenance_never_crosses_between_needs():    # invariant 2 (no cross-talk)
    for seed in SEEDS:
        w = World(seed)
        reactors, results = _run_fabric(w)
        for nd, handle, _ev, _handled in results:
            if not w.providers_of(nd["cap"]):
                continue
            # the requester collects off the shared ground only the bands whose provenance roots at its handle
            assert reactors[nd["req"]].evidence(handle) == w.handler(nd["cap"])(nd["need"])
            for b in reactors[nd["req"]].bands(handle):
                assert b == w.handler(nd["cap"])(nd["need"])


# ── L2/L3 — focused invariants: ground isolation, key-gated needs, idempotence, degrade, adversarial ──
def test_a_requester_not_connected_to_the_ground_gets_nothing():     # invariant 3 (ground isolation)
    kr = Keyring(b"root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")
    fabric = LoopbackFabric()
    sage = Reactor("sage", keyring=kr, lightcone=lc, fabric=fabric, ground="mesh")       # provider on ground "mesh"
    sage.serve("op.retrieve", lambda need: {"hits": [need]})
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric, ground="mesh")     # same ground → connected
    snoop = Reactor("snoop", keyring=kr, lightcone=lc, fabric=fabric, ground="other")    # a different ground

    handle = lumen.reach({"q": "x"}, to="op.retrieve")
    assert lumen.evidence(handle) == {"hits": [{"q": "x"}]}                              # shares the ground → gets it
    assert snoop._inbox.bands(handle) == []                          # not on sage's ground → the circuit is open


def test_non_provider_on_the_capability_wire_absorbs_nothing():      # invariant 3 (key-gated needs)
    kr = Keyring(b"root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")   # mallory not joined to the cap
    fabric = LoopbackFabric()
    sage = Reactor("sage", keyring=kr, lightcone=lc, fabric=fabric)
    sage.serve("op.retrieve", lambda need: {"hits": [need]})
    mal = Reactor("mallory", keyring=kr, lightcone=lc, fabric=fabric)
    mal_prov = mal.serve("op.retrieve", lambda need: {"stolen": need})        # subscribes, but lacks the cap key
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric)

    handle = lumen.reach({"q": "x"}, to="op.retrieve")
    assert lumen.evidence(handle) == {"hits": [{"q": "x"}]}                   # sage answered
    assert mal_prov.handled == {}                                            # isolation: opened no sealed need


def test_reach_is_idempotent_no_duplicate_evidence_on_redelivery():   # invariant 4
    kr = Keyring(b"root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")
    carrier = InMemoryCarrier()
    sage = Reactor("sage", keyring=kr, lightcone=lc, fabric=None, fallback=carrier)
    sage.serve("op.retrieve", lambda need: {"hits": [need]})
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=None, fallback=carrier)

    handle = lumen.reach({"q": 1}, to="op.retrieve")
    sage.pump(carrier); sage.pump(carrier)                                    # handle twice
    lumen.pump(carrier); lumen.pump(carrier)                                  # pick up twice
    assert lumen.evidence(handle) == {"hits": [{"q": 1}]}
    assert lumen.bands(handle) == [{"hits": [{"q": 1}]}]                      # exactly one band, no dup
    assert len(carrier) == 2                                                  # one need + one evidence
    assert len(sage._providers[0]._seen) == 1                                 # the need handled once


def test_reach_resolves_store_and_forward_across_a_partition():       # invariant 5 (degrade + heal)
    kr = Keyring(b"root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")
    node_req, node_prov = InMemoryCarrier(), InMemoryCarrier()                 # two nodes, partitioned
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=None, fallback=node_req)
    sage = Reactor("sage", keyring=kr, lightcone=lc, fabric=None, fallback=node_prov)
    sage.serve("op.retrieve", lambda need: {"hits": [need]})

    handle = lumen.reach({"q": 1}, to="op.retrieve")                          # need on node_req only
    sage.pump(node_prov)
    assert sage._providers[0].handled == {}                                   # partitioned: provider sees nothing

    reconcile(node_req, node_prov)                                            # heal
    sage.pump(node_prov)                                                      # resolves; evidence onto node_prov ground
    reconcile(node_req, node_prov)                                            # evidence returns through the ground
    lumen.pump(node_req)
    assert lumen.evidence(handle) == {"hits": [{"q": 1}]}                     # delivered store-and-forward

    reconcile(node_req, node_prov); sage.pump(node_prov); lumen.pump(node_req)  # replay everything
    assert lumen.bands(handle) == [{"hits": [{"q": 1}]}]                      # exactly-once, no dup


def test_adversary_forged_need_provenance_is_rejected():             # L3: forged need envelope fails safely
    kr = Keyring(b"root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")
    carrier = InMemoryCarrier()
    reach(carrier, {"q": 1}, to="op.retrieve", keyring=kr, node="lumen", hlc=HLC("lumen"))
    leaf = carrier.poll()[0]

    forged = dict(leaf, cap="op.other", id=leaf["id"] + "x")                  # rewrite the cleartext provenance
    prov = Provider("op.retrieve", lambda need: {"hits": [need]}, keyring=kr, lightcone=lc,
                    principal="sage", node="sage", hlc=HLC("sage"))
    prov.pump(_one(forged))
    assert prov.handled == {}                                                 # sealed binding mismatch → reject

    ok = Provider("op.retrieve", lambda need: {"hits": [need]}, keyring=kr, lightcone=lc,
                  principal="sage", node="sage", hlc=HLC("sage"))
    ok.pump(carrier)
    assert ok.handled != {}                                                   # the untampered need is handled


def test_adversary_forged_evidence_provenance_is_rejected():         # L3: forged evidence reference fails safely
    kr = Keyring(b"root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve").join("lumen", GROUND)
    carrier = InMemoryCarrier()
    reach(carrier, {"q": 1}, to="op.retrieve", keyring=kr, node="lumen", hlc=HLC("lumen"))
    prov = Provider("op.retrieve", lambda need: {"hits": [need]}, keyring=kr, lightcone=lc,
                    principal="sage", node="sage", hlc=HLC("sage"))
    prov.pump(carrier)                                                        # evidence now on the ground (carrier)
    ev = [l for l in carrier.poll() if l["content_type"].endswith("evidence+json")][0]

    forged = dict(ev, root="deadbeefdeadbeef", id=ev["id"] + "x")             # rewrite the provenance root
    inbox = Requester("lumen", lc, kr)
    inbox.on_leaf(forged)
    assert inbox.bands("deadbeefdeadbeef") == []                             # sealed root mismatch → reject
    inbox.on_leaf(ev)                                                         # the untampered one is picked up
    assert inbox.bands(ev["root"]) == [{"hits": [{"q": 1}]}]


def test_adversary_tampered_sealed_payload_does_not_open():          # L3: tampered ciphertext fails safely
    kr = Keyring(b"root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")
    carrier = InMemoryCarrier()
    reach(carrier, {"q": 1}, to="op.retrieve", keyring=kr, node="lumen", hlc=HLC("lumen"))
    leaf = carrier.poll()[0]
    tampered = dict(leaf, sealed=leaf["sealed"][:-4] + ("AAAA" if not leaf["sealed"].endswith("AAAA") else "BBBB"),
                    id=leaf["id"] + "t")
    prov = Provider("op.retrieve", lambda need: {"hits": [need]}, keyring=kr, lightcone=lc,
                    principal="sage", node="sage", hlc=HLC("sage"))
    prov.pump(_one(tampered))
    assert prov.handled == {}                                                 # AEAD tag fails → silence


def test_module_imports_nothing_from_ember_lumen_or_sage():          # the injected-handler boundary
    import prism.reach as reach_mod
    src = inspect.getsource(reach_mod)
    for banned in ("import ember", "from ember", "import lumen", "from lumen", "import sage", "from sage"):
        assert banned not in src, "reach.py must stay signal-native — found %r" % banned


# ── L2 scenario — the Phase-2 target: lumen reaches sage's `op.retrieve`, no in-process import ─────────
def test_lumen_reaches_sage_retrieve_over_the_plane():
    """The concrete reach lumen→sage: a stub sage `op.retrieve` handler returns fake hits; a lumen-style
    requester places its grounding need, sage discharges evidence onto the ground, and lumen picks it up by
    following provenance — no in-process import, no carried return address. The exact call `wiring` puts
    lumen→sage onto."""
    kr = Keyring(b"genesis-root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")
    fabric = LoopbackFabric()

    def sage_retrieve(need):                                                    # stub — stands in for sage
        q = need["query"]
        return {"cap": "op.retrieve",
                "hits": [{"doc": "d1", "score": 0.91, "text": "…%s…" % q},
                         {"doc": "d2", "score": 0.72, "text": "…more on %s…" % q}]}

    sage = Reactor("sage", keyring=kr, lightcone=lc, fabric=fabric)
    sage.serve("op.retrieve", sage_retrieve)
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric)

    # The persona call — lumen places a need on the `op.retrieve` capability; evidence returns via the ground.
    handle = lumen.reach({"query": "who wrote Hamlet?"}, to="op.retrieve")
    evidence = lumen.evidence(handle)

    assert evidence["cap"] == "op.retrieve"
    assert [h["doc"] for h in evidence["hits"]] == ["d1", "d2"]                 # sage-style evidence, verbatim
    # the value is equal but re-serialized — it was sealed and crossed the plane, not shared in-process.
    assert sage._providers[0].handled[handle] == evidence
    # Provenance ties the answer back: the evidence artifact references the need (its own handle).
    prov = lumen.provenance(handle)
    assert prov[0]["in_reply_to"] == handle and prov[0]["root"] == handle and prov[0]["origin"] == "sage"


# ── the membrane seam: absorb-the-coupled-band, propagate-the-residual (multi-hop) ────────────────────
def _band_tekton(band_key, next_to=None):
    """A tekton that couples to one band of the signal: it absorbs `band_key`, condenses it to evidence, and
    transmits the residual (the signal minus its band) onward to `next_to`. Conservation by construction:
    incident bands = absorbed ⊕ residual."""
    def handler(need):
        remaining = dict(need["bands"])
        if band_key not in remaining:
            return Absorption(evidence=None, residual=need, to=next_to)   # no coupling → pure pass-through
        band = remaining.pop(band_key)
        residual = {"bands": remaining} if remaining else None
        return Absorption(evidence={band_key: band}, residual=residual, to=next_to)
    return handler


def test_signal_propagates_through_two_tektons_each_absorbing_its_band():   # invariant 6 (membrane + provenance)
    """A signal stays intact along its path; tekton A absorbs band x and transmits the residual to tekton B,
    which absorbs band y. Both bands return through the ground under one root (the reach handle); their union
    reconstructs the incident signal (conservation), and the residual hop is a tracked artifact whose
    provenance is `derived_from` the original need."""
    kr = Keyring(b"membrane-root")
    lc = (Lightcone().define_group("op.capA").define_group("op.capB")
          .join("tektonA", "op.capA").join("tektonB", "op.capB"))
    fabric = LoopbackFabric()
    clk = _counter()
    residual_needs = []
    fabric.subscribe("op.capB", lambda leaf: residual_needs.append(leaf))     # sniff the residual hop's provenance

    ta = Reactor("tektonA", keyring=kr, lightcone=lc, fabric=fabric, hlc=HLC("tektonA", clock=clk))
    ta.serve("op.capA", _band_tekton("x", next_to="op.capB"))                # absorbs x, transmits residual to B
    tb = Reactor("tektonB", keyring=kr, lightcone=lc, fabric=fabric, hlc=HLC("tektonB", clock=clk))
    tb.serve("op.capB", _band_tekton("y"))                                   # absorbs y, residual empty → terminates
    req = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric, hlc=HLC("lumen", clock=clk))

    incident = {"bands": {"x": 1, "y": 2}}
    handle = req.reach(incident, to="op.capA")

    bands = req.bands(handle)                                                 # every band absorbed, HLC-ordered
    assert bands == [{"x": 1}, {"y": 2}]                                      # A coupled x, then B coupled y
    merged = {}
    for b in bands:
        merged.update(b)
    assert merged == incident["bands"]                                       # conservation: union == incident signal
    assert list(ta._providers[0].handled.values()) == [{"x": 1}]             # A absorbed exactly its band
    assert list(tb._providers[0].handled.values()) == [{"y": 2}]             # B absorbed exactly its band
    # the residual hop is a tracked artifact: same root (the handle), derived_from the original need.
    rn = residual_needs[0]
    assert rn["root"] == handle and rn["derived_from"] == handle and rn["path"] == ["op.capA", "op.capB"]
    # every returned band shares the one root; the second answers the residual need, not the original.
    prov = req.provenance(handle)
    assert {r["root"] for r in prov} == {handle}
    assert prov[0]["in_reply_to"] == handle and prov[1]["in_reply_to"] == rn["id"]


def test_a_fully_absorbing_tekton_transmits_no_residual():
    """Single hop is the fully-absorbed case of the same seam: residual is None → the signal terminates, one
    band comes back. (A plain-value handler is the shorthand for this — proven green across the suite above.)"""
    kr = Keyring(b"membrane-root")
    lc = Lightcone().define_group("op.capA").join("tektonA", "op.capA")
    fabric = LoopbackFabric()
    clk = _counter()
    ta = Reactor("tektonA", keyring=kr, lightcone=lc, fabric=fabric, hlc=HLC("tektonA", clock=clk))
    ta.serve("op.capA", _band_tekton("x", next_to="op.capB"))                # would forward to capB…
    req = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric, hlc=HLC("lumen", clock=clk))

    handle = req.reach({"bands": {"x": 1}}, to="op.capA")                    # …but nothing remains after x
    assert req.bands(handle) == [{"x": 1}]                                    # residual empty → no second hop
    assert req.evidence(handle) == {"x": 1}


def _one(leaf):
    """A one-leaf carrier — the smallest transport for an adversarial leaf."""
    c = InMemoryCarrier()
    c.put(leaf)
    return c


def _counter():
    n = {"v": 0}
    def clk():
        n["v"] += 1
        return n["v"]
    return clk
