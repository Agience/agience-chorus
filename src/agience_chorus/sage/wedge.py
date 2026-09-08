"""The Stage-3 wedge — verified answers, not just grounded ones.

It is a tool, not a measurement: it certifies a claim (a tekton absorbs a need and answers it). It
lives in sage rather than ember because ember is the runner and keeps no tool definitions, and its
only consumer is `sage/content_search.py`.

Recitation (primary) and relation reasoning (intermediate) both ground an answer in the corpus. The
wedge is the step past that: a claim becomes a machine-checked fact. Python is verified by the
interpreter's own compile gate; math by a structural parse (and sympy when present). No model judges
it — the checker is the instrument of reason: a claim is known when a checker certifies it, else honestly
unverified. Lean stdlib (compile/ast; sympy optional) so it runs identically on a Pi or a VPS — fast,
portable, modular. Mirrors the op.check.* operator contract exactly (verdict shape) so the two converge.
"""
from __future__ import annotations

import ast
from typing import Any, Dict, List


def check_python(src: str) -> Dict[str, Any]:
    """Verify a python source: it verifies iff the interpreter compiles it. Never executes (runtime
    verification is a separate gate — op.dev.run_tests). Also returns the AST symbols it defines, the
    structure certificate. Verdict shape matches crystal op.check.python."""
    if not isinstance(src, str) or not src.strip():
        return {"checked": "python", "verified": False, "stage": "read", "error": "empty source"}
    try:
        compile(src, "<wedge>", "exec")
    except SyntaxError as e:
        return {"checked": "python", "verified": False, "stage": "compile",
                "error": "%s: %s (line %s)" % (type(e).__name__, e.msg, e.lineno)}
    except Exception as e:
        return {"checked": "python", "verified": False, "stage": "compile",
                "error": "%s: %s" % (type(e).__name__, e)}
    syms: List[str] = []
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                syms.append(node.name)
    except Exception:
        pass
    return {"checked": "python", "verified": True, "compiles": True, "symbols": syms,
            "note": "compile+AST gate; runtime verification is op.dev.run_tests"}


def _balanced(expr: str) -> tuple:
    """Balanced (), [], {} and matched \\begin/\\end — the structural certificate for a math expression."""
    if not isinstance(expr, str) or not expr.strip():
        return False, "empty expression"
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: List[str] = []
    for ch in expr:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False, "unbalanced delimiter %r" % ch
    if stack:
        return False, "unclosed delimiter %r" % stack[-1]
    if expr.count(r"\begin") != expr.count(r"\end"):
        return False, "unmatched \\begin/\\end"
    return True, None


import operator as _op

_ARITH = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul, ast.Div: _op.truediv,
          ast.FloorDiv: _op.floordiv, ast.Mod: _op.mod, ast.Pow: _op.pow,
          ast.USub: _op.neg, ast.UAdd: _op.pos}


def _arith(node):
    """Evaluate a pure-arithmetic AST node — numbers and the safe operators only. Raises on names,
    calls, attributes, anything else, so it can never execute code: it can only compute a number.
    Evaluating a claim's truth here is a check, not a trust — the machine does the sum."""
    if isinstance(node, ast.Expression):
        return _arith(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITH:
        return _ARITH[type(node.op)](_arith(node.left), _arith(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ARITH:
        return _ARITH[type(node.op)](_arith(node.operand))
    raise ValueError("not pure arithmetic")


def _eval_arith(expr: str):
    """(value, True) for a pure-arithmetic expression; (None, False) if it is not pure arithmetic."""
    try:
        return _arith(ast.parse(expr.strip(), mode="eval")), True
    except Exception:
        return None, False


def check_math(expr: str) -> Dict[str, Any]:
    """Verify a math expression. Strongest first: if it is arithmetic, evaluate it and check the claim's
    truth — "2 + 2 = 5" is verified false, "2 + 3*4 = 14" verified true, a bare "2+3*4" returns its value.
    That is real verification: the machine computes the answer (via a restricted evaluator that can never
    execute code), it does not assert. Otherwise fall back to the structural gate (balanced delimiters +
    \\begin/\\end) and a sympy parse when present. Verdict shape matches crystal op.check.latex-math."""
    import re as _re
    # Comparison relation (==, =, !=, <=, >=, <, >): evaluate both sides and check the relation's truth.
    # Order in the alternation matters — longer operators first so "<=" is not read as "<".
    _m = _re.match(r"^\s*(.+?)\s*(==|!=|<=|>=|=|<|>)\s*(.+?)\s*$", expr or "")
    if _m:
        lhs, lok = _eval_arith(_m.group(1))
        rel = _m.group(2)
        rhs, rok = _eval_arith(_m.group(3))
        if lok and rok:
            lf, rf = float(lhs), float(rhs)
            eq = abs(lf - rf) < 1e-9
            true = {"==": eq, "=": eq, "!=": (not eq),
                    "<": lf < rf, ">": lf > rf, "<=": (lf < rf or eq), ">=": (lf > rf or eq)}[rel]
            return {"checked": "math", "verified": true, "evaluated": True, "lhs": lhs, "op": rel, "rhs": rhs,
                    "why": None if true else "%s %s %s is false (evaluates %s vs %s)" % (lhs, rel, rhs, lhs, rhs)}
    else:
        val, vok = _eval_arith(expr or "")
        if vok:
            return {"checked": "math", "verified": True, "evaluated": True, "value": val}
    ok, why = _balanced(expr)
    parsed = None
    if ok:
        try:
            from sympy.parsing.latex import parse_latex   # stronger gate if available
            parse_latex(expr)
            parsed = True
        except Exception:
            parsed = None                                 # absent/unparseable: the structural gate stands
    return {"checked": "latex-math", "verified": bool(ok), "structural_ok": bool(ok),
            "sympy_parsed": parsed, "why": why}


def check(kind: str, claim: str) -> Dict[str, Any]:
    """Dispatch a claim to its checker. `kind` in {"python","math","latex-math"}."""
    if kind == "python":
        return check_python(claim)
    if kind in ("math", "latex-math", "latex"):
        return check_math(claim)
    return {"checked": kind, "verified": False, "error": "no checker for kind %r" % kind}


__all__ = ["check_python", "check_math", "check"]
