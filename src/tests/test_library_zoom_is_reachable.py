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

from agience_chorus.aria.facets import browse, browse_routes

pytest.importorskip("mcp.server.fastmcp", reason="the facet is served by aria's FastMCP app")
from mcp.server.fastmcp import FastMCP                # noqa: E402
from starlette.testclient import TestClient           # noqa: E402

try:
    from _fakes import _FakeStore                     # ember's double, via src/conftest.py
except ImportError:                                    # pragma: no cover
    _FakeStore = None


def _client(store):
    """Aria's surface, built the way `create_aria_app` builds it — a FastMCP instance, then the
    Starlette app it generates. Driving the route is the only way to learn what the query string
    actually does; reading the handler's source only learns how it was spelled."""
    mcp = FastMCP("aria-test")
    browse_routes.mount_browse(mcp, lambda: store)
    return TestClient(mcp.streamable_http_app(), raise_server_exceptions=False)


@pytest.mark.skipif(_FakeStore is None, reason="no agience-ember checkout — its store double is used")
def test_the_serve_path_PARSES_resolution_not_only_refresh():
    """The `/library` handler must read `resolution` off the query string, so the rendered links
    carry a choice rather than decoration.

    THIS TEST HAD NO BODY. It carried this docstring and asserted nothing, so it passed on every
    tree it was ever run against, including ones where the handler ignored the parameter entirely —
    the exact failure it names. It now drives the route.

    The claim is narrow and behavioural: asking for a level must not return the same bytes as
    asking for nothing. A handler that parses `refresh` alone sends every rendered link back to the
    offer page, and that is what this catches.

    The value the page receives is RECORDED rather than inferred from rendered bytes: a fake corpus
    offers no zoom levels, so comparing pages could only ever skip. What is always true, and is the
    whole claim, is that `?resolution=0.42` reaches `library_page` as `0.42`, and a bare `/library`
    reaches it as `None`.
    """
    seen = []
    real = browse.library_page
    browse.library_page = lambda store, **kw: (seen.append(kw.get("resolution")), "<html></html>")[1]
    try:
        c = _client(_FakeStore())
        assert c.get("/library?resolution=0.42").status_code == 200
        assert c.get("/library").status_code == 200
    finally:
        browse.library_page = real

    assert seen == [0.42, None], (
        "the handler passed %r to library_page. A handler that parses `refresh` alone passes None "
        "for every rendered link, which sends them all back to the offer page." % (seen,))


def test_library_page_and_view_BOTH_accept_a_resolution():
    """The parameter survives the whole trip: handler -> page -> view -> plan. A signature anywhere
    in that chain that stops carrying it leaves the handler parsing a value it then discards, which
    looks the same from outside as the parameter being ignored.
    """
    for fn in (browse.library_page, browse.library_view):
        assert "resolution" in inspect.signature(fn).parameters, fn.__name__


@pytest.mark.skipif(_FakeStore is None, reason="no agience-ember checkout")
def test_an_UNREADABLE_level_is_treated_as_NO_level_not_an_error():
    """`?resolution=banana` lands on the offer page. An unreadable level is no level, so the handler
    falls back to `resolution = None` and offers the choices again.

    An unguarded `float(...)` would take the whole page down on a malformed query string — and
    handing out those links is the page's own job.

    Driven through the route rather than read off the handler's source. The source form of this
    assertion looked for the literal `float(resolution)` and broke the day the handler renamed its
    local variable — while the behaviour it names was still correct. A grep over an implementation
    measures its spelling; this measures what a malformed query string gets back.
    """
    c = _client(_FakeStore())
    bad, offer = c.get("/library?resolution=banana"), c.get("/library")
    assert bad.status_code == 200, "an unreadable level 500ed instead of offering the choices: %s" % bad.text[:200]
    assert bad.text == offer.text, "an unreadable level did not fall back to the offer page"


def test_the_view_CACHES_PER_RESOLUTION_not_per_root():
    """The resolution is part of the cache key. Keyed on `root` alone, `_LIB_CACHE` serves the first
    level asked for to every level after it, so the links resolve and return identical content —
    which reads as working.
    """
    src = inspect.getsource(browse.library_view)
    assert "(root, resolution)" in src or "key = (root" in src, (
        "the library cache is not keyed by resolution — every zoom would serve the first one asked for")
