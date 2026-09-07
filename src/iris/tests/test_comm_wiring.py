"""Wiring the plane to the real fleet access + crypto + carriers (`iris/comms/wiring.py`, `carriers.py`).
Tested against fakes (a dict-backed S3 client, an injected light-cone fn) so no live bucket/store is
needed — but `MantleKeyring` uses the fleet's actual `collection_key` derivation, and `S3Carrier` exercises
the real object-store logic. The plane's invariants (isolation, delivery, group vs direct-ember) hold the
same over the wired components as over the in-memory ones."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.carriers import InMemoryCarrier, S3Carrier, reconcile  # noqa: E402
from prism.plane import Lightcone, open_sealed, seal  # noqa: E402
from comms.wiring import MantleKeyring, MantleLightcone, build_plane  # noqa: E402


# ── a fake S3 client: dict-backed put_object / get_object / list_objects_v2 ────────────────────────────
class _Body:
    def __init__(self, data): self._d = data
    def read(self): return self._d


class FakeS3:
    def __init__(self): self.objs = {}
    def put_object(self, Bucket, Key, Body): self.objs[(Bucket, Key)] = Body
    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objs:
            raise KeyError(Key)
        return {"Body": _Body(self.objs[(Bucket, Key)])}
    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        return {"Contents": [{"Key": k} for (b, k) in self.objs if b == Bucket and k.startswith(Prefix)],
                "IsTruncated": False}


# ── MantleKeyring uses the fleet's real content-key derivation ────────────────────────────────────────
def test_mantle_keyring_uses_the_fleet_content_key_and_seals():
    kr = MantleKeyring(b"fleet-root-secret")
    k_project = kr.group_key("project")
    assert k_project == kr.group_key("project")                 # deterministic (all members derive the same)
    assert kr.group_key("private") != k_project                 # per-group, distinct
    sealed = seal({"m": "hi"}, k_project, aad="project")                        # a real AES-256 key
    assert open_sealed(sealed, [k_project], aad="project") == {"m": "hi"}
    assert open_sealed(sealed, [kr.group_key("private")], aad="project") is None   # a different group's key cannot open it


# ── MantleLightcone wraps the read light-cone; adds the ember's own address ───────────────────────────
def test_mantle_lightcone_is_read_access_plus_self():
    grants = {"alice": ["project", "acme"], "bob": []}          # a fake reachable-collections
    lc = MantleLightcone(store=None, reach=lambda _store, p: grants.get(p, []))
    assert lc.reaches("alice") == {"project", "acme", "alice"}  # her collections + her own ember address
    assert lc.reaches("bob") == {"bob"}                         # only her own address (no grants)


# ── S3Carrier round-trips and reconciles like any carrier ─────────────────────────────────────────────
def test_s3_carrier_put_poll_get_ids_and_reconcile():
    s3 = FakeS3()
    a = S3Carrier(s3, "bucket", prefix="mesh/comms")
    a.put({"id": "L1", "hlc": "002", "to": "g", "sealed": "x"})
    a.put({"id": "L2", "hlc": "001", "to": "g", "sealed": "y"})
    a.put({"id": "L1", "hlc": "002", "to": "g", "sealed": "x"})   # idempotent
    assert a.ids() == {"L1", "L2"}
    assert [l["id"] for l in a.poll()] == ["L2", "L1"]           # HLC-ordered
    assert a.get("L2")["sealed"] == "y"
    b = InMemoryCarrier()                                        # reconcile S3 ⟷ in-memory (carrier-agnostic)
    assert reconcile(a, b) == 2
    assert reconcile(a, b) == 0                                  # idempotent
    assert b.ids() == {"L1", "L2"}


# ── the whole plane, wired (real keyring + real S3 carrier + injected grants) ─────────────────────────
def test_build_plane_end_to_end_on_wired_components():
    grants = {"alice": ["project"], "bob": []}                  # alice ∈ project; bob has no grants
    reach = lambda _store, p: grants.get(p, [])
    s3 = FakeS3()

    def clk(c=[0]):
        c[0] += 1
        return c[0]

    alice = build_plane(node="alice", store=None, root_secret=b"root",
                        carriers=[S3Carrier(s3, "bucket")], reach=reach, clock=clk)
    bob = build_plane(node="bob", store=None, root_secret=b"root",
                     carriers=[S3Carrier(s3, "bucket")], reach=reach, clock=clk)

    alice.send("project", {"m": "kickoff"})          # group target
    alice.send("bob", {"m": "just you"})             # direct ember target

    assert [m["signal"]["m"] for m in alice.receive("alice")] == ["kickoff"]   # in project; not the DM to bob
    assert [m["signal"]["m"] for m in bob.receive("bob")] == ["just you"]      # the direct message only
    # Isolation: bob is not in project → cannot read the project message even though it is in the bucket.
    assert "kickoff" not in [m["signal"]["m"] for m in bob.receive("bob")]
