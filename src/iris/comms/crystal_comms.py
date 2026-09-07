"""crystal.comms — the guardian↔guardian communication crystal.

The watch/comms plane made a crystal: a node's guardian (the agent tending its ember — Claude on
45, Claude on 71) speaks through the `guardian` facet; the `courier` tekton carries messages over
the `plane` facet (a shared NAS folder, `_comms/`, plaintext so a human can read the thread too);
change events flow out the `events` facet. The organons are the message primitives (`op.comms.*`).

Two embers each running this crystal + `node/comms-loop.py` (the courier's watch tick) form the
plane: drop to your own ember, the peer's guardian reads it. The definition is data — it validates,
hashes and refuses tampering through crystal_model, exactly like crystal.workbench.
"""
from __future__ import annotations

from crystal.crystal_model import crystal_artifact, validate

COMMS = {
    "name": "crystal.comms",
    "facets": [
        # The guardian conduit — the agent tending this ember drops/reads messages here (both ways).
        # Bound by the waveform (§12.1); the content type is born at the courier tekton.
        {"name": "guardian", "direction": "both",
         "content_type": "application/vnd.agience.message+json"},   # discovery hint, never a gate
        # The plane conduit — the shared NAS folder the courier carries messages across.
        {"name": "plane", "direction": "both"},
        # The event feed — new-message / delivered events flowing out (to a UI or a poll).
        {"name": "events", "direction": "out"},
    ],
    "tektons": [
        {"name": "courier", "domain": "comms"},          # carries messages ember↔plane↔ember
    ],
    "organons": [
        {"name": "op.comms.send", "requires": ["store.write"]},
        {"name": "op.comms.inbox", "requires": ["store.read"]},
    ],
    "lattice_seed": {
        "collections": ["comms.thread"],                 # the node's private message thread
    },
    "created_by": "connect@agience.ai",
}

assert validate(COMMS) == [], validate(COMMS)


def comms_artifact() -> dict:
    """The comms crystal as a store artifact — validated, sha-stamped, refusing tampering."""
    return crystal_artifact(COMMS)


__all__ = ["COMMS", "comms_artifact"]
