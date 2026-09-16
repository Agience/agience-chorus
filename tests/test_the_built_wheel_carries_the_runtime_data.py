"""The built wheel carries every runtime data file, and nothing it should not.

This is the outcome; `test_runtime_data_is_declared_for_packaging.py` is the intent. They fail
differently and both are worth having — a declaration can be right and the build still wrong, and a
declaration can be complete while the enumeration that checks it is not.

⛔ TWICE THE DECLARATION GATE WAS GREEN WHILE THE WHEEL WAS WRONG. On 2026-09-15, 39 `type.json`
files in the source tree and 0 in the wheel. On 2026-09-16, `ophan/policy/` — 13 files that
`licensing.py` reads off the installed package, whose docstring says "It ships with ophan" — again
0. Neither was a wrong pattern; both were a file nobody had thought to declare. A check written
against the declaration can only ask about the files someone listed. This asks the archive.

⚠ IT COMPARES COUNTS TO THE SOURCE TREE, NOT TO A NUMBER TYPED HERE. `assert 39` would pass a wheel
that shipped 39 of 45, and would fail honestly-added work. The source tree is the population; the
wheel must carry all of it.

⚠ AND IT ASSERTS THE ABSENCES TOO. The Facet source tree and `aria/www/` must stay out — 373 MB of
`node_modules` sits beside the first of them. `test_the_web_tree_stays_out_of_the_distribution.py`
holds the two guards that keep it so; this checks they worked.

Modelled on `agience-crystal/tests/test_the_wheel_ships_only_crystal.py`, which has built a real
wheel per run since crystal 0.1.0 shipped a top-level `tests` module into site-packages. Measured
2026-09-16: the build takes about 7 seconds, once per session.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PACKAGE = _REPO / "src" / "agience_chorus"


def _tracked(*args: str) -> list[str]:
    """Paths git carries, so the population is the repository's rather than the disk's."""
    proc = subprocess.run(
        ["git", "ls-files", *args], cwd=_REPO, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        pytest.skip("git could not list the tree; this gate has no population to compare against")
    return [line for line in proc.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> zipfile.ZipFile:
    """Build a wheel from a CLEAN copy of the working tree and hand back the archive.

    ⛔ BUILDING IN THE CHECKOUT MAKES THIS GATE UNABLE TO FAIL, AND IT DID. setuptools stages into
    `build/lib/` and reuses whatever is already there. Measured 2026-09-16: with `ophan/policy`
    removed from `package-data`, the wheel still carried all 13 files — they had been staged by an
    earlier build and were copied forward. Every assertion below passed against a defect that was
    present. A gate that reads a build directory is reading the last build, not this one.

    So the tree is rebuilt from `git ls-files`, with WORKING-TREE content rather than `HEAD`: an
    uncommitted `pyproject.toml` is exactly what a person is testing, and `git archive` would
    quietly test the last commit instead. Only tracked files are copied, so no `build/`, no
    `node_modules`, no `.ruff_cache` comes along.

    Session-scoped: one copy and one build for every assertion. `--no-isolation` uses this
    environment's setuptools rather than resolving one from the network, so the gate runs where no
    index is reachable — and it is the same setuptools that builds the real artifact.
    """
    tracked = _tracked()
    src_dir = tmp_path_factory.mktemp("clean-tree")
    for rel in tracked:
        source = _REPO / rel
        if not source.is_file():          # a path removed from the tree but still in the index
            continue
        target = src_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    assert (src_dir / "pyproject.toml").is_file(), (
        "the clean copy has no pyproject.toml, so the build below would not be this project's")

    out = tmp_path_factory.mktemp("wheel")
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(out)],
        cwd=src_dir, capture_output=True, text=True, check=False)
    built = list(out.glob("*.whl"))
    if proc.returncode != 0:
        pytest.skip("`python -m build` unavailable here:\n%s" % (proc.stderr[-2000:],))
    assert built, "build reported success and produced no wheel"
    return zipfile.ZipFile(built[0])


def test_the_wheel_was_built_and_is_not_empty(wheel: zipfile.ZipFile) -> None:
    """A gate over an empty archive agrees with everything asked of it."""
    names = wheel.namelist()
    assert len(names) > 100, "the wheel holds %d entries, which is too few to be this package" % len(names)
    assert any(n.endswith(".py") for n in names), "the wheel carries no Python at all"


def test_the_wheel_has_one_top_level_package(wheel: zipfile.ZipFile) -> None:
    """`pip install agience-chorus` may add exactly one importable name.

    Crystal 0.1.0 shipped `src/tests/` as a top-level `tests` module and squatted that name for
    everything else in the environment. The same `src/` shape is here.
    """
    roots = {n.split("/")[0] for n in wheel.namelist()}
    roots -= {r for r in roots if r.endswith(".dist-info")}
    assert roots == {"agience_chorus"}, (
        "the wheel ships %s. Only `agience_chorus` may be installed by this distribution." % sorted(roots))


def test_every_type_json_reaches_the_wheel(wheel: zipfile.ZipFile) -> None:
    """The registration input. Zero of these is the exact state that shipped on 2026-09-15.

    `push_server_types` returns before it posts when a server has no types, so a persona missing
    its `ui/` tree registers NOTHING rather than something diminished — the node boots, answers
    `/healthz`, and `/types/all` stays empty for ever.
    """
    in_source = [p for p in _tracked("src/agience_chorus") if p.endswith("type.json")]
    in_wheel = [n for n in wheel.namelist() if n.endswith("type.json")]
    assert in_source, "no type.json in the source tree; this gate is measuring nothing"
    assert len(in_wheel) == len(in_source), (
        "the source tree has %d type.json and the wheel carries %d. Every one of them is a content "
        "type a persona registers at startup." % (len(in_source), len(in_wheel)))


def test_the_licensing_policy_reaches_the_wheel(wheel: zipfile.ZipFile) -> None:
    """`licensing.py::_packaging_root()` reads these off the installed package.

    Absent, `_load_profile` raises `OphanToolError("Unknown profile '<name>'")` — fail-closed, so
    no licensing operation is wrongly permitted, but every one of them fails and the message blames
    the profile name rather than the missing tree.
    """
    in_source = _tracked("src/agience_chorus/ophan/policy")
    in_wheel = [n for n in wheel.namelist() if "/ophan/policy/" in n]
    assert in_source, "no policy tree in the source; this gate is measuring nothing"
    assert len(in_wheel) == len(in_source), (
        "the source tree has %d licensing policy files and the wheel carries %d."
        % (len(in_source), len(in_wheel)))


@pytest.mark.parametrize("tree", ["astra/web/", "aria/www/"])
def test_a_build_tree_does_not_reach_the_wheel(wheel: zipfile.ZipFile, tree: str) -> None:
    """Built, not shipped. 373 MB of `node_modules` sits beside the first of these."""
    carried = [n for n in wheel.namelist() if tree in n]
    assert not carried, (
        "the wheel carries %d file(s) from %s, which is a source tree the build consumes and the "
        "runtime never reads:\n  %s" % (len(carried), tree, "\n  ".join(carried[:10])))
