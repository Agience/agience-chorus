"""seraph's operator manifest — the op.* this persona owns; no shared catalog. seraph owns
op.install (a true organon — installs signed-crystal bundles: verify sha + capability gate +
ground).

This persona travels as a bundle. A bundle group exists whenever its sha-verified payload exists —
`prism.runner` does not require the group name to be pre-declared in a fixed list — and `install` is
the group built from a spec entry, verified the same way as any other.

`seraph/install.py` is the authoritative source: `op.bundle.observe` (this persona's own organon, M3)
reads it at that exact path, and `op.bundle.condense` builds the `install` bundle from it. At runtime
this module asks `prism.runner` for the group's declared `register_fns`, and the runner

  * resolves the bundle from the store first (artifact `bundle-install`, the mesh path), then from a
    host-registered file, then from the shipped `agience-chorus/bundles/install.json`;
  * re-hashes the canonical payload and does not exec on a mismatch (`BundleIntegrityError`), nor on
    a payload that names a different group;
  * execs it into an isolated namespace `_agience_bundle_install_<sha12>` — never a same-named module
    that happens to be on `sys.path`.

`install` declares no host seam. seraph's organon reaches `prism.canonical` and `crystal.*`, both
installed packages, so nothing needs binding at boot. The seam leg is exercised by the `operators`
group (which declares `match`, filled by ember and deliberately left unfilled in chorus).

This manifest needs a bundle source at import: a store carrying `bundle-install`, a `register_group`
binding, or `AGIENCE_BUNDLE_ROOT` / this repository's own `bundles/`. With none, `register_fns`
raises and `chorus.personas._persona_manifest` logs the failure and yields an empty roster for
seraph. That is the mechanism being honest about a missing payload; it is not a fallback, and there
is deliberately no in-package copy to fall back to.
"""
from __future__ import annotations

from typing import Any, Dict, List

from crystal.manifest_base import collect as _collect, operators as _operators

from prism import runner as _runner

#: The bundle group carrying seraph's organon source. Named once; `register_fns` is what turns it
#: into callables, so this file transcribes no operator definition and no function name.
# Two groups: `install` (the consumer of the distribution path) and `bundling` (its producer —
# op.bundle.observe + op.bundle.condense). They belong to one persona because they are two halves of
# one act: seraph makes the payload a node can verify, and seraph is what verifies and grounds it.
# Splitting them would put the producer's contract and the consumer's check in two personas free to
# drift.
#
# The plural is the only declaration, deliberately. `test_..._every_payload_is_CLAIMED` reads this
# file's source and returns on the first match, so a lingering singular `BUNDLE_GROUP = "install"`
# above this line would shadow the tuple and `bundling` would read as an unclaimed payload — built,
# wired, registered, and reported as rotting. `INSTALL_GROUP` below is a plain name, not a second
# declaration.
BUNDLE_GROUPS = ("install", "bundling")
INSTALL_GROUP = BUNDLE_GROUPS[0]

# The register functions come from the bundle's own manifest (`register_fns`), sha-verified before
# any exec. Listing them here by name would be a second copy of a declaration that already travels
# with the code it describes.
REGISTRARS = [fn for _g in BUNDLE_GROUPS for fn in _runner.register_fns(_g)]


def collect(store: Any = None) -> int:
    return _collect(REGISTRARS, store)


def operators() -> List[Dict[str, Any]]:
    return _operators(REGISTRARS)


OPERATORS = operators()


def bundle_sha256() -> Dict[str, str]:
    """The sha per group of the bundles this process is actually running for seraph — a published
    stat, so a node can say which operator bytes it is serving rather than which it was configured
    to.

    A dict because seraph runs two groups, matching aria, sage and lumen. Returning one sha would
    publish `install`'s bytes as if they were seraph's, so the bundling tekton's bytes could change
    with the stat unmoved — and this persona is the one that verifies bundles, which makes a stat
    that cannot report its own producer worse here than anywhere else.
    """
    _loaded = _runner.loaded()
    return {g: _loaded[g]["sha256"] for g in BUNDLE_GROUPS}


def bundle_origin() -> Dict[str, str]:
    """Where each of those bundles came from: ``"store"`` (the mesh path), ``"host"`` (a registered
    file), or ``"shipped"``. Per group, for the same reason as `bundle_sha256`."""
    _loaded = _runner.loaded()
    return {g: _loaded[g]["origin"] for g in BUNDLE_GROUPS}


__all__ = ["OPERATORS", "REGISTRARS", "BUNDLE_GROUPS", "INSTALL_GROUP", "collect", "operators",
           "bundle_sha256", "bundle_origin"]
