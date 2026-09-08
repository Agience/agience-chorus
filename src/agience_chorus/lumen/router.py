"""The domain router — dev-action -> arithmetic -> code -> content -> semantic, in that order.

This is the conversation dispatch tekton: it decides which act answers, and composes the answer
prose (`_answer_from_evidence`). Both are persona acts, which is why it lives in lumen rather than
ember, alongside `code.py` (it dispatches to it) — a coupling internal to one persona rather than
crossing repos.

Ember reaches this over the plane, inactive by default: with no live fabric its callers get the
honest computed null and fall through to the keyed/semantic backstop — they never fabricate.

Imports are relative to lumen (`from . import X` means `lumen.X` here); ember's modules are named
explicitly, since a persona reading the runner is the allowed direction.
"""

from __future__ import annotations

from typing import Tuple

# `Answer` comes from the operator bundle (`prism.runner.answer`), not from ember.
from prism.runner import answer as _answer_mod

Answer = _answer_mod.Answer
from agience_chorus.lumen import code
from prism.runner import arithmetic, dev_ops     # the single distribution path (prism/runner.py)


def _answer_from_evidence(query: str, evidence) -> Answer:
    """Assemble a grounded Answer from sage's `op.retrieve` evidence — the `[{id,title,content,score}]`
    contract the reach returns. Ember does not re-rank or condense here (that reasoning is the tekton's,
    which lives in sage); it presents the cited evidence as the grounded answer. Empty evidence is
    not grounded (silence stays silence), so the caller falls through."""
    hits = [h for h in (evidence or []) if (h.get("title") or h.get("content"))]
    if not hits:
        return Answer(text="", grounded=False, cited=[],
                      read={"engine": "content", "reason": "no-evidence"})
    lines, cited = [], []
    for h in hits:
        title = (h.get("title") or "").strip()
        body = (h.get("content") or "").strip()
        line = ("%s — %s" % (title, body)) if title and body else (title or body)
        if line:
            lines.append(line)
        if h.get("id"):
            cited.append(str(h["id"]))
    return Answer(text="\n\n".join(lines), grounded=bool(lines), cited=cited,
                  read={"engine": "content", "via": "reach:op.retrieve", "hits": len(lines)})


def _reach_content(store, query: str, *, k: int, fabric, principal: str, root_secret) -> Answer:
    """Places the retrieval need on sage's `op.retrieve` over the ground plane and turns the
    returned evidence into an Answer. Uses chorus's own `reach_wiring` (prism's Reactor over the
    mantle-backed plane, not ember); returns None while nothing resolves, so an inactive or one-way
    carrier degrades to an honest fall-through rather than a fabricated answer."""
    from agience_chorus.reach_wiring import reach as _reach
    try:
        evidence = _reach(store, principal, {"query": query, "k": k},
                          to="op.retrieve", root_secret=root_secret, fabric=fabric)
    except Exception:
        return None
    if not evidence:
        return None
    return _answer_from_evidence(query, evidence)


