# Operator code lives in chorus. Distributed as a content-addressed source bundle; ember
# sha-verifies before exec.
"""Stage-3 wedge checkers — op.check.python + op.check.latex-math.

A checker is an operator with fitness: it turns a claim into a machine-checked fact. The reasoning
wedge is verification-bearing content — a symbol/answer is trusted iff its checker passes, so the
corpus that teaches reasoning is checkable, never prose hoped to be right. Checkers exist before the
corpus (RUNBOOK §H2): a checker is the operator with fitness that lets machine-checkable answers
enter the lattice as facts.

  • op.check.python     — compile gate + AST symbols (sym-*/calls via code_index, one extractor, no
                          dual path). Verified == it compiles. Runtime verification is a separate,
                          heavier gate that stays with `op.dev.run_tests` (subprocess pytest) — this
                          operator never execs candidate code, so it is safe on untrusted corpus.
  • op.check.latex-math — a structural parse gate (balanced delimiters + \\begin/\\end), plus a real
                          sympy parse when sympy/antlr is present (a stronger gate, honestly optional).

stdlib only in this file — Apache-pure, no network, no exec. The symbol extractor is reached (see
below).
"""
from __future__ import annotations

import ast
import re
from typing import Callable, Dict, List, Optional

from crystal.evolution import OPERATOR_CONTENT_TYPE


# ── the symbol extractor: reached, not path-loaded ──────────────────────────────────────────────
# `astra/code_index.py` is the authoritative home of the symbol extractor; it is distributed
# content-addressed — ember publishes it in the `operators` bundle and sha-verifies it before exec
# (`ember/runner.py`, `_SHARED["code_index"]`) — and reached here through `prism.runner`
# (`from prism.runner import code_index`), the same single path `lumen/code.py:24` already uses.
# There is exactly one extractor; this module does not load astra's file directly.
#
# Resolved lazily and guarded, for the same reason `lumen/reach_provider.py` resolves its `match`
# seam lazily: importing `check` must not require a host to be present. Unresolved, the checker
# degrades honestly — the compile gate is lumen's own and still returns its certificate, and the
# read says the symbol leg did not run (`symbols_available: False`) rather than reporting an empty
# symbol list as if the file defined nothing.
_SYMBOL_EXTRACT: Optional[Callable[[str, str], tuple]] = None   # host/test injection point
_RESOLVED: list = []   # one-slot memo; resolving is a bundle load, not an attribute lookup


def _symbol_extract() -> Optional[Callable[[str, str], tuple]]:
    """The `(path, source) -> (symbols, calls)` extractor, or None when it is not reachable here.

    Injection (`_SYMBOL_EXTRACT`) wins, so a host that reaches `code_index` over the ground plane — or a
    test that wants the leg dark — sets it directly. Otherwise resolve the one distributed copy.

    Memoised including the failure: `from prism.runner import code_index` triggers a bundle load
    (`runner.__getattr__` → sha-verify → exec), so retrying it per checked artifact would repeat that work
    on every call, and repeat a `BundleIntegrityError` traceback with it. Set `_RESOLVED.clear()` to force
    re-resolution (a host that wires the bundle after import).
    """
    if _SYMBOL_EXTRACT is not None:
        return _SYMBOL_EXTRACT
    if _RESOLVED:
        return _RESOLVED[0]
    try:
        from prism.runner import code_index as _ci            # sha-verified single distribution path
        fn = getattr(_ci, "extract", None)
    except Exception:
        fn = None
    _RESOLVED.append(fn)
    return fn


def _check_python(a: Dict) -> Dict:
    """Compile-gate + AST symbol extraction. Never executes the candidate."""
    path = a.get("path") or "<snippet>"
    src = a.get("source")
    if src is None and a.get("path"):
        try:
            with open(a["path"], encoding="utf-8") as f:
                src = f.read()
        except Exception as e:
            return {"checked": "python", "verified": False, "stage": "read", "error": str(e)}
    src = src or ""
    try:
        compile(src, path, "exec")                       # the syntax certificate
    except SyntaxError as e:
        return {"checked": "python", "verified": False, "stage": "compile",
                "error": "%s at line %s" % (e.msg, e.lineno)}
    extract = _symbol_extract()
    if extract is None:
        # Honest degrade: the compile certificate stands on its own (it is lumen's, stdlib `compile`), but
        # the symbol leg did not run and says so. `symbols: []` alone would read as "this file defines
        # nothing", which is a claim this cannot make.
        return {"checked": "python", "verified": True, "compiles": True,
                "symbols": [], "n_symbols": 0, "symbols_available": False,
                "note": "compile gate only — the code_index extractor is not reachable in this "
                        "deployment, so sym-*/calls were NOT extracted (not an empty file). "
                        "Runtime verification is op.dev.run_tests."}
    try:
        symbols, _calls = extract(path, src)              # sym-* + calls, the one extractor
    except Exception as e:
        return {"checked": "python", "verified": True, "compiles": True,
                "symbols": [], "n_symbols": 0, "symbols_available": False,
                "note": "compile gate only — the code_index extractor raised "
                        "(%s), so sym-*/calls were NOT extracted (not an empty file)." % type(e).__name__}
    syms = [{"id": s.id(), "qualname": s.qualname, "kind": s.kind, "name": s.name,
             "calls": list(s.calls), "line": s.line} for s in symbols]
    return {"checked": "python", "verified": True, "compiles": True,
            "symbols": syms, "n_symbols": len(syms), "symbols_available": True,
            "note": "runtime verification is op.dev.run_tests (this gate is compile+AST only)"}


