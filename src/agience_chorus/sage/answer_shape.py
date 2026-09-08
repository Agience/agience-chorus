"""The `Answer` shape sage's content-search tektons return.

Sage owns this dataclass rather than importing it from ember, because personas may not import each
other and may not reach into ember's bundle distribution path for a contract. The shape is
field-identical to `lumen/answer.py`, which is the precedent: each persona owns the shape its own
tektons return, and two personas holding a field-identical four-field dataclass is the cost of that
rule rather than duplication of a shared type.

Field-identical is deliberate and load-bearing: `read` carries the engine-specific measurement and
`cited` the evidence ids, so an answer produced here crosses the reach boundary unchanged and a
caller cannot tell which persona built it. `grounded=False` means the surface declined to answer —
a refusal, never a low-confidence guess, which is the honesty contract of this surface.
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
