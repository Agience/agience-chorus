r"""Text completion: recognise, predict to the horizon, then run recognition backwards.

    cd agience-chorus/src
    EMBER_SQLITE_DIR=<shard-dir> python -c "import ember, runpy, sys; \
        sys.argv=['complete','read:colimit','It is a truth']; \
        runpy.run_module('lumen.reading.complete', run_name='__main__')"

Four steps, each an operation that already exists elsewhere:

    recognise   signal -> placed vertices -> the junction over them    (`reading_junction.cover`)
    predict     the placed vertices are a path; `sequence_operator` reads its operator and rolls it
                to the operator's own horizon `l = ceil(ln(contrast)/(-ln m))` — a continuation of
                the path, never a search over neighbours
    context     the predicted states, handed back to the ontology, are the new context: concepts
    outgest     run recognition backwards — a vertex decomposes through its colimit members until
                what is left carries a surface, and the surfaces are the text

The middle is concepts, not prose. `text -> signal -> screen -> ontology -> predict -> ontology ->
screen -> signal -> text` has text at both ends and nowhere between. Emitting a stored passage would
be retrieval wearing generation's clothes; what is generated here is the selection and the order of
concepts, and the surfaces come from the vertices those concepts are.

Outgest is recognition with the arrows reversed. Recognition places a signal at the longest vertex
that covers it and re-places the residual; outgest takes a vertex and descends its colimit
morphisms until it reaches vertices that carry surface. Same edges, walked the other way — which is
why the triple can carry both directions and why no second structure is needed to emit.

This completes from what was read and from nothing else. A prefix whose vertices the reading never
formed places thinly and predicts thinly, and both the coverage and the operator's own read ride
out with the answer, so a thin completion cannot be mistaken for a confident one — and a path with
no horizon returns the refusal rather than a guess.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import numpy as np

from agience_chorus._host_seams import seam as _seam

import agience_chorus.reading_junction as _j


def _db() -> str:
    # The shard is a data volume, not part of the checkout, so no default here could be right
    # on another box. Unset is REFUSED rather than guessed: a reader silently opening a store
    # nobody chose does not fail, it reports an empty corpus — which reads as "nothing found"
    # when the truth is "nothing configured".
    root = (os.environ.get("EMBER_SQLITE_DIR") or "").strip()
    if not root:
        raise RuntimeError(
            "EMBER_SQLITE_DIR is unset. Point it at the directory holding lattice.db.")
    return os.path.join(root, os.environ.get("EMBER_SQLITE_DB", "lattice.db"))


def predict(ro, reading, placed):
    """Continue the current path to the operator's own horizon.

    The placed vertices are a path — an ordered sequence of points in the reading's coordinate — so
    the instrument for continuing it is the dynamical one. `sequence_operator` reads the operator off
    that trajectory and publishes how far it may be rolled:

        l = ceil( ln(contrast) / (-ln m) )        m = |mu| of the dominant mode

    The horizon is the operator's answer, not a reach anyone picks: past `l` the operator would be
    predicting from an amplitude it no longer has, and `roll()` stops there by construction.

    Depth is 1: in a proper basis `d = 1` already resolves five to seven timescales, while `d >= 3`
    sends `tau_slow` negative — growth rather than decay, which the reader refuses. The reading's
    own basis is a proper basis, so no delay lift is taken.

    Returns `(states, read)` — the predicted coordinates, one per step within the horizon, and what
    the operator reported about itself."""
    import numpy as np
    idx, coord = reading.idx, reading.coord
    if coord is None:
        return [], {"refusal": "the reading has no coordinate to continue a path in"}
    rows = [coord[idx[_j.unit_id(reading.collection, t)]] for t in placed
            if _j.unit_id(reading.collection, t) in idx]
    if len(rows) < 3:
        return [], {"refusal": "fewer than three placed vertices — that is not a path to continue"}
    path = np.vstack(rows)

    op = _seam("optics").sequence_operator(path, depth=1)
    if op is None:
        return [], {"refusal": "the path is too short to fit an operator"}
    if op.horizon is None:
        return [], {"refusal": op.refusal, "contrast": round(float(op.contrast), 4),
                    "resolved_modes": int(op.resolved_modes)}
    states = [np.asarray(d, dtype=float) for _step, d in op.roll(path[-1])]
    return states, {"horizon": int(op.horizon), "contrast": round(float(op.contrast), 4),
                    "resolved_modes": int(op.resolved_modes),
                    "margin": round(float(op.margin), 4), "refusal": None}


def recognise_states(ro, reading, states, exclude=()):
    """The vertices a predicted state couples to — prediction handed back to the ontology.

    The screen is excluded from its own candidates: a continuation is what the path reaches next,
    so what the prefix already holds cannot be the answer — without the exclusion the strongest
    coupling is the prefix coupling to itself.

    Coupling, never nearness: each candidate offers its own direction as a rank-one band and
    `absorb_transmit` measures what the predicted state gives it."""
    import numpy as np
    idx, coord = reading.idx, reading.coord
    skip = set(exclude)

    # The split is one call on the whole frame. Projecting every candidate onto the predicted
    # state's direction is `absorb_transmit(coord, basis=state)` — the candidates are the rows, so
    # the instrument does all of them in a single read and hands back a row per vertex.
    names = list(idx.keys())
    out = []
    for st in states:
        v = np.asarray(st, dtype=float).ravel()
        if v.size != coord.shape[1] or not np.any(v):
            continue
        res = _seam("optics").absorb_transmit(coord, basis=v.reshape(-1, 1))
        if res is None:
            continue
        energy = (np.abs(res[0]) ** 2).sum(axis=1)          # one row per candidate
        for j in np.argsort(-energy):
            name = names[int(j)]
            if name in skip:
                continue
            out.append((name, float(energy[int(j)])))
            skip.add(name)                 # a vertex is reached once; the path moves on
            break
    return out


# Comparing labels is the colimit's business, at the instrument, and nowhere else: "what follows this
# vertex" and "the edge of the screen" are questions the coupling answers, never string arithmetic
# on surfaces done inside the ontology.


_SUCC = {}


def successors(ro, collection, vertex):
    """The vertices this one was read before — the order edges out of it, and nothing else.

    An order edge is the only relation the text states, so this is the whole candidate set for a
    continuation. Indexed on `src`; the work is set by the question, never by how much was read.

    Both halves of the operator are read here and at every other edge query in this file.
    `observed` and `observed_alone` are the same context→content link — the operator discriminates
    them, it does not decide which exist — so a query naming only `observed` is blind to every
    vertex a context holds alone, which on a collection written that way is every paragraph-unique
    concept. `read_basis.OBSERVED` and `query_neighbourhood` already read both."""
    import json as _json
    got = _SUCC.get(vertex)
    if got is not None:
        return got
    out = []
    for d, pr in ro.execute(
            "SELECT dst, props FROM edge WHERE src = ? "
            "AND label IN ('observed','observed_alone')", (vertex,)):
        if not pr or '"next"' not in pr:           # string-test before parsing: this is a hot path
            continue
        try:
            p = _json.loads(pr) or {}
        except Exception:
            continue
        if "next" in p:                            # order; a colimit edge carries bits_saved instead
            out.append((d, p))
    # Cached: the walk asks the same spine vertices on every step, and a common vertex has
    # thousands of order edges to decode. The store is opened read-only, so this cannot go stale
    # within a process.
    _SUCC[vertex] = out
    return out


_ctx_cache = {}


def _frame_over(ro, collection, screen, extra, holders):
    """The frame this instrument gives — factored out so the probe that asks whether an instrument
    resolves and the caller that uses it build the identical frame. Two copies of this would drift,
    and the probe would be answering about a frame nobody uses."""
    import collections as _c

    import numpy as np
    bits = _seam("optics").self_information_bits
    mates = _c.Counter()
    for o in holders:
        for (d,) in ro.execute(
                "SELECT dst FROM edge WHERE src = ? "
                "AND label IN ('observed','observed_alone')", (o,)):
            mates[d] += 1
    closure = set(screen) | {d for d, n in mates.items() if n > 1}

    # A row is a vertex, a column is a context — the incidence of the Galois connection itself.
    # Clark's lattice is built on strings x contexts, and that is the orientation in which "what is
    # this vertex" is a vector: its context signature. Built the other way up (contexts as rows,
    # vertices as features) the frame is a handful of near-identical sparse rows and
    # `principal_directions` resolves nothing.
    rows = sorted(closure | set(extra))
    ctxs = sorted(holders)
    if len(rows) < 2 or len(ctxs) < 2:
        return None, [], {}, set()
    at = {c: j for j, c in enumerate(ctxs)}
    want = set(rows)
    inc = _c.defaultdict(set)
    for o in ctxs:
        for (d,) in ro.execute(
                "SELECT dst FROM edge WHERE src = ? "
                "AND label IN ('observed','observed_alone')", (o,)):
            if d in want:
                inc[d].add(o)
    deg = _c.Counter()
    for v, cs in inc.items():
        for c in cs:
            deg[c] += 1
    total = float(sum(deg.values()))
    if total <= 0:
        return None, [], {}, set()
    amp = {}
    for c in ctxs:
        b = bits(float(deg.get(c, 0)), total) if deg.get(c) else None
        amp[c] = float(np.sqrt(b)) if b and b > 0.0 else 0.0
    F = np.zeros((len(rows), len(ctxs)), dtype=float)
    for i, v in enumerate(rows):
        for o in inc.get(v, ()):
            F[i, at[o]] = amp[o]
    cols = rows
    return F, cols, amp, closure


def _resolves(ro, collection, screen, extra, holders):
    """Can this instrument carry a read? The instrument answers, and nothing here guesses."""
    F, _cols, _amp, _cl = _frame_over(ro, collection, screen, extra, holders)
    if F is None:
        return False
    Fw = _seam("optics").screen_normalize(F)
    if Fw is None:
        return False
    B = _seam("optics").principal_directions(Fw)
    return B is not None and getattr(B, "ndim", 0) == 2 and B.shape[1] >= 1


def screen_frame(ro, collection, screen, extra=(), polar=(), history=()):
    """The local instrument — rows are the reading's own steps that hold this screen.

    The prefix's own positions are not enough rows: a screen built from the placed units alone
    cannot resolve a direction out of itself, because `principal_directions` needs contexts, not
    just the units themselves, to read a correlation. So the rows are the steps the reading took
    that hold these vertices, reached by indexed lookup on the colimit edges into each observation
    — an instrument that is finite, built for this question, and much smaller than the frame
    `read_cloud` derives over the whole reading.

    Returns `(F, cols, amp)`; `(None, [], {})` when nothing holds this screen."""
    import collections as _c

    import numpy as np
    bits = _seam("optics").self_information_bits

    # Clark's syntactic concept lattice (FG09) builds a Galois connection between substrings and
    # contexts: `S' = {contexts holding every string in S}`, `C' = {strings fitting every context
    # in C}`, and a concept is a closed pair `S'' = S`. The polar here is an intersection over the
    # screen's vertices, not a union: a union answers "what is related to something on this
    # screen", which on a common unit reaches thousands of contexts, while the intersection answers
    # "what context does this screen have" and is small by construction.
    #
    # The closure is the screen. `place` collapses a prefix into two or three long junctions, which
    # cannot resolve a direction of their own; `S''` — every vertex fitting all of the screen's
    # contexts — widens it to the concept the screen actually names, rather than to whatever
    # happened to be nearby.
    #
    # The intersection belongs to a concept, not to a sequence: taken over the whole screen it is
    # empty, since no one context holds every vertex of a sentence plus every colimit member of
    # each. Clark is explicit that the concept of a sequence is the monoid product of its parts'
    # concepts, not the concept of the set. So the polar is the frontier's — the steps in which the
    # thing being continued actually occurred — and the rest of the screen stays as features, which
    # is what disambiguates which of those steps this one is like.
    #
    # A context holding only one vertex of this screen is incidental to it. Two shared vertices is
    # a coincidence the reading actually witnessed — the same recurrence the colimit requires
    # before it will fuse anything — and it keeps the rare case: the sentence that holds `It is a `,
    # `truth ` and `universally ` still qualifies, while the thousands that merely contain `a `
    # do not.
    #
    # The instrument opens where the screen's most informative element is. A context holding only
    # common vertices narrows nothing — `a ` sits in thousands of them — so the rarest element says
    # where this screen lives, read off `self_information_bits` over the context counts themselves:
    # fewest contexts is most information. It bounds the instrument uniformly and by measurement
    # rather than by a capacity anyone picked, and the rest of the screen then narrows what is left
    # by the same shared-recurrence rule.
    #
    # A vertex occurs wherever the junctions above it occur. An observation is a colimit over its
    # top-level path, so once the ladder is deep a base word is almost never a direct member of
    # one — its contexts are one level up. Climbing the colimit recovers them exactly and needs no
    # extra edge: if `Bennet` is a member of `Mr. Bennet ` and that sits in obs-42, then `Bennet`
    # is in obs-42. The climb is memoised — `' '` is a member of tens of thousands of junctions,
    # and the naive recursion would re-walk the same ladder once per path into it — so remembering
    # each vertex's answer makes it one traversal of the edges above the screen.
    def _contexts(v):
        got = _ctx_cache.get(v)
        if got is not None:
            return got
        _ctx_cache[v] = set()                      # cycle guard: an in-progress vertex adds nothing
        out = set()
        for src, pr in ro.execute(
                "SELECT src, props FROM edge WHERE dst = ? "
                "AND label IN ('observed','observed_alone')", (v,)):
            if ":obs-" in src:
                out.add(src)
            elif '"bits_saved"' in (pr or ""):      # a junction this vertex is a member of
                out |= _contexts(src)
        _ctx_cache[v] = out
        return out

    per = {}
    for v in polar:
        per[v] = _contexts(v)
    per = {v: cs for v, cs in per.items() if cs}
    if not per:
        return None, [], {}, set()
    # The instrument opens until it can read. Anchored on the rarest element alone it is small and
    # cheap but frequently cannot carry a read at all, so the vertices are taken in order of
    # information, most informative first, and each one's contexts are added until the frame
    # resolves. The stopping condition is the instrument's own refusal, not a capacity: an instrument
    # opens until it admits enough light, and how much that is depends on the scene.
    order = sorted(per, key=lambda v: len(per[v]))  # fewest contexts = most bits
    holders = set()
    for v in order:
        holders |= per[v]
        if len(holders) > 1 and _resolves(ro, collection, screen, extra, holders):
            break
    if not holders:
        return None, [], {}, set()
    # History does not narrow the contexts here — a hard intersection empties after one or two
    # vertices and starves the frame before it is built. The history narrows the signal instead,
    # by propagation, in `walk`.

    # The screen is its closure, not the units that were placed. A screen with too few rows of
    # constraint against a frontier with hundreds of successors cannot select anything but the most
    # generic candidate. Clark's concept is `S''` — everything sharing the screen's contexts — and
    # that is the object with a direction. A vertex earns a place in it by appearing in more than
    # one of those contexts, the same recurrence the colimit requires before it will fuse anything;
    # one shared context is what being common looks like.
    return _frame_over(ro, collection, screen, extra, holders)


_SURFACE = {}
_CONTEXTS = {}
_SPINE = {}


def outgest(ro, collection, vertex, seen=None):
    """The opposite of recognise: a vertex, descended through its colimit members to surface.

    Recognition climbs — a signal is placed at the longest vertex covering it. Outgest descends —
    a vertex hands back the members it is a colimit over, and each of those does the same, until
    what is left carries surface. Same edges, walked the other way.

    Termination is the structure's: a vertex with no colimit members is a leaf and yields its own
    surface, so the walk stops because the ontology stops. A cycle is caught by remembering what
    this descent has already entered, rather than by a depth limit — a colimit may be built to any
    depth, and a limit would truncate a vertex built higher than it, returning an interior
    junction's id instead of the surface it descends to."""
    seen = set() if seen is None else seen
    if vertex in seen:                             # the store has a cycle; this arm is spent
        return ""
    got = _SURFACE.get(vertex)
    if got is not None:
        return got
    seen = seen | {vertex}
    # A junction's members are the edges that carry a saving — the measurement, not a label. The
    # props are string-tested before they are parsed: `outgest` walked 1.86 MILLION `json.loads`
    # calls on one completion, because every edge out of every vertex it descended was decoded in
    # full to read one key.
    mem = []
    for d, pr in ro.execute(
            "SELECT dst, props FROM edge WHERE src = ? "
            "AND label IN ('observed','observed_alone')", (vertex,)):
        if not pr or '"bits_saved"' not in pr:
            continue
        try:
            q = __import__("json").loads(pr) or {}
        except Exception:
            continue
        if q.get("bits_saved") is not None:
            mem.append((q.get("at"), d))
    if not mem:
        out = _j.surface(vertex)
        _SURFACE[vertex] = out
        return out
    # Members come back in whatever order the index yields, so they are put back in the order the
    # READER recorded. A colimit is `a + b`; emitting `b + a` is a different string.
    mem.sort(key=lambda p: (p[0] is None, p[0]))
    out = "".join(outgest(ro, collection, d, seen) for _at, d in mem)
    # A vertex's surface does not change, and the ladder shares members heavily — descending them
    # once per path into them is what made this 21 of the 32 seconds a reply took.
    _SURFACE[vertex] = out
    return out


