"""Local reach host — brings the signal-native reach live on one node (the request path).

Assembles a node's reach runtime and hands back the synchronous responders a facet or CLI injects.
It composes the proven pieces into one object:

  · a `prism.carriers.StoreCarrier` over the node's lattice store — the ground (store-and-forward
    transport)
  · the persona providers (`lumen.op.respond`, `sage.op.retrieve`) served over that carrier
  · a requester (`reach_wiring.reactor` — `prism.reach`'s Reactor over the mantle-backed plane, no
    ember)
  · a `prism.pump.PumpLoop` driving them, and `prism.pump.resolve` for the synchronous
    place→pump→collect

The aria chat bff lights up its `/api/chat` by: `main._RESPOND_CARRIER = {"respond": host.respond}`.

Local-only: running this against node 71's live store is allowed — it is not a fleet deploy. Real
answers (vs. the honest computed null) need two things a plain boot does not have, both gated:
  1. Grants — so lumen and the ember runner reach `op.respond`/`op.retrieve` in the live light-cone
     (the provider derives the ground key only if it reaches the capability). `reach` is injectable
     so the wiring is testable without live grants; in production the real
     `mantle.db.access` light-cone supplies it.
  2. A WordNet `respond_store` bundle — selects the conversation tekton behind `op.respond`; without
     it the provider returns the honest null (`answer=None`, query echoed), never a fabricated
     reply.

Nothing here replaces dark-by-default: a host explicitly constructs this to bring the reach up.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from prism.carriers import StoreCarrier
from prism.pump import PumpLoop, resolve

RESPOND_CAP = "op.respond"
RETRIEVE_CAP = "op.retrieve"


def runner_principal() -> Optional[str]:
    """The requester's identity: the runner's own client credentials. `None` when it has none.

    A principal is only meaningful if some authority issued it, so this is not a literal placeholder
    string: the runner authenticates with the service key it actually holds on disk
    (`keys/<name>.private.pem`, loaded at host startup) — the same client credential that signs
    every other cross-service call. That identity is the delegate: it is what reaches, and what a
    grant can be minted for. The person it acts for is carried separately, since memory belongs to
    the delegate and privacy belongs to the person (`ember/runtime/delegate.py`).

    The light-cone gate lives on the provider, which must reach the capability to open the need, not
    on the requester: `Reactor.reach()` (`prism/reach.py`) does not test the requester's light-cone
    against the target, and `Reactor.__init__`'s `lightcone.join(principal, ground)` is an in-memory
    session overlay, so evidence comes back off the ground regardless of the requester's own grants.

    Returns `None` — never a fabricated name — when no service identity is loaded. A runner with no
    credentials has no light-cone, and the honest consequence is a dark carrier, not a borrowed one.
    """
    try:
        from prism.trust.service_identity import get_service_identity
        return get_service_identity().name
    except Exception:
        return None


class ReachHost:
    """One node's local reach runtime. Build it, `serve_lumen()`/`serve_sage()` the providers you want,
    then `respond(query)`/`retrieve(query)` (synchronous), or `start()`/`stop()` the background cadence.

    `store` is the node's lattice store (the shared ground). `root_secret` is the fleet content-key root
    (both the requester and the providers derive identical ground keys from it). `respond_store` is the
    ember WordNet bundle that selects the real conversation tekton (None → honest null). `reach` injects a
    light-cone fn (tests / explicit wiring); when omitted the providers/requester use the real grant
    light-cone (`mantle.db.access`). Usable as a context manager (`with ReachHost(...) as h:`).

    `principal` is the runner's client credential — the identity needs are addressed under,
    defaulting to the loaded service identity (`runner_principal`). `person` is who the runner acts
    for, a per-turn override on `respond()`; it never affects entitlement, only whose private memory
    is in scope.

    Entitlement is snapshotted once, not re-read live: both `Reactor.__init__` (for the requester)
    and each `Provider.__init__` (`prism/reach.py`, called when `serve_lumen()`/`serve_sage()` wires
    a provider) capture `lightcone.reaches(principal)` at build time. So a grant minted afterward is
    invisible until a new host or provider is built, and one host serves exactly one principal. That
    is why `person` is a per-call argument and `principal` is not: rebinding the person is free,
    rebinding the credential means a new host."""

    def __init__(self, store: Any, *, root_secret: bytes, respond_store: Any = None,
                 principal: Optional[str] = None, person: Optional[str] = None,
                 reach: Optional[Callable[[Any, str], Any]] = None) -> None:
        # The requester acts under the runner's own client credentials (see `runner_principal`).
        # An explicit `principal` still wins — tests and an explicitly-wired host both need it.
        principal = principal or runner_principal()
        if not principal:
            raise ValueError(
                "no runner principal: this host holds no service identity, so the requester has no "
                "client credentials to reach under. Load one (init_service_identity) or pass "
                "principal= explicitly — a made-up name would reach nothing and look like a bug in "
                "the reach instead of a missing credential.")
        self.principal = principal
        self.person = person
        self._store = store
        self._root = root_secret
        self._respond_store = respond_store
        self._reach = reach
        self.carrier = StoreCarrier(store)
        from agience_chorus.reach_wiring import reactor as _reactor    # beam's Reactor over the mantle-backed plane
        self._requester = _reactor(store, principal, root_secret=root_secret, fabric=None,
                                   fallback=self.carrier, reach=reach)
        self._servers: List[Any] = []
        self.loop = PumpLoop(self.carrier, [self._requester])

    def serve_lumen(self) -> "ReachHost":
        """Stand lumen up as the `op.respond` provider on this host's carrier (the chat responder)."""
        # The host says how cognition is obtained, so the persona does not have to guess.
        # `conversation._as_delegate` resolves in three steps — an already-built Delegate, this
        # resolver, then importing ember's Delegate itself. Injecting here means the live reach path
        # (`store_respond` hands in a bare store) stops at step 2 and lumen never reaches the runner
        # for cognition. Unwired, it still works one step further along; this closes an edge rather
        # than adding a requirement, which is why it is safe to do only where a host actually exists.
        self._bind_cognition()
        from agience_chorus.lumen import reach_provider as lrp
        rc = lrp.serve_respond(self._store, root_secret=self._root, fabric=None,
                               respond_store=self._respond_store, reach=self._reach,
                               caps={lrp.RESPOND_CAP: "respond"})
        self._servers.append(rc)
        self.loop.add(rc)
        return self

    def _bind_cognition(self) -> None:
        """Point lumen's delegate resolution at the runner this host is already holding.

        The Delegate is the runner's by charter — `ember/runtime/delegate.py` exists to guarantee
        there is never shared cognitive state, and `Delegate.get` is the per-process-per-person
        registry that enforces it. That does not mean a persona should import it directly: this is a
        composition root, and a composition root is exactly the place that may know both sides.

        Cognition is asked for by name, through the declared `delegate` seam, rather than imported
        directly from `ember.runtime.delegate`: the requester itself comes from `reach_wiring`,
        whose only imports are `prism.reach` and `mantle.db.plane`, so a direct import here
        would be this file's only edge into ember. The seam resolves to whatever module the running
        host bound.

        The `except ImportError: return` is load-bearing: `HostSeamUnfilled` subclasses
        `ImportError`, so a process with no runner leaves `conversation`'s own three-step resolution
        in charge, exactly as it would if the import itself had failed."""
        try:
            from agience_chorus.lumen import conversation as _conv
            from agience_chorus._host_seams import resolve as _seam
            _delegate = _seam("delegate")
        except ImportError:
            return                      # no lumen, or no host bound `delegate`: leave the fallback in charge
        _conv.set_delegate_resolver(lambda store, person: _delegate.Delegate.get(store, person=person))

    def serve_sage(self, **kw: Any) -> "ReachHost":
        """Stand sage up as the `op.retrieve` provider on this host's carrier (retrieval/grounding)."""
        from agience_chorus.sage import reach_provider as srp
        rc = srp.serve_retrieve(self._store, root_secret=self._root, fabric=None, reach=self._reach, **kw)
        self._servers.append(rc)
        self.loop.add(rc)
        return self

    def respond(self, query: str, *, person: Optional[str] = None) -> Any:
        """Place a conversation need on `op.respond` and drive the cadence to the answer (or None).
        The op.respond shape is `{answer, grounded, cited, ...}`; honest null without a substrate,
        never fabricated.

        Two identities travel here, and they are not the same one. The need is addressed under the
        runner's client credentials (`self.principal`, snapshotted into the requester's light-cone at
        construction) — that is what is entitled to open `op.respond`. The need's own `principal`
        field is the person the runner acts for, and it scopes private memory (`private.<person>`)
        inside the tekton. Collapsing them would either leak one person's memory to another or make
        the reach un-openable; they are the delegate and the person, kept apart on purpose.

        Omitted entirely when there is no person, rather than sent as a default: the tekton resolves
        its own non-person identity, and a placeholder here would attribute a stranger's turn to it."""
        need = {"text": query, "query": query}
        who = person or self.person
        if who:
            need["principal"] = who
        return resolve(self._requester, need, to=RESPOND_CAP, loop=self.loop)

    def retrieve(self, query: str) -> Any:
        """Place a retrieval need on `op.retrieve` and drive the cadence to the hits (or None)."""
        return resolve(self._requester, {"query": query}, to=RETRIEVE_CAP, loop=self.loop)

    def start(self) -> "ReachHost":
        """Run the cadence on a background thread (for a long-lived server that answers as NEEDs arrive)."""
        self.loop.start()
        return self

    def stop(self) -> None:
        self.loop.stop()

    def __enter__(self) -> "ReachHost":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


__all__ = ["ReachHost", "RESPOND_CAP", "RETRIEVE_CAP"]
