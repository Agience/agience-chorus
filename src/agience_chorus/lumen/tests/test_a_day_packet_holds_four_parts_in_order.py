"""A day packet (FR-034) is one artifact a day in Reports, for its person's sitting: yesterday's
outcomes, the decisions needed, tomorrow's plan and the risks, always in that order. Each outcome
names its source, each decision has two to four choices and a default, and each plan item has its
level and names the request that approves it. The packet approves nothing."""
from __future__ import annotations

import json
from pathlib import Path

TYPE = (Path(__file__).resolve().parents[1] / "ui" / "application"
        / "vnd.agience.day-packet+json" / "type.json")


def _type():
    return json.loads(TYPE.read_text(encoding="utf-8"))


def test_its_four_parts_are_lists_in_order():
    t = _type()
    assert t["content_type"] == "application/vnd.agience.day-packet+json"
    schema = t["context_schema"]
    parts = [k for k in schema if schema[k].get("type") == "array"]
    assert parts == ["outcomes", "decisions", "plan", "risks"]
    for part in parts:
        assert schema[part]["default"] == [] and schema[part]["mutable"] is True


def test_each_outcome_names_its_source_and_each_plan_item_its_level():
    schema = _type()["context_schema"]
    assert schema["outcomes"]["items"]["required"] == ["line", "source"]
    assert schema["plan"]["items"]["required"] == ["line", "level"]
    assert "request" in schema["plan"]["items"]["properties"]
    assert schema["risks"]["items"]["required"] == ["risk", "response"]


def test_a_decision_has_two_to_four_choices_and_a_default():
    item = _type()["context_schema"]["decisions"]["items"]
    choices = item["properties"]["choices"]
    assert (choices["minItems"], choices["maxItems"]) == (2, 4)
    assert item["required"] == ["question", "choices", "default"]


def test_its_day_does_not_change_and_it_holds_no_decision_of_its_own():
    t = _type()
    assert t["context_schema"]["date"]["mutable"] is False
    assert "state" not in t["context_schema"] and "fields" not in t
    assert t["ui"]["states"] == ["view"]
    assert t["ui"]["resource_uri"] == "ui://astra/vnd.agience.record.html"
