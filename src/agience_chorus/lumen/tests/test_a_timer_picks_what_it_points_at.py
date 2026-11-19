"""Each artifact a timer points at (its target, where runs are recorded, where a failure is raised)
is a link field the type declares, chosen with the app's picker and shown by title. The view has no
box to type an id into."""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "ui" / "application" / "vnd.agience.timer+json"
TYPE = json.loads((HERE / "type.json").read_text(encoding="utf-8"))
VIEW = (HERE / "view.html").read_text(encoding="utf-8")


def _timer_fields():
    p = TYPE["context_schema"]["timer"]["properties"]
    return {"target": p["target"]["properties"]["artifact_id"],
            "results_to": p["results_to"], "inbox_to": p["inbox_to"]}


def test_the_type_declares_each_pointer_as_a_link_field():
    for name, field in _timer_fields().items():
        assert field["editor"] == "link", name
    assert set(_timer_fields()["target"]["x-content-types"]) == {
        "application/vnd.agience.transform+json", "application/vnd.agience.operator+json"}


def test_each_link_field_is_chosen_with_the_picker():
    assert "ui/open-picker" in VIEW and "ui/notifications/picker-result" in VIEW
    for name in _timer_fields():
        assert f'data-choose="{name}"' in VIEW, name
        assert f'data-pick-for="{name}"' in VIEW, name


def test_the_view_has_no_id_text_box():
    inputs = re.findall(r"<input[^>]*>", VIEW)
    assert all("data-kind=" in i or 'id="operation"' in i for i in inputs), inputs
    for gone in ('id="target"', 'id="resultsTo"', 'id="inboxTo"', "artifact id"):
        assert gone not in VIEW, gone


def test_a_pick_is_shown_by_its_title():
    assert "titles[k] || id" in VIEW
    assert "timer.titles" in VIEW
