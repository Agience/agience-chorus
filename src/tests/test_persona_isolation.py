"""Guards against a persona importing another persona.

Personas reach each other over the ground plane (`beam.reach`), never by Python import. That is what
makes a persona relocatable, independently deployable, and unable to drag a sibling's dependency tree
into its own process. `ember/tests/test_reach_wiring.py` guards the ember side of the DAG (ember must
not import chorus); this file guards the persona-to-persona edge.

A persona-to-persona import does not fail loudly: it works in-process on a dev box where every persona
is on the path, and only fails once the persona is deployed on its own and the import is gone. It is
also the exact coupling the ember-to-chorus migration removes, so it can grow back unless something
counts it.

The known-violation roster (`KNOWN`, below) is currently empty: every persona-to-persona source import
is one this test flags as a new violation. If a violation is ever deliberately accepted, it goes into
`KNOWN` with a reason, keeping the count exact instead of loosening the assertion.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]          # agience-chorus/src

PERSONAS = ("aria", "astra", "iris", "lumen", "ophan", "sage", "seraph")

# Kept as an explicit, empty roster rather than deleted: if a violation is ever deliberately accepted,
# it goes here with a reason, and the count stays exact instead of the assertion being loosened.
KNOWN: set[tuple[str, str, str]] = set()

assert (SRC / "sage").is_dir(), (
    f"SRC resolved to {SRC}, which holds no personas — this file moved and parents[] is now wrong")


def _persona_of(path: Path) -> str | None:
    rel = path.relative_to(SRC).parts
    return rel[0] if rel and rel[0] in PERSONAS else None


def _persona_py_files(include_tests: bool = False):
    """Every persona-owned .py file this guard is responsible for. One definition, so the scan and the
    parse-failure check below cannot disagree about what is in scope."""
    for py in SRC.rglob("*.py"):
        if "__pycache__" in py.parts or "node_modules" in py.parts:
            continue
        if _persona_of(py) is None:
            continue
        if "tests" in py.relative_to(SRC).parts and not include_tests:
            continue
        yield py


def _parse_failures(include_tests: bool = False):
    """(relpath, error) for every persona file that will not parse — the files the scan cannot see.

    An unparseable file contributes zero violations and is indistinguishable from a clean one unless
    this check surfaces it separately, so a bare `except`/`continue` inside `_cross_persona_imports`
    cannot silently drop it from the count. A UTF-8 BOM is enough to trigger this
    (`ast.parse` on a leading `\\ufeff` raises `SyntaxError`).
    """
    bad = []
    for py in _persona_py_files(include_tests):
        try:
            ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            bad.append((py.relative_to(SRC).as_posix(), f"{type(exc).__name__}: {exc}"))
    return bad


def _cross_persona_imports(include_tests: bool = False):
    """(importer, relpath, lineno, imported) for every persona→other-persona import. AST, not grep:
    a regex counts the word in a docstring and misses `from iris . comms import`."""
    out = []
    for py in _persona_py_files(include_tests):
        mine = _persona_of(py)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # Not a silent skip: the same file is reported by `_parse_failures`, which
            # `test_an_unparseable_persona_file_FAILS_rather_than_vanishing` turns into a failure here.
            # Skipping in this loop only keeps the violation list well-typed.
            continue
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            elif isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            for root in roots:
                if root in PERSONAS and root != mine:
                    out.append((mine, py.relative_to(SRC).as_posix(), node.lineno, root))
    return out


def test_no_persona_SOURCE_imports_another_persona():
    """Checks source files only, deliberately.

    The rule exists so a persona can be deployed on its own: a sibling import drags that sibling's
    dependency tree into this persona's process, and the persona cannot then be shipped alone. A test
    file is never deployed, and a test that exercises a cross-persona path (lumen's router reaching
    sage's `op.retrieve`) legitimately needs both sides in one process to assert anything. Tests are
    counted separately, in `test_cross_persona_TEST_imports_stay_visible_and_bounded`, rather than
    exempted silently.

    If a module moved and a test now fails this check: reach the moved module over the plane rather
    than adding the import to the source."""
    found = _cross_persona_imports()
    as_set = {(a, b, d) for a, b, _, d in found}

    new = as_set - KNOWN
    assert not new, (
        "NEW persona→persona import(s) — a persona must REACH a sibling over the ground plane "
        "(`beam.reach`), never import it, or it cannot be deployed on its own:\n"
        + "\n".join(f"  {b}:{ln}  {a} → {d}" for a, b, ln, d in sorted(found)
                    if (a, b, d) in new)
        + "\n\nIf this import is genuinely a MEASUREMENT both personas need, the measurement belongs "
          "in ember or beam (that is why `tekton_basis` lives in ember, not sage) — move it down, do "
          "not import sideways.")

    fixed = KNOWN - as_set
    assert not fixed, (
        "good news, and this test now needs updating: a known persona→persona import is GONE:\n"
        + "\n".join(f"  {a} → {d}  ({b})" for a, b, d in sorted(fixed))
        + "\n\nShrink KNOWN to match, so the remaining debt stays exactly counted. When it empties, "
          "replace the whole roster with `assert not found` and delete this branch.")


def test_an_unparseable_persona_file_FAILS_rather_than_vanishing():
    """A file that does not parse contributes zero violations, so without this test it would read as
    clean. The guard must fail on it instead; `test_the_unparseable_detector_can_actually_fire` proves
    this check can actually fire."""
    bad = _parse_failures(include_tests=True)
    assert not bad, (
        "persona file(s) the isolation scan CANNOT READ — it reported no violations for them, which is "
        "not the same as them having none:\n"
        + "\n".join(f"  {rel}  ({err})" for rel, err in sorted(bad))
        + "\n\nFix the file (a UTF-8 BOM is the usual cause — strip it) or the guard is blind to it.")


def test_the_unparseable_detector_can_actually_fire(tmp_path):
    """A check that cannot fail proves nothing. Seed a BOM-prefixed persona file and prove
    `_parse_failures` reports it."""
    seeded = tmp_path / "src" / "lumen"
    seeded.mkdir(parents=True)
    (seeded / "bom.py").write_bytes(b"\xef\xbb\xbfimport os\n")

    global SRC
    real, SRC = SRC, tmp_path / "src"
    try:
        bad = _parse_failures()
        clean = _cross_persona_imports()
    finally:
        SRC = real
    assert any(rel == "lumen/bom.py" for rel, _ in bad), \
        f"the parse-failure detector missed a seeded BOM file: {bad!r}"
    assert not clean, \
        "and this is the blind spot itself: the import scan reported the same file as CLEAN"


def test_the_scan_is_actually_scanning():
    """The vacuous-pass mode: a glob that matches nothing reports no violations and looks green."""
    files = [p for p in SRC.rglob("*.py") if _persona_of(p) is not None]
    assert len(files) > 100, f"only {len(files)} persona files found under {SRC} — the scan is not running"


def test_the_detector_catches_a_seeded_violation(tmp_path):
    """A guard that cannot fail proves nothing. Seed `sage` importing `lumen` and prove it is caught."""
    seeded = tmp_path / "src" / "sage"
    seeded.mkdir(parents=True)
    (seeded / "probe.py").write_text("from lumen.transducer import Transducer\n", encoding="utf-8")

    global SRC
    real, SRC = SRC, tmp_path / "src"
    try:
        found = _cross_persona_imports()
    finally:
        SRC = real
    assert ("sage", "sage/probe.py", 1, "lumen") in found, \
        "the detector missed a seeded sage→lumen import"


def test_cross_persona_TEST_imports_stay_visible_and_bounded():
    """Tests may cross personas; the count must not drift unnoticed.

    Each entry is a test driving a genuinely cross-persona path in one process. That is legitimate --
    but it is also how a "temporary" coupling becomes permanent, so the roster is pinned: a new one
    fails here and has to be justified, and a removed one fails too so the roster shrinks honestly.
    """
    known = {
        # lumen's router -> sage's `op.retrieve`. Lives in sage's suite because the fixture is sage's
        # corpus; it imports lumen only to drive the router.
        ("sage", "sage/tests/test_reach_provider_sage.py", "lumen"),
    }
    found = {(a, b, d) for a, b, _, d in _cross_persona_imports(include_tests=True)
             if "tests" in b.split("/")}

    new = sorted(found - known)
    assert not new, (
        "NEW cross-persona TEST import(s). Legitimate for a genuinely cross-persona path, but record "
        "it here so the coupling stays counted: " + repr(new))

    gone = sorted(known - found)
    assert not gone, (
        "a cross-persona test import is GONE -- good news; shrink the roster to match: " + repr(gone))
