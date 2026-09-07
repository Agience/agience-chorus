"""Guards against lumen loading sage's module in-process, and against any persona loading another
persona by file path rather than reaching it over the plane.

An in-process file load across personas does not fail loudly: it works on a dev box where every
persona sits in one tree, and only fails once the persona is deployed on its own and the path is not
there. It is also invisible to an import-based isolation guard
(`chorus/src/tests/test_persona_isolation.py` walks `ast.Import`/`ImportFrom`; a
`spec_from_file_location` call is neither), so this file scans for `spec_from_file_location` calls
directly.

Invariants:
  no path load    — no `spec_from_file_location` reaching a sibling persona directory, in any persona.
  budget is local — the `LUMEN_*` grounding budget is read by lumen itself, from the same env vars.
  dark is honest  — with no retrieval reach wired, the corpus leg does not run, and says so, rather
                    than falling back to loading sage or inventing evidence.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]          # agience-chorus/src
sys.path.insert(0, str(_SRC))                       # `_persona` — the unique-name loader
_PERSONAS = ("aria", "astra", "iris", "lumen", "ophan", "sage", "seraph")

assert (_SRC / "sage").is_dir(), (
    "_SRC resolved to %s, which holds no personas — this file moved and parents[] is now wrong" % _SRC)


#: Files the scan could not read. Asserted empty before any verdict — see the handler below.
UNREADABLE: list = []


def _path_loads_reaching_a_sibling_persona():
    """Every `spec_from_file_location(...)` whose arguments mention another persona by name.

    Returns structured records `(importer, relpath, lineno, loaded)` rather than formatted strings, so
    the roster check compares fields directly instead of re-parsing display text.

    Uses the AST rather than a text search: the call is what matters, and a docstring naming
    `sage/retrieval.py` (this file does) must not register as a violation.
    """
    bad = []
    UNREADABLE.clear()
    for persona in _PERSONAS:
        root = _SRC / persona
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8-sig"))
            except (SyntaxError, UnicodeDecodeError) as exc:
                # This scan backs an exact allow-list of known violations, not "assert zero", and a
                # file it cannot read contributes no violations — indistinguishable from a clean one.
                # Recorded here and asserted empty before the verdict, so the allow-list cannot end up
                # describing a scan that never saw the file.
                UNREADABLE.append("%s/%s (%s)"
                                  % (persona, py.relative_to(root).as_posix(), type(exc).__name__))
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if name != "spec_from_file_location":
                    continue
                # Any string literal anywhere in the call naming another persona is the violation.
                # Split into path components rather than comparing the whole literal, so a
                # slash-joined path like `"../sage/retrieval.py"` is caught along with the
                # `parent.parent / "sage" / "retrieval.py"` idiom.
                for lit in ast.walk(node):
                    if not (isinstance(lit, ast.Constant) and isinstance(lit.value, str)):
                        continue
                    parts = [p.strip().lower()
                             for p in lit.value.replace("\\", "/").split("/") if p.strip()]
                    for other in parts:
                        if other in _PERSONAS and other != persona:
                            bad.append((persona, py.relative_to(root).as_posix(),
                                        node.lineno, other))
                            break
    return bad


def _fmt(rec):
    return "%s/%s:%d loads persona %r by path" % rec


# Known, exact roster of accepted violations — not "assert zero". `sage/describe.py` loads astra by
# path; it is pinned here rather than fixed because it is sage's own feature code, and rather than
# asserted-zero because a permanently red shared gate is one everybody learns to ignore. The roster
# fails both ways: a new violation fails, and so does removing one without shrinking the set, so the
# debt can neither grow nor be silently reverted.
KNOWN_PATH_LOADS: set = {
    ("sage", "describe.py", "astra"),
}


def _as_keys(found):
    """Line-number-independent identity: (importer, file, loaded). The roster must not churn when an
    unrelated edit moves the call down a line."""
    return {(imp, rel, other) for imp, rel, _ln, other in found}


def test_no_persona_loads_another_persona_by_path():
    """The guard the import-based isolation test structurally cannot provide.

    `chorus/src/tests/test_persona_isolation.py` walks `ast.Import`/`ImportFrom`; a
    `spec_from_file_location` call is neither. A clean import graph is not a clean dependency graph.
    """
    found = _path_loads_reaching_a_sibling_persona()
    # The roster below is exact — "these and no others" — which cannot rest on files the scan could
    # not read: an unreadable module yields no violations and reads exactly like a clean one.
    assert not UNREADABLE, (
        "these persona sources could not be parsed and were therefore NOT scanned for path loads: "
        "%s. The exact roster below would describe a scan that never saw them." % UNREADABLE)
    keys = _as_keys(found)

    new = keys - KNOWN_PATH_LOADS
    assert not new, (
        "NEW cross-persona PATH LOAD(s):\n  "
        + "\n  ".join(_fmt(r) for r in sorted(found)
                      if (r[0], r[1], r[3]) in new)
        + "\n\nAn in-process file load across personas works on a dev box and vanishes on deployment, and it "
          "is invisible to the AST IMPORT guard. Reach the capability over the ground plane instead "
          "(`sage/reach_provider.py` serves `op.retrieve`)."
    )

    fixed = KNOWN_PATH_LOADS - keys
    assert not fixed, (
        "good news, and this test now needs updating: a known cross-persona path load is GONE:\n  "
        + "\n  ".join("%s/%s -> %s" % k for k in sorted(fixed))
        + "\n\nShrink KNOWN_PATH_LOADS to match, so the remaining debt stays exactly counted. When it "
          "empties, replace the roster with `assert not found` and delete this branch."
    )


def test_the_lumen_to_sage_load_is_the_one_that_is_GONE():
    """Whatever debt remains, lumen must not load sage by path. Independent of the roster above."""
    found = _path_loads_reaching_a_sibling_persona()
    offending = [_fmt(r) for r in found if r[0] == "lumen" and r[3] == "sage"]
    assert not offending, "lumen still loads sage by path: %r" % (offending,)


def test_the_detector_catches_a_seeded_path_load(tmp_path):
    """A guard that cannot fail proves nothing. Seed lumen loading sage by path and prove it is caught."""
    global _SRC
    seeded = tmp_path / "lumen"
    seeded.mkdir(parents=True)
    (seeded / "probe.py").write_text(
        "import importlib.util as u\n"
        "s = u.spec_from_file_location('x', '../sage/retrieval.py')\n", encoding="utf-8")
    real, _SRC = _SRC, tmp_path
    try:
        found = _path_loads_reaching_a_sibling_persona()
    finally:
        _SRC = real
    assert any(r[1] == "probe.py" and r[3] == "sage" for r in found), \
        "the detector missed a seeded cross-persona path load: %r" % (found,)


def test_the_grounding_budget_is_lumens_own_and_reads_the_same_env_vars(monkeypatch):
    """Lumen reads its own grounding-budget configuration rather than reaching into sage for it. The env
    vars are named `LUMEN_*`; the budget is lumen's finite context window. The env var is the single
    source, and both personas read the same name, so a real deployment cannot disagree."""
    monkeypatch.setenv("LUMEN_GROUNDING_CHARS", "1234")
    monkeypatch.setenv("LUMEN_GROUNDING_PER_DOC_CHARS", "56")
    import _persona
    srv = _persona.load("server", __file__)
    assert srv.GROUNDING_CHAR_BUDGET == 1234, "lumen does not read LUMEN_GROUNDING_CHARS itself"
    assert srv.PER_DOC_CHAR_CAP == 56, "lumen does not read LUMEN_GROUNDING_PER_DOC_CHARS itself"


def test_the_default_budget_matches_sages_copy():
    """The env var is the shared source, but the default is written in two places (`lumen/server.py`
    and `sage/retrieval.py:34-35`). If the two defaults diverge, the personas trim to different budgets
    whenever the env var is unset, which is every local run."""
    def _defaults(path: Path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            args = [a for a in ast.walk(node) if isinstance(a, ast.Constant)]
            names = [a.value for a in args if isinstance(a.value, str)]
            for env in ("LUMEN_GROUNDING_CHARS", "LUMEN_GROUNDING_PER_DOC_CHARS"):
                if env in names:
                    lits = [a.value for a in args if isinstance(a.value, str) and a.value != env]
                    if lits:
                        out[env] = lits[0]
        return out

    lumen = _defaults(_SRC / "lumen" / "server.py")
    sage = _defaults(_SRC / "sage" / "retrieval.py")
    assert lumen, "could not find lumen's budget defaults — did the constants move?"
    for env, val in lumen.items():
        if env in sage:
            assert sage[env] == val, (
                "%s default DRIFTED: lumen=%r sage=%r. The env var is the shared source but the fallback is "
                "duplicated by value; keep them equal or one persona trims to a different budget on every "
                "local run." % (env, val, sage[env]))


def test_the_corpus_leg_is_dark_and_says_so_rather_than_reloading_sage():
    """Guards against a fallback that quietly re-adds the coupling, or one that invents evidence.
    Unwired, the module-level reach hook is None — that is the whole degrade, and it is inspectable."""
    import _persona
    srv = _persona.load("server", __file__)
    assert srv._RETRIEVE_REACH is None, "the retrieval reach must be DARK by default"


def test_no_EXECUTABLE_path_load_survives_in_lumen():
    """Checks executable lines only, so a comment in `server.py` mentioning `spec_from_file_location`
    does not count as a violation. Complements the AST sweep above with a direct read of the file where
    an in-process load would matter most."""
    src = (_SRC / "lumen" / "server.py").read_text(encoding="utf-8")
    live = [ln for ln in src.splitlines()
            if "spec_from_file_location" in ln and not ln.lstrip().startswith("#")]
    assert not live, "an executable path load is back in lumen/server.py: %r" % (live,)
