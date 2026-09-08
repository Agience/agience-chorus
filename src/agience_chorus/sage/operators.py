# The authoritative home for operator code is chorus; there is no shared catalog and no code
# mirrors. It is distributed to hosts as a content-addressed source bundle
# (agience-observe/build_bundles.py); ember executes it via ember/runtime/runner.py, sha-verified
# before exec. Changes happen here, in chorus.
"""Describe = invoking a describe-operator artifact (the Chorus/tool mechanism, local).

Every artifact records its operator as an edge (the content-context-operator triple:
given two of {content, context, operator} you can infer the third). A describe-operator
is itself an artifact that advertises an offer ("describes markdown documents"). At
first observation of some content we match the input's need (its content-type) to an
operator's offer, invoke that operator on the content, and the result becomes the new
artifact's `context` — i.e. its own offer. Geometric: offer<->need, operator applied.

This mirrors Mantle's InvokeArtifactRequest(name, input, arguments) so the local leaf
and the platform share one mechanism. When Ember peers with a Mantle, the same operator
artifacts can be invoked over HTTP instead of in-process — nothing else changes.

The handler bodies below (offer-framing templates, KIND_SYNONYMS, the content-type ->
operator routing) encode assumptions about how to describe content, not learned knowledge — a
stand-in that lets retrieval work before there is a learned foundation for kinds and description.
What is structural and correct regardless: the operator artifact, its offer, the operator edge, and
the invoke mechanism. See [[offers-needs-retrieval]] / [[content-context-operator-triple]].
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type

# ── deterministic, bias-free primitives (the file describing itself) ──────────
def _md_offer(text: str, max_chars: int = 700):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = next((l.lstrip("#").strip() for l in lines if l.startswith("#")), (lines[0] if lines else ""))
    return title, " ".join(lines[:8])[:max_chars]


def _py_offer(text: str, max_chars: int = 700):
    try:
        tree = ast.parse(text)
    except Exception:
        return "", _generic_summary(text)
    doc = (ast.get_docstring(tree) or "").strip()
    purpose = doc.split("\n", 1)[0]
    syms = [n.name for n in tree.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
    detail = (doc + ("  defines: " + ", ".join(syms[:24]) if syms else "")).strip()[:max_chars]
    return purpose, detail


def _generic_summary(text: str, max_chars: int = 400) -> str:
    return "\n".join(text.splitlines()[:8]).strip()[:max_chars]


# Kind synonyms to widen need->offer matching — see the module header.
KIND_SYNONYMS = {
    "overview":       "overview, description, introduction, summary, about",
    "description":    "description, overview, explanation, summary, information about",
    "guide":          "guide, tutorial, how-to, walkthrough, getting started, usage",
    "reference":      "reference, API documentation, specification, contract",
    "design":         "design, architecture, plan, proposal, rationale",
    "implementation": "implementation, source code, module",
    "example":        "example, test, sample, demonstration",
}


def _classify_kind(path: Optional[Path], suf: str, name: str) -> str:
    if suf in {".md", ".markdown", ".rst", ".txt"}:
        if any(k in name for k in ("readme", "overview", "about", "intro", "index", "home")):
            return "overview"
        if any(k in name for k in ("guide", "tutorial", "howto", "how-to", "getting", "usage", "quickstart")):
            return "guide"
        if any(k in name for k in ("reference", "api", "spec", "protocol", "contract")):
            return "reference"
        if any(k in name for k in ("plan", "design", "architecture", "rfc", "proposal")):
            return "design"
        return "description"
    if suf == ".py" and "test" in name:
        return "example"
    return "implementation"


# ── describe-operator handlers: (input) -> offer string ───────────────────────
def _describe_markdown(text: str, path: Optional[str]) -> str:
    p = Path(path) if path else None
    name = (p.stem.replace("_", " ").replace("-", " ")) if p else ""
    kind = _classify_kind(p, (p.suffix.lower() if p else ".md"), (p.stem.lower() if p else ""))
    syn = KIND_SYNONYMS.get(kind, kind)
    title, intro = _md_offer(text)
    topic = title or name
    return (f"This document is a {kind} of {topic}. It provides a {syn} of {topic}. "
            f"It is documentation about {topic}.\n{intro}").strip()


def _describe_python(text: str, path: Optional[str]) -> str:
    p = Path(path) if path else None
    name = (p.stem.replace("_", " ").replace("-", " ")) if p else "module"
    kind = _classify_kind(p, ".py", (p.stem.lower() if p else ""))
    syn = KIND_SYNONYMS.get(kind, kind)
    purpose, detail = _py_offer(text)
    return f"This is the {kind} ({name}) — it provides {purpose or name}. ({syn})\n{detail}".strip()


def _describe_generic(text: str, path: Optional[str]) -> str:
    p = Path(path) if path else None
    name = (p.stem.replace("_", " ").replace("-", " ")) if p else "file"
    kind = _classify_kind(p, (p.suffix.lower() if p else ""), (p.stem.lower() if p else ""))
    return f"This file ({name}) is {kind} that contains:\n{_generic_summary(text)}".strip()


@dataclass(frozen=True)
class DescribeOperator:
    name: str                    # stable operator id (also the artifact id)
    offer: str                   # what it advertises — its context
    suffixes: tuple              # content-type surface it describes (prop: file suffixes)
    handler: Callable[[str, Optional[str]], str]


# The operator registry + suffix routing. The operators themselves are real and survive; the
# suffix routing is scaffolding for content-type -> operator selection.
OPERATORS: List[DescribeOperator] = [
    DescribeOperator("op.describe.markdown", "describes markdown / prose documents",
                     (".md", ".markdown", ".rst", ".txt"), _describe_markdown),
    DescribeOperator("op.describe.python", "describes python source modules",
                     (".py",), _describe_python),
    DescribeOperator("op.describe.generic", "describes source and text files",
                     (), _describe_generic),
]


def select_operator(suffix: str) -> DescribeOperator:
    """need (a content-type/suffix) -> offer, by exact key only. See `select_for` for the
    geometric path; this remains for callers that have a suffix and nothing else."""
    return select_for(suffix)[0]


def select_for(suffix: str, *, artifact_store=None, text: str = "",
               ) -> tuple:
    """need -> offer, returning `(operator, basis)`.

    The suffix is a perfect gate, and geometry is the fallback — not the other way round. A `.py`
    file is a python file, and an exact key beats a distance every time it applies; blanket-replacing
    exact routing with propagation would be a downgrade. This mirrors `router.route`, which runs its
    deterministic, self-verifying arms before semantic retrieval for exactly the same reason.

    So: exact suffix -> geometric propagation over registered offers (D14) -> generic.

    The basis is returned rather than a bare operator, because "we matched nothing and guessed" and
    "we chose this" are different results and must not share a return shape. That is the
    unmeasured-rendering-as-measured pattern this codebase keeps re-learning.
    """
    suf = (suffix or "").lower()
    for op in OPERATORS:
        if suf in op.suffixes:
            return op, "suffix"

    # No exact key. Propagate the need over registered operator offers and see what lights up. The
    # geometric operator-selection tekton lives in `sage/match.py` ([[ember-is-a-runner]]); it reaches
    # ember's measurement (`propagate`/`_offers`/`activation`). The try/except is honest degradation,
    # not a missing-module guard: if the ontology cannot ground the need (no WordNet index / IC),
    # `select` returns `basis="unavailable"` and we fall through to generic — saying so via the
    # returned basis, never presenting a guess as measured.
    if artifact_store is not None and text:
        try:
            from . import match as _match
            r = _match.select(artifact_store, text)
            # Separated, not merely ranked. A geometric answer whose top two candidates differ by
            # noise is not a selection — see `match.select`'s measurement (0.4% margin over
            # WordNet-mis-grounded technical vocabulary). Fall through to generic and say so.
            if r.get("basis") == "geometric" and r.get("separated") and r.get("matches"):
                best = r["matches"][0]["operator"]
                op = next((o for o in OPERATORS if o.name == best), None)
                if op is not None:
                    return op, "geometric"
        except Exception:
            pass                       # geometry unavailable -> fall through and say generic
    return OPERATORS[-1], "generic"


def register_operators(artifact_store, graph_store=None, *, author: str = "ember-local") -> int:
    """Upsert the describe-operators as artifacts (idempotent). Each is an artifact
    whose `context` is its offer — so operators are themselves discoverable by
    need->offer match. Returns how many were registered."""
    from crystal import evolution
    n = 0
    for op in OPERATORS:
        evolution.put_operator(artifact_store, {
            "id": op.name,
            "content_type": OPERATOR_CONTENT_TYPE,
            "state": "committed",
            "context": op.offer,
            "content": f"describe-operator {op.name}: {op.offer}",
            "created_by": author,
        })
        n += 1
    return n


def invoke(artifact_store, name: str, *, input: str, arguments: Optional[Dict] = None) -> str:
    """The InvokeArtifactRequest analogue: run the named describe-operator on `input`.
    `arguments.path` (optional) gives the operator the source path hint. Verifies the
    operator artifact exists in the store first (it is a real, addressable artifact)."""
    if artifact_store is not None and artifact_store.get_artifact(name) is None:
        raise KeyError(f"operator artifact '{name}' not registered in store")
    op = next((o for o in OPERATORS if o.name == name), None)
    if op is None:
        raise KeyError(f"no handler for operator '{name}'")
    path = (arguments or {}).get("path")
    return op.handler(input, path)


def describe_at_first_observation(artifact_store, *, suffix: str, text: str,
                                  path: Optional[str] = None) -> tuple:
    """Select the operator by need->offer, invoke it, return (operator_name, offer).
    The caller writes the artifact with context=offer and an operator edge
    (artifact --operator--> op.name), completing the content-context-operator triple.

    Selection is exact-then-geometric (`select_for`): a known suffix routes exactly, anything else
    propagates the text over registered offers."""
    op, _basis = select_for(suffix, artifact_store=artifact_store, text=text)
    offer = invoke(artifact_store, op.name, input=text, arguments={"path": path})
    return op.name, offer
