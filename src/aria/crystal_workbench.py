"""crystal.workbench — the founding crystal (the platform's first real specimen).

The web workbench: a React facet (the human conduit) + the tektons it engages + the organons
it invokes. This is the definition; agience-facet is the facet's implementation (the render
runtime); the browser prism (prism-js) grounds it.

Delivery (OPERATOR-ARCHITECTURE §12 made market-real):
- founder: authors facets/tektons/organons in the repos; this definition is the assembly.
- community: visits the hosted facet (zero install) or runs the seed bundle (self-host);
  later `prism install crystal.workbench` delivers it from the store.

The definition is data — built through crystal_model so it validates, hashes, and refuses
tampering exactly like every crystal that follows it.
"""
from __future__ import annotations

from crystal.crystal_model import crystal_artifact, validate

WORKBENCH = {
    "name": "crystal.workbench",
    "facets": [
        # The React web UI — the human conduit. Bound by the waveform (§12.1): the UI carries
        # the signal both ways; content types are born at the tektons it talks to.
        {"name": "web", "direction": "both",
         "content_type": "text/html"},                   # discovery hint, never a gate (§12.1)
        # The artifact browser conduit — reads the lattice through mantle's API.
        {"name": "store", "direction": "in"},
        # The event feed — change events flowing out to the UI.
        {"name": "events", "direction": "out"},
    ],
    "tektons": [
        {"name": "lumen", "domain": "wisdom"},           # reasoning/inference — the converse panel
        {"name": "sage", "domain": "knowledge"},         # retrieval/memory
        {"name": "astra", "domain": "input"},            # ingest/describe
        {"name": "aria", "domain": "output"},            # presentation
    ],
    "organons": [
        {"name": "op.respond", "requires": ["compute.local", "store.read"]},
        {"name": "op.reason", "requires": ["compute.local"]},
        {"name": "op.retrieve", "requires": ["store.read"]},
        {"name": "op.describe", "requires": ["store.read", "compute.local"]},
        {"name": "op.remember", "requires": ["store.write"]},
    ],
    "lattice_seed": {
        "collections": ["workbench.session"],            # where a fresh workbench's state grows
    },
    "created_by": "connect@agience.ai",
}

assert validate(WORKBENCH) == [], validate(WORKBENCH)


def workbench_artifact() -> dict:
    """The founding crystal as a store artifact — validated, sha-stamped, refusing tampering."""
    return crystal_artifact(WORKBENCH)


__all__ = ["WORKBENCH", "workbench_artifact"]
