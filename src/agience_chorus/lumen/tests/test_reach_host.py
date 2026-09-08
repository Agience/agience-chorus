"""The local reach host — the go-live assembly that flips the reach up on one node (#2a capstone).

`ReachHost` composes the proven pieces (StoreCarrier + PumpLoop + resolve + the real lumen/sage providers +
the ember requester) into one object a facet injects: `main._RESPOND_CARRIER = {"respond": host.respond}`.
This proves the assembly end-to-end with the real providers over a fixture store and an injected light-cone
(the stand-in for the gated live grants). Without a WordNet `respond_store` the responder returns the honest
null — what these tests prove is the wiring; real answers come from the gated on-71 run. Invariants:

  responds honestly — `host.respond(q)` drives the cadence to lumen's op.respond and returns the honest null
                      (grounded False, answer None, query echoed) — assembled correctly, never fabricated.
  retrieve wires    — `serve_sage()` + `host.retrieve(q)` completes without error, honest-empty / honest-silence.
  lifecycle         — a `with ReachHost(...)` block leaves no background loop running on exit.
"""
from __future__ import annotations

from mantle.db import open_lattice
from agience_chorus.reach_host import ReachHost

ROOT = b"fleet-root-secret-host-0001"


def _lc(store, principal):
    """Injected light-cone: both the requester and the providers reach op.respond + op.retrieve, so they
    derive matching ground keys. The stand-in for the real grant light-cone (the gated live piece)."""
    return {"op.respond", "op.retrieve"}


def _store(tmp_path):
    L = open_lattice(str(tmp_path / "ground.db"), origin="node-71")
    L.artifacts.ensure_schema()
    return L


def test_host_respond_is_assembled_and_honest(tmp_path):
    host = ReachHost(_store(tmp_path), root_secret=ROOT, reach=_lc).serve_lumen()
    ev = host.respond("what is a dog?")
    assert ev is not None                                    # the assembled host reached lumen op.respond
    assert ev.get("grounded") is False and ev.get("answer") is None   # honest null (no substrate)
    assert ev.get("echo") == "what is a dog?"                # query-dependent — the need crossed the wire


def test_host_retrieve_wires_without_crashing(tmp_path):
    host = ReachHost(_store(tmp_path), root_secret=ROOT, reach=_lc).serve_sage()
    got = host.retrieve("hamlet")                            # empty store ⇒ honest-empty or honest-silence
    assert got in (None, [])                                 # never an exception, never a fabricated hit


def test_host_context_manager_stops_the_loop(tmp_path):
    host = ReachHost(_store(tmp_path), root_secret=ROOT, reach=_lc).serve_lumen()
    with host.start():
        assert host.loop.running
    assert not host.loop.running                             # context-exit stopped the background cadence
