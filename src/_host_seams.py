"""Host seams, for chorus code that is not a bundle — chorus declares what it needs, and the host that
runs it answers.

`agience-chorus/requirements.txt` does not declare ember, and the shipped chorus image installs prism,
beam, and crystal only, so chorus code cannot import ember directly: ember and chorus are both L3, and
the layer model in `ARCHITECTURE-TARGET.md` §2 forbids sideways edges between them. Chorus code uses a
seam instead of an ember import.

MEASURED 2026-08-26: **48 seam call sites across 23 files**, over six names — `activation`,
`delegate`, `forgetting`, `match`, `optics`, `projection`. The list is deliberately NOT written out
here, because the hand-written version was: it named six files and two seam names while the tree had
grown past it, understating chorus's dependence on ember behaviour nearly fourfold in the one
document that exists to make that dependence reviewable. It also still claimed
`src/sage/match.py seam("activation")`, which that file no longer calls.

To re-derive the current list, from `agience-chorus/src` (no escapes, so it pastes cleanly):

    grep -rnE '_?seam[(]"' --include=*.py . | grep -v _host_seams.py

The shape, as of that measurement: the `activation`/`delegate`/`match` seams are the persona request
paths (`lumen/conversation.py`, `lumen/reach_provider.py`, `sage/*`, `reach_host.py`), and
`optics`/`projection`/`forgetting` carry the reading stack — `astra/reading/` and `lumen/reading/`,
twelve files, which is the bulk of it and which the old list did not mention at all.

The mechanism mirrors `prism/runner.py`'s bundle wiring, where the seam-to-module mapping is registered
by the host (`register_seam`); ember binds `match` the same way for the `operators` bundle.
`sage/canon.py` and `aria/web_bff.py` read seams the same way.

A seam is not merely a dependency written differently:

1. Chorus never names ember. The value bound to `"activation"` is `ember.ontology.activation` on an
   ember host. A fork, a store-only node, or a test may bind something else, and this module does not
   know or care which.
2. Nothing is imported by declaring. `register_seam` stores a dotted string. A process that never
   reaches `seam("projection").frame(...)` never imports `ember.signal.projection`.
3. An unfilled seam refuses; it never substitutes. Resolution goes through
   `prism.runner.registered_seams()` and nowhere else — never `importlib.import_module(name)` on the
   bare seam name, never `sys.path`. A module named `match` sitting on the path is not reachable from
   here; `tests/test_chorus_does_not_import_ember.py::test_an_UNFILLED_seam_RAISES_and_never_takes_a_module_lying_in_sys_modules`
   proves this with a planted decoy.

`HostSeamUnfilled` subclasses `ImportError` so call sites that guard an ember import with
`except ImportError` or `except Exception` keep their existing refusal on exactly the same input:
`except Exception: return cand, {"reach": "unavailable"}, set()`,
`except Exception: _basis = None`, `except ImportError: return`. Raising an `ImportError` subclass at the
point of use, rather than at import, preserves those refusal paths.

A seam changes how a dependency is wired, not whether one is needed: a node that wants sage to rank by
measured reach still needs something that measures it. The seam makes that dependency declared and
substitutable instead of compiled in.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Optional


class HostSeamUnfilled(ImportError):
    """No host registered a module for this seam name.

    A subclass of `ImportError` so that a call site guarding the equivalent ember import with
    `except ImportError` / `except Exception` keeps its exact refusal on exactly the same input.
    See the module docstring."""


def target(name: str) -> Optional[str]:
    """The dotted module a host bound to seam `name`, or None when nobody bound one.

    `prism.runner.registered_seams()` is the only source, read fresh on every call rather than cached:
    a host registers at boot, and a cached miss taken during import would outlive the registration that
    was supposed to fix it."""
    from prism.runner import registered_seams
    return registered_seams().get(str(name)) or None


def filled(name: str) -> bool:
    """Has a host bound this seam? A question, never a threshold — a caller that wants to degrade
    honestly reads this instead of catching the refusal."""
    return target(name) is not None


def resolve(name: str) -> ModuleType:
    """Import the module a host bound to seam `name`. Raises `HostSeamUnfilled` when none is bound.

    There is no fall-through to `sys.path`: `importlib.import_module` is called on the host's dotted
    target, never on the seam name, so a module that happens to be importable under the seam's own name
    can never be bound by accident. The decoy in
    `tests/test_chorus_does_not_import_ember.py` checks this directly."""
    dotted = target(name)
    if dotted is None:
        raise HostSeamUnfilled(
            "host seam %r is unfilled: no host called prism.runner.register_seam(%r, ...). Chorus "
            "DECLARES what it needs and the host says which module fills it — on an ember runner "
            "that binding happens in `ember/runtime/seams.py` at import of `ember`. Bound here: %s"
            % (name, name, sorted(_bound()) or "(nothing)"))
    return importlib.import_module(dotted)


def _bound() -> dict:
    from prism.runner import registered_seams
    return registered_seams()


class _Seam:
    """A host seam, usable as though it were the module — resolved on first attribute access.

    Laziness is load-bearing, not an optimisation. `seam("activation")` at a module's top keeps the
    import graph as flat as `from ember.ontology import activation` looks, while moving the actual
    resolution to the moment a measurement is asked for — by which time a host has booted and bound its
    seams. Eager resolution at import would require every importer of `lumen/conversation.py` to already
    be a host.

    Dunder access is refused without resolving: `copy`, `pickle`, `inspect`, and pytest all probe
    `__wrapped__` / `__bases__` / `__iter__` on arbitrary objects, and letting those resolve the seam
    would turn a repr in a traceback into an import of the host."""

    __slots__ = ("_seam_name", "_seam_module")

    def __init__(self, name: str) -> None:
        self._seam_name = str(name)
        self._seam_module = None

    def __repr__(self) -> str:                      # never resolves; see the class docstring
        state = "resolved" if self._seam_module is not None else (
            "bound to %s" % target(self._seam_name) if filled(self._seam_name) else "UNFILLED")
        return "<host seam %r (%s)>" % (self._seam_name, state)

    def __getattr__(self, attr: str):
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(attr)
        module = self._seam_module
        if module is None:
            module = resolve(self._seam_name)
            self._seam_module = module
        return getattr(module, attr)


def seam(name: str) -> _Seam:
    """Declare a host seam by name. Reads like the module it stands for; resolves on first use.

        _A = seam("activation")          # at module scope — binds nothing
        ...
        _A.recognize(store, text)        # resolves now, or raises HostSeamUnfilled
    """
    return _Seam(name)


__all__ = ["HostSeamUnfilled", "seam", "resolve", "target", "filled"]
