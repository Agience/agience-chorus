"""lumen's per-persona operator manifest — it declares exactly the op.* it owns (no shared catalog)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

from agience_chorus import _persona  # noqa: E402

# `sys.modules` is keyed by name and process-global, so a bare `import reach_provider` /
# `import manifest` resolves to whichever persona imported it first — several personas own a
# module by each of those names, and in a combined chorus run that misdirects sage's tests to
# lumen's provider (`AttributeError: … no attribute 'serve_retrieve'`). `_persona.load` loads
# this persona's copy under the unique name `<persona>.<module>`, so that substitution is
# impossible.
manifest = _persona.load("manifest", __file__)


def test_manifest_declares_only_lumens_operators():
    ids = {o["id"] for o in manifest.OPERATORS}
    # op.reason + op.math.* (13) + op.check.* (2) + op.dev.* (8) = 24; op.retrieve is not here (sage's).
    assert "op.reason" in ids
    assert {i for i in ids if i.startswith("op.math.")} and len({i for i in ids if i.startswith("op.math.")}) == 13
    assert {i for i in ids if i.startswith("op.check.")}
    assert {i for i in ids if i.startswith("op.dev.")}
    assert "op.retrieve" not in ids, "op.retrieve is sage's — lumen reaches it, never owns it"


def test_every_manifest_operator_is_wellformed():
    # The register fn is the source of truth for the def it writes (id/content/content_type/created_by).
    # offer/needs/entry (discovery + execution) are enrichment added when the manifest is published;
    # per-persona enrichment is a flagged Phase-2 seam.
    for o in manifest.OPERATORS:
        assert o["id"].startswith("op.")
        assert o["content_type"] == "application/vnd.agience.operator+json"
        assert (o.get("content") or "").strip()


def test_collect_counts_match_the_manifest():
    assert manifest.collect() == len(manifest.OPERATORS)
