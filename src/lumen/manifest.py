"""lumen's operator manifest — the op.* this persona owns, declared by the persona itself.

Operator definitions are not a shared crystal catalog: each persona owns its organons' code and
its own manifest. `OPERATORS` is the list of operator-definition artifacts lumen offers, produced
by running its own organons' register functions against a capture — the register fn is the source
of truth for the definition, never transcribed. The chorus host registers each persona's manifest
to Mantle per-persona (see `chorus.operator_manifests`).

This persona travels as bundles, and takes more than one group: five, all declared the same way
(`bundle_spec.json` + `build_bundles.py`, no prism edit needed to add one), so nothing here is
imported by bare name and a developer copying this file learns the mechanism rather than a
`sys.path` trick.

The organon files under `src/lumen/` remain the authoritative source — `op.bundle.observe`
(seraph's organon, M3) reads each at its exact path. At runtime, the runner resolves each group
from the store first (artifact `bundle-<group>`, the mesh path), then a host-registered file, then
the shipped `agience-chorus/bundles/<group>.json`; it re-hashes the canonical payload and raises
`BundleIntegrityError` on any mismatch, executing into an isolated namespace
`_agience_bundle_<group>_<sha12>` — never a same-named module that happens to be on `sys.path`.

None of lumen's five groups declares a host seam: the organons reach `crystal.*` (including
`crystal.ontology`), `prism.*`, `ember.optics`, numpy and httpx, all installed packages, so nothing
needs binding at boot. The seam leg is exercised by the
`operators` group (which declares `match`, filled by ember and deliberately left unfilled in
chorus).

This manifest needs a bundle source at import — a store carrying the `bundle-<group>` artifacts,
`register_group` bindings, or `AGIENCE_BUNDLE_ROOT` / this repository's own `bundles/`. With
none, `register_fns` raises and `chorus.personas._persona_manifest` logs the failure and yields an
empty roster for lumen: the mechanism reporting a missing payload honestly, with no in-package
copy to fall back to.
"""
from __future__ import annotations

from typing import Any, Dict, List

from crystal.manifest_base import collect as _collect, operators as _operators

from prism import runner as _runner

# lumen owns: op.reason (instrument reasoning), op.math.* (arithmetic), op.check.* (verification
# wedge), op.curriculum.certify (the level certificate — curriculum is lumen's declared domain),
# op.dev.* (the copilot's real-world fs/git hands — a true organon). op.retrieve is sage's; lumen
# reaches it, so it is not in lumen's manifest.
#
#: The bundle groups carrying lumen's organon source, one per register group, which is what a
#: bundle is. Named once here; `register_fns` is what turns each into callables, so this file
#: transcribes no operator definition and no function name.
BUNDLE_GROUPS = ("reasoning", "arithmetic", "check", "curriculum", "dev_ops")

# The register functions come from each bundle's own manifest (`register_fns`), sha-verified
# before any exec. Listing them here by name would be a second copy of a declaration that already
# travels with the code it describes.
REGISTRARS = [fn for _g in BUNDLE_GROUPS for fn in _runner.register_fns(_g)]


def collect(store: Any = None) -> int:
    """Register every operator this persona owns into `store`; returns the count (host uses this against
    a Mantle-backed client at startup)."""
    return _collect(REGISTRARS, store)


def operators() -> List[Dict[str, Any]]:
    return _operators(REGISTRARS)


OPERATORS = operators()


def bundle_sha256() -> Dict[str, str]:
    """The shas of the bundles this process is actually running for lumen, per group — a published
    stat, so a node can say which operator bytes it is serving rather than which it was configured
    to. Plural where astra's and seraph's are singular, because lumen genuinely rides five groups
    and collapsing them to one number would report a thing that does not exist."""
    _loaded = _runner.loaded()
    return {g: _loaded[g]["sha256"] for g in BUNDLE_GROUPS}


def bundle_origin() -> Dict[str, str]:
    """Where each of those bundles came from: ``"store"`` (the mesh path), ``"host"`` (a registered
    file), or ``"shipped"``."""
    _loaded = _runner.loaded()
    return {g: _loaded[g]["origin"] for g in BUNDLE_GROUPS}


__all__ = ["OPERATORS", "REGISTRARS", "BUNDLE_GROUPS", "collect", "operators",
           "bundle_sha256", "bundle_origin"]


# ── the crystal ──────────────────────────────────────────────────────────────────────────────────
# lumen is a crystal: "lumen" is a stage name; the thing itself is a crystal — facets (conduits),
# tektons (condensors), organons (real-world instruments). Declared here because this file is
# already the roster source of truth for what this component owns.
#
# Nothing here is invented: every tekton below is an operator this persona already registers
# (`REGISTRARS` above), and `op.respond` is the conversation tekton `reach_provider` already serves.
CRYSTAL: Dict[str, Any] = {
    "name": "lumen",

    # A crystal with no facet is sealed glass. lumen's conduit is the reach: a need arrives on the
    # ground plane and evidence leaves the same way. `both`, because the same conduit carries the
    # signal in and the condensed answer out.
    "facets": [
        {"name": "reach", "direction": "both",
         "content_type": "application/vnd.agience.need+json"},
    ],

    # The condensors. `domain` is what the tekton is tuned to — the band it absorbs.
    "tektons": [
        {"name": "op.respond", "domain": "conversation"},
        {"name": "op.reason",  "domain": "trajectory"},
        {"name": "op.math",    "domain": "arithmetic"},
        {"name": "op.check",   "domain": "verification"},
        {"name": "op.dev",     "domain": "code"},
    ],

    # The real-world instruments. `op.dev.*` is a true organon — it reaches outside this process,
    # so it is capability-gated: `activates_on(prism)` will not ground it on a prism that does not
    # advertise these. Everything else lumen does is a read over its own store and needs nothing.
    #
    # `op.dev.git` / `run_tests` spawn a process, and `prism/capabilities.py` has no capability kind
    # for that — the vocabulary is fs.* / net.* / compute.* / store.* / ui.render / human.ask /
    # sensor.* / actuator.*. The process-spawning organon is left out of this list rather than
    # declared under a capability kind that misstates what it does: nothing gates it, which is more
    # honest than gating it under the wrong name. Adding a `proc.spawn` kind is a prism decision.
    "organons": [
        {"name": "op.dev.fs", "requires": ["fs.read", "fs.write"]},
    ],

    "created_by": "connect@agience.ai",
}
