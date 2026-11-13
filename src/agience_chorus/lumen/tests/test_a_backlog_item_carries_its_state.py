"""A backlog item carries where it is in the platform loop, and the chair report reads it
(G6, 2026-11-12): open → working (on next) → in_cut (on the day's release branch) → validated
(on 71/test) → shipped (promoted) → closed (out of the open Backlog, with the release it closed in)."""
from __future__ import annotations

import json
from pathlib import Path

TYPE = (Path(__file__).resolve().parents[1] / "ui" / "application"
        / "vnd.agience.backlog-item+json" / "type.json")


def test_the_states_are_the_loop_in_order_and_editable():
    t = json.loads(TYPE.read_text(encoding="utf-8"))
    assert t["content_type"] == "application/vnd.agience.backlog-item+json"
    state = t["context_schema"]["state"]
    assert state["type"] == "enum" and state["mutable"] is True
    assert state["values"] == ["open", "working", "in_cut", "validated", "shipped", "closed"]
    assert t["context_schema"]["size"]["values"] == ["S", "M", "L"]
    assert t["ui"]["creatable"] is True and t["ui"]["viewer"] == "record"


def test_a_closed_item_names_the_release_it_closed_in():
    t = json.loads(TYPE.read_text(encoding="utf-8"))
    closed_in = t["context_schema"]["closed_in"]
    assert closed_in["type"] == "string" and closed_in["mutable"] is True
    assert "YYYYMM.DD.N" in closed_in["description"]
