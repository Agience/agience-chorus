"""One phase of the recognition-tekton proof, run as its own process. `argv: <phase> <tmpdir>`.

Each phase is a separate process, which is the measurement itself rather than test hygiene: the
claim under test is that a chain stage discharges in a process where ember is not importable. A host
seam resolves in-process, so running the requester and the provider as two objects in one
interpreter would prove nothing — the seam would simply resolve. Splitting them across processes,
with `ember` blocked at the meta-path on the requester side, is what makes the wire load-bearing.
`prism.carriers.StoreCarrier` is store-and-forward over a lattice, so the phases are also
sequential: place, then provide, then collect. No concurrency is needed to cross a process boundary.

Keeping the ontology out of the suite's process matters too: `_install_offline_wordnet` installs a
process-global index and rebinds `crystal.ontology.driver`'s module state. Doing that inside the
chorus test process would leak into every later test in the run. Here it dies with the phase.

Phases:
  control   — ember blocked: the blocker bites and the seam is unfilled (the control)
  place     — ember blocked: place needs on the plane for the chain capabilities
  provide   — ember present: serve the tektons, pump the carrier, and measure persistence
  collect   — ember blocked: pick the fields up off the ground by provenance
  refuse    — ember blocked: a refusal reads as a refusal, never an empty field
  paths     — ember present: measure whether seed→spread, fire, and recognize agree
  allcaps   — ember present: exercise all seven capabilities, and report which answer and which
              refuse
"""
from __future__ import annotations

import json
import os
import sys

# Self-locating, so nothing has to hand this process a PYTHONPATH. `src/` is where `_host_seams`
# and `reach_wiring` live; `src/sage/` is what makes `import recognition` resolve the way the persona
# host mounts it. Deriving both from `__file__` keeps the invocation `python <this file> <phase>`.
_TESTS = os.path.dirname(os.path.abspath(__file__))
_SAGE = os.path.dirname(_TESTS)
_SRC = os.path.dirname(_SAGE)
for _p in (_SAGE, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT_SECRET = b"genesis-fleet-root"
GRANT_CT = "application/vnd.agience.grant+json"
QUERY = "what is a dog"


class _BlockEmber:
    """A meta-path finder that blocks `ember`, at any depth.

    Inserted at `sys.meta_path[0]`, so it is consulted before every other finder — including the one
    that would find an editable install. It raises rather than returning `None`, because returning
    `None` only means "I cannot find it" and the next finder would then succeed."""

    def find_module(self, name, path=None):        # legacy protocol, still consulted by some loaders
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        if name == "ember" or name.startswith("ember."):
            raise ImportError("ember is blocked at the meta-path: %r" % name)
        return None


def _block_ember() -> str:
    """Install the blocker and confirm it bites. Returns the exception type name it raised.

    This control runs first, and its failure is fatal: a blocker that silently did not fire would
    make every assertion below pass against a process that had ember all along, and a check that
    cannot fail proves nothing."""
    sys.meta_path.insert(0, _BlockEmber())
    for mod in [k for k in list(sys.modules) if k == "ember" or k.startswith("ember.")]:
        del sys.modules[mod]
    try:
        import ember  # noqa: F401  (the control: this line must raise)
    except ImportError as exc:
        return type(exc).__name__
    raise AssertionError("the ember blocker did not bite: `import ember` succeeded")


def _seam_state() -> str:
    """What `seam("match")` does in this process — the measurement the tekton exists to answer."""
    from _host_seams import HostSeamUnfilled, seam
    try:
        seam("match").tekton_basis_for
    except HostSeamUnfilled as exc:
        return type(exc).__name__
    except ImportError as exc:
        return type(exc).__name__
    return "RESOLVED"


def _store(tmp: str):
    from mantle.db import open_lattice
    return open_lattice(os.path.join(tmp, "plane.db"), origin="test")


def _emit(payload) -> None:
    print("PROBE " + json.dumps(payload))


# ── ember-present phases ───────────────────────────────────────────────────────────────────────────
def _install_ontology() -> bool:
    """Reuse ember's own offline WordNet fixture rather than writing a second one.

    It is located from `ember.__file__` rather than a relative path, because this file runs from a
    subprocess whose cwd is not fixed, and a second copy of a 100-line extraction would duplicate a
    fixture that already exists."""
    import ember
    tests = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ember.__file__))), "tests")
    if tests not in sys.path:
        sys.path.insert(0, tests)
    from _fakes import _install_offline_wordnet
    return bool(_install_offline_wordnet())


def _grant_all(store, principal: str, caps) -> None:
    """Mint the read grants that put these capabilities in `principal`'s light-cone.

    Called before the provider is constructed: `Provider.__init__` snapshots
    `lightcone.reaches(principal)`, so a grant minted afterwards is invisible and the symptom is
    silence rather than an error."""
    for cap in list(caps) + ["ground"]:
        store.artifacts.put_artifact({
            "id": "grant." + cap, "content_type": GRANT_CT, "state": "active",
            # `effect` is half the authority: `entities.grant.mask_of` reads the CRUDEASIO bits for
            # WHICH action and this for whether the grant authorizes at all, matched positively so
            # an absent or unrecognized value confers nothing.
            "effect": "allow",
            "grantee_id": principal, "grantee_type": "user", "can_read": True,
            "resource_id": cap})


