"""CHORUS — tekton (persona) discovery & host binding.

Chorus members are tektons — the operators of one domain. This module's identifiers use the
name "persona" for the same concept, matching the wider codebase.

chorus = "operators, by domain": only the tekton modules live here. The host/gateway process
lives in ``crystal.host`` (GENESIS-NEXT §B1.10). This module is the chorus-specific seam that
discovers chorus's own tekton modules (layout detection, importlib loading, the Lumen premium
runtime swap, service-identity boot) and adapts each into the duck-typed persona-provider
surface :mod:`crystal.host` consumes — so ``crystal.host`` imports no tekton by name (which
would be a dependency cycle: chorus depends on crystal, never the reverse).

``load_personas()`` returns the tekton roster — a list of :class:`PersonaBinding`, one per
tekton (a condensor; its tools are organons, invoked by condensation — OPERATOR-ARCHITECTURE
§12); the chorus shim (``server.py``) hands it to ``crystal.host.build_app``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

log = logging.getLogger("chorus.personas")

HOST_DIR = Path(__file__).resolve().parent

# The shared plumbing (beam/crystal) is installed on the platform path. This insert keeps
# legacy `from core import ...` style resolution working during persona import.
_platform_parent = str(HOST_DIR.parent)
if _platform_parent not in sys.path:
    sys.path.insert(0, _platform_parent)

# Load the chorus service identity once at process boot, before any persona
# AgienceServerAuth instance is constructed. Each persona signs its own platform JWTs
# with this key (sub=persona_client_id, iss=chorus, aud=mantle). The persona provider —
# not the generic host — owns identity, because the identity is "chorus".
from prism.trust import service_identity  # noqa: E402

service_identity.init_service_identity("chorus")
log.info("Chorus service identity loaded — kid=chorus-1")


# ---------------------------------------------------------------------------
# Persona module loading (local dev subdirs vs flat Docker layout).
# ---------------------------------------------------------------------------
_LOCAL_LAYOUT = (HOST_DIR / "aria" / "server.py").exists()


def _load_module(module_name: str, file_path: Path, *extra_paths: Path) -> ModuleType:
    search_paths = [file_path.parent, *extra_paths]
    for path in reversed(search_paths):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module {module_name!r} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


#: The persona crystals this node loads. Empty/unset selects all of them.
#:
#: A node does not need to load all of chorus: a node serving the chat needs exactly two
#: crystals — aria presents it and lumen reasons it — so this variable lets a deployment
#: declare a subset rather than import, register, and fail to register against endpoints it
#: will never need.
_SELECTED = tuple(p.strip().lower() for p in (os.getenv("CHORUS_CRYSTALS") or "").split(",") if p.strip())


def _wanted(name: str) -> bool:
    return not _SELECTED or name in _SELECTED


# ── the roster, derived ──────────────────────────────────────────────────────────────────────────
#
# Role is emergent from what a node holds, never declared centrally (ARCHITECTURE-TARGET §5:
# "Capacity is installed; role is read from what a node holds and can discharge … there is no
# role to configure."). The roster below is a projection of the persona crystals this node
# actually holds, so a node holding two crystals has two entries.
#
# The shape matches `mantle.services.server_registry.ManifestEntry`
# (`{name, title, path, client_id, role, summary}`), and the title/summary derivation is the
# same one `crystal.persona_registration._register_server` performs on every live
# self-registration (`title = name.capitalize()`, `summary = role`), so the roster and the live
# push describe a persona the same way.

def _entry(name: str, meta: dict) -> dict:
    """One roster record, derived from the persona's own declaration; nothing is transcribed."""
    role = meta.get("role", "")
    return {
        "name": name,
        "title": name.capitalize(),
        "path": meta.get("endpoint") or f"/{name}/mcp",
        "client_id": meta.get("client_id") or f"agience-server-{name}",
        "role": role,
        "summary": role,
    }


def roster(modules: Optional[dict] = None) -> list[dict]:
    """The tekton roster — the persona crystals this node holds, in the registry's own record shape.

    `modules` defaults to the crystals this node loads (`_load_persona_modules`, which already
    honours `CHORUS_CRYSTALS`), so the roster and the mounted set are the same measurement rather
    than two lists that agree until someone edits one.

    A persona that declares no `PERSONA` still appears, with an empty role: absence of a
    declaration is not evidence the node does not hold the crystal, and dropping it here would
    make the roster smaller than the set of things actually mounted.
    """
    mods = _load_persona_modules() if modules is None else modules
    return [_entry(name, getattr(mod, "PERSONA", {}) or {}) for name, mod in mods.items()]


