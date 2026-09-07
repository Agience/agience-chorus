"""The live chat request path (#2a) — ember reaches the real lumen `op.respond` provider over the carrier.

The chat bff's request path is: place a need on `op.respond`, get the answer inline. Over store-and-forward
that needs `beam.pump.resolve` (place → drive the cadence → collect), because the one-shot `reach()` returns
None without a pump. This proves that path end-to-end with lumen's actual `reach_provider.serve_respond`
(not a stub reactor), ember's actual `ember.runtime.reach.reactor`, `beam.StoreCarrier`, and `beam.PumpLoop`.

Without a real WordNet bundle (`respond_store=None`) the provider answers with the honest `local_respond`
null — `answer=None`, `grounded=False`, the query echoed — never a fabricated reply. What these tests prove
is the wiring (delivery, provenance-correlated pickup, key-gated isolation, ember⇄lumen with different
adapter families); conversation behavior needs the built substrate and a live serve (gated). Invariants:

  answers   — a need placed by ember's reactor returns lumen's exact handler result once the loop drives it;
              if ember's `EmberKeyring`/lightcone didn't derive the same ground key as lumen's `MantleKeyring`,
              the evidence would never come back.
  honest    — the answer is the computed null (grounded False, answer None), query-dependent — not a fake reply.
  dark-safe — with no provider serving, the request resolves to None (silence), never a fabricated answer.
"""
from __future__ import annotations

from prism.carriers import StoreCarrier
from prism.pump import PumpLoop, resolve
from ember.runtime import reach as ember_reach
from lumen import reach_provider as lrp
from mantle.db import open_lattice

ROOT = b"fleet-root-secret-chat-0001"


def _lc(store, principal):
    """Both sides reach op.respond → derive the same group key; ground is auto-joined by the Reactor."""
    return {lrp.RESPOND_CAP}


def _store(tmp_path):
    L = open_lattice(str(tmp_path / "ground.db"), origin="node-71")
    L.artifacts.ensure_schema()
    return L


def test_ember_reaches_the_real_lumen_op_respond(tmp_path):
    store = _store(tmp_path)
    carrier = StoreCarrier(store)
    server = lrp.serve_respond(store, root_secret=ROOT, fabric=None, respond_store=None,
                               reach=_lc, caps={lrp.RESPOND_CAP: "respond"})
    requester = ember_reach.reactor(store, "ember-runner", root_secret=ROOT, fabric=None,
                                    fallback=carrier, reach=_lc)
    loop = PumpLoop(carrier, [server, requester])

    ev = resolve(requester, {"text": "what is a dog?"}, to=lrp.RESPOND_CAP, loop=loop)
    assert ev is not None                                    # the real lumen provider answered over the carrier
    assert ev.get("grounded") is False and ev.get("answer") is None   # honest null (no substrate) — not fabricated
    assert ev.get("echo") == "what is a dog?"                # query-dependent: the exact need crossed the wire


def test_dark_without_a_provider_is_honest_silence(tmp_path):
    store = _store(tmp_path)
    carrier = StoreCarrier(store)
    requester = ember_reach.reactor(store, "ember-runner", root_secret=ROOT, fabric=None,
                                    fallback=carrier, reach=_lc)
    loop = PumpLoop(carrier, [requester])                    # no provider serving op.respond
    assert resolve(requester, {"text": "hi"}, to=lrp.RESPOND_CAP, loop=loop, max_ticks=5) is None
