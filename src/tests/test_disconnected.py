"""Ember answers with the network unplugged, and reports plainly when it holds nothing.

Moved here from `agience-ember/tests/test_disconnected.py`: these exercise operators through ember's
runner, so they need a sha-verified operator payload present. The payloads are
chorus's, built from chorus source, and ember is the engine that runs them — so the
test belongs beside the operators rather than beside the engine.
"""
from __future__ import annotations
import numpy as np
import pytest
from _fakes import _StubAnswerer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ember import LocalCache, answer_query, build
from mantle.search.anchors.anchorset import AnchorSet
DIM = 16
MODEL = "test-embed"
PRINCIPAL = "0fa20e2c-0bb4-4fc8-94ea-f79e73659a64"
COLLECTION = "c7b1a2d3-4e5f-4a6b-8c9d-0e1f2a3b4c5d"
def _anchorset() -> AnchorSet:
    """Well-separated anchors: one axis per topic."""
    a = AnchorSet(model_id=MODEL, dim=DIM)
    for i in range(4):
        v = np.full(DIM, 0.05, dtype=np.float32)
        v[i] = 1.0
        a.add_text(f"anchor-{i}", v)
    return a
def _vec(axis: int, jitter: float = 0.0) -> np.ndarray:
    v = np.full(DIM, 0.05, dtype=np.float32)
    v[axis] = 1.0
    if jitter:
        v[(axis + 5) % DIM] += jitter
    return v
@pytest.fixture()
def cache() -> LocalCache:
    c = LocalCache(_anchorset(), PRINCIPAL, COLLECTION, nprobe=3)
    priv = Ed25519PrivateKey.generate()
    # Author local artifacts on axis 0 — "your own content is a region this node originates".
    c.put(
        [
            ("art-1", b"Ontologies name the things a system can talk about.", _vec(0)),
            ("art-2", b"An anchor set is the shared coordinate system.", _vec(0, 0.02)),
            ("art-3", b"A shard is a set of anchor-region artifacts.", _vec(0, 0.04)),
        ],
        version=1, authority="ember-local", priv=priv,
    )
    return c


def test_miss_is_honest_when_disconnected(cache: LocalCache) -> None:
    """Disconnected and missing the nearest cell: the read reports what it lacks.

    `nprobe` pulls in outer probe cells, so `search` returns near-orthogonal artifacts from a
    neighbourhood this node happens to hold, and an answerer with no corpus of its own sees only
    spans — an axis-2 query would come back with confident axis-0 content. Holding the nearest cell
    is what makes an answer an answer, so the read carries `provisional` and names the regions it
    would need.
    """
    res = answer_query(cache, _StubAnswerer(), "unrelated question", _vec(2), refill=None)
    assert not res.routing.hit
    assert res.served_offline
    assert res.answer.refused                       # no reading to give, rather than a guess
    assert "don't hold" in res.answer.text
    assert res.answer.read["provisional"] is True
    assert res.answer.read["missing_regions"]       # and it names exactly what it lacks
    # Still reports what it does hold, which is more useful to a caller than silence.
    assert res.answer.cited


def test_refill_only_pulls_the_missing_working_set(cache: LocalCache) -> None:
    """On a miss Ember asks for the routed cells it lacks, which is a working set rather than the
    corpus. The refill is injected, so the read path is exercised as transport-agnostic with no
    socket involved."""
    asked: list = []

    def fake_refill(regions):
        asked.append(list(regions))
        return []                              # peer had nothing; the read path carries on

    res = answer_query(cache, _StubAnswerer(), "q", _vec(2), refill=fake_refill)
    assert asked, "a miss must attempt a refill"
    assert asked[0] == res.routing.missing
    assert len(asked[0]) <= 3                  # an nprobe-bounded working set
