"""The browse facet is reachable over HTTP, from aria, with no engine imported.

Rendering and serving are different claims, and only the second one is what a person actually gets.
The facet moved out of ember with its renderer intact and, for a while, nothing mounted it: every
page still rendered when called directly and every route was gone.

THEN IT HAPPENED A SECOND WAY, WHICH IS WHY THIS FILE LOOKS LIKE IT DOES. The mount was written
against FastAPI (`@app.get(...)`) and driven here by a FastAPI app, so it passed. Aria's real app is
`mcp.streamable_http_app()` — a **Starlette** app with no `.get` — so the registration raised
`AttributeError`, `create_aria_app` logged it and carried on, and `/browse` answered 404 in the
running host while this suite stayed green. A test that builds its subject a different way than
production does is measuring a thing that does not ship.

So everything below goes through a real `FastMCP` instance and the app it generates, which is what
`prism.trust.server_auth.create_app` wraps. Two properties of that object are load-bearing and both
are pinned here: it is Starlette, not FastAPI, and it is REBUILT on every call — so routes have to
live on the FastMCP instance rather than on any one app.

Crystal routes, ember runs, chorus is the tool surface — so these pages are served by aria, and the
store arrives by injection. That is what lets this bind a fake store and get real HTML back with no
engine anywhere in the process.
"""

from __future__ import annotations

import pytest

from aria.facets.browse_routes import ROUTES, mount_browse

pytest.importorskip("mcp.server.fastmcp", reason="aria's surface is a FastMCP app")
from mcp.server.fastmcp import FastMCP                # noqa: E402
from starlette.testclient import TestClient           # noqa: E402

try:
    from _fakes import _FakeStore                     # ember's double, on the path via src/conftest.py
except ImportError:                                    # pragma: no cover
    _FakeStore = None

#: The concrete paths a person visits. `ROUTES` carries the registered patterns; this is that list
#: with the one path parameter filled in, so these are requests rather than templates.
VISITED = tuple(r.replace("{artifact_id:path}", "some-id") for r in ROUTES)


def _app(store):
    """Aria's surface, built exactly as `create_aria_app` builds it: register on the instance, then
    generate the app. Not a FastAPI app — that is the substitution this file exists to prevent."""
    mcp = FastMCP("aria-test")
    mount_browse(mcp, lambda: store)
    return TestClient(mcp.streamable_http_app(), raise_server_exceptions=False)


# ── the shape of the thing production actually serves ─────────────────────────────────────────────

def test_the_generated_app_is_starlette_and_is_not_reusable():
    """The two facts that made the previous version of this file wrong.

    If `streamable_http_app()` ever starts returning a FastAPI app, or starts caching, the reasoning
    in `browse_routes.py` needs revisiting — so it is asserted rather than assumed.
    """
    mcp = FastMCP("aria-test")
    a, b = mcp.streamable_http_app(), mcp.streamable_http_app()
    assert not hasattr(a, "get"), (
        "the generated app grew a FastAPI-style `.get`; browse_routes.py chose `custom_route` "
        "because it did not have one")
    assert a is not b, (
        "the generated app is now cached; routes registered on one app would survive, but "
        "`custom_route` is still correct and this assertion should simply be updated")


def test_registering_survives_app_regeneration():
    """The trap: `create_app` calls `streamable_http_app()` again to wrap it. Routes registered on
    an app instance would be discarded there; routes on the FastMCP instance are not."""
    mcp = FastMCP("aria-test")
    mount_browse(mcp, lambda: None)
    mcp.streamable_http_app()                          # the throwaway build
    paths = {getattr(r, "path", "") for r in mcp.streamable_http_app().routes}
    assert set(ROUTES) <= paths, "lost on regeneration: %s" % sorted(set(ROUTES) - paths)


def test_registering_adds_every_route_and_no_more():
    """The registration is the contract. A route added without a test below, or dropped while a
    page still links to it, is what this pins."""
    mcp = FastMCP("aria-test")
    mount_browse(mcp, lambda: None)
    mounted = {getattr(r, "path", "") for r in mcp.streamable_http_app().routes
               if getattr(r, "path", "").startswith(("/browse", "/chat", "/status", "/dashboard",
                                                     "/library", "/api/"))}
    assert mounted == set(ROUTES), sorted(mounted)


# ── what a person gets ────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(_FakeStore is None, reason="no agience-ember checkout — its store double is used")
@pytest.mark.parametrize("route", VISITED)
def test_every_facet_route_answers(route):
    """Answers, and answers as itself: HTML for a page, JSON for an API read."""
    r = _app(_FakeStore()).get(route)
    assert r.status_code == 200, "%s -> %s: %s" % (route, r.status_code, r.text[:200])
    kind = "application/json" if route.startswith("/api/") else "text/html"
    assert r.headers.get("content-type", "").startswith(kind), (
        "%s answered %r, not %s" % (route, r.headers.get("content-type"), kind))
    assert r.text, "%s answered 200 with an empty body" % route


@pytest.mark.parametrize("route", VISITED)
def test_an_unbound_host_refuses_rather_than_rendering_over_nothing(route):
    """503 with a reason, not a traceback and not an empty page.

    A host that has bound no store is UNINITIALISED. That is a different fact from broken, and the
    two must read differently or an operator debugs the wrong thing.
    """
    r = _app(None).get(route)
    assert r.status_code == 503, "%s -> %s on an unbound host" % (route, r.status_code)
    assert "no store is bound" in r.text, r.text[:200]


@pytest.mark.skipif(_FakeStore is None, reason="no agience-ember checkout")
def test_an_unreadable_zoom_level_lands_on_the_offer_page():
    """`?resolution=banana` is NO level, not an error.

    An unguarded `float(...)` takes the whole page down on a malformed query string, and handing out
    those links is this page's own job — so the guard lives with the route, and is exercised here
    through the route rather than read off its source.
    """
    c = _app(_FakeStore())
    bad, plain = c.get("/library?resolution=banana"), c.get("/library")
    assert bad.status_code == 200, bad.text[:200]
    assert bad.text == plain.text, "an unreadable level did not fall back to the offer page"


# ── the wiring, not just the mechanism ────────────────────────────────────────────────────────────

def test_the_shipped_aria_app_carries_the_facet(_chorus_test_identity):
    """`create_aria_app()` itself — the function the chorus host calls — must produce an app whose
    route table holds every facet path.

    Everything above tests `mount_browse` in isolation, and that is what let the defect through:
    isolation passed while `aria/server.py` handed it the wrong object and swallowed the
    `AttributeError` in a `try/except` that exists so a broken facet cannot take the tekton down.
    That guard is right, and it means a mount failure is a WARNING in a log nobody reads — so the
    wiring needs its own assertion, here, driving the real function.

    The app is returned wrapped (`UserTokenMiddleware -> _LifespanWrapper -> Starlette`), so the
    routed application is reached by unwrapping `_app` until something carries `routes`.
    """
    import aria.server as aria_server

    app = aria_server.create_aria_app()
    cur = app
    for _ in range(6):
        if hasattr(cur, "routes"):
            break
        cur = getattr(cur, "_app", None)
        if cur is None:
            pytest.fail("no routed application under the wrappers returned by create_aria_app()")
    paths = {getattr(r, "path", "") for r in cur.routes}
    missing = sorted(set(ROUTES) - paths)
    assert not missing, (
        "create_aria_app() serves %s but not %s. The facet did not mount: aria/server.py logs that "
        "as a warning and carries on, so nothing else fails when this happens." % (sorted(paths), missing))
    assert "/mcp" in paths, "the MCP surface is aria's contract and must still be there"
