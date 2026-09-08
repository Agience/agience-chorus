"""Frame-native op.respond (§A.2) — lumen's provider treats its need as a signal, not just a text turn.

When the need carries a `(T,F)` beam frame, the conversation provider absorbs this tekton's coupled
band and merges the residual into the response, to propagate onward — the absorb-and-propagate
mechanism live at the conversation tekton, over the real `StoreCarrier` reach. Invariants:

  absorbed — a frame need must come back with the absorbed band (`absorbed_k ≥ 1`) plus the
             residual, alongside the (honest-null, no-substrate) response; conserved end-to-end.
             A dropped frame would break the signal's full length.
  backward — a text-only need is unchanged: the op.respond shape, no frame fields, never a
             fabricated answer.

This file imports `ember` explicitly (below) because it is its own host: absorbing a band is a
measurement, resolved through `prism.instrument` (injected keyword → process default → error).
`ember/__init__.py` registers `ember.optics` as that default at import, which is how a node becomes
a host — a test file that never imports `ember` has no default to resolve against, and would only
pass by borrowing one from whatever other test happened to import it first.
"""
from __future__ import annotations

import ember  # noqa: F401  — registers the instrument default; see the header. Not unused.

import numpy as np

from prism import frames as BF
from prism.carriers import StoreCarrier
from prism.pump import PumpLoop, resolve
from ember.runtime import reach as ember_reach
from agience_chorus.lumen import reach_provider as lrp
from mantle.db import open_lattice

ROOT = b"fleet-root-respond-frame-1"


def _lc(store, principal):
    return {lrp.RESPOND_CAP}


def _store(tmp_path):
    L = open_lattice(str(tmp_path / "g.db"), origin="node-71")
    L.artifacts.ensure_schema()
    return L


def _planted(T=64, Fd=16, r=2, seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((T, r)) @ rng.standard_normal((r, Fd)) + 0.02 * rng.standard_normal((T, Fd))


def _stack(tmp_path):
    store = _store(tmp_path)
    carrier = StoreCarrier(store)
    server = lrp.serve_respond(store, root_secret=ROOT, fabric=None, respond_store=None,
                               reach=_lc, caps={lrp.RESPOND_CAP: "respond"})
    requester = ember_reach.reactor(store, "ember", root_secret=ROOT, fabric=None, fallback=carrier, reach=_lc)
    return carrier, PumpLoop(carrier, [server, requester]), requester


def test_a_frame_is_absorbed_at_the_respond_tekton(tmp_path):
    carrier, loop, requester = _stack(tmp_path)
    W = _planted()
    ev = resolve(requester, {"text": "hi", BF.FRAME_KEY: BF.encode_frame(W)}, to=lrp.RESPOND_CAP, loop=loop)
    assert isinstance(ev, dict) and ev.get("absorbed_k", 0) >= 1     # the conversation tekton absorbed a band
    assert ev.get("answer") is None and ev.get("grounded") is False  # honest null response (no substrate) — merged
    residual = BF.decode_frame(ev[BF.FRAME_KEY])
    assert residual is not None and residual.shape == W.shape
    e_in, e_res = float((W ** 2).sum()), float((residual ** 2).sum())
    assert abs(e_in - (ev["absorbed_energy"] + e_res)) < 1e-6 * e_in  # conserved end-to-end over the reach


def test_a_text_only_need_is_unchanged(tmp_path):
    carrier, loop, requester = _stack(tmp_path)
    ev = resolve(requester, {"text": "what is a dog?"}, to=lrp.RESPOND_CAP, loop=loop)
    assert isinstance(ev, dict) and ev.get("answer") is None and ev.get("grounded") is False
    assert BF.FRAME_KEY not in ev and "absorbed_k" not in ev         # no frame → no frame fields, unchanged shape
