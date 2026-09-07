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

The store arrives by INJECTION, not by import. `mount_browse(app, store_provider)` takes a callable
so a host binds whatever it is serving — ember on a full node, something else on a store-only one —
and this module never learns which. That is the same rule the facet itself follows for the engine
seams it reads, and it is why aria can serve this without importing ember.

A host that binds no store gets 503 with a reason, rather than a traceback or an empty page: an
uninitialised surface and a broken one are different facts and must read differently.
"""

from __future__ import annotations

from typing import Callable, Optional

from aria.facets import browse


def mount_browse(app, store_provider: Callable[[], object]) -> None:
    """Attach the browse facet's routes to `app`.

    `app` is a FastAPI/Starlette application; `store_provider` returns the store to render, or None
    when the host has not bound one. It is called per request rather than once at mount, so a host
    that binds its store after startup still serves.
    """
    from fastapi import HTTPException, Query
    from fastapi.responses import HTMLResponse

    def _store():
        store = store_provider()
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="no store is bound to this host, so there is nothing to browse. A host "
                       "binds one when it mounts this facet; unbound is uninitialised, not broken.")
        return store

    @app.get("/browse", response_class=HTMLResponse)
    def browse_page() -> str:
        _store()                      # 503 rather than a page that renders over nothing
        return browse.PAGE

    @app.get("/chat", response_class=HTMLResponse)
    def chat_page() -> str:
        _store()
        return browse.CHAT_PAGE

    @app.get("/status", response_class=HTMLResponse)
    def status_page() -> str:
        return browse.status_page(_store())

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page() -> str:
        return browse.dashboard_page(_store())

    @app.get("/library", response_class=HTMLResponse)
    def library_page(refresh: bool = False,
                     resolution: Optional[str] = Query(default=None)) -> str:
        # An unreadable level is NO level, not an error: the page offers the choices again rather
        # than 500ing on `float("banana")`. Handing out those links is this page's own job.
        level: Optional[float]
        try:
            level = float(resolution) if resolution else None
        except (TypeError, ValueError):
            level = None
        return browse.library_page(_store(), refresh=refresh, resolution=level)

    @app.get("/api/artifacts")
    def api_artifacts(type: Optional[str] = None, skip: int = 0,
                      limit: int = 40, lemma: Optional[str] = None) -> dict:
        return browse.api_artifacts(_store(), content_type=type, skip=skip,
                                    limit=min(200, limit), lemma=lemma)

    @app.get("/api/artifact/{artifact_id:path}")
    def api_artifact(artifact_id: str) -> dict:
        return browse.api_artifact(_store(), artifact_id)
