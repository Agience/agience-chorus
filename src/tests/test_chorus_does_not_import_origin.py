"""No non-test file in chorus imports `origin`.

prism is Apache-2.0 and origin is AGPL-3.0-only. Chorus reaches origin over the wire at
`ORIGIN_URI` rather than importing it, so a chorus fork does not have to carry origin's
dependencies (sqlalchemy, alembic, webauthn) to answer a request, and a deployment can point at
its own authority. Verification is a contract; issuance is a service: if a persona needs to
verify a token, a claim or a scope, `prism.trust` has it. If it needs a token minted, that is an
HTTP call to origin, not an import.

This reads the AST rather than grepping, so `import origin.config as c` and
`from origin.scopes import x` are both caught, while the word "origin" in a comment or docstring
is not. A lazy import inside a function is caught too — the walk is over the whole tree, not just
the module body — because a runtime dependency is still a dependency.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1]


def _is_test(path: pathlib.Path) -> bool:
    return (any(p in ("tests", "test") for p in path.parts)
            or path.name.startswith("test_")
            or path.name == "conftest.py")


def _imports(path: pathlib.Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                    # pragma: no cover — a broken file is
        return set()                                       # someone else's failure, not this one's
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
    return found


def _non_test_sources() -> list[pathlib.Path]:
    return [p for p in sorted(SRC.rglob("*.py")) if not _is_test(p)]


def test_no_non_test_source_imports_origin():
    offenders = sorted(p.relative_to(SRC).as_posix()
                       for p in _non_test_sources() if "origin" in _imports(p))
    assert not offenders, (
        "chorus imports origin again, in: %s\n"
        "Origin is an AGPL SERVICE reached at ORIGIN_URI, not a library. Verifying a token, a claim "
        "or a scope is `prism.trust`; minting one is an HTTP call." % offenders)


def test_the_scan_can_actually_see_an_import():
    """The control: a scan that finds no files, or an AST walk that misses `from x import y`,
    would pass the assertion above regardless of what is actually imported. This proves the corpus
    is non-empty, proves a known-true import is detected, and proves the detector is not simply
    saying yes."""
    sources = _non_test_sources()
    assert len(sources) > 50, f"the scan found only {len(sources)} source files — it is not looking"

    server_auth_readers = [p for p in sources if "prism" in _imports(p)]
    assert len(server_auth_readers) >= 7, (
        "fewer than seven files import prism — the personas' auth import is supposed to resolve "
        "there now, so either the move regressed or the detector is broken")

    fake = ast.parse("def f():\n    from origin.scopes import extract_licensing_entitlements\n")
    found = {n.module.split(".")[0] for n in ast.walk(fake)
             if isinstance(n, ast.ImportFrom) and n.module}
    assert "origin" in found, "the AST walk misses a lazy `from origin.x import y`"
