"""A timer's times are stored as UTC and shown and picked in local time. The type declares how each
time field is shown and edited, and the timer's view uses the editor the type names: a date-time
picker for a one-off run, a time picker for a daily one, never a free-text ISO box."""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "ui" / "application" / "vnd.agience.timer+json"
TYPE = json.loads((HERE / "type.json").read_text(encoding="utf-8"))
VIEW = (HERE / "view.html").read_text(encoding="utf-8")

EDITOR_INPUT = {"datetime": "datetime-local", "time": "time", "number": "number"}


def _schedule_fields():
    return TYPE["context_schema"]["timer"]["properties"]["schedule"]["properties"]


def test_the_type_declares_local_display_and_a_picker_for_each_time_field():
    s = _schedule_fields()
    assert s["at"]["format"] == "date-time" and s["at"]["display"] == "local"
    assert s["at"]["editor"] == "datetime"
    assert s["daily_at"]["format"] == "time" and s["daily_at"]["display"] == "local"
    assert s["daily_at"]["editor"] == "time"
    last = TYPE["context_schema"]["timer_state"]["properties"]["last_run"]
    assert last["format"] == "date-time" and last["display"] == "local"


def test_the_view_uses_the_editor_the_type_names():
    for kind, field in _schedule_fields().items():
        want = EDITOR_INPUT[field["editor"]]
        m = re.search(r'<input[^>]*data-kind="%s"[^>]*>' % kind, VIEW)
        assert m, kind
        assert f'type="{want}"' in m.group(0), (kind, m.group(0))


def test_the_view_has_no_free_text_time_box():
    assert "ISO time" not in VIEW
    assert 'id="scheduleValue"' not in VIEW
    assert "UTC)" not in VIEW


def test_last_run_is_shown_in_local_time():
    assert "localText(st.last_run)" in VIEW
    assert "toLocaleString()" in VIEW