def _load_persona_modules() -> dict[str, ModuleType]:
    """Import each selected tekton's `server` module.

    One route, because there is now one layout. This used to branch: a "local" layout that loaded
    `<HOST_DIR>/aria/server.py` BY PATH with `spec_from_file_location`, and a "flat" layout that did
    `import aria_server` after a Docker build had flattened the tree. Chorus is an installed package
    now — `chorus.<tekton>.server` — so both are the same plain import, and neither the
    working directory nor an image's file arrangement can change which module answers.
    """
    log.info("Loading persona modules%s",
             f" (crystals: {', '.join(_SELECTED)})" if _SELECTED else " (all crystals)")
    known = ("aria", "astra", "sage", "iris", "ophan", "seraph", "lumen")

    # A name that matches nothing is an error, not an empty set: typing `CHORUS_CRYSTALS=aira`
    # must not silently boot an edge with zero crystals that answers healthy.
    unknown = [n for n in _SELECTED if n not in known]
    if unknown:
        raise RuntimeError(
            "CHORUS_CRYSTALS names %s, which is not a persona crystal here; known: %s"
            % (", ".join(unknown), ", ".join(sorted(known))))

    return {n: importlib.import_module("agience_chorus.%s.server" % n)
            for n in known if _wanted(n)}


def _apply_lumen_premium_swap(modules: dict[str, ModuleType]) -> None:
    """Route Lumen through the premium wheel when LUMEN_PACKAGE + LUMEN_MODULE are set.

    Deprecation fallback: if LUMEN_* are unset but the pre-rename VERSO_* names are set,
    honor them with a warning — deployments may still carry the old env names."""
    pkg = (os.getenv("LUMEN_PACKAGE") or "").strip()
    name = (os.getenv("LUMEN_MODULE") or "").strip()
    if not (pkg and name):
        legacy_pkg = (os.getenv("VERSO_PACKAGE") or "").strip()
        legacy_name = (os.getenv("VERSO_MODULE") or "").strip()
        if legacy_pkg and legacy_name:
            log.warning(
                "VERSO_PACKAGE/VERSO_MODULE are deprecated — set LUMEN_PACKAGE/LUMEN_MODULE "
                "instead; honoring the legacy names for this boot"
            )
            pkg, name = legacy_pkg, legacy_name
    if not (pkg and name):
        return
    try:
        import importlib as _importlib

        modules["lumen"] = _importlib.import_module(name)
        log.info("Loaded premium Lumen runtime: package=%s module=%s", pkg, name)
    except ImportError as exc:
        log.error(
            "LUMEN_PACKAGE=%s set but module %s could not be imported: %s — "
            "falling back to bundled public Lumen",
            pkg, name, exc,
        )


def _build_mount_app(name: str, mod: ModuleType) -> Any:
    """Build the ASGI app to mount at /<name>, clearing DNS-rebinding protection first.

    Astra needs both stream webhook routes and MCP under /astra, so it gets a combined
    FastAPI app. This persona-specific wiring stays in chorus; the host mounts whatever
    app it is handed.
    """
    if getattr(mod.mcp.settings, "transport_security", None) is not None:
        mod.mcp.settings.transport_security = None
    create_fn = getattr(mod, "create_server_app", None)
    sub_app = create_fn() if create_fn else mod.mcp.streamable_http_app()

    # Aria carries a facet, not only an MCP surface: a facet is a view whose far side is a
    # browser, and aria's is the chat page plus its bff (`op.web.bff`). The persona's own routes
    # sit on the combined app, with MCP kept as the catch-all mount underneath — the same shape
    # astra uses — so `/aria/mcp` keeps working alongside `/aria/chat` and `/aria/api/chat`.
    if name == "aria":
        from fastapi import FastAPI

        combined = FastAPI()
        try:
            from agience_chorus.aria import web_bff

            combined.include_router(web_bff.bff_app().router)
            log.info("Aria web facet mounted (chat page + bff tekton)")
        except Exception as exc:  # noqa: BLE001 — a missing facet must not unmount the persona
            log.warning("Aria web facet not loaded: %s", exc)
        combined.mount("/", sub_app)
        return combined

    # Sage carries the `pharos` facet. `web.serve` serves a facet carrying a built `dist`; this
    # view has none, because it is rendered from `op.canon.browse` rather than built. So the route
    # lives on the persona's own app, at the path the host's facet router expects: `/sage/pharos`
    # (locally `pharos.home.agience.ai`, via `CRYSTAL_HOST_DOMAIN=home.agience.ai`) — addressed by
    # the name of the thing, not of the view.
    #
    # The tekton behind it is injected later (`_wire_pharos_facet`), because opening the store is
    # the host's act and happens after every binding exists. Until then the route answers 503 with
    # the reason stated, rather than an empty canon.
    if name == "sage":
        from fastapi import FastAPI

        combined = FastAPI()
        try:
            from agience_chorus.sage import pharos

            combined.include_router(pharos.pharos_router())
            log.info("Sage pharos facet mounted (/sage/pharos)")
        except Exception as exc:  # noqa: BLE001 — a missing facet must not unmount the persona
            log.warning("Sage pharos facet not loaded: %s", exc)
        combined.mount("/", sub_app)
        return combined

    if name != "astra":
        return sub_app

    from fastapi import FastAPI

    combined = FastAPI()
    try:
        stream_mod = importlib.import_module("agience_chorus.astra.stream_routes")
        combined.include_router(stream_mod.router)
        log.info("Astra stream routes loaded")
    except Exception as exc:  # noqa: BLE001
        log.warning("Astra stream routes not loaded: %s", exc)
    combined.mount("/", sub_app)
    return combined


