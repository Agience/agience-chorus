"""aria's web surface — the bff tekton (op.web.bff) and the `www` facet.

WEB-FROM-THE-NETWORK §5.2: the standalone www.agience.ai site becomes a facet served by aria
(static `www/dist`) + an aria bff tekton (the `www/bff/main.py` logic, registered as an
operator artifact). This proves both halves are registered, the facet points at a real dist,
and the bff app is callable with its handler logic intact.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

from agience_chorus import _persona  # noqa: E402

# `sys.modules` is keyed by name and process-global, so a bare `import reach_provider` /
# `import manifest` means whichever persona imported it first — and several personas own a
# module by each of those names, so a combined chorus run risks handing one persona's tests
# another persona's module. `_persona.load` loads this persona's copy under the unique name
# `<persona>.<module>`, so substitution is impossible.
manifest = _persona.load("manifest", __file__)
from agience_chorus.aria import web_bff  # noqa: E402
from crystal.manifest_base import Capture  # noqa: E402


# ── The bff tekton (op.web.bff) is registered ─────────────────────────────────

def test_manifest_declares_the_web_bff_tekton():
    ids = {o["id"] for o in manifest.OPERATORS}
    assert web_bff.OP_WEB_BFF in ids, "aria must own op.web.bff (the website bff tekton)"


def test_web_bff_operator_is_wellformed():
    op = next(o for o in manifest.OPERATORS if o["id"] == web_bff.OP_WEB_BFF)
    assert op["content_type"] == "application/vnd.agience.operator+json"
    assert (op.get("content") or "").strip()
    assert (op.get("context") or "").strip()  # its offer


def test_collect_registers_the_bff_tekton():
    cap = Capture()
    n = manifest.collect(cap)
    assert n == len(manifest.OPERATORS) >= 1
    assert web_bff.OP_WEB_BFF in cap.docs


# ── The www facet is registered and points at a real dist ─────────────────────

def test_manifest_declares_the_www_facet():
    names = {f["name"] for f in manifest.facets()}
    assert "www" in names, "aria must serve the www facet (public front door)"
    www = next(f for f in manifest.facets() if f["name"] == "www")
    assert www["persona"] == "aria"
    # Roster: www + apex map to aria (WEB-FROM-THE-NETWORK §1).
    assert "www" in www["subdomains"] and "@" in www["subdomains"]
    assert www["bff_tekton"] == web_bff.OP_WEB_BFF  # facet linked to its condensor


def test_www_facet_dist_path_resolves_inside_the_persona():
    """The configuration claim, split from the build claim below because `www/dist` is gitignored
    (`src/aria/www/.gitignore`) — a Vite build output that a clean checkout does not have. Asserting
    `dist.is_dir()` here would make the test depend on an uncommitted build artifact and fail on any
    checkout that has not run the build.

    What is always true and worth pinning: the manifest names a dist, and that path resolves under
    the persona directory rather than escaping it. That is the half a checkout can check.
    """
    dist = manifest.facet_dist_path("www")
    persona = Path(manifest.__file__).resolve().parent
    assert dist == (persona / "www" / "dist").resolve()
    assert persona in dist.parents, f"the facet dist escapes the persona dir: {dist}"


@pytest.mark.skipif(not manifest.facet_dist_path("www").is_dir(),
                    reason="www/dist is not built — it is a gitignored Vite output, so this runs "
                           "only where `npm run build` has been run. NOT a silent pass: the "
                           "configuration half above runs everywhere and this names what it needs.")
def test_www_facet_dist_is_servable_when_built():
    """The build claim. Runs only where the artifact exists, and the skip reason names its
    precondition rather than passing silently.
    """
    dist = manifest.facet_dist_path("www")
    assert (dist / "index.html").is_file(), "www facet dist has no index.html"


# ── The bff app is callable, handler logic intact (behaviour-preserving wrap) ──

def test_bff_app_is_callable_and_serves_healthz():
    from starlette.testclient import TestClient

    app = web_bff.bff_app()
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True  # identical to www/bff/main.py:healthz


def test_bff_app_exposes_the_declared_routes():
    app = web_bff.bff_app()
    paths = {r.path for r in app.routes}
    for expected in ("/api/contact", "/api/chat", "/api/blog", "/healthz"):
        assert expected in paths, f"bff route {expected} missing (handler logic must be intact)"
