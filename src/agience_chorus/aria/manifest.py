"""aria's operator + facet manifest — the op.* and web surfaces this persona owns. aria owns
op.web.bff (the website backend-for-frontend tekton) and serves the `www` facet (the public front
door).

Facet roster (WEB-FROM-THE-NETWORK §1): `www` and the apex map to aria — aria is the canonical
public front door (Presentation & Interface). The facet's static bundle is `www/dist`; its bff
tekton is op.web.bff (see web_bff.py).

aria travels as a bundle across two groups: `web_bff` and `identity`. `web_bff.py` opens with
`_BFF_MAIN = Path(__file__).resolve().parent / "www" / "bff" / "main.py"` at module scope, and a
bundle module is exec'd from distributed text with no location — `__file__` is not defined there.
It is the only organon in chorus that reads a dunder path; `test_the_flattening_argument_is_FALSIFIABLE`
in iris's suite checks the same property of every module it carries, for the same reason.

`www/bff/main.py` is a file in the persona directory: it does not travel, and no `cwd`-relative
guess could honestly stand in for it. aria's own `CRYSTAL` below already says serving this facet is
a host capability (`web.serve`), not aria's — so which module backs the facet is the host's answer,
exactly like a seam. The `web_bff` group therefore declares `host_seams: ["bff_main"]`. Chorus's own
code binds nothing: in this host the tekton is registered from the sha-verified bundle while
`chorus/personas.py` and `chorus/live_service.py` reach `aria.web_bff` directly for the app, and the
file-beside-this-one route answers there. On a host that has neither the file nor a bound seam,
`bff_app()` raises and names which two things are missing — registration works from the bundle
regardless.

`aria/web_bff.py` remains the authoritative source — `agience-observe/build_bundles.py` reads it at
that exact path. At runtime, the group resolves from the store first (artifact `bundle-web_bff`),
then a host-registered file, then the shipped `agience-chorus/bundles/web_bff.json`; it re-hashes
the canonical payload and raises on any mismatch (`BundleIntegrityError`), and execs into
`_agience_bundle_web_bff_<sha12>`.

This manifest needs a bundle source at import: a store carrying `bundle-web_bff`, a `register_group`
binding, or `AGIENCE_BUNDLE_ROOT` / this repository's own `bundles/`. With none, `register_fns`
raises and `chorus.personas._persona_manifest` logs the failure and yields an empty roster for aria.
There is deliberately no in-package fallback.
"""
from __future__ import annotations



from pathlib import Path
from typing import Any, Dict, List

from crystal.manifest_base import collect as _collect, operators as _operators

from prism import runner as _runner

#: The bundle group carrying aria's organon source. Named once; `register_fns` is what turns it into
#: callables, so this file transcribes no operator definition and no function name.
#:
#: Two groups: the www-facet's condensor and the identity organon, the same shape sage uses for its
#: five. A capability that is not in a bundle cannot be registered.
#:
#: The plural is the only declaration, deliberately: `test_..._every_payload_is_CLAIMED` reads the
#: manifest's source and returns on the first match, so a lingering singular
#: `BUNDLE_GROUP = "web_bff"` above this line would shadow the tuple and leave `identity` reading as
#: an unclaimed payload. `WWW_GROUP` below is a plain name, not a second declaration.
BUNDLE_GROUPS = ("web_bff", "identity")
WWW_GROUP = BUNDLE_GROUPS[0]

# ── Operators (tektons + organons) aria owns ──────────────────────────────────
REGISTRARS = [fn for _g in BUNDLE_GROUPS for fn in _runner.register_fns(_g)]

#: The tekton id, read from the loaded bundle rather than re-typed here — `FACETS` and `CRYSTAL` below
#: both link the `www` view to its condensor by this name, and a transcribed copy is how a view ends up
#: pointing at a tekton that no longer exists.
OP_WEB_BFF = _runner.load(WWW_GROUP).OP_WEB_BFF

#: Read from the loaded bundle, never imported. `test_no_organon_is_imported_by_bare_name_in_arias_manifest`
#: forbids `from identity import ...` here: an organon reached by import bypasses the sha
#: verification the bundle exists to provide, so the manifest would be describing a module the host
#: never checked. Same pattern as OP_WEB_BFF above — the name travels with the payload.
IDENTITY_VERIFY_CAP = _runner.load("identity").IDENTITY_VERIFY_CAP


def collect(store: Any = None) -> int:
    return _collect(REGISTRARS, store)


