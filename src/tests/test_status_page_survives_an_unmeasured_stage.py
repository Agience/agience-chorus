"""The status page survives a curriculum stage nobody measured.

Moved here from `agience-ember/tests/test_keyed_arm.py` with the facet it tests. `browse.py` is a
FACET, so it lives in chorus with the other tools; ember is the workflow engine and no longer owns a
rendered view of what it holds.

The two engine modules the test patches — `improve` and `genesis` — are reached through the host
seams the facet itself uses, so the patch lands on the same object the page reads.
"""
from __future__ import annotations


def _seam_mod(name: str):
    from _host_seams import resolve
    return resolve(name)


def test_status_page_survives_an_unmeasured_curriculum_stage(monkeypatch):
    """D7: the status page renders a stage whose `have` is unmeasured, and renders it as
    "not measured" rather than as 0.

    A stage nobody measured and a stage measured at zero are different facts, so they read
    differently on the page. `f"{None:,}"` raises, so the formatting is guarded as well as the
    comparison — one unmeasured stage would otherwise take the whole page to a 500."""
    from aria.facets import browse
    improve = _seam_mod("improve")
    genesis = _seam_mod("genesis")
    monkeypatch.setattr(improve, "metrics", lambda b: {
        "rho": 1.0, "keyed_coverage": None, "dark_matter": 0, "avg_operator_fitness": 0.0,
        "total_artifacts": 1, "wordnet": 1, "content_docs": 1, "operators": 1, "symbols": 0,
        "bytes": 1, "generator_bytes": 1, "by_content_type": {}})
    monkeypatch.setattr(improve, "trend", lambda b, last=40: [])
    monkeypatch.setattr(genesis, "all_metrics", lambda b: {"collections": {}})
    monkeypatch.setattr(genesis, "health", lambda s: {
        "metrics": {}, "healthy": True, "worker": {}, "consistency": {}, "provenance": {},
        "curriculum": [
            {"stage": "lexicon", "have": None, "target": 500000, "progress": None,
             "promoted": False},
            {"stage": "worldst", "have": 12, "target": None, "progress": 0.5,
             "promoted": False}]})

    html = browse.status_page(object())
    assert "not measured" in html
    assert "0 / 500,000" not in html, "an unmeasured stage was rendered as a real zero"
