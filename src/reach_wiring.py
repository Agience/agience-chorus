"""Chorus's requester assembly — build a `beam.reach.Reactor` over the mantle-backed plane.

A persona (or the local reach host) that wants to place a need needs a `Reactor` wired to the two plane
contracts. This module is the one place chorus assembles one:

    Reactor(principal, keyring=LatticeKeyring(root_secret), lightcone=LatticeLightcone(store, ...))

This is composition, not a second implementation of `ember.runtime.reach`. The behaviour has exactly one
home: the light-cone rule (`reachable_collections` + containment + session grounds) and the key rule
(`collection_key = HKDF(root, origin_root)`) live once, in `mantle/db/plane.py`. Nothing here
re-implements either; a second definition is how two hosts would derive different group keys and a reach
would silently complete for nobody. What is assembled here is three arguments handed to a beam
constructor — ember composes its own requester the same way from the same parts, because a requester is a
per-process object built from that process's own store, principal and root secret. Two callers building
the same shape from one implementation is not two implementations.

There is no shared home below both sides. The assembly needs `beam.reach.Reactor` and a mantle backing:
  * it cannot live in **mantle** — mantle is beam's sibling in the target DAG (mantle reaches only
    origin), so `mantle → beam` would trade one violation for another;
  * it cannot live in **beam** — beam is the signal, entroptics-only, and `beam → mantle` would break the
    "beam is signal" property the dependency graph maintains;
  * it cannot live in **ember** for chorus's use — that would recreate the `chorus → ember` edge this
    module exists to avoid.
So each side composes locally from single-homed parts.

This module is deliberately top-level in `src/` (a peer of `reach_host.py`/`personas.py`), not inside a
persona: `lumen/router.py` and `aria/www/bff/main.py` both use it, and a persona importing a sibling
persona is banned by `src/tests/test_persona_isolation.py`. It imports no persona, so nothing here can
create that edge either.

The API mirrors `ember.runtime.reach`'s `reactor`/`reach` argument-for-argument, so a call site moving off
ember changes its import line and nothing else.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from prism.reach import GROUND, Reactor

__all__ = ["reactor", "reach", "GROUND"]


def reactor(store: Any, principal: str, *, root_secret: bytes, fabric: Any = None,
            reach: Optional[Callable[[Any, str], Iterable[str]]] = None, ground: str = GROUND,
            fallback: Any = None, hlc: Any = None) -> Reactor:
    """Build the `beam.reach.Reactor` a chorus call site holds — serves capabilities and issues reaches
    over the ground plane, wired with the mantle-backed `LatticeLightcone`/`LatticeKeyring`.

    `store` is the lattice store (holds `.artifacts`/`.graph` for the light-cone); `principal` is the
    persona/host identity; `root_secret` the fleet content-key root; `fabric` a live streaming fabric
    (`LoopbackFabric` in tests, WebRTC/QUIC/RF in prod) — omit it and the reactor rides a `fallback`
    carrier (store-and-forward, driven by `Reactor.pump`). `reach` injects a light-cone fn for tests."""
    from mantle.db.plane import LatticeKeyring, LatticeLightcone   # lazy: mirrors the adapters' own
    lightcone = LatticeLightcone(store, reach=reach)
    keyring = LatticeKeyring(root_secret)
    return Reactor(principal, keyring=keyring, lightcone=lightcone, fabric=fabric, ground=ground,
                   fallback=fallback, hlc=hlc)


def reach(store: Any, principal: str, need: Any, *, to: str, root_secret: bytes, fabric: Any = None,
          reach_fn: Optional[Callable[[Any, str], Iterable[str]]] = None, ground: str = GROUND,
          fallback: Any = None) -> Any:
    """Place a need on capability `to` and return the evidence picked up off the ground — the fire-and-
    collect convenience over a live `fabric`, where the round-trip is synchronous propagation (place need →
    provider fires → discharges evidence onto the ground → this reactor's ground connection picks it up).
    Returns `None` while nothing has resolved (silence stays silence). For the store-and-forward path, hold
    a `reactor(...)` and drive `pump`."""
    rc = reactor(store, principal, root_secret=root_secret, fabric=fabric, reach=reach_fn, ground=ground,
                 fallback=fallback)
    handle = rc.reach(need, to=to)
    return rc.evidence(handle)
