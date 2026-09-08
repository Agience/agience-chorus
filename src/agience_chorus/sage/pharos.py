"""The `pharos` facet — one page, a browser into the canon collections.

Collections are the pharos folders; a collection holds sub-folders and docs; a doc holds sections.
The page walks that tree and nothing else. No search, no ranking, no zoom — the structure the canon
already has, rendered.
"""
from __future__ import annotations

import html
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

# Imported at module scope, not inside the router factory. `from __future__ import annotations`
# makes every annotation a string, and FastAPI resolves the route's `request: Request` against this
# module's globals — imported inside the factory it would be invisible there, so FastAPI would read
# `Request` as an unknown query parameter and the whole facet would answer 422.
try:
    from starlette.requests import Request
except Exception:                       # the renderer must import where no web stack is installed
    Request = Any  # type: ignore[assignment,misc]

#: The tekton behind this view, injected by the host at boot (`chorus/personas.py`). None means the
#: node holds no canon; the page says so rather than rendering an empty tree.
_BROWSE_CARRIER: Optional[Callable[[Any], Dict[str, Any]]] = None


def _e(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _q(**params: Any) -> str:
    kept = {k: v for k, v in params.items() if v}
    return "?" + urllib.parse.urlencode(kept) if kept else "?"


_CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem;font:16px/1.6 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
     max-width:56rem;margin-inline:auto;background:#fff;color:#16181d}
a{color:#0b5bd3;text-decoration:none}
a:hover{text-decoration:underline}
header{border-bottom:1px solid #e3e6ea;padding-bottom:.9rem;margin-bottom:1.25rem}
h1{font-size:1.35rem;margin:0}
.sub{color:#5b6470;font-size:.88rem;margin-top:.2rem}
.crumb{font-size:.9rem;margin-bottom:1rem;color:#5b6470}
ul{list-style:none;padding:0;margin:0}
li{padding:.5rem .2rem;border-bottom:1px solid #f0f2f5;display:flex;gap:.6rem;align-items:baseline}
.ico{width:1.2rem;color:#8a929c;flex:none}
.n{margin-left:auto;color:#5b6470;font-size:.85rem;flex:none}
.meta{color:#5b6470;font-size:.85rem}
.lic{font-size:.72rem;color:#6b7480;border:1px solid #e3e6ea;border-radius:.35rem;padding:.05rem .35rem}
.body{margin-top:1rem;white-space:pre-wrap;overflow-wrap:anywhere;font:14.5px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;
      background:#fbfbfc;border:1px solid #e3e6ea;border-radius:.6rem;padding:1rem 1.15rem}
.null{background:#fbfbfc;border:1px solid #e3e6ea;border-radius:.6rem;padding:1rem 1.15rem;color:#3d444d}
footer{margin-top:2rem;padding-top:.9rem;border-top:1px solid #e3e6ea;color:#6b7480;font-size:.8rem}
@media(prefers-color-scheme:dark){
 body{background:#111418;color:#e6e9ee}a{color:#7db1ff}
 header,footer,li,.lic,.null,.body{border-color:#2a2f37}
 .body{background:#171b21}
 .sub,.crumb,.meta,.n,.ico{color:#98a2ae}.null{background:#171b21;color:#c9d1da}}
"""


def _shell(body: str, *, sub: str = "") -> str:
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Pharos</title><style>%s</style></head><body>"
            "<header><h1>Pharos</h1>%s</header>%s"
            "<footer>The canon, held as artifacts in collections that mirror the pharos folders.</footer>"
            "</body></html>" % (_CSS, ("<div class=sub>%s</div>" % sub) if sub else "", body))


def _crumbs(locus: str) -> str:
    """Every ancestor folder is a link — the tree is walkable in both directions."""
    out = ["<a href='?'>pharos</a>"]
    if locus:
        prefix = "collection:"
        path = locus[len(prefix):] if locus.startswith(prefix) else locus
        parts = [p for p in path.split("/") if p]
        for i, part in enumerate(parts):
            cid = prefix + "/".join(parts[:i + 1])
            out.append("<a href='%s'>%s</a>" % (_e(_q(collection=cid)), _e(part)))
    return "<div class=crumb>" + " › ".join(out) + "</div>"


def render(answer: Dict[str, Any]) -> str:
    answer = answer or {}
    level = answer.get("level")
    locus = str(answer.get("locus") or "")

    if not answer.get("observed"):
        why = answer.get("why") or "nothing here"
        return _shell(_crumbs(locus if level == "collection" else "")
                      + "<div class=null>%s</div>" % _e(why))

    if level == "section":
        cit = answer.get("citation") or {}
        back = str(answer.get("doc") or "")
        crumb = (_crumbs(str(answer.get("collection") or ""))
                 + ("<div class=crumb><a href='%s'>%s</a></div>"
                    % (_e(_q(doc=back)), _e(back.rsplit("/", 1)[-1])) if back else ""))
        return _shell(crumb
                      + "<div class=body>%s</div>" % _e(answer.get("content") or ""),
                      sub="%s · <code>%s</code> · %s"
                          % (_e(answer.get("title")), _e(cit.get("cite_id") or answer.get("locus")),
                             _e(answer.get("license") or cit.get("license"))))

    if level == "doc":
        rows = []
        for it in answer.get("items") or []:
            cit = it.get("citation") or {}
            ref = cit.get("ref") or it.get("id")
            sid = cit.get("cite_id") or it.get("id")
            rows.append("<li><span class=ico>§</span><span>"
                        "<a href='%s'><strong>%s</strong></a><br>"
                        "<span class=meta>%s · <code>%s</code></span></span>"
                        "<span class=lic>%s</span></li>"
                        % (_e(_q(section=sid)),
                           _e(it.get("title") or cit.get("heading") or ref), _e(ref), _e(sid),
                           _e(it.get("license") or cit.get("license"))))
        return _shell(_crumbs(str(answer.get("collection") or "")) + "<ul>" + "".join(rows) + "</ul>",
                      sub="%s · %s sections" % (_e(locus), _e(answer.get("extent"))))

    rows = []
    for it in answer.get("items") or []:
        if it.get("kind") == "collection":
            rows.append("<li><span class=ico>▸</span><a href='%s'>%s</a>"
                        "<span class=n>%s</span></li>"
                        % (_e(_q(collection=it.get("id"))), _e(it.get("title")), _e(it.get("sections"))))
        else:
            rows.append("<li><span class=ico>·</span><a href='%s'>%s</a>"
                        "<span class=n>%s</span></li>"
                        % (_e(_q(doc=it.get("id"))), _e(it.get("title")), _e(it.get("sections"))))
    return _shell(_crumbs(locus) + "<ul>" + "".join(rows) + "</ul>",
                  sub="%s sections below here" % _e(answer.get("extent")))


DARK_PAGE = _shell("<div class=null><strong>The canon is dark on this node.</strong><br>"
                   "No canon tekton is wired here, so there is nothing to browse.</div>")


def pharos_router():
    """`GET /pharos` — the whole facet. Mounted under `/sage` by the host."""
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse

    router = APIRouter()

    @router.get("/pharos", response_class=HTMLResponse, include_in_schema=False)
    def pharos(request: Request, collection: str = "", doc: str = "", section: str = ""):
        if _BROWSE_CARRIER is None:
            return HTMLResponse(DARK_PAGE, status_code=503)
        # Who is asking travels with the need. Anonymous today — signing in happens at the authority
        # (`origin.home.agience.ai/login`, same-origin with the endpoint that verifies it), and this
        # surface has no session of its own yet, so the light-cone reaches only the public top, which
        # is why a gated collection is absent rather than forbidden. The principal is read from what
        # the host resolved and verified, never from a query parameter: a caller naming its own
        # principal is not authentication.
        need: Dict[str, Any] = {"principal": getattr(request.state, "principal", None)}
        if section:
            need["section"] = section
        elif doc:
            need["doc"] = doc
        elif collection:
            need["collection"] = collection
        return HTMLResponse(render(_BROWSE_CARRIER(need)))

    return router


__all__ = ["render", "pharos_router", "DARK_PAGE", "_BROWSE_CARRIER"]
