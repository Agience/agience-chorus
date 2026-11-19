"""A spend is charged to a budget: created in a collection edged by charged_to to a budget, the
create adds its amount to the budget's spent and stamps the budget's id; past the limit it is
refused. These types declare the rule; Mantle runs it as a bounded add."""
from __future__ import annotations

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "ui" / "application"


def _type(name: str) -> dict:
    return json.loads((APP / f"vnd.agience.{name}+json" / "type.json").read_text(encoding="utf-8"))


def test_the_spend_charges_the_budget_it_is_edged_to():
    t = _type("spend")
    assert t["fields"]["budget"]["on_create"] == {
        "from_edge": "charged_to", "amount": "amount", "to": "spent", "limit": "limit"}
    assert _type("budget")["on_create"] == {"does": "add"}


def test_a_spend_cannot_change_after_it_is_made():
    t = _type("spend")
    for path in ("amount", "budget"):
        assert t["context_schema"][path]["mutable"] is False, path
    assert all(not f["editable"] for f in t["ui"]["record"]["fields"])


def test_the_budget_holds_its_limit_and_what_is_spent():
    t = _type("budget")
    schema = t["context_schema"]
    assert schema["limit"]["type"] == schema["spent"]["type"] == "number"
    assert schema["spent"]["default"] == 0
    record = {f["path"]: f for f in t["ui"]["record"]["fields"]}
    assert record["limit"]["editable"] is True
    assert record["spent"]["editable"] is False