def operators() -> List[Dict[str, Any]]:
    return _operators(REGISTRARS)


OPERATORS = operators()


# ── Facets (web surfaces) aria serves ─────────────────────────────────────────
# Declarative source-of-truth for the host→facet router (WEB-FROM-THE-NETWORK §2, gated on
# host-header routing). A facet is a view whose far side is a browser; `www`/apex → aria per the
# roster. `bff_tekton` links this view to its condensor.
#
# There is no `login` facet here: the credential form belongs to the authority. Served by aria and
# posting to origin it would be a cross-origin credential flow (CORS, and a session cookie browsers
# drop as third-party); served by origin it is same-origin, which is how every OIDC provider works.
# `op.identity.verify` is unaffected — a persona verifying a bearer token over the wire is a
# different act from a human signing in.
FACETS: List[Dict[str, Any]] = [
    {
        "name": "www",
        "persona": "aria",
        "direction": "both",              # the UI carries the signal both ways (§12.1)
        "content_type": "text/html",      # discovery hint, never a gate
        "subdomains": ["www", "aria", "@"],  # @ = apex; www/apex redirect to aria (§1)
        "dist": "www/dist",               # the static bundle, relative to this persona dir
        "bff_tekton": OP_WEB_BFF,         # the tekton behind the view
    },
]


def facets() -> List[Dict[str, Any]]:
    """The facet manifest — aria's web surfaces (roster source of truth)."""
    return FACETS


def facet_dist_path(name: str = "www") -> Path:
    """Resolve a facet's static `dist` to an absolute path under this persona dir."""
    entry = next((f for f in FACETS if f["name"] == name), None)
    if entry is None:
        raise KeyError(f"no facet named {name!r} in aria manifest")
    return (Path(__file__).resolve().parent / entry["dist"]).resolve()


def bundle_sha256() -> dict:
    """The sha per group of the bundles this process is actually running for aria — a published
    stat, so a node can report which operator bytes it is serving rather than which it was
    configured to.

    A dict, one entry per group, matching sage and lumen: a single sha would publish `web_bff`'s
    bytes as if they were aria's for both groups, and the identity organon's bytes could then change
    with the stat unmoved — a published number that cannot report the thing it names is worse than
    no number.
    """
    _loaded = _runner.loaded()
    return {g: _loaded[g]["sha256"] for g in BUNDLE_GROUPS}


def bundle_origin() -> dict:
    """Where each of those bundles came from: ``"store"`` (the mesh path), ``"host"`` (a registered
    file), or ``"shipped"``. Per group, for the same reason as `bundle_sha256`."""
    _loaded = _runner.loaded()
    return {g: _loaded[g]["origin"] for g in BUNDLE_GROUPS}


__all__ = [
    "OPERATORS", "REGISTRARS", "BUNDLE_GROUPS", "WWW_GROUP", "OP_WEB_BFF",
    "IDENTITY_VERIFY_CAP", "collect", "operators",
    "FACETS", "facets", "facet_dist_path", "bundle_sha256", "bundle_origin",
]


# ── the crystal ──────────────────────────────────────────────────────────────────────────────────
# aria is the presentation crystal: its facets are conduits whose far side is a browser, and its
# tekton is the bff that condenses a surface gesture into a typed act.
#
# Derived from `FACETS` above, not re-typed. That list is already the roster source of truth and
# already carries `name` / `direction` / `content_type` — exactly the crystal facet shape. Building
# the spec from it means the two can never drift; a facet added there is in the crystal by
# construction. (`subdomains` / `dist` / `bff_tekton` are aria's own routing metadata and ride
# alongside — the contract ignores unknown keys, so the declaration stays in one place.)
CRYSTAL: Dict[str, Any] = {
    "name": "aria",
    "facets": [
        {k: v for k, v in f.items() if k in ("name", "direction", "content_type")}
        for f in FACETS
    ],
    # The condensor behind the view: surface gesture -> typed action. `op.web.bff` is the tekton
    # `web_bff.py` already registers as an operator artifact.
    "tektons": [{"name": OP_WEB_BFF, "domain": "web"}],

    # aria reaches lumen's `op.respond` for the answer; it does not own a reasoning organon, and a
    # pure-conduit crystal is explicitly allowed to declare none ("a crystal that routes without
    # transforming"). Serving the static facet is a host capability (`web.serve`), not aria's.
    "organons": [],

    "created_by": "connect@agience.ai",
}
