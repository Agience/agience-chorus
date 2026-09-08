"""Lumen as a provider of the conversation tekton (`op.respond` / `op.act` / `op.learn` / `op.thought`)
over the ground-plane reach — the persona face of the P7 capstone.

The conversation tekton lives here (`lumen/conversation.py`); ember is simply a runner and reaches it.
This module is the signal-native face of that tekton: lumen builds its own `Reactor` over the shared
ground plane and `.serve("op.respond", handler)` (plus the act/learn/thought siblings), so an Apache
runner (ember) can reach it by placing a need on the plane — no import of lumen from ember, no carried
return address; evidence returns through the ground correlated by provenance (see `beam/reach.py`).
Mirrors `sage/reach_provider.py`, the same pattern.

The provider is wired with the plane adapters `mantle.db.plane.LatticeKeyring`/`LatticeLightcone`,
so lumen's entitlement to open a need addressed to `op.respond` is the same grant light-cone that keys its
content at rest, and the ground key is the same fleet `collection_key` derivation the runner derives — the
circuit completes because both sides derive identical keys from the shared root. These adapters live in
mantle, which both the runner and the personas depend on, so there is one implementation shared by both
sides without either reaching the other's package.

The handler. With a real ember `store` bundle (WordNet + the private-triple lattice) the handler is the
conversation tekton (`conversation.respond/act/learn/think` over the caller's delegate). Without a store it
is `local_respond`, a minimal honest stand-in in the op.respond shape that proves the wiring
(delivery/provenance/isolation) without the substrate: it never fabricates — it returns the computed null
(`answer=None`, no citation), echoing the query so the reach is query-dependent. Full conversation
behavior verification needs a built substrate and a live serve.

Cross-process carrier wiring (a real WebRTC/QUIC/RF fabric plus a durable ground carrier) is a separate
gated deploy step — this module stays loopback/same-process by design; the default `_default_wiring()`
returns None so the provider is dark on a plain boot (ember then honestly refuses op.respond rather than
fabricating).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from prism.reach import GROUND, Reactor

# `mantle.db.plane.LatticeLightcone`/`LatticeKeyring` are imported lazily inside `serve_respond`.
# Deliberately not module-level: the adapters reach `mantle.db.access` lazily themselves, so
# importing lumen must not drag the lattice package onto the path for callers that never stand up a
# provider. Keeping it lazy preserves that.

RESPOND_CAP = "op.respond"
ACT_CAP = "op.act"
LEARN_CAP = "op.learn"
THINK_CAP = "op.thought"
CAPS = {RESPOND_CAP: "respond", ACT_CAP: "act", LEARN_CAP: "learn", THINK_CAP: "think"}

__all__ = ["RESPOND_CAP", "ACT_CAP", "LEARN_CAP", "THINK_CAP", "CAPS",
           "local_respond", "store_respond", "respond_handler",
           "serve_respond", "serve_respond_if_configured"]


def local_respond(text: str, *, act: str = "respond") -> Dict[str, Any]:
    """A minimal honest stand-in for the conversation tekton, in its op.respond shape, for the loopback
    proof (no WordNet substrate). It never fabricates: it returns the computed null — `answer=None`, no
    citation — echoing the query so the evidence is query-dependent (different text -> different echo),
    which is all the wiring proof needs. The full `conversation.<act>` drops in behind this signature
    (see `store_respond`) once a real store is wired."""
    return {"answer": None, "act": act, "echo": (text or ""), "grounded": False,
            "activations": [], "cited": []}


def store_respond(store: Any, text: str, *, act: str = "respond",
                  principal: Optional[str] = None) -> Dict[str, Any]:
    """The conversation tekton behind the reach — `conversation.<act>` over an ember `store` bundle
    (WordNet + the private-triple lattice), resolving this caller's delegate. This is the capability
    `local_respond` stands in for: the full tekton backs the reach in-process. `store` is an ember
    LocalStore bundle; `conversation` reaches back into `ember.ontology.activation`'s recognition primitives."""
    # A bare `import conversation` only resolves when lumen's own dir is on sys.path (its server/tests
    # add it). In a cross-persona host — `chorus/src/reach_host.py::ReachHost`, any real go-live deploy —
    # only `chorus/src` is on the path, so the bare import raises ImportError, which the reach `Provider`
    # swallows (a handler error -> no evidence -> a silent no-answer). Try the package path first, fall
    # back to the bare (in-persona) form, so it works in both launch shapes.
    try:
        from agience_chorus.lumen import conversation as _conv           # cross-persona host (chorus/src on path)
    except ImportError:
        import agience_chorus.lumen.conversation as _conv                      # lumen-local (persona process has lumen/ on path)
    fn = getattr(_conv, CAPS.get("op." + act, act), None) or getattr(_conv, act)
    return fn(store, text or "", principal=principal)


