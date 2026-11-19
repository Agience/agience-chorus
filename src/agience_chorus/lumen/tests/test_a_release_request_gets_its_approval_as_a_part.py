"""A release request gets its approval as a part: filed in a collection edged by initialized_by to
an initializer, the create makes an approval in the initializer's home and stamps its id on the
request. Who decides is whoever holds update on that home; Mantle stamps who and when."""
from __future__ import annotations

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "ui" / "application"


def _type(name: str) -> dict:
    return json.loads((APP / f"vnd.agience.{name}+json" / "type.json").read_text(encoding="utf-8"))


def test_the_request_takes_its_part_from_the_initializer_it_is_edged_to():
    t = _type("release-request")
    assert t["content_type"] == "application/vnd.agience.release-request+json"
    assert t["fields"]["part"]["on_create"] == {"from_edge": "initialized_by"}
    assert _type("initializer")["on_create"] == {"does": "create"}


def test_what_the_request_asks_for_cannot_change_after_it_is_filed():
    schema = _type("release-request")["context_schema"]
    for path in ("level", "kind", "action", "action_digest", "part"):
        assert schema[path]["mutable"] is False, path
    # The level is the id of an approval-level artifact; the type names no level.
    assert schema["level"]["type"] == "string" and "values" not in schema["level"]


def test_the_approval_carries_its_level_shown_and_not_editable():
    t = _type("approval")
    level = t["context_schema"]["level"]
    assert level["type"] == "string" and level["mutable"] is False and "values" not in level
    record = {f["path"]: f for f in t["ui"]["record"]["fields"]}
    assert record["level"]["editable"] is False


def test_a_level_is_plain_data_each_workspace_makes():
    t = _type("approval-level")
    assert t["content_type"] == "application/vnd.agience.approval-level+json"
    assert "on_create" not in t and "fields" not in t
    assert t["ui"]["creatable"] is True
    assert set(t["context_schema"]) == {"title", "description"}


def test_the_approval_s_decider_and_time_are_stamped_from_the_update_that_sets_its_state():
    t = _type("approval")
    assert t["context_schema"]["state"]["values"] == ["pending", "approved", "declined"]
    assert t["fields"]["decided_by"] == {"on_update": {"stamp": "caller", "when": "state"}}
    assert t["fields"]["decided_at"] == {"on_update": {"stamp": "time", "when": "state"}}
    record = {f["path"]: f for f in t["ui"]["record"]["fields"]}
    assert record["state"]["options"] == t["context_schema"]["state"]["values"]
    assert record["decided_by"]["editable"] is False and record["decided_at"]["editable"] is False
    # An approval is made by its request's create, never by hand.
    assert t["ui"]["creatable"] is False


def test_neither_type_holds_a_secret():
    for name in ("release-request", "approval", "approval-level"):
        schema = _type(name)["context_schema"]
        assert not any(v.get("secret") for v in schema.values()), name
