"""§0.1.4 — the durable go-live service, exercised against a temp lattice (never node 71).

`live_service.py` is a module shared across chorus (`chorus/src/`, like `reach_host.py`) that wires
aria's bff to a `ReachHost`; it belongs to no single persona, so its tests live here in the shared
`src/tests/` rather than in a persona's own suite.

`ReachHost` and aria's bff are each tested on their own, but the wiring between them is a seam
neither side's own tests can see, since each proves only its own half: without something
constructing the first and handing it to the second, the chat facet's carrier resolves to `None` and
the facet answers with the offline text regardless of whether either half works.
`live_service.build_live` is that entrypoint; this proves the assembly, so the only thing left for a
live run is the gated store work.

Invariants, failure mode first:

  carrier reaches the running app — the one that is easiest to get silently wrong. `aria/web_bff` loads
        `www/bff/main.py` under a unique module name and caches it; a plain `import main` yields a different
        object, so setting `_RESPOND_CARRIER` on it would wire a module the app never reads. The chat would
        stay dark with no error anywhere.
  no invented secret  — both ends derive the ground key from `root_secret`; a generated one builds a host
        that only talks to itself and looks fine, because one process is both ends.
  honest degrade      — no `respond_store` ⇒ the computed null, never a fabricated answer.
  clean stop          — the loop stops and the previous carrier is restored; a dead carrier left behind makes
        the bff call into a stopped loop, which blocks rather than reporting offline (a hang reads as a slow
        answer, not a stopped service).
  no listener         — assembly must not bind a port, or none of the above is testable in-process.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "agience_chorus"
# The package root. Personas are `agience_chorus.<persona>` subpackages now, not bare
# directories under `src/` — the assertion below caught exactly that move.
assert (_SRC / "aria").is_dir(), (
    "_SRC resolved to %s, which holds no personas — this file moved and parents[] is now "
    "wrong (the silent-vacuous-pass shape this workspace has been bitten by twice)" % _SRC)
for _p in (str(_SRC), str(_SRC / "aria")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT = b"fleet-root-secret"


def _store(tmp_path, name="ground.db"):
    """A real lattice — the shared ground. Never node 71: this is a temp path by construction."""
    from mantle.db import open_lattice
    L = open_lattice(str(tmp_path / name), origin="test-node")
    L.artifacts.ensure_schema()
    return L


def _lc(_store_obj, principal):
    """Stand-in for the grant light-cone — the gated piece. `ReachHost` documents `reach` as injectable so
    the wiring is testable without live grants; production leaves it None and `mantle.db.access` decides."""
    return {"op.respond", "op.retrieve"}


def _build(tmp_path, **kw):
    from agience_chorus import live_service
    return live_service.build_live(_store(tmp_path), root_secret=ROOT, reach=_lc, **kw)


# ── no invented secret ────────────────────────────────────────────────────────────────────────────
def test_a_missing_root_secret_is_refused(tmp_path):
    """Failure mode: generating one. A host would then talk only to itself and look correct, because a single
    process is both ends of the reach."""
    from agience_chorus import live_service
    for bad in (None, b"", 0):
        with pytest.raises(ValueError, match="root_secret"):
            live_service.build_live(_store(tmp_path), root_secret=bad)


# ── carrier reaches the running app ───────────────────────────────────────────────────────────────
def test_the_carrier_is_set_on_the_module_the_app_actually_reads(tmp_path):
    """The load-bearing check. Asserted through `aria.web_bff._load_bff_module()` — the same object the running
    app was built from — not through a fresh `import main`, which would be a different module and would let
    a broken wiring pass."""
    from agience_chorus.aria import web_bff
    svc = _build(tmp_path, respond_store=None)
    bff = web_bff._load_bff_module()

    assert getattr(bff, "_RESPOND_CARRIER", None) is None, "the bff should start DARK"
    with svc:
        carrier = getattr(bff, "_RESPOND_CARRIER", None)
        assert isinstance(carrier, dict) and callable(carrier.get("respond")), \
            "the respond carrier was not wired onto the loaded bff module"
        # And the bff's own accepter must accept it — otherwise we wired a shape it rejects.
        assert bff._respond_carrier() is not None, \
            "the bff refused the carrier shape we installed (see main.py's two accepted shapes)"


def test_the_bff_reports_dark_before_and_after_the_service_runs(tmp_path):
    """Failure mode: a carrier left behind on stop. `_respond_carrier()` must go back to None, or the bff
    calls into a stopped loop and blocks instead of answering offline."""
    from agience_chorus.aria import web_bff
    bff = web_bff._load_bff_module()
    svc = _build(tmp_path, respond_store=None)

    assert bff._respond_carrier() is None
    svc.start()
    assert bff._respond_carrier() is not None
    svc.stop()
    assert bff._respond_carrier() is None, "stop() left a dead carrier on the bff"


def test_stop_restores_a_pre_existing_carrier_rather_than_clearing_it(tmp_path):
    """Failure mode: clobbering a carrier someone else installed. Restore, don't delete."""
    from agience_chorus.aria import web_bff
    bff = web_bff._load_bff_module()
    sentinel = {"respond": lambda q: {"answer": "pre-existing"}}
    bff._RESPOND_CARRIER = sentinel
    try:
        with _build(tmp_path, respond_store=None):
            assert bff._RESPOND_CARRIER is not sentinel
        assert bff._RESPOND_CARRIER is sentinel, "stop() did not restore the previous carrier"
    finally:
        bff._RESPOND_CARRIER = None


