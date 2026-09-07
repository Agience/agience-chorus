# The authoritative home for operator code is chorus; there is no shared catalog and no code
# mirrors. It is distributed to hosts as a content-addressed source bundle
# (agience-observe/build_bundles.py); ember executes it via ember/runtime/runner.py, sha-verified
# before exec. Changes happen here, in chorus.
"""Per-content-type describe handlers — "each content type has its own lemmas."

`describe(store, artifact)` dispatches by content_type to the handler that extracts the
artifact's keyed representation (its lemmas, and for code its symbol sub-artifacts + edges).
This is the unified describe step: dark matter (an observed artifact) -> described (keyed).
Sources call it on every observation, so ingestion of any type gets the right handler —
Python -> symbols, prose -> key terms, WordNet -> already keyed. New types register a handler.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, Dict, Optional

# Loaded two ways (bundle module vs persona-load bare name) — see the note on the same
# import in `lumen/arithmetic.py`. Relative resolves the bundle sibling; bare resolves
# under the persona-load convention. Bare-only silently un-bundles this module.
try:
    from . import content as C
except ImportError:
    import content as C

# op.describe describes code + prose, but indexing is astra's domain ("Ingestion & Indexing"). Interim
# reach: load astra's extractors in-process by path until a capability reach lands (not a copy — the
# code lives only in astra).
import importlib.util as _ilu
import sys as _sys
from pathlib import Path as _P

logger = logging.getLogger("sage.describe")


def _astra(_n: str):
    _mn = f"_astra_{_n}"
    _s = _ilu.spec_from_file_location(_mn, _P(__file__).resolve().parent.parent / "astra" / f"{_n}.py")
    _m = _ilu.module_from_spec(_s)
    _sys.modules[_mn] = _m           # register before exec so the module's @dataclass types resolve
    _s.loader.exec_module(_m)
    return _m


# In a bundle, prefer the bundle's own copies. `bundle_spec.json` already ships `code_index` and
# `doc_index` as modules of the `operators` group, so reaching them by filesystem path is wrong in
# two independent ways once this module is bundled:
#   1. It cannot work. `_astra()` builds the path from `__file__`, and a bundle module is exec'd from
#      an in-memory source string with no `__file__` bound — NameError, at import, for the whole
#      group.
#   2. It defeats the integrity gate. The runner sha-verifies a bundle before exec precisely so a node
#      runs the bytes the mesh carries. Loading a sibling off local disk executes whatever happens to
#      be in the checkout — unverified — while the verified copy sits unused in the same bundle.
# The path shim stays as the fallback, for the persona-load convention it was actually written for
# (sage reaching astra in-process, no bundle involved).
try:
    from . import code_index, doc_index          # bundle siblings — sha-verified with this module
except ImportError:                              # persona-load: no package, reach astra by path
    code_index = _astra("code_index")
    doc_index = _astra("doc_index")

# content_type -> handler(bundle, artifact_dict) -> None  (writes lemmas / symbols / edges)
HANDLERS: Dict[str, Callable] = {}


def register_handler(content_type: str, fn: Callable) -> None:
    HANDLERS[content_type] = fn


def handler_for(content_type: str) -> Optional[Callable]:
    return HANDLERS.get(content_type)


def describe(bundle, artifact: dict) -> bool:
    """Run the content-type's handler on the artifact (resolving full content via content_ref).
    `bundle` is the LocalStore. True if a handler existed."""
    h = HANDLERS.get(artifact.get("content_type", ""))
    if not h:
        return False
    h(bundle, artifact)
    return True


#: Set on an artifact whose description is the always-terminating FALLBACK, not an extraction.
#:
#: The fallback itself stays — `_describe_python` states why: "so describe is always terminating —
#: the file never stays dark and the self-improvement loop can't spin on it forever." What was
#: wrong is that it was INDISTINGUISHABLE from a real description, and `describe_dark` skips on
#: exactly that signal (`if a.get("lemmas"): continue`). Measured on 71/home 2026-08-27: 874
#: capture artifacts carry the literal `['document']` and 473 carry `['module']` — every one a body
#: `resolve_text` could not open (it returned a sealed MEC1 envelope), extracted to nothing, and
#: then skipped forever. `_split` records the identical shape being fixed once before for a
#: different cause.
DESCRIBE_FALLBACK = "describe_fallback"


# ── built-in handlers ─────────────────────────────────────────────────────────
def _split(bundle, artifact: dict):
    """Split an ingested file artifact into (path, source-body).

    Keyed on the actual prefix rather than on `content_ref`: strip line 1 only when it really is
    this artifact's path. `FolderSource` emits `content = f"{path}\\n{text}"` for both the inline
    and the Garage-backed (`content_ref`) cases, so keying the strip on `content_ref` alone misses
    one of them and leaves the path line glued to the source. That matters because `ast.parse`
    treats an absolute path as a hard SyntaxError, which makes `code_index.extract` return
    `([], [])` — no symbol sub-artifacts, with the file still keyed from its stem, so
    `describe_dark` skips it forever with no error at any layer. Checking the actual prefix is
    correct for the Garage-backed case, the inline case, and a source that does not prefix at all.
    """
    text = C.resolve_text(bundle, artifact)   # full content via content_ref (never truncated)
    first, sep, rest = text.partition("\n")
    path = artifact.get("path") or first
    body = rest if (sep and first == path) else text
    return path, body


def _describe_python(bundle, artifact: dict) -> None:
    """Code -> symbol sub-artifacts (keyed individually) + the file's own lemmas. A file with no
    top-level symbols (e.g. __init__.py, a script, or an unparseable file) still gets keyed from
    its module name + imports (with a stem fallback), so describe is always terminating — the file
    never stays dark and the self-improvement loop can't spin on it forever."""
    path, text = _split(bundle, artifact)
    symbols, imports = code_index.extract(path, text)
    docs = [{
        "id": s.id(), "content_type": code_index.SYMBOL_CONTENT_TYPE, "state": "committed",
        "context": s.offer(), "content": s.offer(), "created_by": "ember-local",
        "via": "op.describe.python",                  # the operator that produced this (fitness)
        "lemmas": list(dict.fromkeys([s.name.lower(), s.qualname.lower()])),
        "calls": [c.lower() for c in s.calls], "kind": s.kind,
        "path": s.path, "line": s.line, "sym": s.name, "qualname": s.qualname,
    } for s in symbols]
    if docs:
        bundle.artifacts.put_many(docs, batch=500)
    mod_parts = [t for t in re.split(r"[._/\\]", code_index.module_of(path).lower()) if t and t != "py"]
    lemmas = list(dict.fromkeys(
        [s.name.lower() for s in symbols] + mod_parts + [i.lower() for i in imports]))[:40]
    fell_back = not lemmas
    if fell_back:                                     # truly nothing extractable -> key by file stem
        lemmas = [Path(path).stem.lower() or "module"]
    d = dict(artifact); d["lemmas"] = lemmas; d["via"] = "op.describe.python"
    d[DESCRIBE_FALLBACK] = fell_back
    bundle.artifacts.put_artifact(d)


