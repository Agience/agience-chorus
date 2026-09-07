"""MCP over the Agience signal reach (`prism.mcp_bridge`; there is no `iris/comms/mcp_bridge.py`
re-export shim), tested to
`pharos/genesis/TEST-ARCHITECTURE.md` — named invariants proven over a generated world-space against an
independent oracle, plus an adversarial case that must fail safely. The thesis: an external MCP `tools/call`
lands as a need that propagates to the coupling capability, and the evidence propagates back shaped as an MCP
`tools/call` result — with zero client-side change. A tool call is a need; an external MCP server is an
organon; MCP is a legacy skin over a signal core.

Every assertion is one of:

  (1) round-trip   — an MCP tools/call for capability X, with a provider served on the reach, returns exactly
                     the provider's evidence, shaped as a valid MCP result — not an in-process call.
  (2) over-plane   — the payload crossed as a sealed signal: the reach tied the evidence back to this need
                     (the provider recorded resolving this handle), and the result wraps that band verbatim.
  (3) isolation    — a non-member provider on the same wire opens nothing; the answer is the legit provider's.
  (4) darkness     — a tools/call for a capability with no provider returns an MCP error result, never a
                     fabricated success (honest darkness).
  (5) event-driven — the bridge holds no sleep/poll/async loop; the round trip completes in one synchronous
                     dispatch (the loopback fabric fires the provider on arrival).
  (6) outbound     — an external MCP server behind an organon: a need calls the external server (chorus_client
                     shape) and its result returns as evidence — "an external MCP server is just an organon."

The oracle shapes the MCP result directly from the provider's own output (not via the bridge's shaper), so the
test cannot be fooled by the bridge and the oracle sharing a bug. See `agience-pharos/genesis/MCP-VS-SIGNAL-AUDIT.md` §3.
"""
from __future__ import annotations

import inspect
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → the local `comms` package

from prism.plane import HLC, Keyring, Lightcone  # noqa: E402
from prism.reach import Reactor  # noqa: E402
from prism.streams import LoopbackFabric  # noqa: E402
from prism import mcp_bridge  # noqa: E402
from prism.mcp_bridge import (dispatch_tools_call, external_mcp_handler,  # noqa: E402
                              serve_external_mcp, tools_call)

SEEDS = range(120)   # the generated world-space (each seed = a reproducible tool + args)


# ── the independent oracle — the MCP result shape, recomputed from first principles ───────────────────
def oracle_mcp_result(evidence):
    """The MCP `tools/call` result an oracle expects for a persona tool's plain-value evidence: one text
    content item carrying the JSON of the evidence, not an error. Computed directly here — never by calling
    the bridge's shaper — so a shared bug cannot hide."""
    return {"content": [{"type": "text", "text": json.dumps(evidence, sort_keys=True, default=str)}],
            "isError": False}


def _retrieve_stub(hits):
    """A stub `op.retrieve`-style provider: evidence is a pure function of the need's query (fake hits). Stands
    in for a real persona tool — the bridge imports no persona; the capability is injected at the seam."""
    def handler(need):
        q = need["arguments"].get("query", "")
        return {"cap": "op.retrieve", "query": q, "hits": [dict(h, q=q) for h in hits]}
    return handler


def _world(seed):
    """One world: a `sage` persona serving `op.retrieve` on a loopback fabric, and a `lumen` reactor that will
    place MCP tools/calls onto the reach. Deterministic hits per seed."""
    r = random.Random(seed)
    kr = Keyring(b"mcp-bridge-%d" % seed)
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")
    fabric = LoopbackFabric()
    hits = [{"doc": "d%d" % i, "score": round(r.random(), 3)} for i in range(r.randint(0, 3))]
    sage = Reactor("sage", keyring=kr, lightcone=lc, fabric=fabric, hlc=HLC("sage", clock=_counter()))
    handler = _retrieve_stub(hits)
    sage.serve("op.retrieve", handler)
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric, hlc=HLC("lumen", clock=_counter()))
    args = {"query": "q%d-%s" % (seed, r.choice(["hamlet", "π", "who?", ""]))}
    return sage, lumen, handler, args


