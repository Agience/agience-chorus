"""The Facet source tree is built, not shipped, and nothing may quietly make it packageable.

`test_runtime_data_is_declared_for_packaging.py` asserts everything the runtime READS is declared.
This is its complement: that what must not travel, does not. Both failures are silent — one ships a
package missing the files it needs, the other ships one carrying files it does not.

⛔ WHAT IS BEHIND THIS DOOR. `src/agience_chorus/astra/web` holds 342 tracked files — TypeScript
sources, Vite config, Playwright specs — beside an untracked `node_modules`. None of it is read at
runtime: the runtime reads the BUILT output, which is declared separately.

Measured 2026-09-16: `node_modules` is **373 MB**, against a legitimate tracked payload of 4.1 MB.
A wheel that picked this up would be ninety times the size of the package it was meant to be.

⛔ IT ALSO HOLDS ONE BROKEN PYTHON FILE. `web/src/legacy-lumen-ui/lumen_chat_bff.py` has no imports
at all — `os`, `app`, `Depends`, `Header` and `HTMLResponse` are every one of them undefined, 20
`F821`s in a single file, which is every undefined name in this repo. It cannot be imported and it
is not meant to be; it sits in a hyphenated directory that is not a legal package path. It is the
retired Lumen host's UI, kept as reference. Shipping it would put a module that raises `NameError`
on import inside a published distribution.

TWO INDEPENDENT GUARDS KEEP IT OUT, and this file holds both, because either one alone is a guard
that can be removed by someone who checked only for the other:

1. `web` is not a package — no `__init__.py` — so `packages.find` never considers it.
2. `packages.find.exclude` names it, which is what catches a subpackage that acquires one.

⚠ THE `__init__.py` IS THE LIKELY ACCIDENT. It is a one-character-looking change that a person
makes to get an import working in a test, and its blast radius is a distribution.
"""

from __future__ import annotations

import pathlib

import pytest

try:
    import tomllib
except ModuleNotFoundError:                                  # pragma: no cover - <3.11
    tomllib = None

_REPO = pathlib.Path(__file__).resolve().parents[1]
_WEB = _REPO / "src" / "agience_chorus" / "astra" / "web"
_PYPROJECT = _REPO / "pyproject.toml"


def _find_config() -> dict:
    assert tomllib is not None, "tomllib is unavailable; this gate cannot read pyproject"
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["tool"]["setuptools"]["packages"]["find"]


def test_there_is_a_web_tree_to_keep_out():
    """Without this, every assertion below is true of a directory that is not there."""
    assert _WEB.is_dir(), (
        "%s is gone. If Facet moved, point this gate at its new home rather than deleting it — "
        "the property it protects did not go away with the directory." % _WEB)
    assert list(_WEB.rglob("*.ts")) or list(_WEB.rglob("*.tsx")), (
        "no TypeScript found under the web tree, so this may no longer be the source directory "
        "this gate was written about")


def test_no_directory_under_the_web_tree_is_a_python_package():
    """An `__init__.py` here turns a build directory into something setuptools will consider.

    `node_modules` is skipped: it is untracked, it is enormous, and a stray `__init__.py` inside a
    vendored dependency is not this repository's decision. The guard that covers that case is the
    exclude pattern, asserted below.
    """
    offenders = [
        p.relative_to(_REPO).as_posix()
        for p in _WEB.rglob("__init__.py")
        if "node_modules" not in p.parts
    ]
    assert not offenders, (
        "the Facet source tree has become a Python package:\n  " + "\n  ".join(offenders) +
        "\n\nThat makes 342 tracked TypeScript files — and whatever else is on disk beside them — "
        "candidates for the wheel. Import what you need from a real package instead.")


@pytest.mark.parametrize("pattern", ["*.web*", "*.www*"])
def test_the_exclude_pattern_still_names_the_build_trees(pattern: str):
    """The second guard, and the one that still holds if the first is breached.

    Kept as an exact-string check on purpose. A cleverer assertion — resolving what setuptools
    would actually discover — would need setuptools' own resolution and would pass on the day the
    pattern was reworded into something that no longer matches.
    """
    exclude = _find_config().get("exclude", [])
    assert pattern in exclude, (
        "`%s` is no longer in packages.find.exclude — it is now %r. That pattern is why "
        "agience-crystal 0.1.0's `top_level.txt` still lists `tests` and this package's does not."
        % (pattern, exclude))


def test_discovery_is_still_anchored_to_the_package_name():
    """`include` is the outer bound: without it setuptools packages whatever it finds under src."""
    include = _find_config().get("include", [])
    assert "agience_chorus*" in include, (
        "packages.find.include no longer anchors discovery to this package: %r. Without it "
        "setuptools also packaged `tests` and `types` from a sibling src/ — which shipped." % include)
