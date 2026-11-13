"""An agent's memory is typed artifacts in its own collection (FR-019): each one a feedback,
project, reference or user fact, with a slug other memories link to and a one-line summary the
agent reads to decide relevance when it loads its index at session start."""
from __future__ import annotations

import json
from pathlib import Path

TYPE = (Path(__file__).resolve().parents[1] / "ui" / "application"
        / "vnd.agience.agent-memory+json" / "type.json")


def test_the_memory_type_names_its_kinds_and_index_fields():
    t = json.loads(TYPE.read_text(encoding="utf-8"))
    assert t["content_type"] == "application/vnd.agience.agent-memory+json"
    s = t["context_schema"]
    assert s["kind"]["type"] == "enum"
    assert s["kind"]["values"] == ["feedback", "project", "reference", "user"]
    for field in ("name", "summary", "agent", "title"):
        assert s[field]["type"] == "string" and s[field]["mutable"] is True
    assert t["ui"]["creatable"] is True and t["ui"]["is_container"] is False