def phase_provide(tmp: str) -> None:
    if not _install_ontology():
        _emit({"phase": "provide", "skipped": "no offline wordnet"})
        return
    import ember  # noqa: F401  — the host: importing it binds the seams (ember/runtime/seams.py)
    import recognition
    from prism.carriers import StoreCarrier

    store = _store(tmp)
    _grant_all(store, "sage", recognition.RECOGNITION_CAPS)
    carrier = StoreCarrier(store)
    reactor = recognition.serve_recognition(store, root_secret=ROOT_SECRET, fallback=carrier)
    reactor.pump(carrier)

    # Persistence, measured rather than asserted from the code: the same need, taken twice.
    # `list_artifacts` yields — counting the rows is the measurement, so it is drained, not len()'d.
    rows = lambda: sum(1 for _ in store.artifacts.list_artifacts(
        content_type=recognition.RECOGNITION_CT))
    handler = recognition.recognition_handlers(store)[recognition.GROUND_CAP]
    # A fresh input, so "+1 then no second row" is unambiguous. `QUERY` was already measured by the
    # pump above, and re-taking it is a separate claim (below) rather than the same one.
    fresh = "why is the sky blue"
    before = rows()
    first = handler({"text": fresh})
    mid = rows()
    second = handler({"text": fresh})
    after = rows()
    # And the input the pump already measured, taken again here through a different code path: the
    # address must be the one already on the ground, and the row count must not move.
    repeat = handler({"text": QUERY})
    replayed = rows()
    _emit({"phase": "provide", "seam": _seam_state(), "rows_before": before, "rows_mid": mid,
           "rows_after": after, "rows_replayed": replayed,
           "address_1": first.get("tekton"), "address_2": second.get("tekton"),
           "address_pumped": repeat.get("tekton"),
           "field_size": len(first.get("field") or {}), "scales": first.get("scales"),
           "corpus": first.get("corpus")})


def phase_paths(tmp: str) -> None:
    """Do the three recognition paths agree? §5 says freezing them into one capability would make the
    disagreement a wire contract, so the split is measured here rather than assumed."""
    if not _install_ontology():
        _emit({"phase": "paths", "skipped": "no offline wordnet"})
        return
    import ember  # noqa: F401
    import recognition
    from _host_seams import resolve as seam

    store = _store(tmp)
    activation, match = seam("activation"), seam("match")
    seeded = recognition.seed(QUERY)
    spread = recognition.spread(seeded)
    fired = recognition.fire(QUERY, store)
    rows = activation.recognize(store, QUERY) or []
    recognized = [(r.get("concept") or r.get("name") or r.get("synset") or r.get("id"))
                  for r in rows if isinstance(r, dict)]
    shared = set(spread) & set(fired)
    union = set(spread) | set(fired)
    _emit({"phase": "paths", "seed": sorted(seeded), "spread": sorted(spread),
           "fire": sorted(fired), "recognize": [c for c in recognized if c][:20],
           "recognize_keys": sorted(rows[0]) if rows and isinstance(rows[0], dict) else [],
           "spread_top": sorted(spread, key=spread.get, reverse=True)[:3],
           "fire_top": sorted(fired, key=fired.get, reverse=True)[:3],
           "jaccard": (len(shared) / len(union)) if union else None,
           "xi": match.xi(), "gap": match.propagation_floor()})


# ── ember-blocked phases ───────────────────────────────────────────────────────────────────────────
def phase_control(tmp: str) -> None:
    blocked = _block_ember()
    import recognition  # noqa: F401  — the tekton module itself must import with ember unreachable
    _emit({"phase": "control", "import_ember": blocked, "seam": _seam_state(),
           "recognition_imported": True})


def _requester(tmp: str):
    from prism.carriers import StoreCarrier
    from reach_wiring import reactor
    store = _store(tmp)
    carrier = StoreCarrier(store)
    return reactor(store, "lumen", root_secret=ROOT_SECRET, fabric=None,
                   fallback=carrier), carrier


def phase_place(tmp: str) -> None:
    blocked = _block_ember()
    import recognition
    rq, _carrier = _requester(tmp)
    # `op.ground` is the one published capability that returns a field, and a field crossing a
    # process boundary is what this phase exists to prove. `op.seed` / `op.fire` are internal
    # stages, so a need placed on one would test an unregistered name rather than the plane. The
    # remaining published caps answer about a field
    # (`op.frame` returns a frame, `op.propagate` a scalar pair), so they cannot stand in here.
    handles = {recognition.GROUND_CAP: rq.reach({"text": QUERY}, to=recognition.GROUND_CAP)}
    json.dump(handles, open(os.path.join(tmp, "handles.json"), "w"))
    _emit({"phase": "place", "import_ember": blocked, "seam": _seam_state(), "handles": handles})


