"""`agience-beam` is archived. This is what keeps chorus off the dead address, and off the new one.

The three pieces of `beam` now live at:

    THE WIRE        → `prism.*` (behind `prism[wire]`)   reach · plane · streams · carriers · frames
                                                          propagation · mcp_bridge · schema · demurrage
                                                          minting · settlement · pump · minhash
                                                          error_threshold · extraction · conservation
    THE DERIVATIONS → `prism.*` (dependency-free base)   resolution · adaptive_cut
    THE INSTRUMENT    → `ember.optics`, under ember's AGPL

The ban is total: there is no legitimate `beam` address left, the package does not exist, so every
submodule is banned and there is nothing to count.

Reading the source matters even though a relapse would raise `ModuleNotFoundError`, because that
error only raises on the branch that executes. Chorus reaches measurement code through lazy,
function-local imports by design, so a `beam` import inside a rarely-taken branch runs green until
the day it does not.

The instrument edge is still pinned, just at a different name. `chorus → ember` is the L3→L3 edge
now, and the ratchet that holds it at 0 with a mutation control is
`test_chorus_does_not_import_ember.py`. This file adds beside it the instrument-specific slice a
reader comes here looking for, plus the half no other file checks: that chorus's tests still
declare themselves hosts. See `test_the_instrument_moved_to_ember_and_only_tests_may_hold_it`.

AST, not grep: `import beam.reach as r`, `from beam.reach import x` and `from beam import reach`
are all caught (the third is why the walk resolves the imported names too), a lazy import inside a
function is caught because the walk covers the whole tree, and the word "beam" in a docstring is
not.
"""
from __future__ import annotations

import ast
import pathlib
import tempfile

SRC = pathlib.Path(__file__).resolve().parents[1]

#: The wire, as it now stands in prism. Kept as a list, not collapsed into "everything", because the
#: failure message has to tell a reader where the module went, and "reach is prism.reach now" is the
#: sentence that fixes the offending line.
WIRE = frozenset({
    "reach", "plane", "streams", "carriers", "frames", "propagation", "mcp_bridge", "schema",
    "demurrage", "minting", "settlement", "pump", "minhash", "error_threshold", "extraction",
    "conservation",
})

#: What moved to prism's dependency-free base.
MOVED_TO_PRISM = frozenset({"resolution", "adaptive_cut"})

#: The instrument. It is `ember.optics` now.
INSTRUMENT = "optics"

#: The pin: `chorus -> ember.optics` reaches held at 0. A ratchet, not a target — moving down is the
#: work; moving up needs a reason written beside it. It is at the floor.
INSTRUMENT_SITES_NON_TEST = 0


def _is_test(path: pathlib.Path) -> bool:
    return (any(p in ("tests", "test") for p in path.parts)
            or path.name.startswith("test_")
            or path.name == "conftest.py")


