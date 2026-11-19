"""An install is one release installed on one node: its node, release, time, wheels by sha256 and
commits never change after it is made. Only its validation does."""
from __future__ import annotations

import json
from pathlib import Path

TYPE = (Path(__file__).resolve().parents[1] / "ui" / "application"
        / "vnd.agience.install+json" / "type.json")


def _schema():
    t = json.loads(TYPE.read_text(encoding="utf-8"))
    assert t["content_type"] == "application/vnd.agience.install+json"
    return t["context_schema"]


def test_what_was_installed_never_changes():
    schema = _schema()
    for key in ("node", "release", "item", "at", "wheels", "commits", "installed"):
        assert schema[key]["mutable"] is False, key


def test_only_its_title_and_validation_change():
    schema = _schema()
    assert sorted(k for k, v in schema.items() if v["mutable"]) == ["title", "validated"]


def test_wheels_and_commits_map_names_to_digests():
    schema = _schema()
    for key in ("wheels", "commits"):
        assert schema[key]["type"] == "object"
        assert schema[key]["additionalProperties"] == {"type": "string"}
