"""`corpus.py` reads `exact_limit` and `signal_end` from `prism.resolution` rather than carrying its
own definitions, because a second decision-maker can drift from the first — and this file exists to
keep proving it hasn't.

`old_signal_end` and `old_indistinguishable` below are an independent implementation, kept as an
oracle: the point of a second implementation is that it was written separately, so it can disagree.
Featureless ramps — `resolution.py`'s own canonical "nothing to find" case — are the shape most
likely to expose a disagreement, which is why `prism/resolution.py::_tie_break` is the one
definition every consumer shares rather than each side carrying its own tie-break. The sweep finds
0 disagreements.

This file is not a formality and must not be deleted alongside the copy it checks against: it is
the only thing in the tree that can tell us the surviving implementation has drifted.
"""
from __future__ import annotations

import random

import corpus
from prism.resolution import exact_limit, signal_end


# ── an independent implementation, kept as an oracle ─────────────────────────────────────────────
# Do not fold these into a call to the thing they exist to check: an oracle that delegates to its
# subject is a check that cannot fail.
def old_indistinguishable(union_shingles: int) -> float:
    return 1.0 - 1.0 / max(1.0, float(union_shingles))


def old_signal_end(scores) -> int:
    vals = [float(s) for s in scores]
    n = len(vals)
    if n <= 1:
        return n
    total = sum(vals)
    mean = total / n
    var_total = sum((v - mean) ** 2 for v in vals)
    if var_total <= 0.0:
        return n                       # every reading identical: nothing to separate

    def _best(series):
        tot = sum(series)
        mu = tot / len(series)
        vt = sum((v - mu) ** 2 for v in series)
        bb, bc, run = -1.0, len(series), 0.0
        for i in range(1, len(series)):
            run += series[i - 1]
            m1, m2 = run / i, (tot - run) / (len(series) - i)
            btw = i * (m1 - mu) ** 2 + (len(series) - i) * (m2 - mu) ** 2
            if btw > bb:
                bb, bc = btw, i
        return bc, (bb / vt if vt > 0 else 0.0)

    cut, eta = _best(vals)
    _null = _best([float(n - i) for i in range(n)])[1]
    return cut if eta > _null + 1e-12 else n


# ── the shared corpus of inputs ──────────────────────────────────────────────────────────────────
def _inputs():
    """Fixed seed, so a disagreement is reproducible from the report rather than from a rerun."""
    rng = random.Random(20260804)
    yield []
    yield [1.0]
    for n in (2, 3, 4, 5, 7, 12, 33, 100, 200):
        yield [5.0] * n                                        # flat
        yield [float(n - i) for i in range(n)]                 # the uniform ramp — reads its own null
        yield [float(n - i) + 1e-15 * i for i in range(n)]     # ramp + float dust
        yield [1.0 - i * 0.001 for i in range(n)]              # the shape that found the defect
        yield [9.0] * (n // 2) + [0.5] * (n - n // 2)          # two clean groups
        yield [100.0] + [1.0] * (n - 1)                        # one dominant
        yield [0.0] * n                                        # all zero
        yield [1e-18 * (n - i) for i in range(n)]              # tiny magnitudes
        yield [1e18 * (n - i) for i in range(n)]               # huge magnitudes
    # The near-duplicate shape: 0.2 -> 0.94 across many pairs with no valley. This is the series
    # `near_duplicates` actually hands it, so it is not an edge case here — it is the case.
    for n in (50, 300, 1661):
        yield [0.94 - (0.74 * i / (n - 1)) for i in range(n)]
    for _ in range(4000):                                      # random, sorted descending
        n = rng.randint(2, 40)
        yield sorted((rng.random() for _ in range(n)), reverse=True)
    for _ in range(2000):                                      # quantised — ties everywhere
        n = rng.randint(2, 25)
        yield sorted((float(rng.randint(0, 6)) for _ in range(n)), reverse=True)
    for _ in range(2000):                                      # a planted cliff at a random place
        n = rng.randint(4, 40)
        k = rng.randint(1, n - 1)
        hi, lo = rng.uniform(1, 10), rng.uniform(0, 0.2)
        yield ([hi + rng.random() * 0.01 for _ in range(k)]
               + [lo + rng.random() * 0.01 for _ in range(n - k)])
    for _ in range(2000):                                      # Jaccard-shaped
        n = rng.randint(2, 30)
        yield sorted((rng.uniform(0.2, 1.0) for _ in range(n)), reverse=True)


def test_the_sweep_is_not_vacuous():
    """The control, run first: two assertions that would each make the sweep meaningless — an empty
    corpus, and an oracle that has been quietly turned into a call to its own subject."""
    cases = list(_inputs())
    assert len(cases) > 10_000, "the input corpus is %d cases — it is not sweeping" % len(cases)
    assert any(len(c) > 1000 for c in cases), "nothing long enough to condition badly"

    # The oracle must be able to disagree. Perturb the subject's answer and watch the comparison
    # fire — a sweep that passes against a deliberately wrong subject is proving nothing.
    seeded = [10.0, 9.0, 8.0, 1.0, 0.9]
    assert old_signal_end(seeded) == signal_end(seeded) == 3
    assert old_signal_end(seeded) != signal_end(seeded) + 1


def test_signal_end_agrees_with_the_deleted_copy_everywhere():
    """Every disagreement is reported, not the first one — the shape of the disagreements is what
    identifies which side is wrong."""
    bad = []
    n = 0
    for scores in _inputs():
        n += 1
        a, b = old_signal_end(scores), signal_end(list(scores))
        if a != b:
            bad.append("n=%d  deleted-copy=%s  prism=%s  head=%s" % (len(scores), a, b, scores[:6]))
    assert not bad, (
        "`prism.resolution.signal_end` and the independent oracle implementation "
        "disagree on %d of %d inputs:\n  %s\n"
        "Do not assume prism is right without checking: last time this fired, the oracle was "
        "correct and prism was cutting a featureless ramp. Read what the inputs have in common "
        "before changing either side." % (len(bad), n, "\n  ".join(bad[:40])))


def test_indistinguishable_agrees_with_the_deleted_copy_everywhere():
    bad = [(u, old_indistinguishable(u), exact_limit(u))
           for u in list(range(0, 200)) + [1000, 10_000, 1_000_000, 2 ** 31, 2 ** 53]
           if old_indistinguishable(u) != exact_limit(u)]
    assert not bad, "exact_limit disagrees with the deleted copy at %r" % bad[:20]


def test_corpus_reads_the_one_definition_and_holds_no_copy_of_it():
    """The dedupe itself: `corpus.indistinguishable` must be `exact_limit`, not agree with it.

    Read as source as well as behaviour: a re-added local block that happened to agree today would
    pass every assertion above while being exactly the second decision-maker this file exists to
    catch."""
    import inspect

    assert corpus.indistinguishable(20) == exact_limit(20)
    assert corpus._signal_end is signal_end, (
        "`corpus._signal_end` is %r, not `prism.resolution.signal_end`. A local definition is a "
        "second decision-maker, whatever it currently returns." % corpus._signal_end)

    src = inspect.getsource(corpus)
    assert "def _signal_end" not in src, "a local `_signal_end` came back into sage/corpus.py"
    assert "_best(" not in src, "the Otsu block came back into sage/corpus.py"
    assert "1e-12" not in src, "the invented tie-break came back into sage/corpus.py"
