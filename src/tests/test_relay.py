"""The relay Channel: outward refill from the cloud, verified, over an injected transport.

Moved here from `agience-ember/tests/test_relay.py`: these exercise operators through ember's
runner, so they need a sha-verified operator payload present. The payloads are
chorus's, built from chorus source, and ember is the engine that runs them — so the
test belongs beside the operators rather than beside the engine.
"""
from __future__ import annotations
import numpy as np
import pytest
from _fakes import _StubAnswerer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ember import Ember, MeshChannel
from ember.config import Settings
from ember.embed import HashEmbedder
from mantle.mesh.node import MeshNode
from mantle.search.anchors.anchorset import AnchorSet
from mantle.mesh.anchor_routing import route_write_region
DIM = 16
CANON = "canonical-test"
ALICE = "0fa20e2c-0bb4-4fc8-94ea-f79e73659a64"
WORK = "c7b1a2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d"
LABELS = ["ontology", "storage", "identity", "streaming"]
QUERY = "An ontology names the things a system can talk about."
def _anchors() -> AnchorSet:
    a = AnchorSet(model_id=CANON, dim=DIM)
    for i, l in enumerate(LABELS):
        v = np.full(DIM, 0.05, dtype=np.float32); v[i] = 1.0
        a.add_text(l, v)
    return a
def _settings(tmp_path) -> Settings:
    return Settings(cache_dir=tmp_path, principal=ALICE, collection_id=WORK,
                    engine="extractive", embed_model="", cloud_uri="", nprobe=3)
def _leaf(tmp_path):
    priv = Ed25519PrivateKey.generate()
    e = Ember.boot(_settings(tmp_path), embedder=HashEmbedder(dim=8), engine=_StubAnswerer()).seed(_anchors(), priv.public_key())
    e.authority_pub = priv.public_key()
    return e, priv
def _cloud_with(priv, anchors, embedder, texts):
    """An in-process 'cloud': a MeshNode holding authored shards. Its get_shard is the transport
    — no socket. It uses the same authority key the leaf trusts and the same anchors, so region ids
    line up (that is exactly why a leaf never authors its own anchors)."""
    from ember.embed import Aligner
    al = Aligner(embedder, anchors).fit()
    node = MeshNode("cloud")
    for item_id, text in texts.items():
        vec = al.encode_query(text)
        region = route_write_region(anchors, vec, ALICE, WORK)
        node.put_shard(region, {item_id: text.encode("utf-8")},
                       version=1, authority="ember-local", priv=priv)
    return node
def _transport(node):
    """Adapt a node to the mesh's (peer, region) GetShard convention — the same shape the real
    HTTP transport (`mesh.service.http_shard_getter`) has, so production drops in unchanged."""
    return lambda peer, region: node.get_shard(region)


def test_an_unreachable_cloud_stays_offline_correct(tmp_path) -> None:
    """A dead transport (raises OSError) leaves the read path intact: the leaf answers from what
    it has, or reports that it holds no answer. Disconnected is a normal state, not an error."""
    e, priv = _leaf(tmp_path)

    def dead_get_shard(peer, region):
        raise OSError("connection refused")
    e.connect(MeshChannel(e.cache.node, e.authority_pub, dead_get_shard))

    res = e.ask("what is an ontology?")     # must not raise
    assert res.answer.refused               # nothing local, cloud dead -> honest miss
    assert res.refilled == []


def test_a_cloud_that_lacks_the_region_is_a_clean_miss(tmp_path) -> None:
    """The cloud simply not holding a region is not tampering and not an error — skip it."""
    e, priv = _leaf(tmp_path)
    def empty_get_shard(peer, region):
        return None, None
    e.connect(MeshChannel(e.cache.node, e.authority_pub, empty_get_shard))
    res = e.ask("what is an ontology?")
    assert res.refilled == [] and res.answer.refused
