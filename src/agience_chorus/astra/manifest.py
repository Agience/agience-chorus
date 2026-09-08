"""astra's operator manifest — the op.* this persona owns. astra owns op.fetch.get (a true organon —
external network GET, a real-world interface).

astra travels as a bundle. `astra/fetch.py` is the authoritative source — `op.bundle.observe`, the
organon on seraph, reads it at that exact path, and `op.bundle.condense` builds the `fetch` bundle
from it (`agience-observe/build_bundles.py` is a CLI over those). This module does not `import fetch`;
it asks `prism.runner` for the `fetch` group's declared `register_fns`, and the runner:

  * resolves the bundle from the store first (artifact `bundle-fetch`, the mesh path) and only then
    from the shipped `agience-chorus/bundles/fetch.json`;
  * re-hashes the canonical payload and raises on any mismatch (`BundleIntegrityError`);
  * execs the modules into an isolated namespace `_agience_bundle_fetch_<sha12>`, where the bundle's
    own modules resolve by relative import and any declared host seam resolves to the module the
    host registered — never to a same-named module that happens to be on `sys.path`.

Nothing is imported by bare name here: `src/astra/` is not on `sys.path` under a bare `pytest`
(`pytest.ini` puts only `src`), so `import astra.manifest` needs no path trick to succeed. See
`src/astra/tests/test_manifest_is_a_bundle.py` — the assertion is that the load works with the
persona dir absent from the path.

`fetch` declares no host seam (`host_seams: []` in `bundle_spec.json`) — astra's organon reaches
only `crystal.evolution`, an installed package, so it needs nothing bound at boot. The seam leg of
the mechanism is exercised by the `operators` group, which declares `match`; ember fills it in
`ember/runtime/runner.py` and chorus deliberately leaves it unfilled.

This manifest needs a bundle source at import: a store carrying `bundle-fetch`, or
`AGIENCE_BUNDLE_ROOT` / this repository's own `bundles/`. With neither, `register_fns` raises and
`chorus.personas._persona_manifest` logs the failure and yields an empty roster for astra. There is
deliberately no in-package copy to fall back to.
"""
from __future__ import annotations

from typing import Any, Dict, List

from crystal.manifest_base import collect as _collect, operators as _operators

from prism import runner as _runner

#: The bundle group carrying astra's organon source. Named once; `register_fns` is what turns it
#: into callables, so this file transcribes no operator definition and no function name.
BUNDLE_GROUP = "fetch"

# ── Operators (organons) astra owns ───────────────────────────────────────────
# The register functions come from the bundle's own manifest (`register_fns`), sha-verified before
# any exec. Listing them here by name would create a second copy of a declaration that already
# travels with the code it describes — the same drift a single catalog avoids.
REGISTRARS = _runner.register_fns(BUNDLE_GROUP)


def collect(store: Any = None) -> int:
    return _collect(REGISTRARS, store)


def operators() -> List[Dict[str, Any]]:
    return _operators(REGISTRARS)


OPERATORS = operators()


# ── FACETS — astra's view surfaces ─────────────────────────────────────────────────────────────
#
# `workspace` is the human door onto the lattice: the React bundle in `astra/web/`, which reads and
# writes artifacts through Mantle directly (`/artifacts*`, `/grants*`) and signs in against Origin
# with Authorization Code + PKCE. `crystal/host.py::_persona_for_host` reads `FACETS[*]["subdomains"]`
# from every mounted persona and `crystal/web_serve.py` serves the built `dist` at that same
# address, so declaring it here is the whole of the routing work — locally,
# `workspace.home.agience.ai` with `CRYSTAL_HOST_DOMAIN=home.agience.ai`.
#
# The node has to load astra, or this is declared and unreachable. A facet reaches the host router
# only from a MOUNTED persona, so `CHORUS_CRYSTALS` must name `astra` — and the failure is silent:
# the subdomain falls through to crystal's bare host index, which is a 200. That is exactly how
# `pharos.home.agience.ai` was declared and dark, and `_fleet/peers/71/home/node.env` carries the
# note.
#
# And the bundle is load-bearing for this declaration, which is not obvious. `REGISTRARS` above
# raises when the `fetch` bundle cannot be resolved, and `chorus.personas._persona_manifest` answers
# a raising manifest with `([], [])` — so a node that cannot resolve the bundle loses this facet
# too, not just astra's organon. Measured 2026-08-27 with `AGIENCE_BUNDLE_ROOT` pointed at
# `agience-chorus/bundles`: the manifest loads, 1 operator, `dist_root` resolves to `src/astra`.
#
# There is no `bff_tekton`: unlike aria's `www` (condensed by `op.web.bff`) and sage's `pharos`
# (condensed by `op.canon.browse`), nothing condenses this view server-side. It is a client that
# talks to Mantle and Origin over their own APIs, so naming a tekton here would claim a condensor
# that does not exist.
FACETS: List[Dict[str, Any]] = [
    {
        "name": "workspace", "persona": "astra",
        "direction": "both",              # artifacts out, edits back in
        "content_type": "text/html",      # discovery hint, never a gate
        "subdomains": ["workspace"],
        "dist": "web/dist",               # the Vite bundle, relative to this persona dir
    },
]


def facets() -> List[Dict[str, Any]]:
    """The facet manifest — astra's web surfaces (roster source of truth)."""
    return FACETS


def bundle_sha256() -> str:
    """The sha of the bundle this process is actually running for astra — a published stat, so a
    node can report which operator bytes it is serving rather than which it was configured to."""
    return _runner.loaded()[BUNDLE_GROUP]["sha256"]


def bundle_origin() -> str:
    """Where that bundle came from: ``"store"`` (the mesh path) or ``"shipped"``."""
    return _runner.loaded()[BUNDLE_GROUP]["origin"]


__all__ = ["OPERATORS", "REGISTRARS", "BUNDLE_GROUP", "collect", "operators",
           "bundle_sha256", "bundle_origin"]
