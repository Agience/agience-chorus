"""Every file the runtime reads off the installed package must be declared package-data.

⛔ THE FAILURE THIS EXISTS FOR IS TOTAL AND SILENT, AND IT SHIPPED. Measured 2026-09-15: each
persona's owned content types are read from ``<persona>/ui/<category>/<subtype>/type.json`` by
``crystal.type_registration.collect_server_types``, at registration time, off the INSTALLED
package — and ``[tool.setuptools.package-data]`` declared only ``bundles/*.json``. The wheel
carried 39 ``type.json`` files fewer than the source tree: all of them.

``push_server_types`` returns before it posts when a server ships no types (``if not types:
return 0``), so a persona with no ``ui/`` tree does not register a diminished record — it registers
NOTHING. The host booted, mounted all seven personas, answered ``/healthz``; the gateway logged
"awaiting persona registration" for ever and ``/types/all`` stayed empty, so every client fell back
to its build-time primitives. Healthy from every angle, with no types at all.

⚠ ONLY AN INSTALLED NODE WAS AFFECTED, WHICH IS WHY NOTHING CAUGHT IT. The fleet runs the host with
``--app-dir …/agience-chorus/src``, where the trees are simply present on disk. The path that broke
is the one nobody exercises: ``curl get.agience.ai/install.sh``.

⚠ THIS CHECKS THE DECLARATION, NOT A BUILT WHEEL. Building one here would be ground truth and costs
seconds per run; the declaration is what a person edits and what went wrong, so it is what is
pinned. The translator below is held to its own cases so the gate cannot pass by failing to match
anything.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
PACKAGE = SRC / "agience_chorus"


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """setuptools package-data glob -> regex, with ``**`` spanning directories.

    ``*`` stops at a separator and ``**`` does not; everything else is literal. Written out rather
    than reached for via ``PurePath.match``, which does not treat ``**`` as recursive, and
    ``full_match`` which needs 3.13.
    """
    out = ["^"]
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:[^/]+/)*")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if ch == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(ch))
        i += 1
    out.append("$")
    return re.compile("".join(out))


class TestTheTranslator:
    """The matcher is the part that can silently pass everything or nothing."""

    @pytest.mark.parametrize(
        "pattern,path,expected",
        [
            ("ui/**/*", "ui/application/vnd.agience.prompt+json/type.json", True),
            ("ui/**/*", "ui/index.html", True),
            ("ui/**/*", "bundles/canon.json", False),
            ("bundles/*.json", "bundles/canon.json", True),
            ("bundles/*.json", "bundles/nested/canon.json", False),
            ("seraph/bundle_spec.json", "seraph/bundle_spec.json", True),
        ],
    )
    def test_matching(self, pattern: str, path: str, expected: bool) -> None:
        assert bool(_glob_to_regex(pattern).match(path)) is expected


def _declared() -> dict[str, list[str]]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data.get("tool", {}).get("setuptools", {}).get("package-data", {})


def _ancestor_packages(path: Path) -> list[Path]:
    """Every package directory above this file, nearest first.

    ⚠ NOT JUST THE NEAREST ONE. setuptools globs a package-data pattern relative to the DECLARING
    package's directory and preserves the path underneath it, so `"agience_chorus"` may legitimately
    declare `"seraph/bundle_spec.json"` even though `seraph` is itself a package. Attributing each
    file to its closest `__init__.py` was stricter than setuptools actually is, and reported that
    file as unshipped while it sat in the installed wheel — a gate that invents work.
    """
    out: list[Path] = []
    for parent in path.parents:
        if (parent / "__init__.py").is_file():
            out.append(parent)
        if parent == SRC:
            break
    return out


#: Non-Python files under the package that are NOT read off the installed package, each with the
#: reason. Everything else found by the sweep below must be declared package-data.
#:
#: ⛔ THIS LIST IS THE POINT. The sweep used to be `PACKAGE.glob("*/ui/**/*")` plus the bundles —
#: it enumerated exactly the two categories that had already gone wrong, so it could re-check
#: yesterday's defect and could not discover tomorrow's. Measured 2026-09-16: `ophan/policy/` is 13
#: files read off the installed package by `licensing.py::_packaging_root()`, whose docstring says
#: "It ships with ophan" — and a freshly built wheel carried 0 of them. This gate was green
#: throughout, because nobody had added `policy` to the glob.
#:
#: Inverting it is what makes it a gate rather than a regression test: a new data tree is covered by
#: default, and its author must either declare it or say here why it stays behind.
#: ⚠ KEYED ON PATH, NOT ON FILENAME. A bare `"mcp.json"` would excuse a file of that name ANYWHERE,
#: including a future one that is read at runtime — the same "exclude by name" mistake that makes a
#: `.ruff_cache` filter rot. Each glob is anchored to where the file actually lives, so a copy
#: somewhere new is swept in and has to argue for itself.
_NOT_RUNTIME_DATA = {
    "*/README.md": "developer prose",
    "*/*/README.md": "developer prose",
    "*/_astra_tables.md": "developer prose",
    "*/_lumen_tables.md": "developer prose",
    "*/pyproject.toml": "per-persona dev metadata; the distribution is built from the root one",
    "*/requirements.txt": "per-persona dev metadata",
    "*/entrypoint.sh": "container entrypoint, run by the image, never read off the package",
    "*/*/entrypoint.sh": "container entrypoint, run by the image, never read off the package",
    "*/.well-known/mcp.json": (
        "a static descriptor for standalone persona deployment. The host does NOT read it: "
        "`crystal.host`'s `/.well-known/mcp` builds its answer from `_discovery_entries(personas)` "
        "and the persona map, verified 2026-09-16."),
}

#: Trees excluded from the distribution outright, so nothing inside them is runtime data.
#: `packages.find.exclude` names both, and chorus's own
#: `test_the_web_tree_stays_out_of_the_distribution.py` holds that.
_NOT_SHIPPED_TREES = ("web", "www")


def _runtime_data_files() -> list[Path]:
    """Every non-Python file under the package, less the ones named as not runtime data.

    Discovery, not a list of known cases. A file is assumed to be needed at runtime unless
    `_NOT_RUNTIME_DATA` says otherwise, because that is the direction whose failure is silent: a
    data file nobody declared is simply absent from the wheel, and the code that reads it fails at
    the moment a user first exercises it.
    """
    found: list[Path] = []
    for path in _tracked_files():
        if path.suffix == ".py":
            continue
        parts = path.relative_to(PACKAGE).parts
        if any(t in parts for t in _NOT_SHIPPED_TREES):
            continue
        rel = path.relative_to(PACKAGE).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) for pattern in _NOT_RUNTIME_DATA):
            continue
        found.append(path)
    return found


def _tracked_files() -> list[Path]:
    """Files git is carrying under the package.

    ⚠ TRACKED-NESS, NOT A LIST OF DIRECTORY NAMES TO SKIP. A plain `rglob` swept in 318 files on
    this box, every one of them `.ruff_cache` — and the fix of excluding `.ruff_cache` by name
    would hold only until the next tool invented its own directory. What setuptools ships is drawn
    from what the repository carries, so that is the same question this should ask.

    A checkout without git SKIPS. A gate whose oracle is missing asserts nothing, and answering
    "nothing uncovered" from an empty sweep is the failure this whole file is about.
    """
    proc = subprocess.run(
        ["git", "ls-files", "-z", str(PACKAGE)],
        capture_output=True, cwd=PACKAGE.parents[1], check=False,
    )
    if proc.returncode != 0:
        pytest.skip("git could not list the package tree; the sweep has no oracle here")
    names = [n for n in proc.stdout.decode("utf-8").split(chr(0)) if n]
    if not names:
        pytest.skip("git listed no files under the package; the sweep has no oracle here")
    root = PACKAGE.parents[1]
    return [root / n for n in names]


class TestRuntimeDataIsDeclared:
    def test_there_is_runtime_data_to_check(self) -> None:
        """A tree that has moved makes every assertion below vacuously true."""
        files = _runtime_data_files()
        assert files, f"no runtime data found under {PACKAGE} — this gate is measuring nothing"

        # The registration input specifically. Zero of these is the exact broken state.
        types = [p for p in files if p.name == "type.json"]
        assert types, "no persona type.json found — collect_server_types would return nothing"

    def test_every_runtime_data_file_is_covered_by_a_declared_pattern(self) -> None:
        declared = _declared()
        assert declared, "pyproject declares no package-data at all"

        uncovered: list[str] = []
        for path in _runtime_data_files():
            covered = False
            for package in _ancestor_packages(path):
                rel = path.relative_to(package).as_posix()
                key = package.relative_to(SRC).as_posix().replace("/", ".")
                patterns = list(declared.get(key, [])) + list(declared.get("*", []))
                if any(_glob_to_regex(p).match(rel) for p in patterns):
                    covered = True
                    break
            if not covered:
                uncovered.append(path.relative_to(PACKAGE).as_posix())

        assert not uncovered, (
            f"{len(uncovered)} file(s) the runtime reads are not declared package-data, so the "
            f"wheel will not carry them:\n  " + "\n  ".join(sorted(uncovered)[:20])
        )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
