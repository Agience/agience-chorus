# Operator code lives in chorus. Distributed to hosts as a content-addressed source bundle
# (definitions/build_bundles.py); ember executes it via ember/runner.py, sha-verified before
# exec. There are no code mirrors.
"""The Answer shape returned by this package's operator implementations.

Field-identical to ember's own `Answer` (defined in `ember/engine.py`, alongside the Engine
protocol, Evidence, and retrieval machinery — reasoning-stack code that stays an ember concern),
so answers built here cross the boundary to ember unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Answer:
    text: str
    grounded: bool                       # False => we declined rather than guessed
    cited: List[str] = field(default_factory=list)   # evidence ids the answer rests on
    read: dict = field(default_factory=dict)         # the reasoning read (engine-specific)

    @property
    def refused(self) -> bool:
        return not self.grounded