def _check_latex_math(a: Dict) -> Dict:
    """Structural parse gate for a LaTeX math expression; a real sympy parse when available."""
    expr = str(a.get("expr") or "")
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: List[str] = []
    ok, why, i = True, "", 0
    while i < len(expr):
        c = expr[i]
        if c == "\\":                                    # escaped char: \{ \} are literals, skip pair
            i += 2
            continue
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                ok, why = False, "unbalanced %r" % c
                break
            stack.pop()
        i += 1
    if ok and stack:
        ok, why = False, "unclosed %r" % stack[-1]
    if ok:
        begins = re.findall(r"\\begin\{(\w+)\}", expr)
        ends = re.findall(r"\\end\{(\w+)\}", expr)
        if sorted(begins) != sorted(ends):
            ok, why = False, "\\begin/\\end mismatch"
    parsed: Optional[bool] = None
    if ok:
        try:
            from sympy.parsing.latex import parse_latex     # a stronger gate, if the toolchain is here
            parse_latex(expr)
            parsed = True
        except Exception:
            parsed = None                                   # absent/unparseable-by-sympy: structural gate stands
    return {"checked": "latex-math", "verified": bool(ok), "structural_ok": bool(ok),
            "sympy_parsed": parsed, "why": (why or None)}


_CHECK_OPS = [
    ("op.check.python", "verifies a python artifact: compile gate + AST symbols (sym-*/calls via "
     "code_index); verified iff it compiles. Never execs — runtime tests are op.dev.run_tests. The "
     "wedge's code checker: a fact, not prose"),
    ("op.check.latex-math", "verifies a LaTeX math expression: balanced delimiters + \\begin/\\end, "
     "and a sympy parse when the toolchain is present. The wedge's math parse-gate"),
]
_HANDLERS = {"op.check.python": _check_python, "op.check.latex-math": _check_latex_math}


# ADDED 2026-08-26. Operators were registered with NO `collection_id`, and the content seal keys
# on a collection origin root — so they could never be sealed and
# `data_integrity_check.artifacts_holding_inline_plaintext` climbed off zero on every boot. The
# repair that first drove that count to zero gave collectionless platform vocabulary `stage.system`
# "rather than an exemption"; the writers were never changed. This is that fix reaching the writer.
# `collection_id` alone suffices — `vertex._place` writes the origin containment edge from it, in
# the same savepoint as the row. Inlined, not shared: `_persona.load()` loads these modules
# individually and cross-importing between them is the hazard that module exists to prevent.
_SYSTEM_COLLECTION = "stage.system"


def _now_iso() -> str:
    """This observer's clock reading, claimed. The store never invents one (`vertex._attribute`
    returns untouched when `created_time` is None) and it is first-write-wins."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


#: Read ONCE per process, not per call. `manifest.OPERATORS = operators()` is computed at import
#: while `operators()` recomputes on demand, and `test_the_lumen_manifest_surface_is_unchanged_for_
#: the_host` asserts the two are equal — a fresh timestamp per call makes that impossible, and it
#: also makes the registered dict non-deterministic for anything that compares payloads. Reading
#: the clock at import gives one claim per process, which is what an idempotent upsert wants:
#: first-write-wins means only the first one is ever kept anyway.
_REGISTERED_AT = _now_iso()


def register_check_operators(store, *, author: str = "ember-local") -> int:
    from crystal import evolution
    for name, offer in _CHECK_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": "checker operator %s: %s" % (name, offer),
            "created_by": author,
            "collection_id": _SYSTEM_COLLECTION, "created_time": _REGISTERED_AT}))
    return len(_CHECK_OPS)


def invoke(name: str, arguments: Optional[Dict] = None) -> Dict:
    h = _HANDLERS.get(name)
    if h is None:
        raise KeyError("no check operator %r" % name)
    return h(arguments or {})


__all__ = ["register_check_operators", "invoke"]
