# The operator code's authoritative source lives in chorus. It is distributed to hosts as a
# content-addressed source bundle (definitions/build_bundles.py); ember executes it via
# ember/runner.py, sha-verified before exec. There are no code mirrors — changes happen here.
"""Arithmetic domain: a gate built from deterministic transformation operators.

Each operation (add, subtract, multiply, ..., is_prime, factorize) is a first-class operator: an
invokable artifact with an offer ("adds two numbers"), a deterministic handler, and a
self-verification. This is the content-context-operator triple where the operator computes rather
than describes: given the need (a math query), the matching operator is selected and applied to the
operands (content), and the result carries its own proof (`7 * 8 == 56`, `51 = 3 x 17`). This is the
highest provenance rung, since the answer is its own verification — no corpus, no embedding, no
model. It shares the same invoke mechanism as the describe-operators, so local and platform share one
path (Mantle's InvokeArtifactRequest).

Safety: never `eval`. Composed expressions parse with `ast` and evaluate by walking the tree,
dispatching each BinOp to a registered transform operator — no names, calls, or attributes.
"""
from __future__ import annotations

import ast
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Callable, List, Optional

# The Answer shape (mirrors ember's engine.py). This organon is loaded two ways and the import must
# satisfy both — see `agience-observe/build_bundles.py` (the source is bundled verbatim, no rewriting):
#   1. as a bundle module — `prism.runner` execs it as `<pkg>.arithmetic`, so a sibling resolves
#      relatively (`.answer` -> `<pkg>.answer`). A bare `import answer` raises ModuleNotFoundError
#      there: `_BundleFinder` serves only `pkg` and `pkg.<module>`.
#   2. under the persona-load convention — `lumen/manifest.py` puts the persona dir on `sys.path` and
#      imports organons by bare name (`import arithmetic`), so the module has no package and the
#      relative form raises ImportError.
# Try relative first, fall back to bare, so the organon works whichever way it is loaded.
try:
    from .answer import Answer          # bundle / package context
except ImportError:                     # pragma: no cover - persona-load puts the persona dir on sys.path
    from answer import Answer           # bare-name context

from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type


@dataclass(frozen=True)
class Transform:
    name: str                       # operator/artifact id, e.g. "op.math.add"
    offer: str                      # what it advertises (its context)
    fn: Callable                    # the deterministic transform
    verify: Callable                # (operands, result) -> proof string
    symbol: str = ""                # infix symbol (for composed-expression dispatch)


def _v_binary(sym):
    return lambda ops, r: f"{_fmt(ops[0])} {sym} {_fmt(ops[1])} == {_fmt(r)}"