def walk(ro, collection, placed, right_of, carried=()):
    """Continue a placed signal along the order edges, choosing by the colimit's own measurement.

    The reading already decided which concatenations are real: a junction exists only where a pair
    RECURRED and cost fewer bits joined than apart, and `bits_saved` carries how much. Among the
    vertices read after the frontier, the one this reading most strongly binds is the one whose
    junction with it saves most — measured at read time, not a preference applied here.

    Ranking the same candidates by the screen's absorbed energy or absorbed fraction puts
    whitespace first (`' '`, `'\\n'`), while `bits_saved` gives `' could hardly '`,
    `' much in love '`, `' not '`. The coupling is the more principled quantity and it is what the
    geometric path uses; on this reading it selects worse, so the walk ranks on the colimit's own
    measurement.

    Its limit: `bits_saved` is largest for the rarest join, so a few steps out the walk reaches for
    the same rare long phrases wherever it started, and different prefixes converge.

    The frontier is the deepest anchor that binds. Drawing from every level of the right spine at
    once lets the weakest context win by degree — `' '` is followed by most of the vocabulary — and
    taking the deepest level that merely has successors ends a walk in a word or two, because the
    colimit judged none of those successors worth joining.

    Returns `(said, steps)`."""
    import json as _json
    said, steps, seen_move = [], [], set()
    _closes = {}

    def closes(v):
        """Does this vertex close one of the reading's own observations?

        A position in a colimit, not a punctuation rule: the reader recorded each member's index in
        the observation it belongs to, so the last member of one is where a reading stopped."""
        got = _closes.get(v)
        if got is not None:
            return got
        out = False
        for src, pr in ro.execute(
                "SELECT src, props FROM edge WHERE dst = ? "
                "AND label IN ('observed','observed_alone')", (v,)):
            if ":obs-" not in src or not pr or '"at"' not in pr:
                continue
            try:
                at_here = (_json.loads(pr) or {}).get("at")
            except Exception:
                continue
            row = ro.execute("SELECT doc FROM vertex WHERE id = ?", (src,)).fetchone()
            if not row:
                continue
            try:
                n_mem = int((_json.loads(row[0]) or {}).get("members") or 0)
            except Exception:
                continue
            if at_here is not None and n_mem and int(at_here) == n_mem - 1:
                out = True
                break
        _closes[v] = out
        return out

    def contexts(v):
        """Where this vertex occurs — its own contexts, and those of the junctions above it.

        An observation is a colimit over its top-level path, so a base word is rarely a direct
        member of one: `Bennet` shows three contexts on a reading that uses it hundreds of times.
        They are one level up, and climbing recovers them exactly. Memoised across the process —
        the ladder is shared heavily and a naive climb re-walks it once per path in."""
        got = _CONTEXTS.get(v)
        if got is not None:
            return got
        _CONTEXTS[v] = frozenset()                 # cycle guard
        out = set()
        for src, pr in ro.execute(
                "SELECT src, props FROM edge WHERE dst = ? "
                "AND label IN ('observed','observed_alone')", (v,)):
            if ":obs-" in src:
                out.add(src)
            elif pr and '"bits_saved"' in pr:
                out |= contexts(src)
        out = frozenset(out)
        _CONTEXTS[v] = out
        return out

    lead = list(right_of(_j.unit_id(collection, placed[-1])))   # an id, not a surface
    # The thought ends when it leaves the context it started in, and that context is the question's,
    # fixed here rather than recomputed as the walk proceeds. A greedy walk is deterministic: once
    # two prefixes reach the same frontier they produce the same tail, so ranking alone cannot keep
    # different questions apart — the rarest join and the most-witnessed one both converge, on
    # different phrases. What separates them is how far the answer is still about the question, and
    # a context recomputed from the growing screen loses that: the screen accumulates contexts until
    # everything shares one.
    #
    # The question's parts count as part of the question. A prefix that collapses to a single
    # junction — `she said`, `the ball`, `Jane was` — has a context set nothing intersects, so the
    # walk stops before its first step (4 of 20 prefixes on the measured set). Descending the
    # colimit adds the contexts of what the question is made of, which is the same overlap the
    # reader builds and the same reason `place` covers rather than tiles.
    def _members(v, seen):
        if v in seen:
            return set()
        seen = seen | {v}
        out = {v}
        for d, pr in ro.execute(
                "SELECT dst, props FROM edge WHERE src = ? "
                "AND label IN ('observed','observed_alone')", (v,)):
            if pr and '"bits_saved"' in pr:
                out |= _members(d, seen)
        return out

    # Two context sets, doing two different jobs. The broad one — the question and everything it is
    # made of — decides which candidates are on the table; a prefix that places as a single junction
    # has nothing to intersect without it. The narrow one — the placed vertices themselves — is
    # where the question lives, and once the walk stops touching it the thought has ended. The broad
    # set used for both drifts; the narrow set used for both is silent.
    #
    # The screen carries across turns. One question opens too thin an instrument to read: two or three
    # placed vertices resolve no direction, so selection falls back to a quantity that is a property
    # of the join alone and drifts the same way whatever was asked. What was said earlier is still on
    # the screen, and it is what makes this question's context specific rather than generic.
    #
    # The question's most informative vertex is what makes it this question. Filtering on the union
    # of its contexts lets every question reaching the same frontier offer the same candidates —
    # `She was` and `Jane was` differ only in a subject that contributes nothing. Fewest contexts is
    # most bits, so the rarest placed vertex is the one carrying the question's identity, and
    # requiring a continuation to share its contexts is what separates them. Nothing is weighted or
    # chosen: the reading's own counts say which vertex that is, and the union stays available for
    # when it holds nothing.
    ask_ctx, core_ctx, per_vertex = set(), set(), {}
    for vid in carried:
        core_ctx |= contexts(vid)
        ask_ctx |= contexts(vid)
    for tok in placed:
        vid = _j.unit_id(collection, tok)
        core_ctx |= contexts(vid)
        if contexts(vid):
            per_vertex[vid] = contexts(vid)
        for part in _members(vid, set()):
            ask_ctx |= contexts(part)
    keyed = min(per_vertex.values(), key=len) if per_vertex else frozenset()
    screen = {_j.unit_id(collection, tok) for tok in placed}
    lim = getattr(sqlite3, "SQLITE_LIMIT_VARIABLE_NUMBER", None) or 999

    while True:
        # One query per level, not one per candidate: the join each candidate would form is a
        # vertex id, so all of them are asked for in a single indexed IN.
        cands = []
        for v in lead:
            here = [d for d, _p in successors(ro, collection, v) if d not in screen]
            if not here:
                continue
            sv = _j.surface(v)
            joins = {_j.unit_id(collection, sv + _j.surface(d)): d for d in here}
            ids = list(joins)
            for k in range(0, len(ids), lim - 2):
                part = ids[k:k + lim - 2]
                q = "SELECT id, doc FROM vertex WHERE id IN (%s)" % ",".join("?" * len(part))
                for jid, doc in ro.execute(q, tuple(part)):
                    try:
                        saved = (_json.loads(doc) or {}).get("bits_saved")
                    except Exception:
                        continue
                    if saved is None:
                        continue
                    try:
                        seen_n = float((_json.loads(doc) or {}).get("witnesses") or 0.0)
                    except Exception:
                        seen_n = 0.0
                    cands.append((joins[jid], jid, seen_n, float(saved),
                                  len(_j.surface(joins[jid]))))
            if cands:
                break                              # this level binds; no need to descend further
        if not cands:
            steps.append({"stopped": "the reading binds nothing to this frontier"})
            break

        # Selection asks for the expected continuation rather than the surprising one. `bits_saved`
        # is the colimit's formation test — cheaper joined than apart — and it is largest for the
        # rarest join, so ranking on it alone asks for the most surprising thing the reading ever
        # saw follow this, and every prefix drifts into the same rare phrases. Completion wants the
        # continuation this reading most often walked, which carries the least self-information
        # given the frontier: `witnesses` is how many times the colimit saw it, and it is already on
        # the junction. The saving still gates which pairs are candidates at all — a join the
        # reading never judged worth forming is not offered.
        #
        # A shared context is a filter over a global quantity, so it cannot supply what the ranking
        # lacks. Gating candidates on sharing a context with the screen moves the attractor ('put an
        # end to by the entrance of Lady Catherine's') at 4x the time, because the screen
        # accumulates contexts until nearly every candidate shares one. The drift needs a quantity
        # conditional on the question.
        #
        # `isdisjoint` short-circuits, where an intersection materialises per candidate per step and
        # both sides run to thousands of contexts.
        #
        # The union decides who is on the table; the question's key vertex decides who wins. As a
        # filter the key vertex admits so few candidates that fluency collapses — `Elizabeth was
        # very` falls from `comfortable that it was impossible for her to return into Hertfordshire`
        # to a fragment. As the first sort key it separates two questions that reach the same
        # frontier without narrowing what either may say.
        near = [c for c in cands if not contexts(c[0]).isdisjoint(ask_ctx)]
        if not near:
            steps.append({"stopped": "the continuation has left the context of the question"})
            break
        # The tie-break is total compression earned, not either half of it. `bits_saved` is the
        # saving per occurrence and is largest for the rarest join; `witnesses` is how often the
        # reading walked it and is largest for the most ordinary. Each alone is skewed — the rarest
        # drifts into rare phrases, the most-witnessed into common ones — while their product is
        # what this join has saved the reading over the whole corpus: one number, both facts, and
        # nothing chosen to weight them.
        #
        # Emission takes the longest continuation, as recognition takes the longest cover. Outgest
        # is recognition with the arrows reversed, and `place` puts a signal at the longest vertex
        # covering it, so the way out reaches for the longest vertex the reading offers here — which
        # is what the colimit ladder provides. A short selection makes the walk take many small
        # steps, and every extra step is another chance to drift. Ties go to the join that has
        # earned the reading the most compression.
        #
        # Ten ways of choosing have been measured on this reading: bits_saved, witnesses, their
        # product, absorbed energy, absorbed fraction, shared-context gating, coupling on a frame
        # bounded by the rarest vertex, coupling on a frame fed by the question's closure, and
        # ranking by shared question-context. Only the coupling is conditional on the question, and
        # it is caught between two walls — a screen of a few placed vertices resolves no direction,
        # while its closure carries thousands of contexts and `eigh` on that frame does not return.
        # Any measure of overlap with the screen favours whatever occurs everywhere (`the very much
        # to the very much`), because a common vertex shares more context with any question than a
        # specific one does; overlap discriminates only under a normalisation that entroptics keeps
        # out of scope, since dividing a vector by its norm is cosine. The instrument one question
        # opens is too thin to read and its closure is too wide to decompose, which is why the
        # screen is fed over time rather than reconstructed per question.
        best, best_join, _seen, best_saved, _n = max(
            near, key=lambda c: (bool(keyed) and not contexts(c[0]).isdisjoint(keyed),
                                 c[4], c[2] * c[3]))
        # An observation boundary is a place to stop (it is used as one below) and not a reason to
        # choose: by the time a candidate is on the table its ending is already determined by which
        # junction it is. Preferring candidates that close an observation changes no answer and
        # costs the extra lookups — `Elizabeth was very` runs 3.7s against 14.4s.

        # A transition taken twice from the same edge will be taken forever — a property of the
        # path, not a step count, and what ends a walk the binding does not.
        move = (tuple(lead), best)
        if move in seen_move:
            steps.append({"stopped": "the walk repeated a move it has already made"})
            break
        seen_move.add(move)

        # A weakening binding is not what ends the walk: the compression a join earns does not fall
        # away as the answer wanders, so there is no decline to measure. Drift comes from each
        # binding being strong and none of them being about the question, which is what a screen
        # wide enough to read addresses.
        said.append(outgest(ro, collection, best))
        steps.append({"vertex": _j.surface(best), "vertex_id": best,
                      "bits_saved": round(best_saved, 4),
                      "hole": "content", "act": "deduce"})
        screen.add(best)
        # A thought may end where the reading's own did. An observation is a colimit over its path
        # and the reader recorded each member's position in it, so "this vertex closed a sentence"
        # is a fact about the structure rather than a punctuation rule applied here. It is the one
        # boundary the walk can honour without inventing one.
        closed = False
        for src, pr in ro.execute(
                "SELECT src, props FROM edge WHERE dst = ? "
                "AND label IN ('observed','observed_alone')", (best,)):
            if ":obs-" not in src or not pr or '"at"' not in pr:
                continue
            try:
                at_here = (_json.loads(pr) or {}).get("at")
            except Exception:
                continue
            row = ro.execute("SELECT doc FROM vertex WHERE id = ?", (src,)).fetchone()
            if not row:
                continue
            try:
                n_mem = int((_json.loads(row[0]) or {}).get("members") or 0)
            except Exception:
                continue
            if at_here is not None and n_mem and int(at_here) == n_mem - 1:
                closed = True
                break
        if closed:
            steps.append({"stopped": "the reading's own observation ended here"})
            break
        # The candidate filter is the stop; there is no second gate here. Ending the walk the
        # moment an emitted vertex leaves the placed vertices' own contexts cuts most answers to a
        # single word — `Lydia went to` -> `town` — because a two-vertex question lives in very few
        # contexts. The filter on candidates already keeps the walk inside what the question is
        # about, and with the screen carrying across turns that set widens as the conversation does.
        #
        # Each of the three narrower stop conditions is either too narrow or too wide: the placed
        # vertices' own contexts cut answers to a single word, the question's key vertex does the
        # same and silences some outright, and the union lets every answer run on into the same
        # generic tail. The reading offers no context set between "this exact phrase" and "anything
        # related", because a two-word question does not occur in enough places to define one —
        # the same wall the geometry reaches from the other side.
        pass
        # The new frontier is the PRODUCT, not the last factor. Having joined the anchor with what
        # follows it, what stands at the edge is the junction — `Darcy was` + `' '` leaves
        # `Darcy was `, not `' '`. Taking the emitted member collapsed the context to a bare space,
        # which is followed by most of the vocabulary, so the next choice was made with none.
        lead = list(right_of(best_join)) if ro.execute(
            "SELECT 1 FROM vertex WHERE id = ?", (best_join,)).fetchone() else list(right_of(best))
    return said, steps


