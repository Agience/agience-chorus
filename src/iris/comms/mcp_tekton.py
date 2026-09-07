"""`op.mcp.call` — MCP as a tekton + facet adapter, not a first-class concept.

MCP is not a named layer; it is an adapter expressed in the triple:

  * **tekton** — absorbs an MCP `tools/call` need and removes it from propagation (a sink);
  * **facet** — presents the resulting evidence back to the caller (declared in `iris/manifest.py`);
  * `beam/mcp_bridge.py` is the transport detail behind that tekton, not a concept anybody names.

`.well-known/mcp.json` and the `mcp_bridge` module name are untouched by this adapter, and
`mantle`'s `mcp_resource_importer` is a separate, independent path.

This module dials nothing. `call_tool` is injected, exactly as `beam.mcp_bridge.external_mcp_handler`
requires — iris owns the routing role, not an HTTP client, and a tekton that opened its own sockets
would be an organon in disguise. An unwired host reports that it has no organon to call through (see
`mcp_handler`), never a fabricated tool result: a fake `content` list would be indistinguishable at
the caller from a real one.

Why iris: iris is routing and communication — the persona that already owns the comm plane (it wires
`prism.plane`), its carriers and the persona-side MCP shim. An external MCP server is a world the
reach couples to, so the adapter belongs with the router, not with a domain persona.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from crystal.operator_schema import OPERATOR_CONTENT_TYPE

# The capability id. `op.mcp.call` — one verb, because `tools/call` is the only MCP operation that carries a
# need. `tools/list` is discovery and is already answered by each persona's `.well-known/mcp.json`; modelling
# it as a tekton would make a catalogue read look like a signal that something absorbed.
MCP_CALL = "op.mcp.call"

_MCP_OPS = [
    (MCP_CALL, "absorb an MCP `tools/call` NEED and emit its result as EVIDENCE — the adapter that makes an "
               "external MCP server an ORGANON the reach couples to; the transport is beam.mcp_bridge"),
]


def mcp_handler(call_tool: Optional[Callable[..., Any]] = None, *, server_id: Optional[str] = None,
                user_id: str = "organon", tool_name: Optional[str] = None) -> Callable[[Any], Dict[str, Any]]:
    """The `need -> evidence` tekton handler for `op.mcp.call`.

    Wired (`call_tool` and `server_id` given): delegates to `beam.mcp_bridge.external_mcp_handler`,
    so there is one implementation of the MCP call shape and this module adds no second one.

    Unwired: returns `{"content": [], "isError": True, "reason": "no_mcp_organon"}`. That shape is
    deliberate on both counts: `isError` is MCP's own error channel, so a client reads it correctly
    without special-casing, and `content: []` carries no invented tool output — a dark adapter looks
    dark rather than fabricating a result. Unwired is the default state here, not an edge case.
    """
    if call_tool is None or not server_id:
        def refuse(need: Any) -> Dict[str, Any]:
            req = need if isinstance(need, dict) else {}
            return {"content": [], "isError": True, "reason": "no_mcp_organon",
                    "name": req.get("name"),
                    "detail": "op.mcp.call has no external MCP organon wired on this host; nothing was "
                              "called and no result is being invented"}
        return refuse

    from prism.mcp_bridge import external_mcp_handler
    return external_mcp_handler(call_tool, server_id=server_id, user_id=user_id, tool_name=tool_name)


def serve_mcp(reactor: Any, call_tool: Optional[Callable[..., Any]] = None, *,
              server_id: Optional[str] = None, user_id: str = "organon",
              tool_name: Optional[str] = None, capability: str = MCP_CALL) -> Any:
    """Stand `op.mcp.call` up as a tekton on `reactor`'s reach. Returns the `Provider`.

    Serving it unwired is legitimate and useful: the capability then exists on the plane and reports
    that it has nothing to call, which lets a requester discover that the adapter is present but has
    no organon — distinguishable from the capability not existing at all. Those are different facts
    and a host needs different responses.
    """
    return reactor.serve(capability, mcp_handler(call_tool, server_id=server_id, user_id=user_id,
                                                tool_name=tool_name))


def register_mcp_operators(store, *, author: str = "ember-local") -> int:
    """Mint the `op.mcp.*` operator artifacts. Mirrors `register_comms_operators` exactly — same content type,
    same `preserve_fitness` guard so a re-registration by a process author never clobbers a resolved human
    creator."""
    from crystal import evolution
    for name, offer in _MCP_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": "mcp adapter %s: %s" % (name, offer),
            "created_by": author}))
    return len(_MCP_OPS)


__all__ = ["MCP_CALL", "mcp_handler", "serve_mcp", "register_mcp_operators"]
