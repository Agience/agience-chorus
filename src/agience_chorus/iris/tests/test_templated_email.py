"""Unit tests for the transactional-email helpers used by send_templated_email."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2]))            # src/  → `platform`
sys.path.insert(0, str(_HERE.parent))                # iris/


# 2026-08-26: an inline copy of this loader lived here. `src/_persona.py` is its one home
# and does strictly more — it pops the half-built module from `sys.modules` when
# `exec_module` raises, instead of leaving a broken one for the next importer, and it raises
# a ModuleNotFoundError naming the persona when the file is absent.
from agience_chorus import _persona  # noqa: E402

_server = _persona.load("server", __file__)


def test_resolve_field_content_path():
    content = {"email": "jane@x.com", "name": "Jane"}
    context = {"source": "website-contact"}
    assert _server._resolve_field("$.content.email", content, context) == "jane@x.com"
    assert _server._resolve_field("$.context.source", content, context) == "website-contact"


def test_resolve_field_bare_path_prefers_content():
    assert _server._resolve_field("$.email", {"email": "a@x.com"}, {"email": "b@x.com"}) == "a@x.com"
    assert _server._resolve_field("$.source", {}, {"source": "web"}) == "web"


def test_resolve_field_literal_passthrough():
    assert _server._resolve_field("connect@agience.ai", {}, {}) == "connect@agience.ai"


def test_render_template_substitutes_and_tolerates_missing():
    content = {"name": "Jane"}
    context = {"source": "website-contact"}
    out = _server._render_template("Hi {name} via {source} — ref {missing}", content, context)
    assert out == "Hi Jane via website-contact — ref "


def test_render_template_non_string():
    assert _server._render_template(None, {}, {}) == ""


def test_as_dict_parses_json_string_and_passthrough():
    assert _server._as_dict('{"a": 1}') == {"a": 1}
    assert _server._as_dict({"a": 1}) == {"a": 1}
    assert _server._as_dict("not json") == {}
    assert _server._as_dict("") == {}
