"""No type names a process's levels. Levels are approval-level artifacts each workspace makes, so a
node that loads these types carries no one's process."""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "ui" / "application"
LEVEL_NAMES = re.compile(r"Routine|Costed|Outward|Governance")


def test_no_type_json_names_a_level():
    named = [str(p.relative_to(APP)) for p in APP.rglob("type.json")
             if LEVEL_NAMES.search(p.read_text(encoding="utf-8"))]
    assert named == []
