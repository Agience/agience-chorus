"""The browse facet is reachable over HTTP, from aria, with no engine imported.

Rendering and serving are different claims, and only the second one is what a person actually gets.
The facet moved out of ember with its renderer intact and, for a while, nothing mounted it: every
page still rendered when called directly and every route was gone. This drives the mounted routes so
that cannot happen quietly again.

Crystal routes, ember runs, chorus is the tool surface — so these pages are served by aria, and the
store arrives by injection. That is what lets this test bind a fake store and get real HTML back
without an engine anywhere in the process.
"""

from __future__ import annotations

import pytest

from aria.facets.browse_routes import mount_browse

fastapi = pytest.importorskip("fastapi", reason="the facet is served by a FastAPI app")
from fastapi import FastAPI                       # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402

try:
    from _fakes import _FakeStore                 # ember's double, on the path via src/conftest.py
except ImportError:                                # pragma: no cover
    _FakeStore = None

#: Every route the facet is expected to answer. The list is the point: a route silently dropped
#: from `mount_browse` is exactly the failure this file exists to catch.
ROUTES = ("/browse", "/chat", "/status", "/dashboard", "/library",
          "/api/artifacts", "/api/artifact/some-id")


def _client(store):
    app = FastAPI()
    mount_browse(app, lambda: store)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.skipif(_FakeStore is None, reason="no agience-ember checkout — its store double is used")
@pytest.mark.parametrize("route", ROUTES)
def test_every_facet_route_answers(route):
    """Answers, and answers as itself: HTML for a page, JSON for an API read."""
    r = _client(_FakeStore()).get(route)
    assert r.status_code == 200, "%s -> %s: %s" % (route, r.status_code, r.text[:200])
    kind = "application/json" if route.startswith("/api/") else "text/html"
    assert r.headers.get("content-type", "").startswith(kind), (
        "%s answered %r, not %s" % (route, r.headers.get("content-type"), kind))
    assert r.text, "%s answered 200 with an empty body" % route


@pytest.mark.parametrize("route", ROUTES)
def test_an_unbound_host_refuses_rather_than_rendering_over_nothing(route):
    """503 with a reason, not a traceback and not an empty page.

    A host that has bound no store is UNINITIALISED. That is a different fact from broken, and the
    two must read differently or an operator debugs the wrong thing.
    """
    r = _client(None).get(route)
    assert r.status_code == 503, "%s -> %s on an unbound host" % (route, r.status_code)
    assert "no store is bound" in r.text, r.text[:200]


@pytest.mark.skipif(_FakeStore is None, reason="no agience-ember checkout")
def test_an_unreadable_zoom_level_lands_on_the_offer_page():
    """`?resolution=banana` is NO level, not an error.

    An unguarded `float(...)` takes the whole page down on a malformed query string, and handing out
    those links is this page's own job — so the guard lives with the route, and is exercised here
    through the route rather than read off its source.
    """
    c = _client(_FakeStore())
    bad, plain = c.get("/library?resolution=banana"), c.get("/library")
    assert bad.status_code == 200, bad.text[:200]
    assert bad.text == plain.text, "an unreadable level did not fall back to the offer page"


def test_mounting_adds_every_route_and_no_more():
    """The mount is the contract. A route added here without a test above, or dropped from here
    while a caller still links to it, is what this pins."""
    app = FastAPI()
    mount_browse(app, lambda: None)
    mounted = {r.path for r in app.routes if getattr(r, "path", "").startswith(("/browse", "/chat",
               "/status", "/dashboard", "/library", "/api/"))}
    assert mounted == {"/browse", "/chat", "/status", "/dashboard", "/library",
                       "/api/artifacts", "/api/artifact/{artifact_id:path}"}, sorted(mounted)
