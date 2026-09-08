"""iris's operator + facet manifest — the op.* and views this persona owns.

iris (routing & communication / courier) owns op.comms.* — the guardian-to-guardian message primitives.
These are true organons: they reach the real world (the message plane / carriers across substrates).

MCP is an adapter here, not a layer. `op.mcp.call` is the tekton — it absorbs an MCP `tools/call` need
and removes it from propagation — and the `mcp` entry in `FACETS` is the view that presents the
resulting evidence. `beam/mcp_bridge.py` is thereby the transport detail behind the tekton rather than a
concept anybody names.

This persona travels as a bundle. `prism.runner._BundleFinder` serves `pkg` as a package and
`pkg.<module>` for every module in the payload, so a bundle module's `__package__` is the bundle
package and a one-level relative import (`from .message import Message`) resolves inside the bundle by
construction. What a flat payload cannot carry is a sub-package (`pkg.a.b`), and `iris/comms` has none:
seven modules, every relative import one level deep, no `__file__` or `__path__` read anywhere.
`comms/__init__.py` rides as the entry module named `comms`.

The package in the payload is real implementation only — no re-export shims. `crystal_comms.py` and
`__main__.py` are not in the payload: neither is reachable from the entry module (`__main__` is the
`python -m comms` CLI and `crystal_comms` has no importer), and a bundle carries the entry module plus
its impl-internal deps, not every file that happens to sit in the directory.

The files under `src/iris/comms/` remain the authoritative source — `op.bundle.observe` (seraph's
organon, M3) reads each at its exact path. The runtime reach differs: the runner resolves the group from
the store first (artifact `bundle-comms`), then a host-registered file, then the shipped
`agience-chorus/bundles/comms.json`; it re-hashes the canonical payload and refuses to exec on any
mismatch (`BundleIntegrityError`), and execs into `_agience_bundle_comms_<sha12>`.

The isolation is load-bearing here, not decorative: `comms/operators.py` and `sage/operators.py` are two
different files with the same basename. Inside the bundle, `operators` resolves under the bundle package
name and nowhere else; `bundle_spec.json` pins the source path rather than searching by basename, so
neither file can stand in for the other.

`comms` declares no host seam: it reaches `prism.plane`/`carriers`/`streams`/`reach`/`mcp_bridge`,
`crystal`, and (lazily) `mantle.db`, all installed packages, so nothing needs binding at boot.

Consequence for a deployment: this manifest needs a bundle source at import — a store carrying
`bundle-comms`, a `register_group` binding, or `AGIENCE_BUNDLE_ROOT` / a sibling `agience-observe`
checkout. With none, `register_fns` raises and `chorus.personas._persona_manifest` logs the failure and
yields an empty roster for iris. There is no in-package fallback.
"""
from __future__ import annotations

from typing import Any, Dict, List

from crystal.manifest_base import collect as _collect, operators as _operators

from prism import runner as _runner

#: The bundle group carrying iris's organon source. Named once; `register_fns` is what turns it into
#: callables, so this file transcribes no operator definition and no function name.
BUNDLE_GROUP = "comms"

REGISTRARS = _runner.register_fns(BUNDLE_GROUP)

#: The MCP tekton id, read from the loaded bundle rather than re-typed here. `FACETS` below links the
#: `mcp` view to its condensor by this name, and a transcribed copy is how a view ends up pointing at a
#: tekton that no longer exists.
MCP_CALL = _runner.load(BUNDLE_GROUP).MCP_CALL

# Declarative source-of-truth for the host→facet router, and load-bearing: `crystal/host.py`'s
# host-header routing reads these `subdomains`, carried through by `personas.PersonaBinding.facets`.
# A facet is a view; this one's far side is an MCP client rather than a browser, which is why MCP
# needed no layer of its own — `direction: "both"` because a `tools/call` carries the signal in and
# its result back out.
# No `dist`: this facet renders no static bundle. It is the protocol view of the tekton, so the
# entry carries `bff_tekton` and nothing else — declaring an empty `dist` would make the router try
# to mount a directory that does not exist.
FACETS: List[Dict[str, Any]] = [
    {
        "name": "mcp",
        "persona": "iris",
        "direction": "both",
        "content_type": "application/json",   # discovery hint, never a gate
        "subdomains": ["mcp", "iris"],
        "bff_tekton": MCP_CALL,               # the tekton behind the view
    },
]


def facets() -> List[Dict[str, Any]]:
    """iris's facet manifest — the roster source of truth for this persona's views."""
    return FACETS


def collect(store: Any = None) -> int:
    return _collect(REGISTRARS, store)


def operators() -> List[Dict[str, Any]]:
    return _operators(REGISTRARS)


OPERATORS = operators()


def bundle_sha256() -> str:
    """The sha of the bundle this process is actually running for iris — a published stat, so a node
    can say which operator bytes it is serving rather than which it was configured to."""
    return _runner.loaded()[BUNDLE_GROUP]["sha256"]


def bundle_origin() -> str:
    """Where that bundle came from: ``"store"`` (the mesh path), ``"host"`` (a registered file), or
    ``"shipped"``."""
    return _runner.loaded()[BUNDLE_GROUP]["origin"]


__all__ = ["OPERATORS", "REGISTRARS", "BUNDLE_GROUP", "MCP_CALL", "collect", "operators",
           "FACETS", "facets", "bundle_sha256", "bundle_origin"]
