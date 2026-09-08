# Operator code lives in chorus, the single authoritative path. Distributed to hosts as a
# content-addressed source bundle (definitions/build_bundles.py); ember executes it via
# ember/runner.py, sha-verified before exec. There are no code mirrors — changes happen here.
"""Deterministic code intelligence — a file describes itself by the names it defines,
calls, imports, and inherits. Extracted from the AST: no model, no embedding, no bias.

The output reuses the exact machinery WordNet does:
  • a symbol name is a lemma        -> keyed lookup = find_definition   (store.lookup_by_lemma)
  • a called name is a list-edge    -> find_references = `name in calls` (store.lookup_by_list_field)
  • defines / imports / inherits are graph edges for traversal.

So `where is open_store defined` and `what calls open_store` are exact — the thing frontier
models guess at. Python first (ast); the same shape extends to other languages via their parsers.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

SYMBOL_CONTENT_TYPE = "text/x-python-symbol"


@dataclass
class Symbol:
    name: str                       # simple name, e.g. open_store
    qualname: str                   # module + scope, e.g. mantle.shard.local_store.open_store
    kind: str                       # function | method | class | constant
    path: str                       # posix file path
    line: int
    calls: List[str] = field(default_factory=list)      # names this symbol calls
    bases: List[str] = field(default_factory=list)      # base class names (for classes)
    doc: str = ""                   # first docstring line (deterministic self-description)

    def id(self) -> str:
        return "sym-" + self.qualname

    def offer(self) -> str:
        d = f" — {self.doc}" if self.doc else ""
        b = f"  bases: {', '.join(self.bases)}" if self.bases else ""
        c = f"  calls: {', '.join(self.calls[:12])}" if self.calls else ""
        return f"{self.kind} {self.name} ({self.qualname}){d}\ndefined at {self.path}:{self.line}{b}{c}"


def module_of(path: str) -> str:
    """Dotted module from a file path (strip a leading .../src/, drop extension, / -> .)."""
    p = Path(path).as_posix()
    i = p.rfind("/src/")
    if i != -1:
        p = p[i + 5:]
    p = p.rsplit(".", 1)[0]
    return ".".join(seg for seg in p.split("/") if seg and seg != "src")


def _called_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _calls_within(node: ast.AST) -> List[str]:
    out = [n2 for n in ast.walk(node) if isinstance(n, ast.Call)
           for n2 in [_called_name(n.func)] if n2]
    return list(dict.fromkeys(out))


class _Walker:
    def __init__(self, path: str, module: str):
        self.path, self.module = path, module
        self.symbols: List[Symbol] = []
        self.imports: List[str] = []

    def _add_imports(self, node):
        if isinstance(node, ast.Import):
            self.imports += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                self.imports.append(node.module.split(".")[0])
            self.imports += [a.name for a in node.names]

    @staticmethod
    def _blocks(node):
        """Every statement block of a node, not just `body`.

        A statement that contains a body without being a def — `If`, `Try`, `With`, `For`, `While`
        — must still be descended into, or definitions and imports inside it are dropped along with
        everything they contain:

            import os                    -> found
            try: import ujson as json    -> found
            except ImportError: import json  -> found
            if os.name == 'nt':
                def win_only(): ...      -> found
            else:
                def posix_only(): ...    -> found

        `try/except ImportError` around imports and `if TYPE_CHECKING:` / `if sys.version_info`
        around defs are among the most common shapes in real Python, and they are exactly what
        `find_definition` and `describe`'s lemma extraction are built on. The `else` of an `if`, the
        `else`/`finally` of a `try`, and each `except` handler's body are all included; scope and
        `in_class` are preserved when descending, because a def inside an `if` at module level is
        still module-level and one inside a class is still a method."""
        out = []
        for field in ("body", "orelse", "finalbody"):
            out.extend(getattr(node, field, None) or [])
        for handler in (getattr(node, "handlers", None) or []):
            out.extend(getattr(handler, "body", None) or [])
        return out

    def walk(self, node, scope: str, in_class: bool):
        for child in self._blocks(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                self._add_imports(child)
            elif isinstance(child, ast.ClassDef):
                qual = f"{scope}.{child.name}"
                bases = [b for b in (_called_name(b) or getattr(b, "id", "") for b in child.bases) if b]
                self.symbols.append(Symbol(child.name, qual, "class", self.path, child.lineno,
                                           _calls_within(child), bases,
                                           (ast.get_docstring(child) or "").split("\n", 1)[0][:160]))
                self.walk(child, qual, in_class=True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{scope}.{child.name}"
                self.symbols.append(Symbol(child.name, qual, "method" if in_class else "function",
                                           self.path, child.lineno, _calls_within(child), [],
                                           (ast.get_docstring(child) or "").split("\n", 1)[0][:160]))
                self.walk(child, qual, in_class=False)      # nested defs are functions
            elif isinstance(child, ast.Assign) and scope == self.module:
                for t in child.targets:
                    if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 1:
                        self.symbols.append(Symbol(t.id, f"{self.module}.{t.id}", "constant",
                                                   self.path, child.lineno))
            elif isinstance(child, (ast.If, ast.Try, ast.With, ast.AsyncWith,
                                    ast.For, ast.AsyncFor, ast.While)):
                # A compound statement that is NOT a def: descend, but do NOT change scope —
                # `def f()` inside `if TYPE_CHECKING:` at module level is still module-level.
                self.walk(child, scope, in_class)


def extract(path: str, text: str) -> Tuple[List[Symbol], List[str]]:
    """(symbols, imported_names) for one Python file. Empty on a syntax error — the file is
    still stored as text, just dark to the symbol layer until it parses."""
    module = module_of(path)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], []
    w = _Walker(Path(path).as_posix(), module)
    w.walk(tree, module, in_class=False)
    return w.symbols, list(dict.fromkeys(w.imports))
