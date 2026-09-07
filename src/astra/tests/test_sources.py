"""astra's outward-facing sources — UrlSource and DatasetSource.

`UrlSource` and `DatasetSource` live in astra because they reach the outside world (an external
fetch, a dataset load); the runner does not. Importing them via `from astra import sources` requires
chorus to be installed rather than relying on a permissive `PYTHONPATH`, so these tests exercise the
real installed package rather than a path the runner happens to know.

What they pin: the fetch is credited to `op.fetch.get` (it goes through the operator, not an inline
GET), a blocked or failed fetch emits nothing rather than an empty observation, the content type
prefers the file suffix over a generic server header, and DatasetSource maps its predicate/limit and
stamps what it observed.
"""
from __future__ import annotations

import sys
import types

import pytest

from astra import sources
from astra import sources as S


# ── sources: the read-only url ingest coalgebra ───────────────────────────────
def test_url_source_emits_once_per_change_and_credits_fetch_op():
    from ember.runtime.runner import fetch
    saved = fetch._get
    fetch._get = lambda a: {"ok": True, "url": a["url"], "status": 200,
                            "content_type": "text/markdown; charset=utf-8", "text": "# Doc\nhello"}
    try:
        s = sources.UrlSource("papers", ["https://example.com/a.md"])
        first = list(s.poll())
        assert len(first) == 1
        o = first[0]
        assert o.content_type == "text/markdown"
        # Provenance must be a real rung from prism.mass.Provenance — a string outside that enum
        # raises ValueError on write and would leave the artifact unwritten or degraded to UNKNOWN
        # (mass band 0.12-0.18) instead of OBSERVED's 0.90-0.98.
        from prism.mass import Provenance
        assert Provenance(o.provenance) is Provenance.OBSERVED, (
            "UrlSource must emit a valid rung; Ember fetching the bytes itself IS an observation")
        assert o.meta["via"] == "op.fetch.get" and o.meta["source_url"] == "https://example.com/a.md"
        assert list(s.poll()) == []                     # unchanged content -> no re-emit
        fetch._get = lambda a: {"ok": True, "url": a["url"], "status": 200,
                                "content_type": "text/markdown", "text": "# Doc\nCHANGED"}
        assert len(list(s.poll())) == 1                 # content changed -> emits again
    finally:
        fetch._get = saved


def test_url_source_skips_blocked_or_failed_fetches():
    from ember.runtime.runner import fetch
    saved = fetch._get
    fetch._get = lambda a: {"ok": False, "reason": "refusing internal/loopback host"}
    try:
        assert list(sources.UrlSource("x", ["http://127.0.0.1/y"]).poll()) == []
    finally:
        fetch._get = saved


def test_ct_from_response_header_then_suffix():
    assert sources._ct_from_response("text/markdown; charset=utf-8", "http://x/a") == "text/markdown"
    assert sources._ct_from_response("text/plain", "http://x/mod.py") == "text/x-python"   # suffix wins
    assert sources._ct_from_response("", "http://x/README.md") == "text/markdown"
    assert sources._ct_from_response("application/json", "http://x/data") == "application/json"


# ── DatasetSource coalgebra (no network — a fake in-memory dataset) ───────────
def test_datasetsource_maps_predicate_limit_and_stamp(monkeypatch):

    rows = [{"id": i, "title": f"T{i}", "text": ("word " * 40)} for i in range(10)]
    monkeypatch.setattr(S, "load_dataset" if hasattr(S, "load_dataset") else "load_dataset",
                        lambda *a, **k: iter(rows), raising=False)
    # Patch the symbol the method actually imports: `DatasetSource.poll` does
    # `from datasets import load_dataset` (`astra/sources.py:137`), so a module of that name has to
    # exist for the patch to land on.
    #
    # The REAL HuggingFace `datasets` is not needed and is not a chorus dependency: `load_dataset`
    # is replaced outright and the rows below are in memory, so the library would do no work even
    # if present. When it is absent, a stub module stands in — which keeps this test measuring
    # `DatasetSource`'s predicate/limit/stamp mapping everywhere, rather than skipping wherever a
    # large optional package happens not to be installed. It was passing only on machines that had
    # it; CI has never had it.
    try:
        import datasets
    except ModuleNotFoundError:
        datasets = types.ModuleType("datasets")
        monkeypatch.setitem(sys.modules, "datasets", datasets)
    monkeypatch.setattr(datasets, "load_dataset", lambda *a, **k: iter(rows), raising=False)

    src = S.DatasetSource(
        "fake", "org/fake", split="train",
        to_record=lambda row, i: {"content": row["text"], "content_type": "text/markdown",
                                  "lemmas": [row["title"].lower()], "id": "fake-" + str(row["id"])},
        predicate=lambda row: row["id"] % 2 == 0, limit=3,
        stamp={"collection_id": "stage.1.grammar", "cited_from": "cite.fake",
               "via": "op.source.fake", "provenance": "observed"})
    obs = list(src.poll())
    assert len(obs) == 3                         # limit honored after predicate
    assert all(o.meta["cited_from"] == "cite.fake" for o in obs)   # stamp merged
    assert all(o.meta["collection_id"] == "stage.1.grammar" for o in obs)
    assert obs[0].id == "fake-0" and obs[1].id == "fake-2"          # only even ids
