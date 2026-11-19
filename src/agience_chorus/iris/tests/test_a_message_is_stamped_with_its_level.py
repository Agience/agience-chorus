"""A message is typed (FR-032): its type declares the `level` stamp, so Mantle, not the sender,
says whether a person or an agent's session filed it."""
from __future__ import annotations

import json
from pathlib import Path

TYPE = (Path(__file__).resolve().parents[1] / "ui" / "application"
        / "vnd.agience.message+json" / "type.json")


def test_the_message_type_declares_the_level_stamp():
    t = json.loads(TYPE.read_text(encoding="utf-8"))
    assert t["content_type"] == "application/vnd.agience.message+json"
    assert t["fields"] == {"level": {"on_create": {"stamp": "level"}}}
    assert t["context_schema"]["level"]["values"] == ["typed", "agent"]
    for field in ("subject", "from", "to", "level"):
        assert t["context_schema"][field]["mutable"] is False
