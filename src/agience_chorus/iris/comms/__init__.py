"""Comms plane (Iris — routing & communication) — a crystal that wires a NAS facet (conduit/carrier)
to a comms tekton (condensor) so the guardians of two embers exchange messages over a shared substrate.

This package lives in chorus, under the iris persona (implementations live in chorus, never in the
agnostic crystal base). It is the seed of the communication plane
(`agience-pharos/genesis/COMMUNICATION-PLANE.md`): NasFacet is the first carrier; the plane generalizes
it to direct-peer / s3 / … carriers chosen by least-cost reachability, addressing observer-groups
(grants), delivered by per-group Merkle anti-entropy.

    from comms import build_comms_crystal   # iris dir on sys.path → this package
    tk = build_comms_crystal("71")
    tk.send("45", "stage 0 loaded", subject="training")
    for m in tk.receive():
        ...

CLI (the guardian drop/read): `python -m comms {init|send|inbox|peek|history|watch}`.

`MantleLightcone`/`MantleKeyring` are re-exported lazily (the `__getattr__` at the bottom) rather than
by a `from .wiring import …` at the top. They resolve to the single implementation in
`ember.runtime.reach` (`wiring.py` records why); a top-level from-import would pull ember into import
time for this whole package, and ember is an editable install here, so that dependency is easy to miss.
Lazy resolution keeps `from comms import MantleKeyring` working for callers while `import comms` needs
no ember.
"""
from .message import Message
from .facet_nas import NasFacet
from .tekton_comms import CommsTekton, build_comms_crystal
from .operators import register_comms_operators   # op.comms.* — iris's organon
# MCP as a tekton + facet adapter, not a layer. The transport stays in `prism.mcp_bridge`;
# `mcp_tekton` is the sink that absorbs a `tools/call` need and the thing the `mcp` facet presents.
from .mcp_tekton import MCP_CALL, mcp_handler, register_mcp_operators, serve_mcp

# The names below are re-exported from prism directly, so `from comms import Reactor` (and the
# other names in this block) works without this package owning or implementing the wire itself.
from prism.plane import Plane, Lightcone, Keyring, HLC, send, receive
from prism.carriers import InMemoryCarrier, LocalDirCarrier, NasCarrier, S3Carrier, reconcile
from .wiring import build_plane   # wire to the real grant light-cone + keys
from prism.streams import LoopbackFabric, Stream, StreamReceiver, open_stream   # the live (streaming) mode
from prism.reach import (reach, serve, Provider, Requester, Reactor, Absorption,   # signal-native reach
                         NEED_CT, EVIDENCE_CT)
from prism.mcp_bridge import (need_from_tools_call, tools_call_result_from_evidence,   # MCP ⇄ reach facade
                              dispatch_tools_call, tools_call, external_mcp_handler, serve_external_mcp)

__all__ = ["Message", "NasFacet", "CommsTekton", "build_comms_crystal", "register_comms_operators",
           "Plane", "Lightcone", "Keyring", "HLC", "send", "receive",
           "InMemoryCarrier", "LocalDirCarrier", "NasCarrier", "S3Carrier", "reconcile",
           "MantleLightcone", "MantleKeyring", "build_plane",
           "LoopbackFabric", "Stream", "StreamReceiver", "open_stream",
           "reach", "serve", "Provider", "Requester", "Reactor", "Absorption", "NEED_CT", "EVIDENCE_CT",
           "need_from_tools_call", "tools_call_result_from_evidence", "dispatch_tools_call", "tools_call",
           "external_mcp_handler", "serve_external_mcp"]

# PEP 562 — see the module docstring. `from comms import MantleKeyring` still works; it just
# resolves (and pulls ember in) on first use instead of at import.
_LAZY_FROM_WIRING = ("MantleLightcone", "MantleKeyring")


def __getattr__(name: str):
    if name in _LAZY_FROM_WIRING:
        from . import wiring
        return getattr(wiring, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
