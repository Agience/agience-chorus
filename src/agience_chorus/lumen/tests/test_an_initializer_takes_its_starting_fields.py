"""An initializer's starting fields are set in its record view: the layout marks `fields` as an
open object, and the record view adds and removes fields by any name in such an object."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TYPE = json.loads((ROOT / "lumen" / "ui" / "application" / "vnd.agience.initializer+json"
                   / "type.json").read_text(encoding="utf-8"))
VIEW = (ROOT / "astra" / "ui" / "record" / "view.html").read_text(encoding="utf-8")


def test_the_layout_marks_the_starting_fields_open():
    objects = TYPE["ui"]["record"]["objects"]
    assert {"path": "fields", "label": "Starting fields", "open": True} in objects
    assert TYPE["context_schema"]["fields"]["type"] == "object"


def test_the_record_view_adds_and_removes_fields_of_an_open_object():
    assert "f.open" in VIEW
    assert "placeholder: 'Field name'" in VIEW and "'Add field'" in VIEW
    assert "'Remove'" in VIEW and "delete rest[key]" in VIEW


def test_an_empty_open_object_is_edited_rather_than_skipped():
    assert "if (!(editsThis && f.open)) continue;" in VIEW