def _describe_doc(bundle, artifact: dict) -> None:
    """Prose -> key terms (title/headings/freq + domain terms)."""
    path, text = _split(bundle, artifact)
    lemmas = doc_index.extract_terms(path, text)
    fell_back = not lemmas
    if fell_back:
        lemmas = [Path(path).stem.lower() or "document"]
    d = dict(artifact); d["lemmas"] = lemmas; d["via"] = "op.describe.markdown"
    d[DESCRIBE_FALLBACK] = fell_back
    bundle.artifacts.put_artifact(d)


def _noop(bundle, artifact: dict) -> None:
    pass                                          # WordNet is keyed at ingest


def terms_of(content_type: str, path: str, text: str) -> list:
    """Pure describe: map (content_type, path, full text) -> lemmas, with no store write. This
    is the batchable/parallelizable core of describe — call it in-memory during bulk ingest so
    each artifact is written once (with its lemmas) instead of upserted per-record. Prose ->
    key terms; other types fall back to the path stem."""
    if content_type in ("text/markdown", "text/plain", "text/x-rst", "text/x-toml"):
        return doc_index.extract_terms(path, text) or [Path(path).stem.lower() or "document"]
    return []


for _ct in ("text/x-python",):
    register_handler(_ct, _describe_python)
for _ct in ("text/markdown", "text/plain", "text/x-rst", "text/x-toml"):
    register_handler(_ct, _describe_doc)
register_handler("text/x-wordnet", _noop)


def describe_dark(bundle, *, limit: Optional[int] = None) -> int:
    """Illuminate dark matter: describe committed artifacts that have a handler but no lemmas yet.
    Deterministic — the corpus-side of 'always improving.'

    Runs every worker tick (improve.improve_cycle), bounded by `limit`: at most `limit` artifacts
    described per call. The scan itself streams the committed set through the store's typed
    iterator and stops as soon as the budget is spent.
    """
    store = bundle.artifacts
    n = 0
    skipped_sealed = 0
    for a in store.list_artifacts(state="committed"):
        # A FALLBACK IS NOT A DESCRIPTION. Skipping on `lemmas` alone made one unreadable body a
        # permanently unreadable one: the fallback wrote `['document']`, and this line then never
        # looked at the artifact again. Retrying costs a re-read of something already cheap to
        # read, and the fallback keeps the loop terminating for the case that genuinely has
        # nothing to extract.
        if a.get("content_type") not in HANDLERS:
            continue
        if a.get("lemmas") and not a.get(DESCRIBE_FALLBACK):
            continue
        try:
            described = describe(bundle, a)
        except Exception as exc:
            # A SEALED BODY IS A CUSTODY STATE, NOT A DESCRIBE FAILURE, and it must not take the
            # cycle down with it. `resolve_text` now raises `ContentStillSealed` rather than
            # returning an unopened envelope — correct, and it made the FIRST unreadable capture
            # stop every other artifact being illuminated, because neither this function nor
            # `improve_cycle` caught anything. Trading a silent per-artifact failure for a loud
            # whole-system one is not a repair.
            #
            # Caught by NAME, not by importing mantle: chorus does not depend on mantle and must
            # not gain that edge to handle one exception type. Anything else is re-raised, so a
            # genuine bug in a handler still fails loudly.
            if type(exc).__name__ != "ContentStillSealed":
                raise
            # It stays DARK on purpose: nobody read the body, so writing the fallback would be a
            # claim about content nobody saw. It becomes describable the moment custody exists.
            skipped_sealed += 1
            continue
        if described:
            n += 1
            if limit and n >= limit:
                break
    if skipped_sealed:
        logger.info("describe_dark: %d artifact(s) left dark — content still sealed, so no "
                    "principal held a read grant on their collection. They stay retryable.",
                    skipped_sealed)
    return n
