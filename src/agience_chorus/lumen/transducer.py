"""The language-concept conversion — lumen's transducer facet binding.

A transducer is a surface-concept conversion (a Crystal facet's `Lens`): forward `entry`
(surface→concept), inverse `render` (concept→surface), and running the two to recover the surface
is its losslessness certificate. These conversion classes are the persona-owned facet binding
(F2: lumen owns the language-transducer binding — `Crystal.bind(entry=, inverse=)`); ember keeps
only the measurement read (`crystal.ontology.transducer.persisted_xi` reads the stored ξ) plus the
constants. The artifact read is measurement (ember); the entry/render conversion is the persona
facet (lumen).

lumen→ember is the allowed direction — the shared concept lattice (IS-A tree, IC, geometry) is read
transducer-neutrally through `ember.ontology.wn_store` (keyed, lazy); ember imports nothing back.
Each transducer converts only to/from that one pivot, so a membrane between two transducers is the
composition of their conversions through it — `N` transducer artifacts, never `N²`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from crystal.ontology import driver as _wn
from prism.grounding import TRANSDUCER_OP       # the op-id prefix: `op.transducer.<name>`
from crystal.ontology.transducer import _REG    # the shared instance cache — ember-side (seed_lattice.build
                                                 # clears it after a (re)write; ember can't reach lumen)


class Transducer:
    """A transducer, read from its artifact. Forward is `entry` (surface → concept id); inverse is `render`
    (concept id → surface). Bi-directional by definition."""

    def __init__(self, doc: Dict[str, Any]):
        self.doc = doc or {}
        spec = dict(self.doc.get("spec") or {})
        self.spec = spec
        self.name = str(spec.get("name") or (self.doc.get("id") or "").replace(TRANSDUCER_OP, ""))
        self.entry_label = spec.get("entry_label")
        self.lang = spec.get("lang")

    def frame(self) -> Tuple[Optional[str], Optional[str]]:
        """The (T, F) axes this transducer is ordered on."""
        return (self.spec.get("frame_t"), self.spec.get("frame_f"))

    def entry(self, surface: str) -> List[str]:          # forward: surface → concept ids
        raise NotImplementedError

    def render(self, concept_id: str) -> Optional[str]:  # inverse: concept id → surface
        raise NotImplementedError

    def lossless(self, surface: str) -> bool:
        """The conservation certificate: forward then inverse recovers the surface."""
        cids = self.entry(surface)
        return any(self.render(c) == surface for c in cids)


class LanguageTransducer(Transducer):
    """A language:<lang> transducer. Entry is the keyed `lex:<lang>` reverse lookup (via `wn_store`); render
    is the concept's primary surface form in this language."""

    def entry(self, surface: str) -> List[str]:
        return [s.name() for s in _wn.synsets(surface)]

    def render(self, concept_id: str) -> Optional[str]:
        try:
            s = _wn.synset(concept_id)
        except Exception:
            return None
        lems = [l.name() for l in s.lemmas()]
        return lems[0] if lems else None


class StubTransducer(Transducer):
    """A transducer whose surface we cannot yet measure (space, economy). Its artifact records the frame;
    its conversion is defined when the measurement exists."""

    def entry(self, surface: str) -> List[str]:
        return []

    def render(self, concept_id: str) -> Optional[str]:
        return None


_KINDS = {"language": LanguageTransducer, "space": StubTransducer, "economy": StubTransducer}


def get_transducer(name: str) -> Optional[Transducer]:
    """The transducer named `name` (e.g. "language.en"), read from `op.transducer.<name>` and cached. None if it
    has not been defined (built) yet."""
    if name not in _REG:
        try:
            doc = _wn._arts().get_artifact(TRANSDUCER_OP + name)
        except Exception:
            doc = None
        if not doc:
            return None
        kind = str((doc.get("spec") or {}).get("kind", "language"))
        _REG[name] = _KINDS.get(kind, LanguageTransducer)(doc)
    return _REG.get(name)


__all__ = ["Transducer", "LanguageTransducer", "StubTransducer", "get_transducer"]