def phase_collect(tmp: str) -> None:
    blocked = _block_ember()
    handles = json.load(open(os.path.join(tmp, "handles.json")))
    rq, carrier = _requester(tmp)
    rq.pump(carrier)                              # no providers here — this only absorbs the ground
    out = {}
    for cap, handle in handles.items():
        ev = rq.evidence(handle)
        out[cap] = None if ev is None else {
            "capability": ev.get("capability"), "field_size": len(ev.get("field") or {}),
            "field_sample": sorted((ev.get("field") or {}))[:5], "scales": ev.get("scales"),
            "corpus": ev.get("corpus"), "tekton": ev.get("tekton"),
            "provenance": rq.provenance(handle)}
    _emit({"phase": "collect", "import_ember": blocked, "seam": _seam_state(), "evidence": out})


def phase_refuse(tmp: str) -> None:
    """A node that cannot measure refuses, in both of the shapes it has available."""
    blocked = _block_ember()
    import recognition
    store = _store(tmp)

    def _raises(fn):
        try:
            fn()
        except recognition.RecognitionUnavailable as exc:
            return {"raised": "RecognitionUnavailable", "says": str(exc)[:400]}
        except Exception as exc:                  # OntologyStoreRequired is also a refusal, by name
            return {"raised": type(exc).__name__, "says": str(exc)[:400]}
        return {"raised": None}

    # On the plane, the same conditions must discharge nothing, never `{}`.
    handlers = recognition.recognition_handlers(store)
    _emit({"phase": "refuse", "import_ember": blocked, "seam": _seam_state(),
           "fire_no_store": _raises(lambda: recognition.fire(QUERY, None)),
           "fire_no_host": _raises(lambda: recognition.fire(QUERY, store)),
           "seed_no_host": _raises(lambda: recognition.seed(QUERY)),
           "extent_no_host": _raises(recognition.corpus_extent),
           # The seam refusal on its own, with the ontology question factored out: this is the
           # one that must be `RecognitionUnavailable` and not an ImportError wearing its name.
           "physics_no_host": _raises(lambda: recognition._physics("match")),
           "handler_ground": handlers[recognition.GROUND_CAP]({"text": QUERY}),
           "handler_fire": handlers[recognition.FIRE_CAP]({"text": QUERY})})


def phase_allcaps(tmp: str) -> None:
    """Every capability, exercised against a real ontology, to see which ones actually answer.

    The two proven over the plane are not evidence about the rest: `op.ground` and `op.frame` are
    the cheapest pair to carry end to end, and a suite that stopped there would report every
    capability on the strength of two. Each is invoked through its own handler here — the same
    callable the provider serves — and what it returned is reported rather than asserted, so a
    capability that refuses is named instead of hidden.

    A `None` here is a refusal and is reported as one. `op.frame`/`op.coherent` read the corpus
    projection basis, which an offline index does not carry; whether that is a refusal or an answer
    is what this phase measures rather than assumes."""
    if not _install_ontology():
        _emit({"phase": "allcaps", "skipped": "no offline wordnet"})
        return
    import ember  # noqa: F401
    import recognition

    store = _store(tmp)
    recognition.register_recognition_operators(store)     # the offer artifacts op.basis reads
    handlers = recognition.recognition_handlers(store)
    seeded = recognition.seed(QUERY)
    needs = {
        recognition.GROUND_CAP: {"text": QUERY},
        recognition.PROPAGATE_CAP: {"field": seeded, "targets": ["dog.n.01", "tree.n.01"]},
        recognition.FRAME_CAP: {"names": ["dog.n.01", "cat.n.01", "tree.n.01"]},
        recognition.BASIS_CAP: {"operator": recognition.GROUND_CAP},
        recognition.COHERENT_CAP: {"names": ["dog.n.01", "cat.n.01", "tree.n.01"]},
    }
    out = {}
    for cap, need in needs.items():
        try:
            ev = handlers[cap](need)
        except Exception as exc:                       # a defect, not a refusal — report it as one
            out[cap] = {"raised": type(exc).__name__, "says": str(exc)[:200]}
            continue
        if ev is None:
            out[cap] = {"refused": True}
            continue
        out[cap] = {"keys": sorted(ev), "tekton": ev.get("tekton"),
                    "field_size": len(ev.get("field") or {}) if "field" in ev else None,
                    "energy": ev.get("energy"), "distance": ev.get("distance"),
                    "readable": ev.get("readable"), "grounded": ev.get("grounded"),
                    "coherent": ev.get("coherent")}
    _emit({"phase": "allcaps", "capabilities": out})


PHASES = {"control": phase_control, "place": phase_place, "provide": phase_provide,
          "collect": phase_collect, "refuse": phase_refuse, "paths": phase_paths,
          "allcaps": phase_allcaps}

if __name__ == "__main__":
    PHASES[sys.argv[1]](sys.argv[2])