def complete(ro, collection, prefix, reading=None, carried=()):
    """Recognise, then walk by coupling — one vertex per step, each one back onto the screen.

    This is the KQV-attention shape: the predicted vertices are placed on the screen and the
    prediction is run again on the new screen. Order edges say what could follow; the coupling says
    which one does. Every emitted vertex joins the screen, so the next hop is measured against a
    screen that includes what was just said — and the screen is the only frame anyone builds, per
    question, never over the corpus.

    Two acts, and the order between them is the point. Completion holds the context and the operator
    and the hole is the content, so `walk` — deduction — goes first: the step that held this
    screen also held what followed it, and that is a fact the reading witnessed. `predict` is a
    forecast for a path nobody walked, so it is tried only once deduction has nothing, and the step
    it produces is reported as the weaker act it is (`"act": "forecast"`), which is the distinction
    `chat.py` states in every reply. Reversing them is not a preference: MEASURED on the curriculum,
    every clean completion came via context and every garbled one via the operator, because the
    operator emits fragments, each re-enters the screen, and the next fit is corrupted by the last.

    Termination is the coupling's: the walk ends when nothing absorbs above the frame's own noise
    floor — `next_by_coupling` returning None, "the signal has finished its path" — and then the
    forecast is asked, once, for the same screen. There is no step cap, and a vertex fires at most
    once, so the walk is finite without one."""
    placed = _j.place(ro, collection, prefix)
    if not placed:
        return {"prefix": prefix, "placed": [], "steps": [
            {"stopped": "nothing in this reading places any part of that"}],
            "completion": "", "coverage": 0.0}

    # The screen holds every vertex covering the signal, not one tiling of it. `place` returns the
    # longest cover, so a prefix collapses to only a few junctions — too few rows for the instrument
    # to carry a read. Descending each placed vertex through its colimit puts its shorter members
    # on the screen alongside the longer covers, which is the same overlap the reader builds.
    def _members(v, seen):
        if v in seen:
            return set()
        seen = seen | {v}
        out = {v}
        for d, pr in ro.execute(
                "SELECT dst, props FROM edge WHERE src = ? "
                "AND label IN ('observed','observed_alone')", (v,)):
            if '"bits_saved"' in (pr or ""):
                out |= _members(d, seen)
        return out

    # The frontier is right-anchored, and the `at` ordinal is how it is found. The screen holds
    # every covering vertex, but only the ones whose span ends where the signal ends can lead a
    # continuation — expanding a placed vertex through its colimit also puts its earlier members on
    # the screen, and drawing candidates from an earlier member's successors would continue a
    # position the text never stopped at. Descending only the last member at each level walks the
    # right edge, and which member is last is read off the edge the reader wrote, never off the
    # surfaces.
    def _right(v, seen):
        """The right edge of a vertex: itself, then the member it ends with, in descent order —
        longest first, so the caller can honour the most context available.

        Memoised, and the props are string-tested before they are parsed. Neither was true and this
        was HALF the cost of a reply: 2.5 million `json.loads` calls in one completion, because
        every edge out of every vertex on the spine was decoded in full to read one key, and the
        shared lower rungs of the ladder were re-walked once per path into them. Exactly the defect
        already fixed in `outgest`, left in place here."""
        got = _SPINE.get(v)
        if got is not None:
            return got
        if v in seen:
            return [v]
        seen = seen | {v}
        out, last, best = [v], None, -1
        for d, pr in ro.execute(
                "SELECT dst, props FROM edge WHERE src = ? "
                "AND label IN ('observed','observed_alone')", (v,)):
            if not pr or '"bits_saved"' not in pr or '"at"' not in pr:
                continue
            try:
                q = __import__("json").loads(pr) or {}
            except Exception:
                continue
            if q.get("bits_saved") is None or q.get("at") is None:
                continue
            if int(q["at"]) > best:
                best, last = int(q["at"]), d
        if last is not None:
            out.extend(_right(last, seen))
        _SPINE[v] = out
        return out

    held = [_members(_j.unit_id(collection, t), set()) for t in placed]
    lead_set = _right(_j.unit_id(collection, placed[-1]), set())
    steps = []
    for i in range(len(held)):
        steps.append({v for a in held[:i + 1] for v in a})

    # Fire-at-most-once is a routing rule and this walk is not routing. `next_by_coupling` guards a
    # Cascade so a tekton fires at most once, because coupling is idempotent and revisiting absorbs
    # nothing; termination there is derived from it. In generation `' '` is a vertex that recurs in
    # every sentence, as does every common word, and a walk that cannot emit a space twice welds
    # words together and repeats names: 'Bennet Bennet was likelyto that decidedopinion,'.
    #
    # Repetition is therefore allowed and the cycle is what stops it. A walk that returns to a state
    # it has already been in — same frontier, same screen — repeats that transition forever, which
    # is a fact about the path rather than a step count. `seen_state` records where it has been, and
    # the coupling floor still ends the walk first whenever the signal dies.
    said, out_steps = walk(ro, collection, placed, lambda v: _right(v, set()),
                           carried=carried)
    # What this turn put on the screen, for the next one to be asked against.
    on_screen = [_j.unit_id(collection, tok) for tok in placed]
    on_screen += [s["vertex_id"] for s in out_steps if s.get("vertex_id")]
    fired = set()

    # Deduction is spent. The reading has not walked past here, so the forecast is what is left —
    # the dynamical operator, read off the path the prefix traced and rolled to its OWN horizon, and
    # handed back to the ontology by `recognise_states` so the answer is still the reading's own
    # vertices. It runs once, on the screen deduction stopped at, and is reported as `forecast`.
    #
    # It is asked only when nothing was deduced at all: a completion that ran and then finished has
    # said what the reading holds, and appending a forecast to it would let the weaker act extend an
    # answer the caller was told came from context. Its refusal, when it refuses, is carried out in
    # `stopped` rather than swallowed — a completion that could not continue must say why.
    if not said:
        # The forecast is the only part of this walk that needs a COORDINATE, and the coordinate is
        # the `projection` seam's. Deduction touches none — that is why it is derived here and not
        # up front, and why a host that fills `optics` but not `projection` loses the forecast and
        # keeps the deduction rather than failing the whole completion. `HostSeamUnfilled` subclasses
        # `ImportError` precisely so a call site can keep its refusal on exactly this input.
        # The forecast needs a coordinate over the WHOLE reading, and on a corpus this size that is
        # not a frame anyone can hold: measured on `read:fix`, `Reading.coord` asks for a
        # 97,997 x 52,275 matrix — 38.2 GiB — and numpy refuses it. The refusal is carried out as
        # the reason rather than raised, because it is a real state: this reading is too large for
        # the global-frame arm, while deduction, which needs no coordinate, works on it fine.
        # It does not manufacture the coordinate. Deriving `Reading.coord` here asks for a frame
        # over the whole reading — on `read:fix`, 97,997 x 52,275, which numpy refuses outright at
        # 38.2 GiB and which hangs while assembling even before that. Deduction
        # needs no coordinate and works on this reading; the forecast needs one and cannot have it.
        # So the forecast runs only when a coordinate was HANDED IN, and otherwise says why it did
        # not run. That is a property of the reading, not a size anyone chose.
        try:
            rd = reading
            if rd is None:
                raise ImportError("the forecast needs a coordinate over the whole reading, and "
                                  "none was supplied — deduction needs none and ran")
            states, read = predict(ro, rd, placed)
            found = recognise_states(ro, rd, states, exclude=fired)
        except ImportError as unfilled:
            states, read, found = [], {"refusal": str(unfilled)}, []
        except MemoryError:
            states, read, found = [], {"refusal": "the forecast needs a coordinate over the whole "
                                                  "reading, and this one is too large to hold"}, []
        for name, energy in found:
            said.append(outgest(ro, collection, name))
            out_steps.append({"vertex": _j.surface(name), "energy": round(float(energy), 4),
                              "hole": "content", "act": "forecast", "horizon": read.get("horizon"),
                              "screen": len(placed)})
            fired.add(name)
        if not said and read.get("refusal"):
            out_steps.append({"stopped": read["refusal"]})

    return {"prefix": prefix, "placed": placed, "steps": out_steps, "on_screen": on_screen,
            "completion": "".join(said),
            "coverage": round(sum(len(x) for x in placed) / max(len(prefix), 1), 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("collection")
    ap.add_argument("prefix", nargs="+")
    args = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    try:
        out = complete(ro, args.collection, " ".join(args.prefix))
        print("placed     %s" % (out["placed"],))
        print("coverage   %.2f" % (out["coverage"] or 0.0))
        for s in out["steps"]:
            print("   %s" % s)
        print("\n%s" % (out["completion"] or "(nothing)"))
    finally:
        ro.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