# ── honest degrade ────────────────────────────────────────────────────────────────────────────────
def test_without_a_respond_store_the_answer_is_the_computed_null(tmp_path):
    """Failure mode: a fabricated reply. §0.1.1 requires the WordNet `respond_store`; absent it, the provider
    must return `answer=None` and echo the query — never invented prose."""
    with _build(tmp_path, respond_store=None) as svc:
        ev = svc.host.respond("what is a dog")
    assert ev is not None, "the reach did not complete at all — the wiring, not the substrate, is broken"
    assert ev.get("answer") is None, "an unwired host FABRICATED an answer: %r" % (ev,)
    assert ev.get("grounded") is False


def test_build_reports_what_it_wired_instead_of_implying_a_working_chat(tmp_path):
    """Failure mode: a service that looks live because it started. `wired` is the honest inventory — and
    `grants: True` means the real light-cone is in charge (i.e. `reach` was not injected)."""
    svc = _build(tmp_path, respond_store=None, corpus=None)
    assert svc.wired == {"respond": False, "retrieve": False, "grants": False}, \
        "wired must report the injected-reach case as grants=False: %r" % (svc.wired,)

    from agience_chorus import live_service
    real = live_service.build_live(_store(tmp_path, "g2.db"), root_secret=ROOT)   # reach=None
    assert real.wired["grants"] is True, "with no injected reach, the real mantle.db.access light-cone decides"


# ── lifecycle ─────────────────────────────────────────────────────────────────────────────────────
def test_start_and_stop_are_idempotent_and_leave_no_loop_running(tmp_path):
    """Failure mode: a leaked pump thread outliving the service — the exact thing `ReachHost`'s own
    context-manager test pins, re-asserted at the service layer that owns the lifetime."""
    svc = _build(tmp_path, respond_store=None)
    svc.start(); svc.start()                       # idempotent: a second start must not spawn a 2nd thread
    assert svc.started is True
    assert svc.host.loop.running is True, "the pump loop did not start"   # `running` is a property

    svc.stop(); svc.stop()                         # idempotent
    assert svc.started is False
    assert svc.host.loop.running is False, "a pump thread outlived the service"


def test_assembly_binds_no_port(tmp_path):
    """Failure mode: `build_live` opening a listener, which would make every test above need a free port and
    would put the assembly one step from pointing at 71. Binding is the bring-up script's job."""
    src = (_SRC / "live_service.py").read_text(encoding="utf-8")
    for forbidden in ("uvicorn.run", ".serve(", "socket.socket", "bind("):
        live = [ln for ln in src.splitlines()
                if forbidden in ln and not ln.lstrip().startswith("#")]
        assert not live, "live_service binds/serves a port (%r): %r" % (forbidden, live)


def test_the_app_is_arias_own_bff_app(tmp_path):
    """Failure mode: handing back a different app than the one the carrier was wired into."""
    from agience_chorus.aria import web_bff
    svc = _build(tmp_path, respond_store=None)
    assert svc.app is web_bff.bff_app(), "the service's app is not aria's bff app"