def _submodules_of(path: pathlib.Path, package: str) -> set[str]:
    """Every `<package>.<name>` this file reaches, however it spells the reach.

    `from ember import optics` names the submodule in the imported names, not in the module path, so
    both places are read. A dotted-only scan reports that spelling as nothing. A bare `import ember`
    with no submodule yields `""`, which belongs to no submodule set and is therefore never mistaken
    for an instrument reach."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                    # pragma: no cover — someone else's file
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                if parts[0] == package:
                    found.add(parts[1] if len(parts) > 1 else "")
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            parts = node.module.split(".")
            if parts[0] != package:
                continue
            if len(parts) > 1:
                found.add(parts[1])
            else:                                          # `from <package> import <name>` — the name
                found |= {a.name for a in node.names}       # is the submodule (or an attribute)
    return found


def _sources(tests: bool):
    return [p for p in sorted(SRC.rglob("*.py"))
            if "__pycache__" not in p.parts and _is_test(p) is tests]


def _beam_offenders(tests: bool) -> list[str]:
    """Every reach for the archived package, whatever it names. There is no allow-list."""
    return sorted("%s: %s" % (p.relative_to(SRC).as_posix(),
                              ", ".join(sorted(s or "<the package itself>" for s in hit)))
                  for p in _sources(tests)
                  for hit in [_submodules_of(p, "beam")] if hit)


def _where_it_went(name: str) -> str:
    if name in WIRE:
        return "`prism.%s` (needs the `prism[wire]` extra)" % name
    if name in MOVED_TO_PRISM:
        return "`prism.%s` (prism's dependency-free base)" % name
    if name == INSTRUMENT:
        return "`ember.optics` — and chorus PRODUCT code may not reach it; inject the slot"
    return "nowhere — `beam` no longer exists"


def test_no_non_test_source_imports_the_archived_beam():
    offenders = _beam_offenders(tests=False)
    assert not offenders, (
        "chorus product code imports `beam`, which is ARCHIVED:\n  %s\n\n"
        "Where each piece went:\n  %s"
        % ("\n  ".join(offenders),
           "\n  ".join("%-16s -> %s" % (n, _where_it_went(n))
                       for n in sorted(WIRE | MOVED_TO_PRISM | {INSTRUMENT}))))


def test_no_test_under_src_imports_the_archived_beam():
    """The tests are held to the same line, and here that is not a style rule: a test importing a
    package that no longer exists is a collection error, so this failing is the difference between
    one named line and a suite that will not start."""
    offenders = _beam_offenders(tests=True)
    assert not offenders, (
        "a chorus test imports the archived `beam`:\n  %s" % "\n  ".join(offenders))


def _instrument_sites(paths) -> list:
    """(file, submodules) for every path reaching the instrument at its new address.

    Factored out of the pin so the control can run the same counting path over a seeded reach: a pin
    at 0 whose counter had quietly stopped counting would otherwise pass forever and for nothing."""
    return [(p, sorted(hit)) for p in paths
            for hit in [_submodules_of(p, "ember") & {INSTRUMENT}] if hit]


def test_the_instrument_moved_to_ember_and_only_tests_may_hold_it():
    """Both halves of the instrument edge; the second half is checked nowhere else.

    Product code: 0. `chorus → ember` is the L3→L3 sideways edge `ARCHITECTURE-TARGET.md` §2
    forbids, and the instrument moving into ember did not create an exception to it. Every product
    call site resolves the instrument through `prism.instrument` — an injected `read=` /
    `dynamics=` / `conservation=` keyword, then the process default, then an honest refusal.

    Tests: not zero. A chorus test that measures needs a host, and it becomes one by importing
    ember — `ember/__init__.py` registers `ember.optics` as the process default. That registration
    is process-global, so if the declarations were tidied away as "unused imports" the suite would
    stay green (something else imports ember) while the individual files would fail when run alone.
    Requiring the declarations to still be there is what stops a linter from re-introducing that
    silently.

    `src/conftest.py` also imports ember, deliberately, and is classified as a test file here, so it
    is not what satisfies the floor below on its own.
    """
    product = [(p.relative_to(SRC).as_posix(), hit) for p, hit in _instrument_sites(_sources(tests=False))]
    n = sum(len(hit) for _p, hit in product)
    assert n == INSTRUMENT_SITES_NON_TEST, (
        "chorus product code reaches `ember.optics` %d times, pinned at %d.\n  %s\n"
        "The instrument is EMBER's. Chorus resolves an instrument through `prism.instrument`: pass "
        "`read=` / `dynamics=` / `conservation=`, fall back to the process default, or refuse. "
        "Widening a prism contract from a CONSUMER is how a contract stops describing anything — add "
        "the member in prism first, with the discriminators."
        % (n, INSTRUMENT_SITES_NON_TEST,
           "\n  ".join("%s: %s" % (p, ", ".join(h)) for p, h in product)))

    hosts = sorted(p.relative_to(SRC).as_posix() for p in _sources(tests=True)
                   if _submodules_of(p, "ember"))
    assert len(hosts) >= 5, (
        "only %d chorus test files declare a host (`import ember` / `from ember import optics`), and "
        "there were 7. A test that measures needs the process-default instrument, and the default is "
        "GLOBAL — dropping the declaration leaves the suite green and breaks the file when it is run "
        "ALONE. These are HOST DECLARATIONS carrying `# noqa: F401`, not unused imports.\n  found: %s"
        % (len(hosts), ", ".join(hosts)))


def test_the_scan_can_actually_see_an_import():
    """The controls. Both pins above are 0, so "the count is 0" and "the counter is broken" are the
    same observation unless a violation is seeded and the same code path is required to find it."""
    non_test = _sources(tests=False)
    assert len(non_test) > 50, (
        "the scan found only %d non-test source files — it is not looking" % len(non_test))
    assert _sources(tests=True), "the scan found no tests, so the second assertion is vacuous"

    real = len(_instrument_sites(non_test))
    assert real == INSTRUMENT_SITES_NON_TEST

    with tempfile.TemporaryDirectory() as d:
        seeded = pathlib.Path(d) / "seeded_reach.py"

        # ── the instrument counter, at its new address, in both spellings ──────────────────────────
        seeded.write_text("from ember.optics import entropy_bits\n", encoding="utf-8")
        assert len(_instrument_sites(non_test + [seeded])) == real + 1, (
            "the instrument counter did not fire on a file importing `ember.optics` — the pin at %d is "
            "measuring nothing" % INSTRUMENT_SITES_NON_TEST)
        seeded.write_text("def f():\n    from ember import optics\n", encoding="utf-8")
        assert len(_instrument_sites(non_test + [seeded])) == real + 1, (
            "the counter misses `from ember import optics` — the spelling four scans got wrong")

        # …and it must not fire on a bare `import ember`, which names no submodule, nor on a
        # non-instrument one. Otherwise "0 instrument reaches" would just mean "0 ember reaches".
        seeded.write_text("import ember\nfrom ember.runtime import delegate\n", encoding="utf-8")
        assert len(_instrument_sites(non_test + [seeded])) == real, (
            "the instrument counter fired on a non-instrument ember import — it is counting the package, "
            "not the seam")

        # ── the archived-package ban, in each of the three import spellings ──────────────────────
        for src, want in (("import beam.reach\n", "reach"),
                          ("from beam.reach import Reactor\n", "reach"),
                          ("def f():\n    from beam import reach\n", "reach"),
                          ("import beam\n", "")):
            seeded.write_text(src, encoding="utf-8")
            assert want in _submodules_of(seeded, "beam"), (
                "the AST walk misses this spelling of a beam import: %r" % src)

        # …and it does not fire on the word in prose, or on the packages that now hold the pieces.
        seeded.write_text('"""beam.reach is mentioned here."""\n'
                          "from prism.reach import Reactor\n"
                          "from ember.optics import read_ordered\n", encoding="utf-8")
        assert not _submodules_of(seeded, "beam"), (
            "the detector fires on prose, on `prism.reach`, or on `ember.optics` — it would fail on a "
            "correct repoint")
