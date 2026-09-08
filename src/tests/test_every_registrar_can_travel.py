"""disk → declared: can every capability this repo defines actually travel?

`agience-cloud/deploy/test_bundles_are_what_they_claim.py` checks declared→shipped and
shipped→declared; `test_persona_bundle_conversion_status.py` checks declared→claimed. None of them
asks the question from the tree's side: a module that mints operator offers but rides in no bundle
group cannot reach a node — its capabilities exist only where the source happens to be, which is
the one place nobody deploys to.

[[gate-list-needs-three-directions]] — the declared→reality direction is the one that always gets
written, and the other two are where the defects live.

The tree is clean, with exactly one known exception, named below. This gate exists so that stays
true: a new organon that never reaches `bundle_spec.json`, or the exception quietly growing a
sibling, fails here.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]
#: The spec names its modules WORKSPACE-relative (`agience-chorus/src/...`), so the root they
#: resolve against is named here rather than derived from a neighbouring path. It used to be spelled
#: `BUNDLES.parent`, which was the workspace only while `BUNDLES` pointed at a sibling repository —
#: when the payloads moved into this one that silently became `agience-chorus`, every module
#: resolved to a path that does not exist, and the test reported all seventeen registrars as
#: unbundled. An implied root is the thing that broke; this is the explicit one.
WORKSPACE = SRC.parents[1]
BUNDLES = SRC / "agience_chorus" / "bundles"    # this repository's own payloads, inside the
#                                                package so the wheel carries them
SPEC = SRC / "agience_chorus" / "seraph" / "bundle_spec.json"   # ...and the declaration behind them

#: Known and deliberate, per `sage/recognition.py`'s own docstring: it is not wired into
#: `sage/manifest.py` because sage's registrars come from its five bundle groups
#: (`prism.runner.register_fns`), so advertising these through the manifest would mean a new bundle
#: group and a `bundle_spec.json` entry, not a new list element — a host that wants the offers
#: advertised calls this directly.
#:
#: It mints the offer artifacts for seven recognition capabilities (`op.seed`, `op.spread`,
#: `op.fire`, `op.propagate`, `op.frame`, `op.basis`, `op.coherent`). Listed here rather than
#: pattern-matched so the exception is argued, and so wiring it later shows up as a diff.
KNOWN_UNBUNDLED = {"agience_chorus/sage/recognition.py"}
#: Keyed relative to `SRC`, which is `src/` — so the package segment is part of the key. It was
#: `sage/recognition.py` while the tektons sat directly under `src/`.


def _spec_modules() -> set:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    return {(WORKSPACE / rel).resolve()
            for decl in spec.values() for rel in decl["modules"].values()}


def _mints_operator_offers(path: Path) -> list:
    """Functions that register capabilities — not merely functions named `register_*`.

    The name is not the test: `ophan/exchange.py:register_exchange` writes an exchange agreement
    artifact and registers no capability at all. What distinguishes a registrar is that it mints
    against `OPERATOR_CONTENT_TYPE`, so that is what is looked for.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    if "OPERATOR_CONTENT_TYPE" not in path.read_text(encoding="utf-8", errors="ignore"):
        return []
    return [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("register_")]


def _registrar_modules() -> dict:
    out = {}
    for path in SRC.rglob("*.py"):
        parts = set(path.parts)
        if {"__pycache__", "tests"} & parts or path.name.startswith("test_"):
            continue
        fns = _mints_operator_offers(path)
        if fns:
            out[path.resolve()] = fns
    return out


@pytest.mark.skipif(not SPEC.is_file(),
                    reason="src/agience_chorus/seraph/bundle_spec.json is missing from this repository")
def test_every_capability_module_RIDES_IN_A_BUNDLE():
    """A registrar outside every bundle group is a capability that cannot be deployed — it answers
    only where the source tree is.

    Fails if an organon is added and wired into a manifest without adding it to `bundle_spec.json`:
    the persona would register it locally and no node would ever receive it.
    """
    declared = _spec_modules()
    orphans = {}
    for path, fns in _registrar_modules().items():
        rel = path.relative_to(SRC).as_posix()
        if path not in declared and rel not in KNOWN_UNBUNDLED:
            orphans[rel] = fns
    assert not orphans, (
        "these modules mint operator offers but ride in NO bundle group, so their capabilities "
        "cannot travel to a node: %s. Add a `bundle_spec.json` entry, or name it in "
        "KNOWN_UNBUNDLED with the reason." % orphans)


@pytest.mark.skipif(not SPEC.is_file(), reason="src/agience_chorus/seraph/bundle_spec.json is missing from this repository")
def test_the_KNOWN_exception_still_exists_and_is_still_unbundled():
    """Keeps the exception honest: an allow-list that is never re-read becomes a place to hide
    things. If `sage/recognition.py` is ever wired into a bundle group, this fails and the entry
    must be removed, so the list can never quietly outlive its reason.

    Fails if the module is wired in and the exception is left behind, which would then mask a real
    orphan appearing at the same path.
    """
    declared = _spec_modules()
    for rel in sorted(KNOWN_UNBUNDLED):
        path = (SRC / rel).resolve()
        assert path.is_file(), (
            "%s is named as a known-unbundled module but no longer exists — remove the entry" % rel)
        assert _mints_operator_offers(path), (
            "%s no longer mints operator offers — it is not an exception to anything now" % rel)
        assert path not in declared, (
            "%s IS now in a bundle group. The exception has served its purpose: delete it from "
            "KNOWN_UNBUNDLED so a future orphan at this path is caught." % rel)


def test_THIS_GATE_CAN_ACTUALLY_FAIL():
    """Vacuity control. Every assertion above is over a discovered set; if discovery returned
    nothing they would all pass on an empty workspace.

    A detector that finds no registrars proves nothing about whether they can travel, so this
    proves discovery finds the real ones, and that the name-based shortcut that once produced a
    false positive stays rejected.
    """
    found = _registrar_modules()
    assert len(found) >= 5, "discovery found almost nothing — the gate above is vacuous: %s" % found

    # the false positive that taught the OPERATOR_CONTENT_TYPE discriminator
    exchange = (SRC / "agience_chorus" / "ophan" / "exchange.py")
    if exchange.is_file():
        assert exchange.resolve() not in found, (
            "ophan/exchange.py is back in the registrar set — it defines `register_exchange`, which "
            "writes an exchange AGREEMENT and registers no capability. The NAME is not the test.")
