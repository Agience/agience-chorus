"""Seraph calls no mantle plane that mantle no longer serves.

WHY. `rotate_api_key` targeted `GET|POST|DELETE /api-keys[/{id}]`, which mantle does not serve.
Its first call 404'd and the tool returned its own *"cannot read the existing key — REFUSING to
rotate"* branch, so an operator was told the rotation was refused FOR SAFETY rather than that the
endpoint was gone. A tool that reports a plausible refusal is worse than one that errors: the
refusal reads as the tool working.

It was removed rather than repointed. Mantle's surviving key surface is `/grants/keys`, whose
contract is per-resource CRUDEASIO; the old one was scope-based. There is no mechanical mapping,
and the tool existed precisely to stop a rotation silently re-scoping a key — *"guessing here would
quietly widen access during a security operation"*.

This checks CODE literals only. The tombstone in `server.py` names the dead plane on purpose, and
a check that forbids naming what it removed makes its own rationale unwritable.
"""
from __future__ import annotations

import ast
import io
import pathlib

#: Planes mantle does not serve. Measured 2026-08-26 against its live route table: mantle serves
#: .well-known, artifacts, auth, docs, events, git, grants, mcp, status, system, v2, version.
DEAD_PLANES = ("/api-keys", "/secrets", "/servers", "/workspaces", "/collections",
               "/search", "/issuers", "/platform", "/downloads", "/gate")

_SERAPH = pathlib.Path(__file__).resolve().parents[1]


def _code_strings(path: pathlib.Path):
    """String literals that are CODE — docstrings skipped, comments never reach the AST."""
    try:
        tree = ast.parse(io.open(path, encoding="utf-8").read())
    except SyntaxError:
        return
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docs.add(id(first.value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs):
            yield node.value
        elif isinstance(node, ast.JoinedStr):
            # f-strings matter most: `f"{MANTLE_URI}/api-keys"` keeps the path in its own
            # Constant half, and a regex over quoted text cannot see it.
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    yield part.value


def _sources():
    for p in _SERAPH.rglob("*.py"):
        if "tests" in p.parts or p.name.startswith("test_"):
            continue
        yield p


def test_the_scan_reads_seraph():
    """A guard that reads nothing passes for ever."""
    assert sum(1 for _ in _sources()) > 3


def test_no_source_calls_a_dead_mantle_plane():
    offenders = []
    for path in _sources():
        for literal in _code_strings(path):
            bare = literal.split("?")[0]
            for plane in DEAD_PLANES:
                if bare == plane or bare.startswith(plane + "/"):
                    offenders.append("%s -> %s" % (path.name, bare))
    assert not offenders, (
        "seraph calls a plane mantle does not serve: " + ", ".join(sorted(set(offenders))))


def test_the_rotation_tool_is_gone_not_merely_unregistered():
    """An unregistered-but-present tool is a body of code that reads as live surface."""
    src = io.open(_SERAPH / "server.py", encoding="utf-8").read()
    assert "async def rotate_api_key" not in src, "the dead rotation tool is back"