@dataclass
class PersonaBinding:
    """A chorus persona adapted to the crystal.host persona-provider surface."""

    name: str
    role: str
    endpoint: str
    mount_app: Any
    session_manager: Optional[Any]
    _startup: Optional[Callable[[], Any]]
    _register: Optional[Callable[[], bool]]
    operators: list = field(default_factory=list)  # this persona's own operator manifest (no shared catalog)
    # This persona's own facet manifest (its view surfaces). Carried for the same reason `operators` is: the
    # persona declares it, the host consumes it, and nothing in between keeps a second copy. `crystal.host`'s
    # host-header router reads `FACETS[*]["subdomains"]` from here — `aria/manifest.py` calls that roster the
    # declarative source of truth for the host-to-facet router.
    facets: list = field(default_factory=list)
    # The persona's own directory — the root a facet's declared `dist` resolves against.
    #
    # The host cannot derive this and does not guess: `aria/manifest.py` declares
    # `"dist": "www/dist"` relative to the persona dir, and `crystal.web_serve` needs a root to
    # join it to. The alternatives are a cwd-relative guess (serves whatever the process started
    # in) or crystal learning the chorus layout (the dependency cycle this module exists to
    # prevent); chorus already knows the path, because it loaded the manifest from it.
    #
    # Absent (a provider that supplies none) means a static surface cannot be resolved, and
    # `web_serve` says so by name rather than inferring one.
    dist_root: Optional[Path] = None

    async def startup(self) -> None:
        if self._startup is not None:
            await self._startup()

    def register(self, register_fn) -> bool:
        if self._register is None:
            return True
        return self._register(register_fn)


def _persona_manifest(name: str, mod: ModuleType) -> tuple:
    """Load a persona's own manifest (`<persona>/manifest.py`) → ``(OPERATORS, FACETS)``, if present.

    A persona that owns organons declares them in a sibling ``manifest.py``; a persona that owns
    none (aria/iris/ophan/…) has no manifest and returns empty lists.

    Imported by dotted name rather than loaded by path. The files are all called ``manifest.py``,
    which is exactly why the by-path loader needed to invent a unique module name for each — as a
    subpackage they are already distinct (``chorus.sage.manifest``), and Python's own module
    cache does the de-duplication that the invented names were standing in for.

    Returns both rosters from one load: loading the manifest a second time to fetch `FACETS`
    would re-execute a module whose body performs operator registration."""
    try:
        m = importlib.import_module("agience_chorus.%s.manifest" % name)
        return list(getattr(m, "OPERATORS", [])), list(getattr(m, "FACETS", []))
    except ModuleNotFoundError:
        return [], []
    except Exception as exc:  # noqa: BLE001 — a broken manifest is a finding, never a boot crash
        log.warning("manifest for %s not loaded: %s", name, exc)
        return [], []