# ── (1)+(2) round-trip + over-plane, over the generated world-space ───────────────────────────────────
def test_tools_call_returns_the_providers_evidence_as_an_mcp_result():   # invariant 1 + 2
    for seed in SEEDS:
        sage, lumen, handler, args = _world(seed)

        # The MCP call — a tools/call {name, arguments} placed on the reach as a need.
        handle, result = dispatch_tools_call(lumen, "op.retrieve", args)

        # (2) over-plane: the provider resolved this exact reach (not an in-process call), and the evidence it
        #     placed back is what the MCP result wraps — the payload crossed as a signal, tied by the handle.
        provider = sage._providers[0]
        assert handle in provider.handled, "seed %d: provider never resolved this reach" % seed
        crossed = provider.handled[handle]
        assert crossed == handler(mcp_bridge.need_from_tools_call("op.retrieve", args))  # the band it absorbed

        # (1) round-trip: the MCP result equals the oracle shape of that evidence, exactly.
        assert result == oracle_mcp_result(crossed), "seed %d: %r" % (seed, result)
        assert result["isError"] is False
        assert result["content"][0]["type"] == "text"
        # the returned band is equal but re-serialized — it was sealed and crossed the plane, not shared.
        assert json.loads(result["content"][0]["text"]) == crossed


# ── (3) isolation — a non-member provider on the same wire absorbs nothing ────────────────────────────
def test_a_non_member_provider_on_the_same_wire_is_bypassed():           # invariant 3
    kr = Keyring(b"iso-root")
    lc = Lightcone().define_group("op.retrieve").join("sage", "op.retrieve")   # mallory not joined
    fabric = LoopbackFabric()
    sage = Reactor("sage", keyring=kr, lightcone=lc, fabric=fabric)
    sage.serve("op.retrieve", lambda need: {"hits": ["real", need["arguments"]]})
    mallory = Reactor("mallory", keyring=kr, lightcone=lc, fabric=fabric)
    mal_prov = mallory.serve("op.retrieve", lambda need: {"stolen": need})     # subscribes, lacks the key
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric)

    handle, result = dispatch_tools_call(lumen, "op.retrieve", {"query": "x"})
    assert mal_prov.handled == {}, "isolation: non-member opened a sealed need"
    body = json.loads(result["content"][0]["text"])
    assert body["hits"][0] == "real"                                          # answer is sage's, never mallory's
    assert sage._providers[0].handled[handle] == body                        # sage resolved exactly this reach


# ── (4) darkness — no provider ⇒ an MCP error result, never a fabricated success ──────────────────────
def test_unresolved_capability_returns_an_mcp_error_result():             # invariant 4
    kr = Keyring(b"dark-root")
    lc = Lightcone().define_group("op.retrieve")                              # defined, but nobody serves it
    fabric = LoopbackFabric()
    lumen = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric)

    result = tools_call(lumen, "op.retrieve", {"query": "anyone?"})
    assert result["isError"] is True                                          # honest darkness, not a fake hit
    assert "no provider" in result["content"][0]["text"]
    assert "op.retrieve" in result["content"][0]["text"]


# ── (5) event-driven — no poll/sleep in the bridge; one synchronous round trip ────────────────────────
def test_bridge_is_event_driven_no_sleep_or_poll_loop():                  # invariant 5
    src = inspect.getsource(mcp_bridge)
    # strip every docstring/string literal so prose (which contains "while", "for") can't mask a real loop.
    code = re.sub(r'""".*?"""|".*?"|\'.*?\'', "", src, flags=re.DOTALL)
    code = re.sub(r"#.*", "", code)                                   # strip comments too
    for banned in ("time.sleep", "asyncio", "sleep(", "while ", "for ", ".poll(", "threading"):
        assert banned not in code, "bridge must stay event-driven — found %r" % banned


def test_bridge_imports_nothing_from_ember_lumen_or_sage():               # the injected-seam boundary
    src = inspect.getsource(mcp_bridge)
    for banned in ("import ember", "from ember", "import lumen", "from lumen", "import sage", "from sage",
                   "httpx", "streamablehttp"):
        assert banned not in src, "bridge must stay a pure shape adapter — found %r" % banned


