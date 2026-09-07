"""Cross-persona invariant: no persona claims `grounded` without citing what grounded it.

This is an AST sweep rather than a behavioural test because `grounded` is the one field every
surface above chorus trusts without re-deriving — aria's bff renders a "grounded" badge from it,
ember's `serve` copies it onto the wire, and a reader has no way to check it except by looking at
`cited`. The property that matters is not "this one query returns the right flag", it is "nowhere
does a persona assert the flag it cannot back". Only a sweep can say that; a per-path behavioural
test proves only the paths someone thought to write.

The rule this pins: **`grounded=True` requires a non-empty `cited`.** A computed answer cites its
engine (an engine id counts as a citation), a retrieved answer cites its sources, a refusal cites
nothing and is not grounded. If an answer genuinely has no provenance, the honest value is
`grounded=False` — not an empty citation list next to a True.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent          # agience-chorus/src
SKIP_PARTS = {"__pycache__", "tests", "node_modules"}


def _production_python():
    for f in sorted(SRC.rglob("*.py")):
        if set(f.parts) & SKIP_PARTS or f.name.startswith("test_"):
            continue
        yield f


def _uncited_grounding_claims(path: pathlib.Path):
    """Every `…(grounded=True, …)` in `path` whose `cited` is absent or an empty literal list."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:                                   # not ours to police here
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        g = kw.get("grounded")
        if not (isinstance(g, ast.Constant) and g.value is True):
            continue
        cited = kw.get("cited")
        # A name/call/comprehension for `cited` is a derived list — it may be empty at runtime, and
        # that is the code doing the right thing dynamically. Only a literal empty list (or no
        # `cited` at all) is a statically-provable uncited claim.
        if cited is None or (isinstance(cited, ast.List) and not cited.elts):
            out.append(node.lineno)
    return out


def test_no_persona_asserts_grounded_without_a_citation():
    offenders = {}
    for f in _production_python():
        lines = _uncited_grounding_claims(f)
        if lines:
            offenders[str(f.relative_to(SRC))] = lines
    assert not offenders, (
        "these assert grounded=True with nothing cited — cite what grounded it (an engine id is a "
        "citation) or report grounded=False:\n  "
        + "\n  ".join(f"{k}: lines {v}" for k, v in sorted(offenders.items())))


def test_the_sweep_can_actually_fail():
    """The negative control. The test above passes trivially if the AST walk is broken, the glob
    matches nothing, or `Answer(...)` stops parsing as a Call — and a sweep that cannot fail is
    indistinguishable from a clean repo. Hand it the exact shape it is meant to reject."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        bad = pathlib.Path(d) / "bad.py"
        bad.write_text("Answer(text='x', grounded=True, cited=[])\n", encoding="utf-8")
        assert _uncited_grounding_claims(bad) == [1]

        # …and does not cry wolf over the two legitimate shapes.
        ok = pathlib.Path(d) / "ok.py"
        ok.write_text("Answer(text='x', grounded=True, cited=['engine:math.percent'])\n"
                      "Answer(text='y', grounded=True, cited=[e.id for e in top])\n"
                      "Answer(text='z', grounded=False, cited=[])\n", encoding="utf-8")
        assert _uncited_grounding_claims(ok) == []


def test_the_sweep_reads_a_nonempty_set_of_files():
    """A path bug would empty the corpus and turn the sweep green by covering nothing."""
    files = list(_production_python())
    assert len(files) > 50, f"only {len(files)} production modules swept — the glob is wrong"
    assert any(f.name == "content_search.py" for f in files), "sage's answer surface is not swept"
