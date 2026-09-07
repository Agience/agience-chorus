"""Wires the communication plane to the fleet's access and crypto layer — a single mechanism, with no
second sharing path.

The plane's `Lightcone` (who reaches which artifact) and `Keyring` (the per-group key) are pluggable
contracts declared in `prism/plane.py`. In tests they are the in-memory models; in production they are
the grant-backed pair that lives in `mantle/db/plane.py` — `LatticeLightcone` / `LatticeKeyring`,
re-exported here under their historical `Mantle*` names so iris's own callers keep working:

  - `MantleLightcone` = `mantle.db.plane.LatticeLightcone` — the read light-cone over CRUDEASIO
                        grants + containment, via `mantle.db.access.reachable_collections`. Comms
                        delivery IS read-access.
  - `MantleKeyring`   = `mantle.db.plane.LatticeKeyring` — per-group AES-256 keys from the same
                        content-key derivation mantle uses at rest (`collection_key = HKDF(root, origin_root)`).

The backings are mantle's: `LatticeLightcone` and `LatticeKeyring` import only `mantle.db.access`
and `mantle.db.content_cache`, nothing else. The `Mantle*` alias exists so callers keep their
historical name while there is exactly one implementation, in `mantle/db/plane.py`.
`sage/reach_provider.py` and `lumen/reach_provider.py` import the same mantle pair directly — one
definition, no persona-to-persona import (`chorus/src/tests/test_persona_isolation.py` pins the count),
and no chorus-to-ember edge.

The comms plane's per-group keying is a distinct property from content-at-rest, which uses one node-wide
key (`shared_content_key`) because per-collection keying would contradict global content addressing — one
immutable object at one address can have only one key. The comms plane has no such constraint: its
per-group keying is real isolation, since a principal derives a group key only if its light-cone reaches
that group. `mantle.db.content_cache.collection_key` remains in use for this caller; the
implementation this keyring calls is `LatticeKeyring.group_key`, in the same package as the function it
names.

`build_plane(node, store, root_secret, carriers)` assembles a live `Plane` from these. The carriers are the
production substrates (`NasCarrier` on the shared `_comms/` folder, `S3Carrier` on the mesh bucket) — see
`prism/carriers.py`. Deploying against the real bucket/NAS is gated by the standing local-only rule; this
module is the wiring and its behaviour, tested against fakes.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from prism.plane import Plane

# The historical iris-side names, resolved lazily (PEP 562) to the one implementation in
# `mantle.db.plane`. Never a subclass and never a copy — a subclass would be a second place for
# behaviour to drift into.
#
# Lazy on purpose: `LatticeLightcone` reaches `mantle.db.access` from inside `_reachable()`, and a
# module-level import here would make the whole lattice package an import-time dependency of iris's comms
# package for callers that only ever touch `Plane`. `__getattr__` keeps the import surface minimal while
# still giving one implementation.
_LAZY = {"MantleLightcone": "LatticeLightcone", "MantleKeyring": "LatticeKeyring",
         "EmberLightcone": "LatticeLightcone", "EmberKeyring": "LatticeKeyring"}


def __getattr__(name: str):
    if name in _LAZY:
        from mantle.db import plane as _mp
        return getattr(_mp, _LAZY[name])
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def build_plane(*, node: str, store: Any, root_secret: bytes, carriers,
                reach: Optional[Callable[[Any, str], Iterable[str]]] = None, clock=None) -> Plane:
    """Assemble a live `Plane` for `node` on the real access + crypto + the given production carriers."""
    from mantle.db.plane import LatticeKeyring, LatticeLightcone   # lazy: only a wired host binds these
    lightcone = LatticeLightcone(store, reach=reach)
    keyring = LatticeKeyring(root_secret)
    return Plane(node=node, keyring=keyring, lightcone=lightcone, carriers=carriers, clock=clock)


__all__ = ["MantleLightcone", "MantleKeyring", "EmberLightcone", "EmberKeyring", "build_plane"]
