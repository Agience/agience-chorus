"""sage's operator manifest — the op.* this persona owns; no shared catalog.
sage owns op.retrieve (sole — lumen reaches it), op.corpus.*, op.docs.*, op.describe.*, op.knowledge.cite.

This persona travels as bundles, like astra, seraph, and lumen: the manifest resolves each of its
five organon groups through `prism.runner`'s bundle mechanism rather than by importing a sibling
file under `chorus.personas._load_module`'s persona-dir path trick.

Three of sage's five organons (`corpus`, `docs_ops`, `operators`) already had bundle groups;
`retrieval` and `canon` did not, until built (`bundle_spec.json` + `build_bundles.py`, no prism
edit), so all five now arrive the same way.

`canon` declares a host seam, the first Foundation persona whose own organon does.
`canon.retrieve_cited` reaches `content_search` — sage's BM25 tekton — and `content_search`'s
closure pulls in `answer_shape`, `offer`, `condense`, and `ember.signal`, so carrying it inside the
canon payload would make that bundle a copy of sage's whole retrieval stack. The bundle instead
names `content_search` as a seam and the host answers or does not, exactly as the `operators` group
names `match`. Chorus fills neither (`runner.registered_seams() == {}`), so in this host `canon`
falls through to its `from sage import content_search` leg and `operators` reports
`basis="generic"` — the mechanism reporting honestly, not a fallback hiding a missing binding.

The organon files under `src/sage/` remain the authoritative source — `op.bundle.observe` (seraph's
organon) reads each at its exact path. The runtime reach: the runner resolves each group from the
store first (artifact `bundle-<group>`, the mesh path), then a host-registered file, then the
shipped `agience-chorus/bundles/<group>.json`; it re-hashes the canonical payload and rejects
execution on any mismatch (`BundleIntegrityError`), and execs into an isolated namespace
`_agience_bundle_<group>_<sha12>` — never a same-named module that happens to be on `sys.path`.

That isolation is load-bearing for the `operators` group in particular: two files in this workspace
are called `operators.py` (`sage/operators.py` and `iris/comms/operators.py`), so resolving by bare
name under `--import-mode=importlib` would be a silent substitution. A group name is not a basename,
and `bundle_spec.json` pins the source path, so the wrong file cannot be served quietly.

This manifest needs a bundle source at import — a store carrying the `bundle-<group>` artifacts,
`register_group` bindings, or `AGIENCE_BUNDLE_ROOT` / this repository's own `bundles/`. With none,
`register_fns` raises and `chorus.personas._persona_manifest` logs the failure and yields an empty
roster for sage. There is no in-package fallback.
"""
from __future__ import annotations

from typing import Any, Dict, List

from crystal.manifest_base import collect as _collect, operators as _operators

from prism import runner as _runner

#: The bundle groups carrying sage's organon source — a group per register group, which is what a
#: bundle is. Named once here; `register_fns` is what turns each into callables, so this file
#: transcribes no operator definition and no function name.
BUNDLE_GROUPS = ("retrieval", "corpus", "docs_ops", "operators", "canon")

# The register functions come from each bundle's own manifest (`register_fns`), sha-verified before
# any exec.
REGISTRARS = [fn for _g in BUNDLE_GROUPS for fn in _runner.register_fns(_g)]


def collect(store: Any = None) -> int:
    return _collect(REGISTRARS, store)


def operators() -> List[Dict[str, Any]]:
    return _operators(REGISTRARS)


OPERATORS = operators()


def bundle_sha256() -> Dict[str, str]:
    """The shas of the bundles this process is actually running for sage, per group — a published
    stat, so a node can say which operator bytes it is serving rather than which it was configured
    to."""
    _loaded = _runner.loaded()
    return {g: _loaded[g]["sha256"] for g in BUNDLE_GROUPS}


def bundle_origin() -> Dict[str, str]:
    """Where each of those bundles came from: ``"store"`` (the mesh path), ``"host"`` (a registered
    file), or ``"shipped"``."""
    _loaded = _runner.loaded()
    return {g: _loaded[g]["origin"] for g in BUNDLE_GROUPS}


# ── FACETS — sage's view surfaces ──────────────────────────────────────────────────────────────
#
# The design canon is not a pile of files only a human reads: `op.canon.source` (organon) reaches
# the prose, `op.canon.condense` (tekton) turns it into cited artifacts, and this facet is where a
# client meets them — the browsable library.
#
# `crystal/host.py::_persona_for_host` reads `FACETS[*]["subdomains"]` from every mounted persona,
# so the declared name resolves here the moment sage is mounted; declaring the facet is the only
# work a router needs.
#
# `sage/pharos.py` renders `op.canon.browse`'s answer at `/sage/pharos` through
# `crystal/web_serve.py` (`web.serve`), and the host measures that route's existence rather than
# trusting this declaration.
#
# `ember/facets/browse.py:library_page` renders a different condensation of the same corpus, not
# the same answer: `library_page` renders `docs_ops.library_plan` (per-doc `{role, staleness,
# action, target}` plus a target tree, keyed on a float resolution), while `op.canon.browse` returns
# sources and sections with citations. `library_plan` is single-sourced in `sage/docs_ops.py`; ember
# reaches it through the bundle, so neither condensation nor rendering is written twice.
CANON_BROWSE_CAP = _runner.load("canon").CANON_BROWSE_CAP

FACETS: List[Dict[str, Any]] = [
    {
        # Named for what it shows, not for the view: the canon is `agience-pharos`, and a named
        # entity is addressed by its name everywhere — you reach pharos, with one subdomain rather
        # than several descriptions of the same surface.
        # Locally: `pharos.home.agience.ai` with `CRYSTAL_HOST_DOMAIN=home.agience.ai`.
        "name": "pharos", "persona": "sage",
        "direction": "both",              # a need carries the locus + zoom in, the structure comes out
        "content_type": "text/html",      # discovery hint, never a gate
        "subdomains": ["pharos"],
        # The condensor behind the view. Unlike aria's `login` (which condenses nothing and so
        # names an organon instead), this view is a condensation: many artifacts in, the structure
        # over them out.
        "bff_tekton": CANON_BROWSE_CAP,
    },
]


def facets() -> List[Dict[str, Any]]:
    """The facet manifest — sage's view surfaces (roster source of truth)."""
    return FACETS


__all__ = ["OPERATORS", "REGISTRARS", "BUNDLE_GROUPS", "CANON_BROWSE_CAP", "collect", "operators",
           "FACETS", "facets", "bundle_sha256", "bundle_origin"]
