# Operator code lives in chorus and is distributed to hosts as a content-addressed source bundle
# (agience-observe/build_bundles.py); ember executes it via ember/runtime/runner.py, sha-verified
# before exec. There are no code mirrors — changes happen here.
"""aria.web_bff — the web BFF as an aria tekton (WEB-FROM-THE-NETWORK §0, §5.2).

The public website (`aria/www/`) is a facet (the React `dist/`, a view whose far side is a
browser) plus a tekton (its backend-for-frontend, `www/bff/main.py` — the condensor behind it).
This module is the tekton half: it registers `op.web.bff` as an operator artifact (so the persona
owns it, exactly like sage owns op.retrieve and astra owns op.fetch.get) and exposes the bff's
FastAPI app for the host→facet router to mount.

Behaviour-preserving wrap: the handler logic is not re-implemented here — the FastAPI app is
loaded verbatim from `www/bff/main.py`. This module only wraps/registers that app the persona way.
The endpoints (contact/nonce, contact, chat, blog, healthz) are byte-for-byte the standalone
service's.

Host-header routing is built: `crystal/host.py:299` `_persona_for_host` and the `_route_by_host`
middleware resolve `<name>.<base>` → the persona mount, `www.<base>`/`<base>` → the apex persona,
and anything unknown → None (left alone, never guessed). It is covered both ways by
`agience-crystal/tests/test_host_header_routing.py`. `CRYSTAL_HOST_DOMAIN` is derived from
`ORIGIN_URI` in `service_common.sh`, and `peers/test_generated_env.py` guards the seam so the wire
cannot go missing silently.

The host mounts a declared facet's built bundle at `/<persona>/<facet>` and points its subdomains
there, so `www.<base>/`, the apex and `/aria/www/` all serve this facet's index.html. This module
still lands only the registration and the mountable app — serving is the host's, and nothing here
fabricates a server.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type

_BFF_MODULE_NAME = "aria_www_bff_main"

#: The seam name this organon declares for the bff app (`bundle_spec.json` -> `host_seams`). The
#: host's answer, not the loader's: `crystal/host.py` already calls serving a facet a host
#: capability (`web.serve`), and aria's own manifest says so in as many words. So when this module
#: travels as a bundle, which module backs the `www` facet is something the host binds with
#: `prism.runner.register_seam("bff_main", …)` — it is not something the payload can carry.
BFF_MAIN_SEAM = "bff_main"


def _bff_main_path() -> Optional[Path]:
    """Where `www/bff/main.py` sits beside this file — or ``None`` when there is no beside.

    This is a function rather than a module-scope constant because a bundle module is exec'd from
    distributed text (`prism.runner._SourceLoader`); its spec has no location, so `__file__` is not
    defined there, and a module-scope read of it would raise `NameError` before
    `register_web_operators` could ever run.

    The answer is `None`, not a guessed path: a bundled copy has no directory of its own, and a
    `cwd`-relative or package-relative fallback would invent a location and silently serve the
    wrong tree on any host that happened to have one. Absence is reported as absence.
    """
    here = globals().get("__file__")
    if here is None:                      # exec'd from a bundle — there is no file, and no beside
        return None
    return Path(here).resolve().parent / "www" / "bff" / "main.py"


#: Kept as a module attribute because it reads as documentation of where the app lives; ``None`` under
#: a bundle, which is exactly the condition `_load_bff_module` reports on.
_BFF_MAIN = _bff_main_path()

# The operator id this persona owns — the web bff tekton. op.web.* is aria's web surface.
OP_WEB_BFF = "op.web.bff"

# The routes the loaded FastAPI app exposes (the tekton's surface — descriptive, not a gate).
BFF_ROUTES = (
    "GET /api/contact/nonce",
    "GET /api/chat/nonce",
    "POST /api/contact",
    "POST /api/chat",
    "GET /chat",             # the chat UI facet page (aria's lumen conversation surface)
    "GET /api/blog",
    "GET /api/blog/{post_id}",
    "GET /healthz",
)

_OFFER = (
    "the public website backend-for-frontend (agience.ai): lead capture, chat relay, "
    "blog, and bot-protection nonce — the tekton behind aria's www facet"
)


def _load_bff_module():
    """The FastAPI app module behind aria's `www` facet (lazy — importing FastAPI is only needed when
    the app is actually mounted, never for manifest/registration).

    Two routes, in order, and the second is not a fallback for the first:

      1. The declared seam. If the host bound `bff_main`, that module is the answer. This is the
         only route available to a bundled copy, and it is the route a third-party host uses.
      2. The file beside this one. When this module was imported from its own file (the chorus
         host, `from aria import web_bff`), `www/bff/main.py` is right there and is loaded
         verbatim, exactly as before. Chorus binds no seam, so this is the route chorus takes.

    Either way the result is registered under `_BFF_MODULE_NAME`, because `chorus/personas.py` and
    `chorus/live_service.py` reach the running app through `sys.modules[web_bff._BFF_MODULE_NAME]`
    to set its carrier. One name, one app object, whichever route produced it.

    With neither route available, this raises and says which two things are missing: a bundled
    copy on a host that bound no seam cannot serve this facet, because the app is a file that does
    not travel, and that is stated rather than papered over with a stub app that would 404 its way
    through a deployment.
    """
    if _BFF_MODULE_NAME in sys.modules:
        return sys.modules[_BFF_MODULE_NAME]

    try:                                       # 1 · the declared host seam
        from . import bff_main as mod          # resolves only through `register_seam`
    except ImportError:
        pass
    else:
        sys.modules[_BFF_MODULE_NAME] = mod
        return mod

    path = _bff_main_path()                    # 2 · the file beside this one
    if path is None:
        raise RuntimeError(
            "aria's web bff cannot be loaded: this copy of `web_bff` was exec'd from a BUNDLE, so "
            "there is no `www/bff/main.py` beside it, and no host bound the %r seam. Serving a facet "
            "is a host capability — bind it with "
            "`prism.runner.register_seam(%r, '<your.bff.module>')` at boot, or reach aria's own "
            "`aria.web_bff` if this process is the chorus host. Registration (`register_web_operators`) "
            "needs none of this and works from the bundle." % (BFF_MAIN_SEAM, BFF_MAIN_SEAM))
    spec = importlib.util.spec_from_file_location(_BFF_MODULE_NAME, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load aria web bff from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_BFF_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def bff_app():
    """Return the bff's FastAPI ASGI app — the identical `www/bff/main.py:app`.

    This is what the host→facet router (WEB-FROM-THE-NETWORK §2, gated on NEXT §C.1) will
    mount under aria's subdomain. Returned as-is so behaviour is preserved exactly."""
    return _load_bff_module().app


def register_web_operators(artifact_store, graph_store=None, *, author: str = "aria") -> int:
    """Upsert the web bff tekton as an operator artifact (idempotent). Mirrors sage's
    `register_retrieval_operators` / astra's `register_fetch_operators`: the operator is an
    artifact whose `context` is its offer, so it is discoverable by need→offer match. Returns
    how many were registered."""
    from crystal import evolution

    artifact_store.put_artifact(evolution.preserve_fitness(artifact_store, {
        "id": OP_WEB_BFF,
        "content_type": OPERATOR_CONTENT_TYPE,
        "state": "committed",
        "context": _OFFER,
        "content": (
            f"web-bff tekton {OP_WEB_BFF}: {_OFFER}. "
            f"routes: {', '.join(BFF_ROUTES)}"
        ),
        "created_by": author,
    }))
    return 1


__all__ = ["OP_WEB_BFF", "BFF_ROUTES", "BFF_MAIN_SEAM", "bff_app", "register_web_operators"]
