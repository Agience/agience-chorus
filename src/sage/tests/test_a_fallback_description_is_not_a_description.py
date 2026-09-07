"""A describer that extracted nothing must not look like one that succeeded.

MEASURED ON 71/home 2026-08-27. 874 capture artifacts carry the literal `lemmas: ['document']` and
473 carry `['module']`. Those are not descriptions — they are `_describe_doc`'s and
`_describe_python`'s own fallback literals, reached because `resolve_text` handed back an unopened
MEC1 envelope and `extract_terms` found no terms in ciphertext.

The fallback itself is DELIBERATE and stays: `_describe_python` says it exists "so describe is
always terminating — the file never stays dark and the self-improvement loop can't spin on it
forever." Removing it would trade this defect for an infinite retry.

What must change is that the fallback was INDISTINGUISHABLE from a real description, and
`describe_dark` skips on exactly that signal:

    if a.get("lemmas") or a.get("content_type") not in HANDLERS:
        continue

So one unreadable body became a permanent one. `_split`'s own docstring records the same shape
being fixed once already, for a different cause — a path line making `ast.parse` fail, leaving the
file "keyed from its stem, so `describe_dark` skips it forever with no error at any layer."

Two properties, and both are needed. Marking without the retry leaves the artifact dark forever
with a nicer label; retrying without the mark spins.
"""
from __future__ import annotations

import sage.describe as D


class _Arts:
    def __init__(self, rows):
        self.rows = {r["id"]: dict(r) for r in rows}

    def list_artifacts(self, state=None):
        return [dict(r) for r in self.rows.values()]

    def put_artifact(self, doc):
        self.rows[doc["id"]] = dict(doc)
        return doc

    def put_many(self, docs, batch=None):
        for d in docs:
            self.rows[d["id"]] = dict(d)


class _Bundle:
    def __init__(self, rows):
        self.artifacts = _Arts(rows)


def _doc(i="a1", **kw):
    d = {"id": i, "content_type": "text/markdown", "state": "committed"}
    d.update(kw)
    return d


# ── the mark ─────────────────────────────────────────────────────────────────────────────────────

def _with_text(body):
    """Stub `_split` rather than widen a production signature for a test."""
    return lambda bundle, artifact: ("a1.md", body)


def test_a_fallback_is_marked_as_one():
    """`['document']` must be accompanied by a statement that extraction found nothing."""
    b = _Bundle([_doc()])
    orig, D._split = D._split, _with_text("")
    try:
        D._describe_doc(b, dict(b.artifacts.rows["a1"]))
    finally:
        D._split = orig
    row = b.artifacts.rows["a1"]
    assert row.get("lemmas") == ["document"] or row.get("lemmas") == ["a1"]
    assert row.get(D.DESCRIBE_FALLBACK) is True, (
        "the fallback is indistinguishable from a real description — which is exactly what let "
        "1,347 unreadable bodies read as described")


def test_a_real_description_is_not_marked():
    b = _Bundle([_doc()])
    orig, D._split = D._split, _with_text(
        "# Mantle mass\n\nMass is resistance to acceleration. Mass gates revision.")
    try:
        D._describe_doc(b, dict(b.artifacts.rows["a1"]))
    finally:
        D._split = orig
    row = b.artifacts.rows["a1"]
    assert not row.get(D.DESCRIBE_FALLBACK)
    assert row.get("lemmas") and row["lemmas"] != ["document"]


# ── the retry ────────────────────────────────────────────────────────────────────────────────────

def test_describe_dark_retries_a_fallback():
    """An artifact whose description was a fallback is still dark, and must be offered again."""
    rows = [_doc("fell-back", lemmas=["document"], **{D.DESCRIBE_FALLBACK: True}),
            _doc("described", lemmas=["mantle", "mass"])]
    b = _Bundle(rows)
    seen = []
    orig = D.describe
    D.describe = lambda bundle, a: (seen.append(a["id"]), True)[1]
    try:
        D.describe_dark(b)
    finally:
        D.describe = orig
    assert "fell-back" in seen, "a fallback description was treated as a real one"
    assert "described" not in seen, "a genuinely described artifact must not be re-described"


def test_a_dark_artifact_is_still_offered():
    b = _Bundle([_doc("dark")])
    seen = []
    orig = D.describe
    D.describe = lambda bundle, a: (seen.append(a["id"]), True)[1]
    try:
        D.describe_dark(b)
    finally:
        D.describe = orig
    assert seen == ["dark"]


# ── sealed content is a custody state, not a describe failure ────────────────────────────────────

class ContentStillSealed(Exception):
    """Stands in for `mantle.shard.content.ContentStillSealed` without importing mantle here —
    chorus does not depend on mantle, and `describe` must not gain that edge to handle this.

    THE NAME IS THE CONTRACT. `describe_dark` catches by `type(exc).__name__` precisely so it needs
    no import, which means this double must carry the real name and not a convenient alias — a
    first version called it `_Sealed` and the re-raise fired, correctly."""


def test_one_sealed_body_does_not_kill_the_cycle():
    """`resolve_text` now RAISES on an unopened envelope instead of returning ciphertext — which is
    correct, and which made the first sealed artifact take the whole improve cycle down with it:
    neither `describe` nor `improve_cycle` catches anything, so one unreadable capture would stop
    ALL dark matter being illuminated, not just captures.

    Trading a silent per-artifact failure for a loud whole-system one is not a repair. A sealed
    body is a CUSTODY state: record it, skip that artifact, keep going."""
    rows = [_doc("sealed"), _doc("fine")]
    b = _Bundle(rows)
    seen = []

    def _describe(bundle, a):
        seen.append(a["id"])
        if a["id"] == "sealed":
            raise ContentStillSealed("still sealed")
        return True

    orig = D.describe
    D.describe = _describe
    try:
        n = D.describe_dark(b)
    finally:
        D.describe = orig
    assert "fine" in seen, "a sealed artifact stopped the cycle before reaching the next one"
    assert n == 1, "the sealed artifact must not be counted as illuminated"


def test_a_sealed_artifact_stays_dark_and_is_not_marked_described():
    """It must NOT take the fallback: the body was never read, so `['document']` would be a claim
    about content nobody saw. It stays dark, and becomes describable the moment custody exists."""
    b = _Bundle([_doc("sealed")])

    def _describe(bundle, a):
        raise ContentStillSealed("still sealed")

    orig = D.describe
    D.describe = _describe
    try:
        D.describe_dark(b)
    finally:
        D.describe = orig
    row = b.artifacts.rows["sealed"]
    assert not row.get("lemmas"), "a body nobody could read was given lemmas anyway"