# The primitive transforms. Binary ops back the expression evaluator; named ops are
# invoked directly by pattern. Every one is deterministic and self-verifying.
TRANSFORMS: List[Transform] = [
    Transform("op.math.add", "adds two numbers", lambda a, b: a + b, _v_binary("+"), "+"),
    Transform("op.math.subtract", "subtracts one number from another", lambda a, b: a - b, _v_binary("-"), "-"),
    Transform("op.math.multiply", "multiplies two numbers", lambda a, b: a * b, _v_binary("×"), "*"),
    Transform("op.math.divide", "divides one number by another", lambda a, b: a / b, _v_binary("÷"), "/"),
    Transform("op.math.floordiv", "integer-divides one number by another", lambda a, b: a // b, _v_binary("//"), "//"),
    Transform("op.math.modulo", "the remainder of dividing one number by another", lambda a, b: a % b, _v_binary("mod"), "%"),
    Transform("op.math.power", "raises a number to a power", lambda a, b: a ** b, _v_binary("^"), "**"),
    Transform("op.math.is_prime", "tests whether a number is prime",
              lambda n: len(_factorize(int(n))) == 1 and int(n) >= 2,
              lambda ops, r: (f"no divisor 2≤d≤√{int(ops[0])}" if r else f"{int(ops[0])} = {_factor_str(_factorize(int(ops[0])))}")),
    Transform("op.math.factorize", "gives the prime factorization of a number",
              lambda n: _factorize(int(n)),
              lambda ops, r: f"product of factors = {math.prod(r) if r else 1} == {int(ops[0])}"),
    Transform("op.math.sqrt", "the square root of a number", lambda n: math.sqrt(n),
              lambda ops, r: f"{_fmt(r)}² = {_fmt(r*r)} ≈ {_fmt(ops[0])}"),
    Transform("op.math.factorial", "the factorial of a non-negative integer",
              lambda n: math.factorial(int(n)), lambda ops, r: f"{int(ops[0])}! = 1×2×…×{int(ops[0])}"),
    Transform("op.math.gcd", "the greatest common divisor of two integers",
              lambda a, b: math.gcd(int(a), int(b)), lambda ops, r: f"{r} divides both {int(ops[0])} and {int(ops[1])}"),
    Transform("op.math.lcm", "the least common multiple of two integers",
              lambda a, b: abs(int(a) * int(b)) // math.gcd(int(a), int(b)) if a and b else 0,
              lambda ops, r: f"gcd({int(ops[0])},{int(ops[1])})={math.gcd(int(ops[0]),int(ops[1]))}; |a·b|/gcd = {r}"),
]
_BY_NAME = {t.name: t for t in TRANSFORMS}
_BY_SYMBOL = {t.symbol: t for t in TRANSFORMS if t.symbol}


# ADDED 2026-08-26. Operators were registered with NO `collection_id`, and the content seal keys
# on a collection origin root — so they could never be sealed and
# `data_integrity_check.artifacts_holding_inline_plaintext` climbed off zero on every boot. The
# repair that first drove that count to zero gave collectionless platform vocabulary `stage.system`
# "rather than an exemption"; the writers were never changed. This is that fix reaching the writer.
# `collection_id` alone suffices — `vertex._place` writes the origin containment edge from it, in
# the same savepoint as the row. Inlined, not shared: `_persona.load()` loads these modules
# individually and cross-importing between them is the hazard that module exists to prevent.
_SYSTEM_COLLECTION = "stage.system"


def _now_iso() -> str:
    """This observer's clock reading, claimed. The store never invents one (`vertex._attribute`
    returns untouched when `created_time` is None) and it is first-write-wins."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


#: Read ONCE per process, not per call. `manifest.OPERATORS = operators()` is computed at import
#: while `operators()` recomputes on demand, and `test_the_lumen_manifest_surface_is_unchanged_for_
#: the_host` asserts the two are equal — a fresh timestamp per call makes that impossible, and it
#: also makes the registered dict non-deterministic for anything that compares payloads. Reading
#: the clock at import gives one claim per process, which is what an idempotent upsert wants:
#: first-write-wins means only the first one is ever kept anyway.
_REGISTERED_AT = _now_iso()


def register_transform_operators(artifact_store, *, author: str = "ember-local") -> int:
    """Upsert the arithmetic transforms as invokable operator artifacts (idempotent),
    each advertising its offer. They become discoverable like any operator.

    That last sentence was NOT true before 2026-08-25. The offer was written into
    ``context``, and the lexical arm indexes ``offer`` — so all 48 operator artifacts carried
    an empty offer and none was findable, the same defect the colimits had before their offer was
    backfilled. Measured on 71/home: **0 of 48** carried an offer.

    The offer now goes to ``offer``, where the index reads it, and nothing is written to
    ``context`` at all. John, 2026-08-25: *"context, offer, description, title — all the same
    field. Tags or other properties are just collection edges."* So this writes ONE naming field
    and invents no second one; ``kind`` and ``symbol`` are properties of the operator and belong
    on edges rather than in a metadata blob.

    The 48 rows already in the store keep the old shape until something rewrites them; this
    fixes what is WRITTEN, not what was written."""
    from crystal import evolution
    n = 0
    for t in TRANSFORMS:
        evolution.put_operator(artifact_store, {
            "id": t.name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "offer": t.offer,
            "content": f"deterministic transform {t.name}: {t.offer}",
            "created_by": author,
            "collection_id": _SYSTEM_COLLECTION, "created_time": _REGISTERED_AT,
        })
        n += 1
    return n


def invoke(name: str, *operands):
    """Apply a transform operator by name; return (result, proof-string)."""
    t = _BY_NAME.get(name)
    if t is None:
        raise KeyError(f"no transform operator '{name}'")
    result = t.fn(*operands)
    return result, t.verify(list(operands), result)


# ---- expression parsing (composed operators) --------------------------------
_AST_OP = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
           ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**"}
_PHRASES = [("to the power of", "**"), ("raised to", "**"), ("multiplied by", "*"),
            ("divided by", "/"), ("plus", "+"), ("minus", "-"), ("times", "*"),
            ("over", "/"), ("modulo", "%"), (" mod ", "%"), ("squared", "**2"), ("cubed", "**3")]
_MARKERS = ("prime", "factor", "sqrt", "square root", "factorial", "gcd", "lcm",
            "how much is", "what is", "calculate", "compute", "!")


# ---- number-words (grade-1 numeracy) -----------------------------------------
# Reading "two", "twenty-three", "one hundred and five" as values is the first thing a child does
# with numbers. It is a deterministic lexicon (the numbers themselves) + positional composition —
# not a fit, not a model. It lets the same op.math operators compute a spoken query.
_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_MULT = {"thousand": 1000, "million": 1000000, "billion": 1000000000}
_NUMWORD = set(_ONES) | set(_TENS) | {"hundred"} | set(_MULT)


def _chunk_value(toks) -> int:
    """Compose number-word tokens into an integer (positional: hundreds/thousands scale)."""
    total = cur = 0
    for w in toks:
        if w in _ONES:
            cur += _ONES[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w in _MULT:
            total += (cur or 1) * _MULT[w]
            cur = 0
    return total + cur


def _numberize(s: str) -> str:
    """Replace maximal runs of number-words with their digit value ('two plus two' -> '2 plus 2',
    'twenty-three' -> '23', 'one hundred and five' -> '105'). Standalone 'and' only joins a run."""
    out, run = [], []
    for tok in s.split():
        sub = [w.lower() for w in tok.replace("-", " ").split()]
        if sub and all(w in _NUMWORD for w in sub):
            run.extend(sub)
        elif sub == ["and"] and run:
            run.append("and")                      # mid-number connector, ignored in value
        else:
            if run:
                out.append(str(_chunk_value(run))); run = []
            out.append(tok)
    if run:
        out.append(str(_chunk_value(run)))
    return " ".join(out)


def _norm(q: str) -> str:
    s = q.lower().strip().rstrip("?.")
    for frame in ("what is", "whats", "how much is", "calculate", "compute", "evaluate", "the value of"):
        if s.startswith(frame):
            s = s[len(frame):].strip()
    s = _numberize(s)                              # number-words -> digits, before phrase->symbol
    for w, sym in _PHRASES:
        s = s.replace(w, sym)
    return s.replace("^", "**").replace("×", "*").replace("÷", "/").strip()


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _AST_OP:
        # dispatch to the registered transform operator for this symbol
        t = _BY_SYMBOL[_AST_OP[type(node.op)]]
        return t.fn(_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    raise ValueError(f"disallowed node: {type(node).__name__}")


def _safe_calc(expr: str):
    return _eval(ast.parse(expr, mode="eval"))


def _fmt(x) -> str:
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    if isinstance(x, float):
        return f"{x:.10g}"
    return str(x)


def _factorize(n: int):
    factors, d, m = [], 2, abs(n)
    while d * d <= m:
        while m % d == 0:
            factors.append(d); m //= d
        d += 1 if d == 2 else 2
    if m > 1:
        factors.append(m)
    return factors


def _factor_str(factors) -> str:
    parts = [f"{p}" + (f"^{e}" if e > 1 else "") for p, e in sorted(Counter(factors).items())]
    return " × ".join(parts) if parts else "1"


def looks_arithmetic(query: str) -> bool:
    q = query.lower()
    if any(m in q for m in _MARKERS):
        return True
    s = _norm(query)
    return bool(re.search(r"\d", s)) and bool(re.search(r"[+\-*/%]|\*\*", s))


def _factorial_digits(n: int) -> int:
    """Decimal digits of n!, without computing n!.

    `lgamma(n+1)` is ln(n!), so `floor(log10(n!)) + 1` is the digit count — evaluated in constant
    time. Computing the factorial to count its digits would cost exactly what the bound exists to
    avoid, and for a refusal message it would be absurd: the whole point is that the number is too
    large to handle.
    """
    if n < 2:
        return 1
    return math.floor(math.lgamma(n + 1) / math.log(10)) + 1


def _max_renderable_factorial() -> int:
    """The largest n whose n! this interpreter can render — derived, never typed in.

    CPython 3.11+ caps int→str at `sys.get_int_max_str_digits()` (4300 by default, from
    CVE-2020-10735). That cap, not compute cost, is what actually bounds a printable factorial:
    `math.factorial(2000)` takes under a millisecond and then cannot be turned into a string.

    Deriving it rather than pinning it means the answer follows the interpreter — raise the limit
    with `sys.set_int_max_str_digits()` and this rises with it, which a constant could not do.
    Binary search over a monotone digit count; a handful of `lgamma` calls.
    """
    limit = sys.get_int_max_str_digits()
    lo, hi = 0, 1
    while _factorial_digits(hi) <= limit:
        hi *= 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _factorial_digits(mid) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _ans(text: str, op: str, verification: str) -> Answer:
    return Answer(text=text, grounded=True, cited=[f"{op} — {verification}"],
                  read={"engine": "arithmetic", "operator": op, "verified": True, "check": verification})


# ---- learn the operator from examples (content+context -> operator) ---------
_LEARN_MARK = re.compile(r"\b(infer|learn|what operator|which operation|what maps|what rule|guess the)\b")
_EXAMPLE = re.compile(
    r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?\s*(?:->|→|=>|to|gives|maps to|=)\s*(-?\d+(?:\.\d+)?)")


def _num(s):
    f = float(s)
    return int(f) if f.is_integer() else f


def learn_operator(query: str) -> Optional[Answer]:
    """content + context → operator: infer which transform maps the given example pairs,
    by the Occam rule (simplest fit). The developmental seam — the operator is learned from
    data, not hardcoded. Honest None-answer when no single operator fits."""
    # Loaded two ways (bundle module vs persona-load bare name) — see the note on the same
    # import in `lumen/arithmetic.py`. Relative resolves the bundle sibling; bare resolves
    # under the persona-load convention. Bare-only silently un-bundles this module.
    try:
        from . import category as category
    except ImportError:
        import category as category
    if not _LEARN_MARK.search(query.lower()):
        return None
    pairs = _EXAMPLE.findall(query)
    if len(pairs) < 1:
        return None
    examples = [([_num(a), _num(b)], _num(c)) for a, b, c in pairs]
    op = category.infer(examples)
    shown = "; ".join(f"({a},{b})→{c}" for (a, b), c in examples)
    if op is None:
        return Answer(text=f"No single operator fits {shown} — can't name that transform "
                           f"from these examples (declining rather than guessing).",
                      grounded=False, cited=[f"infer:no-fit"],
                      read={"engine": "arithmetic.learn", "fit": None, "examples": len(examples)})
    # demonstrate the learned operator on a fresh point for confidence
    demo_a, demo_b = 6, 7
    try:
        demo = category.apply(op, demo_a, demo_b)
        demo_str = f"  (e.g. {op}(6,7) = {_fmt(demo)})"
    except Exception:
        demo_str = ""
    return Answer(text=f"the operator is **{op}** — it fits every example: {shown}{demo_str}",
                  grounded=True, cited=[f"inferred:{op} from {len(examples)} example(s)"],
                  read={"engine": "arithmetic.learn", "operator": op, "examples": len(examples)})


def compute(query: str) -> Optional[Answer]:
    """Select + invoke the matching transform operator; return a verified Answer, or None."""
    q = query.lower().strip().rstrip("?.")

    # Factorization is defined only for n >= 2. `_factorize` takes `abs(n)` and `_factor_str([])` is
    # hardcoded to "1", so without this guard, negative and small inputs would produce a
    # `verified: True` answer whose verify lambda formats `prod == n` as a string without comparing
    # them — printing its own refutation as proof. Decline instead, and say why.
    m = re.search(r"is\s+(-?\d+)\s+(?:a\s+)?prime", q)
    if m:
        n = int(m.group(1))
        if n < 2:
            return _ans(f"no — {n} is not prime", "op.math.is_prime",
                        f"primality is defined only for integers ≥ 2; {n} is below that")
        r, proof = invoke("op.math.is_prime", n)
        return _ans(f"{'yes' if r else 'no'} — {n} is {'prime' if r else 'not prime'}", "op.math.is_prime", proof)

    m = re.search(r"(?:prime\s+factor(?:s|ization)?|factor(?:s|ize)?)\s+(?:of\s+)?(-?\d+)", q)
    if m:
        n = int(m.group(1))
        if n < 2:
            return _ans(f"{n} has no prime factorization", "op.math.factorize",
                        "prime factorization is defined only for integers ≥ 2 "
                        f"({n} is {'negative' if n < 0 else 'a unit or zero'})")
        r, proof = invoke("op.math.factorize", n)
        return _ans(f"{n} = {_factor_str(r)}", "op.math.factorize", proof)

    m = re.search(r"(?:sqrt|square\s+root)\s+(?:of\s+)?(-?\d+(?:\.\d+)?)", q)
    if m:
        n = float(m.group(1))
        # `math.sqrt(-4)` raises ValueError, and nothing wraps this call: `router.route` does not
        # guard `arithmetic.compute`, and `serve` does not guard `router.route`. Without this check,
        # a negative input under a square root would surface as an unhandled exception rather than a
        # decline.
        if n < 0:
            return _ans(f"√{_fmt(n)} is not a real number", "op.math.sqrt",
                        "the square root of a negative number is not defined over the reals")
        r, proof = invoke("op.math.sqrt", n)
        return _ans(f"√{_fmt(n)} = {_fmt(r)}", "op.math.sqrt", proof)

    m = re.search(r"(-?\d+)\s*(?:!|\bfactorial\b)", q)
    if m:
        n = int(m.group(1))
        # CPython 3.11+ refuses int->str conversion above `sys.get_int_max_str_digits()` (4300 by
        # default, added for CVE-2020-10735). The renderable bound is derived from that limit
        # (`_max_renderable_factorial`) rather than typed in, so it stays correct if the limit is
        # raised (`sys.set_int_max_str_digits`) or if CPython changes it.
        if 0 <= n <= _max_renderable_factorial():
            r, proof = invoke("op.math.factorial", n)
            return _ans(f"{n}! = {r}", "op.math.factorial", proof)
        if n >= 0:
            # Refuses by name rather than falling through to a bare None, which would be
            # indistinguishable from "not an arithmetic question". The digit count states why.
            return _ans(
                f"{n}! has about {_factorial_digits(n):,} digits, more than this interpreter will "
                f"render (the limit is {sys.get_int_max_str_digits():,}); the largest factorial it "
                f"can print is {_max_renderable_factorial()}!",
                "op.math.factorial",
                "refused on a DERIVED bound: sys.get_int_max_str_digits(), not a typed-in cap")

    m = re.search(r"(gcd|lcm|greatest common divisor|least common multiple)\D+(-?\d+)\D+(-?\d+)", q)
    if m:
        a, b = int(m.group(2)), int(m.group(3))
        name = "op.math.lcm" if ("lcm" in m.group(1) or "least" in m.group(1)) else "op.math.gcd"
        r, proof = invoke(name, a, b)
        return _ans(f"{name.split('.')[-1]}({a}, {b}) = {r}", name, proof)

    if looks_arithmetic(query):
        expr = _norm(query)
        try:
            val = _safe_calc(expr)
        except (ValueError, SyntaxError, TypeError, ZeroDivisionError):
            return None
        return _ans(f"{expr} = {_fmt(val)}", "op.math.expression", f"recomputed: {expr} == {_fmt(_safe_calc(expr))}")
    return None
