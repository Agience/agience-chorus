"""Frame-native op.retrieve (§A.2) — sage's provider treats its NEED as a signal, not just a query
string.

When the need carries a `(T,F)` beam frame, the provider absorbs this tekton's coupled band and
returns the residual to propagate onward — the absorb-and-propagate-the-remaining mechanism, live at
a real persona provider, over the real `StoreCarrier` reach. Invariants:

  absorbed    — a frame NEED comes back as the frame-response (a coupled band absorbed,
                `absorbed_k ≥ 1`), never silently dropped; the residual returns so the signal can
                keep its full length.
  conserved   — `‖incident‖² = absorbed + ‖residual‖²` end-to-end over the wire (the membrane is
                lossless).
  backward    — a query-only NEED is unchanged: it returns the hits list, never the frame dict.

Absorbing a band is a measurement, so the provider resolves an instrument through
`prism.instrument` — injected keyword, then the process default, then nothing to measure with (§3:
silence stays silence). `ember/__init__.py` registers `ember.optics` as that default at import,
which is how a real node becomes a host. A test process has no runner, so this file imports `ember`
itself and stands in as the host explicitly, the same move `src/conftest.py` makes for the host
seams — a test that only passes because some other test happened to import it first is not
measuring what it claims.
"""
from __future__ import annotations

import ember  # noqa: F401  — registers the instrument default; see the header. Not unused.

import numpy as np

from prism import frames as BF
from prism.carriers import StoreCarrier
from prism.pump import PumpLoop, resolve
from ember.runtime import reach as ember_reach
from mantle.db import open_lattice
from sage import reach_provider as srp

ROOT = b"fleet-root-frame-0001"


def _lc(store, principal):
    return {srp.RETRIEVE_CAP}


def _store(tmp_path):
    L = open_lattice(str(tmp_path / "g.db"), origin="node-71")
    L.artifacts.ensure_schema()
    return L


def _planted(T=64, Fd=16, r=2, seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((T, r)) @ rng.standard_normal((r, Fd)) + 0.02 * rng.standard_normal((T, Fd))


def test_a_signal_frame_is_absorbed_at_the_retrieve_tekton(tmp_path):
    store = _store(tmp_path)
    carrier = StoreCarrier(store)
    server = srp.serve_retrieve(store, root_secret=ROOT, fabric=None, corpus=None, reach=_lc)   # self-resolution
    requester = ember_reach.reactor(store, "ember", root_secret=ROOT, fabric=None, fallback=carrier, reach=_lc)
    loop = PumpLoop(carrier, [server, requester])

    W = _planted()
    ev = resolve(requester, {BF.FRAME_KEY: BF.encode_frame(W)}, to=srp.RETRIEVE_CAP, loop=loop)
    assert isinstance(ev, dict) and ev.get("absorbed_k", 0) >= 1    # a coupled band was absorbed at the tekton
    residual = BF.decode_frame(ev[BF.FRAME_KEY])
    assert residual is not None and residual.shape == W.shape       # the residual returned to propagate onward
    e_in, e_res = float((W ** 2).sum()), float((residual ** 2).sum())
    assert e_res < e_in                                             # a band was shed
    assert abs(e_in - (ev["absorbed_energy"] + e_res)) < 1e-6 * e_in   # conserved end-to-end over the reach


def test_a_query_only_need_is_unchanged(tmp_path):
    store = _store(tmp_path)
    carrier = StoreCarrier(store)
    server = srp.serve_retrieve(store, root_secret=ROOT, fabric=None,
                                docs=[{"id": "d1", "title": "t", "content": "hello world"}], reach=_lc)
    requester = ember_reach.reactor(store, "ember", root_secret=ROOT, fabric=None, fallback=carrier, reach=_lc)
    loop = PumpLoop(carrier, [server, requester])

    ev = resolve(requester, {"query": "hello"}, to=srp.RETRIEVE_CAP, loop=loop)
    assert isinstance(ev, list)                                     # query path → the hits list, not a frame dict
