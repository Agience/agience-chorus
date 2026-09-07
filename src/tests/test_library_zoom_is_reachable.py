"""`/library` offers the zoom levels, and a caller can choose one.

With no resolution supplied the library returns the levels this corpus has, and `library_page`
renders them as `?resolution=<level>` links. Deferring the choice to the query is a measurement only
if the query can then make it: a handler that renders the links and parses `refresh=1` alone sends
every one of them back to the same offer page.

These cover the wiring rather than the clustering. `docs_ops`' own suite covers how the levels are
derived; this covers whether a chosen level survives the trip from the URL to the plan.
"""
from __future__ import annotations

import inspect

import pytest

from aria.facets import browse


@pytest.mark.skip(reason="NOTHING MOUNTS `browse` YET — the claim is recorded, not dropped")
def test_the_serve_path_PARSES_resolution_not_only_refresh():
    """The `/library` handler must read `resolution` off the query string, so the rendered links
    carry a choice rather than decoration.

    This asserted against `ember/surface/serve.py`, which served the facet routes until the facets
    moved here. Ember is the workflow engine and no longer serves them; aria serves facets as a
    FastAPI app behind crystal's host router, and `browse` is not mounted into one yet.

    So the subject of this test does not currently exist anywhere. It is kept, skipped, rather than
    deleted: the claim is about whatever ends up serving `/library`, and a deleted test is a claim
    nobody re-derives. Point it at the mount when there is one — the three tests below already
    cover the half that moved, `library_page` and `library_view` themselves.
    """


def test_library_page_and_view_BOTH_accept_a_resolution():
    """The parameter survives the whole trip: handler -> page -> view -> plan. A signature anywhere
    in that chain that stops carrying it leaves the handler parsing a value it then discards, which
    looks the same from outside as the parameter being ignored.
    """
    for fn in (browse.library_page, browse.library_view):
        assert "resolution" in inspect.signature(fn).parameters, fn.__name__


@pytest.mark.skip(reason="NOTHING MOUNTS `browse` YET — see the note above; the claim is kept")
def test_an_UNREADABLE_level_is_treated_as_NO_level_not_an_error():
    """`?resolution=banana` lands on the offer page. An unreadable level is no level, so the handler
    falls back to `resolution = None` and offers the choices again.

    An unguarded `float(...)` would take the whole page down on a malformed query string — and
    handing out those links is the page's own job.

    Like the test above, this reads the SERVING handler, which moved out of ember with the facets
    and has no home yet. Kept skipped so the claim survives the gap.
    """
    raise AssertionError(
        "unreachable: skipped until something mounts `browse`. Write the assertion against that "
        "mount — read its /library handler and check it parses `resolution` and falls back to None "
        "on an unreadable level, the two facts this docstring names.")


def test_the_view_CACHES_PER_RESOLUTION_not_per_root():
    """The resolution is part of the cache key. Keyed on `root` alone, `_LIB_CACHE` serves the first
    level asked for to every level after it, so the links resolve and return identical content —
    which reads as working.
    """
    src = inspect.getsource(browse.library_view)
    assert "(root, resolution)" in src or "key = (root" in src, (
        "the library cache is not keyed by resolution — every zoom would serve the first one asked for")
