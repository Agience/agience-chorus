"""The HTTP surface for the browse facet — what actually serves the pages.

`browse.py` renders; this mounts. Ember served these routes while the facet lived inside the engine.
It does not any more: crystal routes, ember runs, chorus is the tool surface, and a rendered view of
what a node holds is a tool. So the routes move with the facet, and aria — the output tekton — is
what serves them.

    GET /browse                    the ontology browser page
    GET /chat                      the chat page
    GET /status                    the live status page
    GET /dashboard                 the mesh dashboard (reads snapshots, never scans)
    GET /library?resolution=&refresh=   the zoom levels this corpus has, and a chosen one
    GET /api/artifacts             paged list, filterable by type and lemma
    GET /api/artifact/{id}         one artifact and its typed neighbours

## Registered on the FastMCP instance, not on an app

`mount_browse(mcp, store_provider)` takes aria's **FastMCP instance** and registers through
`mcp.custom_route`. That is not a style choice, it is the only thing that works here, for two
measured reasons:

  * `mcp.streamable_http_app()` returns a **Starlette** app. It has no `.get` decorator — that is
    FastAPI's — so registering with `@app.get(...)` raised `AttributeError` and the mount was
    skipped. The whole facet 404'd in the running host while every unit test passed.
  * That app is **not cached**: each call builds a new one. Routes added to an instance obtained
    here would be discarded when `prism.trust.server_auth.create_app` called it again to wrap.
    `custom_route` registers on the FastMCP object, so every generated app carries them.

Handlers are therefore plain Starlette endpoints — `async def h(request) -> Response` — reading
`request.query_params` and `request.path_params`.

The store arrives by INJECTION, not by import: `store_provider` is a callable, so a host binds
whatever it is serving and this module never learns which. That is the same rule the facet itself
follows for its engine seams, and it is why aria can serve this without importing ember.

A host that binds no store gets 503 with a reason, rather than a traceback or an empty page: an
uninitialised surface and a broken one are different facts and must read differently.
"""

from __future__ import annotations

from typing import Callable, Optional

from agience_chorus.aria.facets import browse

#: Said in one place so the page and API refusals cannot drift apart.
_UNBOUND = ("no store is bound to this host, so there is nothing to browse. A host binds one when "
            "it mounts this facet; unbound is uninitialised, not broken.")

#: Every route this facet answers. The list is the contract — a route dropped from the registration
#: below while a page still links to it is exactly what `test_the_browse_facet_is_servable.py` pins.
ROUTES = ("/browse", "/chat", "/status", "/dashboard", "/library",
          "/api/artifacts", "/api/artifact/{artifact_id:path}")


def mount_browse(mcp, store_provider: Callable[[], object]) -> None:
    """Register the browse facet's routes on aria's FastMCP instance.

    `store_provider` returns the store to render, or None when the host has bound none. It is
    called per request rather than once at registration, so a host that binds its store after
    startup still serves.
    """
    from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

    def _store():
        """The bound store, or None. Callers turn None into the 503 their content type wants."""
        return store_provider()

    def _refused(as_json: bool):
        return (JSONResponse({"detail": _UNBOUND}, status_code=503) if as_json
                else PlainTextResponse(_UNBOUND, status_code=503))

    @mcp.custom_route("/browse", methods=["GET"])
    async def browse_page(request):                      # noqa: ANN001
        store = _store()
        if store is None:
            return _refused(False)                       # never render a page over nothing
        return HTMLResponse(browse.PAGE)

    @mcp.custom_route("/chat", methods=["GET"])
    async def chat_page(request):                        # noqa: ANN001
        store = _store()
        if store is None:
            return _refused(False)
        return HTMLResponse(browse.CHAT_PAGE)

    @mcp.custom_route("/status", methods=["GET"])
    async def status_page(request):                      # noqa: ANN001
        store = _store()
        if store is None:
            return _refused(False)
        return HTMLResponse(browse.status_page(store))

    @mcp.custom_route("/dashboard", methods=["GET"])
    async def dashboard_page(request):                   # noqa: ANN001
        store = _store()
        if store is None:
            return _refused(False)
        return HTMLResponse(browse.dashboard_page(store))

    @mcp.custom_route("/library", methods=["GET"])
    async def library_page(request):                     # noqa: ANN001
        store = _store()
        if store is None:
            return _refused(False)
        q = request.query_params
        # An unreadable level is NO level, not an error: the page offers the choices again rather
        # than 500ing on `float("banana")`. Handing out those links is this page's own job.
        level: Optional[float]
        try:
            raw = q.get("resolution")
            level = float(raw) if raw else None
        except (TypeError, ValueError):
            level = None
        refresh = q.get("refresh", "").lower() in ("1", "true", "yes")
        return HTMLResponse(browse.library_page(store, refresh=refresh, resolution=level))

    @mcp.custom_route("/api/artifacts", methods=["GET"])
    async def api_artifacts(request):                    # noqa: ANN001
        store = _store()
        if store is None:
            return _refused(True)
        q = request.query_params

        def _int(name: str, default: int) -> int:
            try:
                return int(q.get(name, default))
            except (TypeError, ValueError):
                return default

        return JSONResponse(browse.api_artifacts(
            store, content_type=q.get("type"), skip=_int("skip", 0),
            limit=min(200, _int("limit", 40)), lemma=q.get("lemma")))

    @mcp.custom_route("/api/artifact/{artifact_id:path}", methods=["GET"])
    async def api_artifact(request):                     # noqa: ANN001
        store = _store()
        if store is None:
            return _refused(True)
        return JSONResponse(browse.api_artifact(store, request.path_params["artifact_id"]))