# ── (6) outbound — an external MCP server behind an organon: external MCP = organon ────────────────────
class _FakeExternalMcpServer:
    """A stub external MCP server with the `chorus_client.call_tool` shape:
    `call_tool(server_id, tool_name, arguments, *, user_id) -> content_list`. Records every call so the test
    can prove the organon actually dialed out to it."""
    def __init__(self):
        self.calls = []

    def call_tool(self, server_id, tool_name, arguments, *, user_id):
        self.calls.append((server_id, tool_name, dict(arguments), user_id))
        payload = {"server": server_id, "tool": tool_name, "echo": arguments, "who": user_id}
        return [{"type": "text", "text": json.dumps(payload, sort_keys=True)}]


def test_a_need_resolves_through_an_external_mcp_organon():               # invariant 6 (outbound)
    kr = Keyring(b"organon-root")
    lc = Lightcone().define_group("net.mcp").join("iris", "net.mcp")
    fabric = LoopbackFabric()
    ext = _FakeExternalMcpServer()

    iris = Reactor("iris", keyring=kr, lightcone=lc, fabric=fabric)
    organon = serve_external_mcp(iris, "net.mcp", ext.call_tool, server_id="ext-123", user_id="alice")
    caller = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric)

    # A need to the organon capability — carrying the external tool name + arguments.
    handle = caller.reach(mcp_bridge.need_from_tools_call("search", {"q": "hello"}), to="net.mcp")
    evidence = caller.evidence(handle)

    # The organon dialed the external server (outbound), and its result came back as evidence.
    assert ext.calls == [("ext-123", "search", {"q": "hello"}, "alice")]      # external MCP = an organon
    assert organon.handled[handle] == evidence                               # organon resolved this reach
    body = json.loads(evidence["content"][0]["text"])
    assert body == {"server": "ext-123", "tool": "search", "echo": {"q": "hello"}, "who": "alice"}


def test_inbound_tools_call_resolved_by_an_external_organon_end_to_end():  # the full skin-over-core story
    """An MCP `tools/call` (inbound facade) whose capability is resolved by an external MCP server (outbound
    organon): the client sees a normal MCP result; internally the need propagated to the organon, which dialed
    out and returned the external server's result as evidence — MCP on the edge, signal in the core."""
    kr = Keyring(b"e2e-root")
    lc = Lightcone().define_group("net.mcp").join("iris", "net.mcp")
    fabric = LoopbackFabric()
    ext = _FakeExternalMcpServer()
    iris = Reactor("iris", keyring=kr, lightcone=lc, fabric=fabric)
    serve_external_mcp(iris, "net.mcp", ext.call_tool, server_id="ext-9", tool_name="fetch")
    client = Reactor("lumen", keyring=kr, lightcone=lc, fabric=fabric)

    _handle, result = dispatch_tools_call(client, "net.mcp", {"url": "https://x"})

    assert result["isError"] is False
    body = json.loads(result["content"][0]["text"])                          # the external server's own result
    assert body["tool"] == "fetch" and body["echo"] == {"url": "https://x"}   # tool_name override honored
    assert ext.calls[0][1] == "fetch"


# ── shared shape check: what every inbound result satisfies ───────────────────────────────────────────
def test_mcp_result_is_a_valid_tools_call_shape_for_every_evidence_kind():
    """The shaper produces a valid MCP `tools/call` result for each evidence kind the plane can return:
    a plain value (persona tool), an already-MCP dict (organon relay), a content list, and None (darkness)."""
    from prism.mcp_bridge import tools_call_result_from_evidence as shape
    plain = shape({"hits": [1, 2]}, name="op.x")
    assert plain["isError"] is False and json.loads(plain["content"][0]["text"]) == {"hits": [1, 2]}
    already = shape({"content": [{"type": "text", "text": "hi"}], "isError": False})
    assert already == {"content": [{"type": "text", "text": "hi"}], "isError": False}
    listed = shape([{"type": "text", "text": "z"}])
    assert listed == {"content": [{"type": "text", "text": "z"}], "isError": False}
    dark = shape(None, name="op.x")
    assert dark["isError"] is True and "op.x" in dark["content"][0]["text"]


def _counter():
    n = {"v": 0}
    def clk():
        n["v"] += 1
        return n["v"]
    return clk
