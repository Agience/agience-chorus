"""The communication plane, tested to `agience-pharos/genesis/TEST-ARCHITECTURE.md` — invariants over a generated
world-space + an independent oracle + an adversarial roster + multi-node reconciliation, on real
crypto (AES-256-GCM + HKDF group keys). Not "it ran": every assertion is a named comms invariant (isolation /
delivery / idempotence / order / propagation / conservation), proven for all generated worlds. The
concrete, diagrammed genesis network lives in `test_comm_plane_scenario.py`.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → the local `comms` package

from prism.plane import Keyring, Lightcone, open_sealed, receive, seal, send  # noqa: E402
from prism.carriers import InMemoryCarrier, reconcile  # noqa: E402

SEEDS = range(150)   # the generated world-space (each seed = a reproducible world + script)


class World:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.keyring = Keyring(b"fleet-root-%d" % seed)
        self.principals = ["p%d" % i for i in range(self.r.randint(2, 6))]
        self.groups = ["g%d" % i for i in range(self.r.randint(2, 5))]
        self.contains = {g: set() for g in self.groups}
        for i, g in enumerate(self.groups):
            higher = self.groups[i + 1:]
            if higher and self.r.random() < 0.5:
                self.contains[g].add(self.r.choice(higher))
        self.member = {p: set(self.r.sample(self.groups, self.r.randint(0, len(self.groups))))
                       for p in self.principals}
        self.lc = Lightcone()
        for g in self.groups:
            self.lc.define_group(g, contains=self.contains[g])
        for p in self.principals:
            for g in self.member[p]:
                self.lc.join(p, g)
        self.events = []
        for i in range(self.r.randint(1, 12)):
            self.events.append({"frm": self.r.choice(self.principals), "to": self.r.choice(self.groups),
                                "signal": {"seq": i}, "hlc": "%06d" % i})

    def _reachable(self, p) -> set:
        """The independent oracle — the read light-cone (grant model): a principal reaches itself, its
        granted groups, and their containment descendants. Computed by a different method than the plane's
        `reaches` (an explicit fixpoint over the descendant relation), so it can still disagree with a plane
        bug. Matches `mantle.db.access.reachable_collections` — a grant on a parent reaches its children."""
        reach = set(self.member[p]) | {p}                    # its groups + its own ember address
        changed = True
        while changed:                                       # fixpoint: pull in every descendant
            changed = False
            for g in list(reach):
                for kid in self.contains.get(g, set()):
                    if kid not in reach:
                        reach.add(kid)
                        changed = True
        return reach

    def expected(self, p) -> set:
        reach = self._reachable(p)
        return {e["signal"]["seq"] for e in self.events if e["to"] in reach}

    def run(self, carrier=None):
        carrier = carrier or InMemoryCarrier()
        for e in self.events:
            send(carrier, to=e["to"], frm=e["frm"], signal=e["signal"], keyring=self.keyring, hlc=e["hlc"])
        return carrier

    def rx(self, carrier, p):
        return receive(carrier, principal=p, lightcone=self.lc, keyring=self.keyring)


# ── L1 — invariants over the generated world-space ────────────────────────────────────────────────────
def test_delivery_and_isolation_equal_the_oracle_for_every_principal():
    for seed in SEEDS:
        w = World(seed)
        c = w.run()
        for p in w.principals:
            got = {m["signal"]["seq"] for m in w.rx(c, p)}
            assert got == w.expected(p), "seed %d %s: plane %s != oracle %s" % (
                seed, p, sorted(got), sorted(w.expected(p)))


def test_idempotence_repoll_and_duplicate_leaves_never_duplicate():
    for seed in SEEDS:
        w = World(seed)
        c = w.run()
        for leaf in list(c.poll()):
            c.put(leaf)                                    # replay every leaf
        for p in w.principals:
            once, twice = w.rx(c, p), w.rx(c, p)
            ids = [m["id"] for m in once]
            assert len(ids) == len(set(ids)) and once == twice


def test_order_is_by_hlc_independent_of_arrival_order():
    for seed in SEEDS:
        w = World(seed)
        c = w.run()
        shuffled = InMemoryCarrier()
        leaves = c.poll()
        random.Random(seed + 1).shuffle(leaves)
        for leaf in leaves:
            shuffled.put(leaf)
        for p in w.principals:
            a = [m["hlc"] for m in w.rx(c, p)]
            b = [m["hlc"] for m in w.rx(shuffled, p)]
            assert a == b == sorted(a)


# ── L3 — the adversarial roster (each fails safely) ───────────────────────────────────────────────────
def test_adversary_without_the_key_cannot_open_a_sealed_signal():
    kr = Keyring(b"fleet-root")
    sealed = seal({"secret": 42}, kr.group_key("family"), aad="family")
    assert open_sealed(sealed, [kr.group_key("family")], aad="family") == {"secret": 42}    # a holder opens it
    assert open_sealed(sealed, [kr.group_key("rivals")], aad="family") is None              # a non-holder gets nothing
    assert open_sealed(sealed, [Keyring(b"other-fleet").group_key("family")], aad="family") is None  # wrong root


def test_adversary_tampering_with_a_sealed_leaf_does_not_open():
    kr = Keyring(b"fleet-root")
    sealed = seal({"secret": 42}, kr.group_key("family"), aad="family")
    tampered = sealed[:-4] + ("AAAA" if not sealed.endswith("AAAA") else "BBBB")
    assert open_sealed(tampered, [kr.group_key("family")], aad="family") is None            # AEAD tag fails → silence


def test_partition_then_heal_delivers_exactly_once_multi_node():
    kr = Keyring(b"fleet-root")
    lc = Lightcone().define_group("g").join("a", "g").join("b", "g")
    node_a, node_b = InMemoryCarrier(), InMemoryCarrier()
    send(node_a, to="g", frm="a", signal={"n": 1}, keyring=kr, hlc="001")
    send(node_a, to="g", frm="a", signal={"n": 2}, keyring=kr, hlc="002")
    assert receive(node_b, principal="b", lightcone=lc, keyring=kr) == []     # partitioned

    assert reconcile(node_a, node_b) == 2
    assert reconcile(node_a, node_b) == 0                                     # idempotent (no dup)
    on_a = [m["signal"]["n"] for m in receive(node_a, principal="b", lightcone=lc, keyring=kr)]
    on_b = [m["signal"]["n"] for m in receive(node_b, principal="b", lightcone=lc, keyring=kr)]
    assert on_b == on_a == [1, 2]                                            # carrier-agnostic, exactly-once