def respond_handler(store: Any = None, *, act: str = "respond",
                    principal: Optional[str] = None) -> Callable[[Any], Dict[str, Any]]:
    """Build the injected `need -> evidence` handler for a conversation capability. The need is
    `{text, principal?}`; the evidence is the op.respond shape. When `store` (a real bundle) is given the
    handler is the conversation tekton (`conversation.<act>`); otherwise it falls back to
    `local_respond` (the loopback proof shape — never a fabricated answer). Missing/empty text →
    the computed null (fail-soft)."""
    def handler(need: Any) -> Dict[str, Any]:
        need = need or {}
        text = need.get("text", "")
        who = need.get("principal", principal)
        inner = (store_respond(store, text, act=act, principal=who) if store is not None
                 else local_respond(text, act=act))
        # Frame-native (§A.2): if the need carries a signal frame, absorb this tekton's band (op.respond's
        # offer coupling) and merge the residual into the response, to propagate onward. Additive: a
        # text-only need is unchanged. `tekton_basis_for` lives in ember (a measurement both personas reach).
        from prism import frames as _frames
        try:
            # The persona declares the measurement by name and the host says which module answers,
            # rather than importing `ember.ontology.match` directly — chorus personas do not import
            # ember. `HostSeamUnfilled` is an `ImportError`, so an unbound host lands in the same
            # `except` on the same input and `_basis` is None.
            from agience_chorus._host_seams import resolve as _seam
            _basis = (_seam("match").tekton_basis_for(store, RESPOND_CAP)
                      if store is not None else None)
        except Exception:
            _basis = None
        _fr = _frames.absorb_need(need, basis=_basis)
        return {**inner, **_fr} if _fr is not None else inner
    return handler


def serve_respond(store: Any, *, root_secret: bytes, fabric: Any, respond_store: Any = None,
                  principal: str = "lumen", ground: str = GROUND,
                  reach: Optional[Callable[[Any, str], Any]] = None,
                  caps: Optional[Dict[str, str]] = None) -> Reactor:
    """Stand lumen up as the provider of the conversation tekton over `fabric`, grounded on `ground`.

    Builds `Reactor(principal, keyring=LatticeKeyring(root_secret), lightcone=LatticeLightcone(store), ...)`
    and serves each conversation capability. The reactor's light-cone (lumen's real grants, via
    `mantle.db.access`) must reach `op.respond` for lumen to open needs addressed to it; the ground key both
    sides derive from `root_secret` is what carries the evidence back. `respond_store` (a real ember
    bundle) selects the `conversation` tekton; None selects `local_respond` (loopback
    proof). Returns the reactor (hold it to keep serving). `reach` injects a light-cone fn for tests."""
    from mantle.db.plane import LatticeKeyring, LatticeLightcone   # lazy: only a wired host binds these
    rc = Reactor(principal, keyring=LatticeKeyring(root_secret),
                 lightcone=LatticeLightcone(store, reach=reach), fabric=fabric, ground=ground)
    for cap, act in (caps or CAPS).items():
        rc.serve(cap, respond_handler(respond_store, act=act))
    return rc


def _default_wiring() -> Optional[Dict[str, Any]]:
    """No carrier by default — a deploy-specific follow-up supplies one. Returns None so the provider
    stays dark."""
    return None


def serve_respond_if_configured(
        *, wiring: Optional[Callable[[], Optional[Dict[str, Any]]]] = None) -> Optional[Reactor]:
    """Host-lifespan hook: stand lumen up as the conversation-tekton provider when — and only when — a
    live carrier is wired. Returns the serving Reactor, or None when nothing is configured (the default
    on a plain boot). Guarded end-to-end: any missing piece or error resolves to None, so lumen boots
    whether or not the ground-plane carrier exists and `server_startup` never breaks.

    The carrier (a real WebRTC/QUIC/RF fabric, the fleet `root_secret`, the grant `store` for the
    light-cone, and the `respond_store` ember bundle for the real tekton) is a separate deploy-specific
    step; `wiring` is the injection point — a callable returning `{store, root_secret, fabric,
    respond_store?, principal?, ground?}`. Until it is provided, this is a no-op: the reach provider
    stays dark and ember honestly refuses `op.respond` rather than fabricating."""
    try:
        cfg = (wiring or _default_wiring)()
    except Exception:
        return None
    if not cfg or cfg.get("fabric") is None or cfg.get("root_secret") is None or cfg.get("store") is None:
        return None
    try:
        return serve_respond(cfg["store"], root_secret=cfg["root_secret"], fabric=cfg["fabric"],
                             respond_store=cfg.get("respond_store"),
                             principal=cfg.get("principal", "lumen"), ground=cfg.get("ground", GROUND))
    except Exception:
        return None