def load_personas() -> list[PersonaBinding]:
    """Discover chorus's persona modules and adapt each into a host provider.

    Each persona module is the source of truth for its own registration data: it exposes a
    module-level ``PERSONA`` dict ({name, role, endpoint, client_id}), a ``register()`` that
    self-registers with Mantle + the gateway, and (if it owns organons) a sibling ``manifest.py``
    declaring the operators it offers. This function reads that metadata; it holds no roster of
    roles/endpoints and no shared operator catalog.
    """
    modules = _load_persona_modules()
    _apply_lumen_premium_swap(modules)
    # Every persona imports its own organons locally — no persona declares ORGANONS, so there is
    # nothing to inject.

    bindings: list[PersonaBinding] = []
    for name, mod in modules.items():
        meta = getattr(mod, "PERSONA", {}) or {}
        role = meta.get("role", "")
        endpoint = meta.get("endpoint", f"/{name}/mcp")
        mount_app = _build_mount_app(name, mod)
        session_manager = getattr(mod.mcp, "_session_manager", None)
        ops, facets = _persona_manifest(name, mod)
        # The persona's own directory — the root `crystal.web_serve` resolves a facet's declared
        # `dist` against. Read from the module that was loaded, so it names where this process
        # actually took the persona from rather than where the layout says personas live.
        _mod_file = getattr(mod, "__file__", "")
        dist_root = Path(_mod_file).resolve().parent if _mod_file else None
        bindings.append(
            PersonaBinding(
                name=name,
                role=role,
                endpoint=endpoint,
                mount_app=mount_app,
                session_manager=session_manager,
                _startup=getattr(mod, "server_startup", None),
                _register=getattr(mod, "register", None),
                operators=ops,
                facets=facets,
                dist_root=dist_root,
            )
        )
    _wire_conversation_carrier()
    _wire_pharos_facet()
    return bindings


def _open_shard_store():
    """The node's own shard, or None with the reason logged.

    One opener, shared by both wirings that need the store (lumen's conversation carrier, sage's
    pharos facet): a second copy of "read EMBER_SQLITE_DIR, open, check ready" would be free to
    drift from this one about what counts as having a store.

    None is a real state: a node with no shard holds no canon and can hold no conversation, and
    each caller degrades on its own surface without raising.
    """
    shard = os.getenv("EMBER_SQLITE_DIR")
    if not shard:
        log.info("no shard — EMBER_SQLITE_DIR unset (store-backed surfaces answer the computed null)")
        return None
    try:
        from mantle.shard.local_store import open_store

        store = open_store()
        if not store.ready():
            log.warning("store at %s opened but is not ready", shard)
            return None
        return store
    except Exception as exc:  # noqa: BLE001 — degrade, never take the host down
        log.warning("shard store unavailable (%s: %s)", type(exc).__name__, exc)
        return None



def _wire_pharos_facet() -> None:
    """Inject sage's own canon tekton into sage's `pharos` facet route.

    Not cross-persona, unlike the conversation carrier below — the tekton and the view are both
    sage's. What the host supplies is the store, which is the host's to open: the persona module
    is imported long before any node decides which shard it holds, and a route that opened its
    own store would be a second answer to that question.

    Every failure leaves the facet dark; none raises. A dark canon is a real state — the route
    answers 503 saying so — without taking the other six personas down with it.
    """
    if not _wanted("sage"):
        return
    store = _open_shard_store()
    if store is None:
        log.info("pharos facet dark — no shard store (the surface says so; it renders nothing)")
        return
    try:
        from agience_chorus.sage import canon, pharos

        pharos._BROWSE_CARRIER = canon.canon_browse_handler(store)
        log.info("pharos facet wired -> %s", canon.CANON_BROWSE_CAP)
    except Exception as exc:  # noqa: BLE001 — degrade, never take the host down
        log.warning("pharos facet dark (%s: %s)", type(exc).__name__, exc)


