"""§9 — MCP as a tekton + facet adapter.

MCP is expressed as an adapter within the triple: `op.mcp.call` is the tekton that absorbs a
`tools/call` need (a sink), the `mcp` entry in `iris/manifest.FACETS` is the view that presents the
evidence, and `prism/mcp_bridge.py` is the transport detail behind it.

Invariants, failure mode first:

  Dark looks dark    — the load-bearing one. Unwired, the tekton returns MCP's own error channel
                        with an empty content list, never a fabricated `content` that would be
                        indistinguishable at the caller from a real tool result. No live external
                        wire exists, so unwired is the default state, not an edge case — §9 lists
                        the whole item as not built for the same reason.
  Present but dark    — serving it unwired is useful: a requester can then distinguish "the adapter
                        exists and has no organon" from "no such capability". Different facts,
                        different responses.
  One implementation  — wired, it delegates to `prism.mcp_bridge` rather than re-implementing the
                        MCP call shape.
  Dials nothing       — `call_tool` is injected; this module opens no socket of its own, so the
                        tekton cannot become an organon in disguise.
  Facet declared      — the view is in the manifest roster and names the tekton behind it, so the
                        host→facet router (which reads `subdomains`) can serve it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # persona dir → bare `comms` import
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))       # chorus/src → `_persona`

from comms.mcp_tekton import MCP_CALL, mcp_handler, register_mcp_operators, serve_mcp  # noqa: E402

import _persona  # noqa: E402


def _manifest():
    """iris's own `manifest.py`, loaded under a unique name.

    Not `importlib.import_module("manifest")`: every persona defines a `manifest.py`, and
    `sys.modules` keys by name alone, so a bare import resolves to whichever persona's copy loaded
    first — correct only when this file runs alone, and wrong (silently) in the combined chorus
    run. That is exactly [[pytest-module-shadowing-silent-substitution]]; `src/_persona.py` loads
    each persona's module under a unique name instead, so the combined run resolves the same
    module every individual run does.
    """
    return _persona.load("manifest", __file__)


# ── dark looks dark ───────────────────────────────────────────────────────────────────────────────
def test_unwired_refuses_honestly_and_invents_no_content():
    """Fails if an unwired call returns a plausible-looking empty tool result instead of using
    `isError`, MCP's own error channel — a client reads that without special-casing, and `content`
    must be empty, with no invented output."""
    h = mcp_handler()                                  # nothing wired: the default state
    out = h({"name": "search", "arguments": {"q": "x"}})
    assert out["isError"] is True, "an unwired adapter reported success"
    assert out["content"] == [], "an unwired adapter invented tool content"
    assert out["reason"] == "no_mcp_organon"
    assert out["name"] == "search", "the refusal should echo what was asked, so it is diagnosable"


def test_unwired_refuses_for_a_malformed_need_too():
    """Fails if junk input raises instead of producing the same graceful no-result response. A
    tekton is a sink; it must absorb and report."""
    for bad in (None, "not-a-dict", 42, []):
        out = mcp_handler()(bad)
        assert out["isError"] is True and out["content"] == []


def test_a_server_id_without_a_call_tool_is_still_dark():
    """Fails if half-configuration reads as wired. Both halves are required — a server id with no
    way to dial it is not an organon."""
    assert mcp_handler(None, server_id="some-server")({"name": "t"})["isError"] is True


def test_a_call_tool_without_a_server_id_is_still_dark():
    """The converse half-configuration."""
    assert mcp_handler(lambda *a, **k: [{"type": "text", "text": "hi"}])({"name": "t"})["isError"] is True


# ── one implementation, and it dials nothing ──────────────────────────────────────────────────────
def test_wired_delegates_to_the_beam_bridge_and_passes_the_call_through():
    """Fails if a second implementation of the MCP call shape lives in iris, free to drift from
    `prism.mcp_bridge`. Wired, the handler must produce the bridge's shape and pass the injected
    `call_tool` exactly what MCP gave it."""
    seen = {}

    def call_tool(server_id, tool, arguments, *, user_id="organon"):
        seen.update(server_id=server_id, tool=tool, arguments=arguments, user_id=user_id)
        return [{"type": "text", "text": "result"}]

    out = mcp_handler(call_tool, server_id="srv-1", user_id="john")({"name": "search",
                                                                    "arguments": {"q": "dog"}})
    assert out == {"content": [{"type": "text", "text": "result"}], "isError": False}
    assert seen == {"server_id": "srv-1", "tool": "search", "arguments": {"q": "dog"}, "user_id": "john"}


def test_tool_name_can_override_the_capability_name():
    """The reach capability name and the remote tool name are allowed to differ — the adapter must not force
    them to match, or every external tool would have to be renamed to be reachable."""
    seen = {}

    def call_tool(server_id, tool, arguments, *, user_id="organon"):
        seen["tool"] = tool
        return []

    mcp_handler(call_tool, server_id="s", tool_name="remote_search")({"name": "op.mcp.call"})
    assert seen["tool"] == "remote_search"


def test_this_module_opens_no_socket_of_its_own():
    """Fails if the tekton is secretly an organon. iris owns routing, not an HTTP client — the world
    is reached only through the injected `call_tool`. Asserted on the source so it cannot regress
    quietly."""
    src = (Path(__file__).resolve().parent.parent / "comms" / "mcp_tekton.py").read_text(encoding="utf-8")
    for forbidden in ("import httpx", "import requests", "urllib.request", "socket.", "aiohttp"):
        assert forbidden not in src, "mcp_tekton dials the world directly (%r) — that is an organon" % forbidden


# ── present but dark, on a real reach ─────────────────────────────────────────────────────────────
def test_serving_it_unwired_makes_the_capability_EXIST_and_refuse():
    """Fails if "no organon" and "no such capability" are conflated. A requester must be able to
    tell them apart — the first is a wiring gap, the second is a missing adapter."""
    from prism.carriers import InMemoryCarrier
    from prism.plane import HLC, Keyring, Lightcone
    from prism.reach import Reactor

    carrier = InMemoryCarrier()
    lc = Lightcone().join("iris", MCP_CALL)
    kr = Keyring(b"fleet-root")
    server = Reactor("iris", keyring=kr, lightcone=lc, fabric=None, fallback=carrier, hlc=HLC("iris"))
    serve_mcp(server)                                   # unwired on purpose
    req = Reactor("req", keyring=kr, lightcone=lc, fabric=None, fallback=carrier, hlc=HLC("req"))

    # Drive the carrier explicitly — one hop needs no PumpLoop.
    handle = req.reach({"name": "search", "arguments": {}}, to=MCP_CALL)
    server.pump(carrier)
    req.pump(carrier)
    ev = req.evidence(handle)

    assert ev is not None, "the capability did not exist on the plane — serving it should register it"
    assert ev["isError"] is True and ev["content"] == [], \
        "a dark adapter answered as if it had called something: %r" % (ev,)


# ── the facet half ────────────────────────────────────────────────────────────────────────────────
def test_the_mcp_facet_is_declared_and_names_its_tekton():
    """Fails if a tekton has no view. The triple says a crystal has a facet because something must
    show what the tekton consumed — and the host→facet router reads these `subdomains`, so an
    undeclared facet is unreachable by name."""
    m = _manifest()
    facets = {f["name"]: f for f in m.facets()}
    assert "mcp" in facets, "iris declares no `mcp` facet"
    f = facets["mcp"]
    assert f["persona"] == "iris" and f["bff_tekton"] == MCP_CALL, \
        "the facet does not name the tekton behind it"
    assert "mcp" in f["subdomains"], "the facet is not reachable by name"
    assert "dist" not in f, "this facet renders no static bundle; a dist would make the router mount nothing"


def test_the_operator_is_registered_into_irises_manifest():
    """The tekton must appear in iris's operator roster, or the host never advertises it."""
    m = _manifest()
    assert any(o.get("id") == MCP_CALL for o in m.OPERATORS), \
        "op.mcp.call is not in iris's operator manifest: %r" % ([o.get("id") for o in m.OPERATORS],)


def test_register_mcp_operators_mints_the_artifact():
    """Fails if the operator mints into the store in a shape nothing can discover."""
    minted = {}

    class _Store:
        def put_artifact(self, doc):
            minted[doc["id"]] = doc
            return doc

        def get_artifact(self, aid):
            return minted.get(aid)

    n = register_mcp_operators(_Store())
    assert n == 1 and MCP_CALL in minted
    assert minted[MCP_CALL]["state"] == "committed"
    assert "mcp" in minted[MCP_CALL]["content"].lower()
