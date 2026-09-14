"""Tests for install_package / export_package helpers in Lumen.

Focuses on the pure-logic helpers (_resolve_rewrite_value,
_infer_package_role) which encode the interesting behavior without
needing a running platform. The async tool coroutines themselves
(install_package, export_package) are exercised end-to-end in the
backend integration tests; here we verify the glue.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# Load lumen's server.py by path so its `_resolve_rewrite_value` /
# `_infer_package_role` helpers are guaranteed to come from lumen, not
# whichever persona's `server.py` happened to import first in a bulk run.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "chorus_lumen_server", _HERE.parent / "server.py"
)
_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_server)


# ---------------------------------------------------------------------------
#  _resolve_rewrite_value
# ---------------------------------------------------------------------------

class TestResolveRewriteValue:
    def test_workspace_artifact_id_token_resolves(self):
        ref_map = {
            "agience://packages/foo/prompts/order": "new-artifact-123",
        }
        result = _server._resolve_rewrite_value(
            "${workspace_artifact_id(agience://packages/foo/prompts/order)}",
            ref_map,
        )
        assert result == "new-artifact-123"

    def test_unknown_ref_returns_none(self):
        result = _server._resolve_rewrite_value(
            "${workspace_artifact_id(agience://packages/foo/prompts/unknown)}",
            {},
        )
        assert result is None

    def test_literal_value_passes_through(self):
        result = _server._resolve_rewrite_value("some literal string", {})
        assert result == "some literal string"

    def test_malformed_token_passes_through(self):
        """No-match on the regex means we treat it as a literal."""
        result = _server._resolve_rewrite_value(
            "${workspace_artifact_id(no closing",
            {"something": "else"},
        )
        assert result == "${workspace_artifact_id(no closing"

    def test_quoted_ref_unquoted(self):
        """Tolerate quoting inside the parens."""
        ref_map = {"agience://packages/foo/prompts/order": "new-id"}
        result = _server._resolve_rewrite_value(
            '${workspace_artifact_id("agience://packages/foo/prompts/order")}',
            ref_map,
        )
        assert result == "new-id"

    def test_whitespace_tolerated(self):
        ref_map = {"ref-1": "id-1"}
        result = _server._resolve_rewrite_value(
            "  ${workspace_artifact_id(ref-1)}  ",
            ref_map,
        )
        assert result == "id-1"


# ---------------------------------------------------------------------------
#  _infer_package_role
# ---------------------------------------------------------------------------

class TestInferPackageRole:
    @pytest.mark.parametrize("content_type,expected", [
        ("application/vnd.agience.transform+json", "transform"),
        ("application/vnd.agience.mcp-server+json", "server"),
        ("application/vnd.agience.prompts+json",   "prompt"),
        ("text/markdown",                          "docs"),
        ("text/markdown; charset=utf-8",           "docs"),
        ("application/json",                       "artifact"),
        ("image/png",                              "artifact"),
    ])
    def test_inferred_from_content_type(self, content_type, expected):
        assert _server._infer_package_role(content_type, {}) == expected

    def test_context_type_prompt_overrides_default(self):
        assert _server._infer_package_role(
            "application/json", {"type": "prompt"},
        ) == "prompt"

    def test_context_type_docs_overrides_default(self):
        assert _server._infer_package_role(
            "application/json", {"type": "docs"},
        ) == "docs"

    def test_unknown_context_type_falls_back(self):
        assert _server._infer_package_role(
            "application/json", {"type": "random-thing"},
        ) == "artifact"

    def test_content_type_beats_context_type(self):
        """Content type wins when it's a known package-role MIME."""
        assert _server._infer_package_role(
            "application/vnd.agience.transform+json",
            {"type": "docs"},  # should be ignored
        ) == "transform"


# ---------------------------------------------------------------------------
#  _package_block — where the store actually put the manifest
# ---------------------------------------------------------------------------

class TestPackageBlock:
    """`install_package` read only the TOP level and so could not install anything a user made.

    Mantle mints a context onto every create and nests the caller's own under `caller`, verbatim,
    by documented contract. A `POST /artifacts` carrying `{"package": {...}}` therefore lands as
    `context.caller.package`, not `context.package`. Measured against production 2026-09-11: the
    tool answered "Artifact is not a package (missing context.package)" for an artifact whose
    context carried the block one level down, and only create-then-PATCH worked — which nothing
    documents and no caller would guess.
    """

    def test_the_minted_shape_a_create_produces_is_found(self):
        ctx = {"addressing": {}, "minted": {}, "minted_by": "mantle.mint_context",
               "provenance": "unknown", "caller": {"package": {"id": "probe.demo"}}}
        assert _server._package_block(ctx) == {"id": "probe.demo"}

    def test_the_flat_shape_a_patch_produces_is_found(self):
        assert _server._package_block(
            {"collections": [], "package": {"id": "probe.demo"}}) == {"id": "probe.demo"}

    def test_an_explicit_patch_overrides_what_the_mint_recorded(self):
        """Flat wins: a PATCH is a deliberate statement, the mint is a record of the create."""
        ctx = {"package": {"id": "patched"}, "caller": {"package": {"id": "minted"}}}
        assert _server._package_block(ctx)["id"] == "patched"

    def test_an_artifact_that_is_not_a_package_still_reads_as_one_that_is_not(self):
        """The negative case, or the two lookups above would just always find something."""
        assert _server._package_block({"addressing": {}, "caller": {}}) == {}
        assert _server._package_block({}) == {}

    def test_a_non_dict_context_does_not_raise(self):
        """Context is caller-supplied and may be an opaque string; a reader must not explode."""
        assert _server._package_block("not a dict") == {}
        assert _server._package_block(None) == {}

    def test_an_empty_package_block_is_not_a_package(self):
        """`{}` is falsy for the caller's purposes — it carries no id, version or contents."""
        assert _server._package_block({"package": {}, "caller": {"package": {"id": "x"}}}) == {"id": "x"}