def _wire_conversation_carrier() -> None:
    """Inject lumen's conversation tekton into aria's bff — the cross-persona wiring.

    The host owns this because neither persona does: chorus personas never import one another, so
    aria's bff ships with `_RESPOND_CARRIER = None` and degrades until something injects a
    responder. That something has to be the component allowed to see both, which is this loader —
    the same wiring `host_lumen.py` performs, letting the chat be served by the crystal instead of
    a bespoke second host outside the model.

    Every failure degrades; none raises. A store that will not open, a lumen that will not import,
    an aria without a bff — each leaves the carrier dark, and a dark carrier is a real state, not
    an outage: the bff reports `offline` with no answer and no invented words. The loader does not
    raise and take all seven personas down because the chat could not be wired.
    """
    store = _open_shard_store()
    if store is None:
        log.info("conversation carrier dark — no shard store (chat answers the computed null)")
        return
    try:
        # Bind the ontology read to the store this process actually holds. An answer measured on
        # a store the host never chose would look identical to one measured on the right store —
        # the same reason host_lumen.py binds it.
        #
        # This bind is load-bearing, not merely correct: `crystal.ontology` may not import
        # mantle, so it has no process-default store to fall back to. With nothing bound and no
        # provider registered, a read raises `driver.OntologyStoreRequired` rather than reading
        # whatever `EMBER_SQLITE_DIR` happened to point at. chorus registers no provider on
        # purpose — this line is the host naming its store.
        from crystal.ontology import driver as wn_store

        wn_store.bind(store)

        from agience_chorus.aria import web_bff

        # The designed route for aria to reach lumen is `ReachHost`, wired through a carrier,
        # evidence, and provenance. This function does not use it: `StoreCarrier.poll()` calls
        # `list_artifacts(content_type=...)` for every leaf ever placed, and every turn appends
        # leaves that every future poll re-reads, so the poll degrades without bound as the corpus
        # grows. Using it here would trade a working chat for an architecturally cleaner one that
        # gets slower forever. Binding this to the reach needs a bounded poll first — a `_seq`
        # watermark, since leaf ids are content-addressed hashes and carry no cursor order.
        bff = sys.modules[web_bff._BFF_MODULE_NAME]

        # The reading answers when a read collection is named: the instrument replaces the ontology
        # path rather than joining it, because the ontology path answers a question like "what is
        # pride" by citing WordNet, which is narrower and less useful than citing what was actually
        # read. `READ_ONTOLOGY=1` (or naming a default collection in `READ_COLLECTION`) points the
        # chat at what has been read instead of at the ontology path.
        #
        # Narrower on purpose: the instrument knows only what has been read into `READ_COLLECTION` —
        # one novel, today. A question outside it reaches the computed null rather than a WordNet
        # citation. A withheld unit retrieves at median rank 15 of 3,870 candidates against a
        # permutation null at 2,040 (`lumen.reading.heldout`).
        #
        # The env var is not a feature flag: it names which collection was read. With none named,
        # there is nothing to answer from, so falling back to the ontology is the correct behaviour
        # rather than a hedge.
        #
        # The collection is the person's choice, not the deployment's: `/use <collection>` and
        # `/collections` are handled by the responder, so which corpus is being talked to can change
        # per conversation without a redeploy. `READ_COLLECTION` only sets where it starts.
        if os.getenv("READ_ONTOLOGY") or os.getenv("READ_COLLECTION"):
            from agience_chorus.lumen.reading import chat as _readchat
            bff._RESPOND_CARRIER = {"respond": _readchat.respond}
            log.info("conversation carrier wired -> lumen.reading CHAT (start %r, store %s)",
                     os.getenv("READ_COLLECTION") or "<none, use /use>",
                     os.getenv("EMBER_SQLITE_DIR", "<unset>"))
            return

        from agience_chorus.lumen import reach_provider

        handler = reach_provider.respond_handler(store, act="respond")
        bff._RESPOND_CARRIER = {"respond": lambda q: handler({"text": q})}
        log.info("conversation carrier wired -> lumen op.respond (grounded by %s)",
                 os.getenv("EMBER_SQLITE_DIR", "<unset>"))
    except Exception as exc:  # noqa: BLE001 — degrade, never take the host down
        log.warning("conversation carrier dark (%s: %s)", type(exc).__name__, exc)


def _content_root_secret(shard: str) -> bytes:
    """The fleet content-key root — derived from the node's own `content.key`, never generated.

    `blake2b(content.key, 32)`, the same derivation `mantle/shard/sqlite_store.py` uses to open the
    lattice's content store. Both ends of a reach derive their ground key from this, so a generated
    one would build a host that talks only to itself — and it would look like it worked, because a
    single process is both ends. Missing key ⇒ raise, so the carrier goes honestly dark rather than
    coming up on a secret nobody shares."""
    import hashlib
    from pathlib import Path

    keyfile = Path(shard) / "keys" / "content.key"
    if not keyfile.exists():
        raise FileNotFoundError(
            "no content.key under %s — the reach needs the fleet content-key root, and inventing "
            "one would produce a host that only talks to itself" % keyfile.parent)
    return hashlib.blake2b(keyfile.read_bytes().strip(), digest_size=32).digest()


if __name__ == "__main__":  # pragma: no cover — the regeneration hook
    # `python src/personas.py` prints the roster. It is not written to a file: a checked-in
    # projection of this function was read by nothing and drifted from it by construction.
    # this way. It is not a source: `src/tests/test_personas.py` fails if the two differ, which
    # keeps the static roster from drifting from the live one.
    import json as _json

    print(_json.dumps(roster(), indent=2))