def route(artifact_store, ember, query: str, *, graph_store=None, k: int = 6,
          store=None, fabric=None, reach_principal: str = "ember",
          root_secret=None) -> Tuple[Answer, str]:
    """Returns (answer, domain). `domain` names every arm that grounded — one of "dev",
    "arithmetic"/"arithmetic.learn", "code", "content", "semantic", or a "+"-joined combination when
    more than one arm grounds the same need.

    `store` is the full LocalStore bundle (with `.content`/`.keys_dir`); the content arm needs it to
    resolve real article text. When absent, the content arm is skipped (the deterministic arms still
    answer).

    The content arm is a reach, not a local call: BM25 retrieval is a sage tool
    (`sage/content_search.py`), and "ember is simply a runner" ([[ember-is-a-runner]]) — it reaches
    sage's `op.retrieve` over the ground plane. That reach needs a live carrier (`fabric` plus the
    fleet `root_secret`), a separate gated deploy step; both default to None, so on a plain node the
    arm is inactive and the router falls through to semantic rather than fabricating an answer. Pass
    a `fabric` and `root_secret` (e.g. a loopback fabric with a sage provider, in tests) to activate
    it. `reach_principal` is the runner identity the need is placed as."""
    # No typed gates: every arm is offered the need, and none decides what kind of need it is. A
    # predicate that filtered before measurement would destroy information at the gate — dropping a
    # need's code-content because it phrased itself outside a fixed regex — and a first-match-wins
    # pick would destroy it again by discarding every other arm's contribution unread, so a need
    # that is genuinely both a definition and an article about it would come back as only one.
    #
    # Instead every arm is offered the need, each reports what it measured (an Answer, or None for
    # "found nothing" — a measurement, not a category), and everything that grounded propagates. An
    # arm returning None is the honest null; order below is presentation only and carries no
    # precedence.
    contributions: list = []

    def _offer(domain: str, produce) -> None:
        """Runs one arm and keeps what it grounded. An arm that raises or finds nothing contributes
        nothing — a reading, not grounds to skip the other arms."""
        try:
            a = produce()
        except Exception:
            a = None
        if a is not None and getattr(a, "grounded", False):
            contributions.append((domain, a))

    _offer("dev", lambda: dev_ops.answer(query))
    _offer("arithmetic.learn", lambda: arithmetic.learn_operator(query))

    # 1. arithmetic — computed, deterministic, self-verifying. `compute` returns None when the need
    # carries no transform it can verify; that None is a measurement, not a predicate's guess.
    _offer("arithmetic", lambda: arithmetic.compute(query))

    # 1a2. reason — op.reason is lumen's reasoning tekton ("ember is simply a runner", so it does
    # not keep a local trajectory arm); numeric-trajectory reasoning is reached at the conversation
    # level (`conversation._quantitative`), not dispatched here. Ember's own SINDy/DMD duplicate
    # (`reason.py`) is retired. [[ember-tekton-facet-consolidation]]

    # 1b. code — exact definition / references from the AST index (the dev wedge). Falls through to
    # content/semantic on a miss, so it never blocks a non-code question. `code.answer` reads the
    # AST index and returns None on a miss — the index itself says whether the need names a symbol
    # it holds, a measurement over the corpus rather than over the phrasing.
    if artifact_store is not None:
        _offer("code", lambda: code.answer(artifact_store, query))

    # 2. content — BM25 retrieval over the real corpus. This is the answer path for anything that
    # isn't a deterministic domain above: it reaches straight to the documents whose terms match,
    # ranked by the corpus's own IDF — no dictionary, no injected stop/question words. There is no
    # curated-sense arm: WordNet synsets are one BM25-retrievable source in the corpus, not a keyed
    # oracle of authoritative meaning.
    if store is not None and fabric is not None and root_secret is not None:
        _offer("content", lambda: _reach_content(store, query, k=k, fabric=fabric,
                                                 principal=reach_principal, root_secret=root_secret))

    # ── everything that grounded propagates; nothing is picked ─────────────────────────────────
    # More than one arm can ground the same need — a symbol definition and the article describing
    # it, say. Choosing between them would destroy information with no measurement behind it: there
    # is no read that says a definition "beats" an article. So all of it is carried, citations
    # unioned, and the caller sees what the corpus actually held. `domain` names every arm that
    # contributed, so the composition is inspectable rather than collapsed to one label.
    if len(contributions) == 1:
        return contributions[0][1], contributions[0][0]
    if contributions:
        texts = [a.text for _, a in contributions if (a.text or "").strip()]
        cited: list = []
        for _, a in contributions:
            for c in (a.cited or []):
                if c not in cited:
                    cited.append(c)
        return (Answer(text="\n\n".join(texts), grounded=True, cited=cited,
                       read={"engine": "+".join(d for d, _ in contributions),
                             "arms": [d for d, _ in contributions]}),
                "+".join(d for d, _ in contributions))

    # 3. semantic (legacy shard cache) — only when the full store isn't available. When no working
    # set is loaded either, the computed null stands; the arms above already reported nothing.
    if ember is None:
        # The response does not name a taxonomy of question kinds back to the asker. The machine
        # ingests information and emits information at one scale; it does not tell the asker which
        # of its own internal doors they failed to open. `read` keeps the measurement (what was
        # available), not a category claim.
        return (Answer(text="", grounded=False, cited=[],
                       read={"engine": "none", "content_index": False}),
                "semantic")
    return ember.ask(query, k=k).answer, "semantic"
