"""The durable go-live service — a persistent `ReachHost` wired to aria's bff.

This is the entrypoint that assembles the two halves of a live chat: `ReachHost` and
`aria/www/bff/main.py` each exist and are tested independently, and this module is where the first
is constructed and handed to the second. Without it, the chat facet resolves its carrier to `None`
and answers the honest-offline text.

    from live_service import build_live
    with build_live(store, root_secret=secret, respond_store=store, corpus=store) as svc:
        app = svc.app                     # aria's bff, carrier already wired
        # serve `app` with uvicorn; svc.stop() on shutdown (the context manager does it)

What it refuses to do, and why each refusal holds:

1. **It does not open a listener.** Assembly is separable from binding a port, so the whole wiring is
   testable in-process against a temp lattice. Binding the socket is the bring-up script's job
   (`agience-ember/node/`), which is also the only layer that should ever be pointed at a live node.

2. **It does not invent a `root_secret`.** Both sides of a reach derive the ground key from it; a
   generated one would build a host that talks only to itself, and it would look like it worked because
   a single process is both ends. Missing raises `ValueError`.

3. **It sets the carrier on the loaded bff module, not a fresh import.** `aria/web_bff._load_bff_module()`
   loads `www/bff/main.py` under a unique name and caches it in `sys.modules`. A plain `import main` would
   produce a different module object, so `_RESPOND_CARRIER` would be set on a module the running app never
   reads — the wiring would silently do nothing and chat would stay dark with no error anywhere.

4. **It does not make the answer true.** With no `respond_store` the provider returns the computed null and
   the bff reports `no_evidence`; with no `corpus` sage's retrieval is empty by construction. Both are
   honest-degrade states that must stay distinguishable from a real answer — `build_live` therefore reports
   what it wired (`svc.wired`) instead of implying a working chat.

Grants are the gated piece, and this module does not paper over them. `beam.reach.Provider` snapshots
entitlement in `__init__` (`self._reach = lightcone.reaches(principal)`), so grants minted after
construction are never seen — the mint must happen before `build_live`. `reach=` is passed straight
through for tests, exactly as `ReachHost` documents; production leaves it None so the real
`mantle.db.access` light-cone decides.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


class LiveService:
    """A running `ReachHost` plus the aria bff app it feeds. Use as a context manager."""

    def __init__(self, host: Any, app: Any, bff_module: Any, wired: Dict[str, bool]) -> None:
        self.host = host
        self.app = app
        self._bff = bff_module
        self.wired = dict(wired)
        self._prev_carrier = None
        self._started = False

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> "LiveService":
        """Start the pump loop and wire the bff's respond carrier. Idempotent."""
        if self._started:
            return self
        self.host.start()
        self._prev_carrier = getattr(self._bff, "_RESPOND_CARRIER", None)
        # The store-and-forward shape the bff accepts: `{respond: (query) -> evidence}`. The host owns
        # the loop, so the bff never needs to distinguish a carrier from a fabric.
        self._bff._RESPOND_CARRIER = {"respond": self.host.respond}
        self._started = True
        return self

    def stop(self) -> None:
        """Stop the loop and restore the bff's previous carrier. Idempotent.

        Restoring rather than deleting matters for tests and for a re-wire: leaving a dead carrier behind
        would make the bff call into a stopped loop, which blocks instead of reporting offline — a hang
        reads as a slow answer, not as a stopped service.
        """
        if not self._started:
            return
        try:
            self._bff._RESPOND_CARRIER = self._prev_carrier
        finally:
            self.host.stop()
            self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def __enter__(self) -> "LiveService":
        return self.start()

    def __exit__(self, *exc) -> bool:
        self.stop()
        return False


def build_live(store: Any, *, root_secret: bytes, respond_store: Any = None, corpus: Any = None,
               principal: Optional[str] = None,
               reach: Optional[Callable[[Any, str], Any]] = None) -> LiveService:
    """Assemble the durable service. Does not start it — `start()` or the context manager does.

    `store` is the shared ground (the lattice the reach operates over, and the grant light-cone store).
    `respond_store` is the WordNet/conversation bundle lumen's `op.respond` grounds on; `corpus` is the
    bundle sage's `op.retrieve` searches. Either omitted ⇒ that leg degrades honestly and `wired` says so.
    """
    if not root_secret:
        raise ValueError(
            "root_secret is required: both ends of a reach derive the ground key from it, so a generated "
            "one would build a host that only talks to itself — and it would look like it worked, because "
            "one process is both ends.")

    from reach_host import ReachHost

    # principal=None ⇒ the runner's own client credentials (`reach_host.runner_principal`); ReachHost
    # raises rather than inventing a name, so a credential-less host fails here instead of building a
    # requester whose light-cone is empty and calling that a working reach.
    host = ReachHost(store, root_secret=root_secret, respond_store=respond_store,
                     principal=principal, reach=reach)
    host.serve_lumen()
    host.serve_sage(corpus=corpus)

    # The bff module object the running app actually reads — see refusal 3 in the module docstring.
    from aria import web_bff
    bff_module = web_bff._load_bff_module()
    app = web_bff.bff_app()

    return LiveService(host, app, bff_module, {
        "respond": respond_store is not None,   # False => lumen returns the computed null, not an answer
        "retrieve": corpus is not None,         # False => sage's retrieval is empty by construction
        "grants": reach is None,                # True => the real mantle.db.access light-cone decides
        # `grants` reports whether the real light-cone is deciding, not a requester-side gate:
        # `beam/reach.py::Reactor.reach()` never tests the requester's reach against the target, and
        # `Reactor.__init__`'s `lightcone.join(principal, ground)` is an in-memory session overlay under
        # which evidence returns regardless of the requester's grants. Entitlement is enforced on the
        # provider side, which must hold the capability to open the need at all.
    })


__all__ = ["LiveService", "build_live"]
