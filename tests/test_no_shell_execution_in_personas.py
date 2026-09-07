"""Guard: no Chorus persona may execute a caller-supplied command in a shell.

Every persona runs in the container holding ``chorus.private.pem`` — the RS256
key each one signs with. A shell reachable from a tool argument (or from a prompt
injection into an agent wired to that tool) reads the key and forges service JWTs
to Mantle and Origin, which defeats every other control in Chorus.

This guards the shape, not one persona: ``iris.exec_shell`` is the named case
``test_iris_exposes_no_shell_tool`` checks below, and the pattern-level scan
above catches the same shape anywhere else in chorus.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Persona servers live under src/<persona>/.
SRC = Path(__file__).resolve().parents[1] / "src"

# Attribute-call sinks: asyncio.create_subprocess_shell, os.system, os.popen, ...
FORBIDDEN_ATTRS = {
    "create_subprocess_shell",
    "system",
    "popen",
    "getoutput",
    "getstatusoutput",
}
# Modules whose calls we care about, to keep `foo.system(...)` on an unrelated
# object from tripping the check.
FORBIDDEN_MODULES = {"asyncio", "os", "subprocess", "commands"}


def _python_files() -> list[Path]:
    """Runtime sources only — test code may legitimately name these sinks."""
    return sorted(p for p in SRC.rglob("*.py") if "tests" not in p.parts)


def _shell_sinks(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"), filename=str(path))
    except SyntaxError:
        return []

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if isinstance(func, ast.Attribute):
            mod = func.value.id if isinstance(func.value, ast.Name) else None
            if func.attr in FORBIDDEN_ATTRS and mod in FORBIDDEN_MODULES:
                found.append((node.lineno, f"{mod}.{func.attr}()"))

        # Any subprocess/asyncio call passing shell=True, however spelled.
        for kw in node.keywords:
            if (
                kw.arg == "shell"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                found.append((node.lineno, "shell=True"))

    return found


def test_no_shell_execution_in_chorus_personas():
    findings = [
        (path.relative_to(SRC).as_posix(), line, what)
        for path in _python_files()
        for line, what in _shell_sinks(path)
    ]
    if findings:
        lines = "\n".join(f"  src/{p}:{line}  {what}" for p, line, what in findings)
        pytest.fail(
            "Shell execution reachable inside the container holding chorus.private.pem.\n"
            "Use argv (no shell) in a workload that does not hold the signing key.\n\n"
            f"{lines}"
        )


def test_iris_exposes_no_shell_tool():
    """No iris tool, under any name, exposes "shell" or "exec"."""
    iris = SRC / "iris" / "server.py"
    tree = ast.parse(iris.read_text(encoding="utf-8-sig", errors="replace"))

    tool_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for dec in node.decorator_list
        # @mcp.tool(...) and bare @mcp.tool
        if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "tool")
        or (isinstance(dec, ast.Attribute) and dec.attr == "tool")
    }

    offenders = {n for n in tool_names if "shell" in n or "exec" in n}
    assert not offenders, f"Iris exposes a shell/exec tool: {sorted(offenders)}"


def test_manifest_advertises_no_shell_tool():
    """The manifest must not advertise a capability the code refuses to provide."""
    import json

    manifest = SRC / "iris" / ".well-known" / "mcp.json"
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    names = [t.get("name", "") for t in data.get("tools", [])]
    offenders = [n for n in names if "shell" in n or "exec" in n]
    assert not offenders, f"Iris manifest advertises: {offenders}"
