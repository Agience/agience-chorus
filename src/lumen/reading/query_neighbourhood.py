"""Completion through a neighbourhood around the query, never over the ontology.

    python -c "import ember"                      # the host binds the seams first
    python -m lumen.reading.query_neighbourhood "Darcy" "with a"

The neighbourhood is a neighbourhood of the query, reached by indexed lookups only:

    query text  -> the units the reading formed that occur in it        (indexed: id lookup)
    those units -> the contexts that hold them                          (indexed: edge by dst)
    those contexts -> the units they hold                               (indexed: edge by src)

Nothing else is touched. The frame is bounded by what the query reaches, so cost is set by the
question rather than by the size of what has been read — observation follows demand
([[operator-is-observation]]). A corpus ten times larger costs the same for the same question.

The bound is reported: how many contexts and units the reach pulled is printed, so a neighbourhood
that swallows the corpus is visible rather than inferred from a stopwatch.
"""
import collections
import json
import os
import sqlite3
import sys
import time

import numpy as np

# One neighbourhood, reached by name. `from ember import optics` is what
# `test_only_the_instrument_seam_imports_entroptics` forbids from chorus, and the seam is how a persona asks
# for a measurement the runner performs. `import ember` (which binds the seams) is the host's act,
# not this module's.
from _host_seams import seam as _seam

_optics = None


def optics():
    """The neighbourhood, resolved on first use so importing this module binds nothing."""
    global _optics
    if _optics is None:
        _optics = _seam("optics")
    return _optics


def _db() -> str:
    """Where the reading lives — resolved from the environment, never assumed.

    A host that had opened one shard and got answers from another would see nothing in the
    response to say so, so the store names its own location and this function reads that name
    rather than hardcoding a path."""
    # The shard is a data volume, not part of the checkout, so no default here could be right
    # on another box. Unset is REFUSED rather than guessed: a reader silently opening a store
    # nobody chose does not fail, it reports an empty corpus — which reads as "nothing found"
    # when the truth is "nothing configured".
    root = (os.environ.get("EMBER_SQLITE_DIR") or "").strip()
    if not root:
        raise RuntimeError(
            "EMBER_SQLITE_DIR is unset. Point it at the directory holding lattice.db.")
    return os.path.join(root, os.environ.get("EMBER_SQLITE_DB", "lattice.db"))


# Resolved once at import so every read here reaches the same store, and so a test can point
# the module at a fixture by overriding this one name. Importing must NOT require a configured
# box — the refusal belongs where a read is attempted, not where the module is loaded — so
# this is empty when the environment names no store, and `_db()` is what states the problem.
DB = _db() if (os.environ.get("EMBER_SQLITE_DIR") or "").strip() else ""
C = os.environ.get("READ_COLLECTION", "read:overlap")


def surface(node):
    u = node[len(C) + 1:] if node.startswith(C + ":") else node
    if u.startswith("span:"):
        try:
            return bytes.fromhex(u[5:]).decode("utf-8")
        except Exception:
            return u
    if u and all(p.startswith("u") and len(p) == 5 for p in u.split("+")):
        try:
            return "".join(chr(int(p[1:], 16)) for p in u.split("+"))
        except ValueError:
            return u
    return u


def unit_id(span):
    return "%s:span:%s" % (C, span.encode("utf-8").hex())


def reach(ro, query):
    """The query's neighbourhood: its units, the contexts holding them, and those contexts' units."""
    # 1. which units of this query does the reading actually hold? An indexed existence check per
    #    candidate substring — never a scan of the lexicon. Advances past a match by its full length
    #    rather than by one character, so a matched span seeds once rather than once per suffix.
    seeds = seed_spans(ro, query)
    if not seeds:
        return None
    seed_ids = [unit_id(s) for s in seeds]
    return _reach_from(ro, seeds, seed_ids)


def seed_spans(ro, query):
    """The units of `query` the reading actually holds, longest-first, advancing by match length.

    Factored out of `reach` because the recognition null runs the IDENTICAL path on random strings:
    a control that seeded differently would measure the difference between two seeding rules rather
    than between a recognised string and an unrecognised one."""
    seeds = []
    n, i = len(query), 0
    while i < n:
        for j in range(n, i, -1):
            # A unit that sits in no context may not seed: existence in `vertex` is not enough,
            # since single characters are maximal repeats too and a span the decomposition never
            # used as a part has no context at all. The neighbourhood must have somewhere to stand
            # ([[grounds-out-not-refusal]]). A unit held only by an `observed_alone` edge is still
            # held by a context, so both labels count here.
            if ro.execute("SELECT 1 FROM edge WHERE dst = ? AND "
                          "label IN ('observed','observed_alone') LIMIT 1",
                          (unit_id(query[i:j]),)).fetchone():
                seeds.append(query[i:j])
                i = j
                break
        else:
            i += 1
    return seeds


def _reach_from(ro, seeds, seed_ids):
    # 2. the contexts that hold them — indexed on dst.
    #
    # The neighbourhood is the INTERSECTION: contexts that observed every seed, not the union of one
    # seed's. A context holding both `jazz` and `improvisation` is far more specific than one
    # holding either, and a conjunctive query deserves a conjunctive neighbourhood.
    #
    # Opening on the rarest seed alone discards the rest of the query. That is invisible on a
    # one-word query (one seed, so the two rules agree) and wrong on a phrase: measured, `jazz
    # improvisation` routed to geography, `volcanic eruption` to science — 3 of 5 phrases to the
    # wrong partition. The union of all seeds fixes nothing and breaks the control: nonsense
    # coupling goes 0% -> 29%, because a wider neighbourhood gives a meaningless string more contexts in
    # which to find one that happens to absorb it.
    #
    # The intersection can only be NARROWER than any single seed's set, so it cannot widen into
    # that blind spot. Measured on the same corpus and probes:
    #
    #   rarest seed   singles relevance 84.8%  phrases relevance 50.0%  nonsense 7.9%
    #   INTERSECTION  singles relevance 84.8%  phrases relevance 75.0%  nonsense 7.9%
    #
    # Backoff, when nothing observed every seed: drop the highest-degree seed — the least
    # informative — and intersect again, down to a single seed. Rarity is the measured degree, the
    # same discriminator that orders the seeds and weights the coupling.
    posting = {}
    for sid in seed_ids:
        srcs = [r[0] for r in ro.execute(
            "SELECT src FROM edge WHERE dst = ? AND label IN ('observed','observed_alone')",
            (sid,)).fetchall()]
        if srcs:
            posting[sid] = set(srcs)
    if not posting:
        return None
    live = sorted(posting, key=lambda k: len(posting[k]))      # rarest first
    inter = set.intersection(*(posting[k] for k in live))
    while not inter and len(live) > 1:
        live.pop()                                             # the most common seed goes first
        inter = set.intersection(*(posting[k] for k in live))
    if not inter:
        return None
    ctx = sorted(inter)

    # 3. what those contexts hold — indexed on src. This is the neighbourhood's extent so far.
    held = {}
    for o in ctx:
        held[o] = [d for (d,) in ro.execute(
            "SELECT dst FROM edge WHERE src = ? AND label IN ('observed','observed_alone')",
            (o,))]
    units = sorted({u for us in held.values() for u in us})
    return seeds, seed_ids, ctx, held, units


def recognition(ro, query, *, draws: int = 20, seed: int = 0):
    """Is this string IN what was read — measured against the same characters carrying no meaning.

    Separate from coupling, and much stronger. Coupling asks whether a neighbourhood absorbs the
    query specifically; recognition asks the prior question, "is this in what I read", and the
    decomposition already answers it: a unit exists exactly when a string occurred repeatedly, so a
    string the reading never saw can only be recognised as the short fragments every text contains.

    The null is a permutation of the query's own characters — same letters, same length, same
    character distribution, meaning destroyed. That is this codebase's null everywhere else, and it
    is what makes the control matched: a null drawn from the reading's alphabet instead compares a
    word against strings containing newlines and punctuation, which cannot form units for reasons
    that have nothing to do with meaning (measured: 22% false positives that way, 2% this way).

    Measured on 4 Wikipedia partitions (1.05M chars, 100 cross-partition probes / 100 matched
    nonsense), longest-seed against 20 permutations:

        recognition   REAL 81.0%   NONSENSE 2.0%
        coupling      REAL 33.3%   NONSENSE 11.7%      (the same probes, the same collection)

    `draws` is a resource envelope. The bar is the null's own extent — above every draw — so there
    is no threshold and no alpha.
    """
    import numpy as _np
    seeds = seed_spans(ro, query)
    longest = max((len(x) for x in seeds), default=0)
    rng = _np.random.default_rng(seed)
    chars, best_null = list(query), 0
    for _ in range(int(draws)):
        rng.shuffle(chars)
        best_null = max(best_null, max((len(x) for x in seed_spans(ro, "".join(chars))), default=0))
    return {"seeds": len(seeds), "longest": longest, "longest_null": best_null,
            "mean_len": (float(_np.mean([len(x) for x in seeds])) if seeds else 0.0),
            "recognised": bool(longest > best_null)}


def query_vector(seeds, idx, coord, dim):
    """The query as a point in the neighbourhood's coordinate — and which seeds it could not use.

    Sums `coord[idx[unit_id(s)]]` only over seeds the neighbourhood's neighbourhood actually holds,
    since the neighbourhood opens on the rarest seed's contexts and a seed held by no context in that
    neighbourhood has no coordinate to sum.

    Returns `(qv, used, unseen)`. `unseen` is measured against the collection's index, so it means
    "this seed is not in the reading's coordinate at all" — NOT "held by no context in this
    neighbourhood". The distinction matters: it is a statement about the reading, not about how far
    the neighbourhood happened to open, and widening the neighbourhood whenever `unseen` is
    non-empty would be widening for a reason that has nothing to do with the neighbourhood.

    A seed with no coordinate is neither an error nor a zero: it is dropped and named.
    """
    qv = np.zeros(dim)
    used, unseen = [], []
    for s in seeds:
        k = idx.get(unit_id(s))
        if k is None:
            unseen.append(s)
        else:
            used.append(s)
            qv += coord[k]
    return qv, used, unseen


def widen(ro, ctx, held):
    """One more hop, taken through the rarest units first. Not called by `answers`.

    The reading's coordinate is derived once from the whole collection, so a query does not have to
    widen its way to a frame that resolves. The hop rule is kept here for a caller that wants it.

    Measured as a way to give the coupling test more to rank over, widening is worse
    on every axis (1.05M-char corpus, 24 cross-partition probes + 24 matched nonsense):

        rarest seed only   median 2 contexts   coupling 54.2% real / 0.0% nonsense   relevance 95.8%
        all seeds          median 4 contexts   coupling 58.3% real / 29.2% nonsense  relevance 87.5%

    Real coupling barely moves while false positives go from nothing to a third: a wider neighbourhood
    gives a meaningless string more contexts in which to find one that happens to absorb it, so the
    null stops being a null. The narrowness is what makes the control valid. Cost is 27x, and the
    p90 neighbourhood goes from 5 contexts to 511 — essentially all of it arriving with the second seed.

    The neighbourhood grows until it can see, and "can see" is the neighbourhood's own answer — whether
    `principal_directions` resolves anything — never a row count anyone chose.

    Expanding through every unit in the frontier at once would overshoot: a common unit sits in
    many contexts, and one hop through it reaches most of the corpus — the same hub problem that
    a full-rank basis would let absorb everything. So the hop goes through the rarest units first,
    and rarity is measured — how many contexts hold the unit — not assigned. A rare unit is both
    more informative about this query and cheaper to follow. This is an order, not a threshold:
    units are taken rarest-first and the walk stops as soon as the frame resolves, so nothing is
    excluded, it is simply reached later or not at all.
    """
    seen = set(ctx)
    frontier = {u for us in held.values() for u in us}
    deg = []
    for uid in frontier:
        # Degree is measured on the unbounded result — see `reach`, which measures rarity the
        # same way and for the same reason: a capped count flattens every hub onto one value and
        # the order stops being an order exactly where it matters most.
        rows = ro.execute(
            "SELECT src FROM edge WHERE dst = ? AND label IN ('observed','observed_alone')",
            (uid,)).fetchall()
        deg.append((len(rows), uid, [r[0] for r in rows]))
    deg.sort()                                   # rarest first — measured degree, ascending
    added = []
    for _d, _uid, srcs in deg:
        for src in srcs:
            if src not in seen:
                seen.add(src); added.append(src)
        if added:
            break                                # one rarity-tier at a time, then re-test the read
    for o in added:
        held[o] = [d for (d,) in ro.execute(
            "SELECT dst FROM edge WHERE src = ? AND label IN ('observed','observed_alone')",
            (o,))]
    ctx = list(ctx) + added
    units = sorted({u for us in held.values() for u in us})
    return ctx, held, units, len(added)


def answers(ro, queries, say=lambda *a: None, null_draws=32):
    """Each query, answered — the one pipeline. `say` prints; callers that only want the answer
    pass nothing. `null_draws` is the resource envelope for the grounding null (see `grounded`) —
    a legitimate external input; there is no threshold beside it. `main()` prints what this yields, so the responder and the CLI cannot drift
    apart: this is the single path from a query to an answer, run standalone or from the bff.

    The answer is the evidence, not a sentence: what comes back is the spans that couple to the
    query, their weight, their distance in characters from the query term in the citing paragraph,
    and the paragraphs themselves. Composing prose over that would be generation rather than
    completion. The work is the answer.

    `grounded` is not "an answer was returned". It is false on every path below that yields no
    answer, and each one names a different reason the neighbourhood had nowhere to stand
    ([[grounds-out-not-refusal]]). A caller that only checks for a non-empty answer would read an
    ungrounded result as a result."""
    # The reading's basis, derived once. It is a property of what was read, not of any one question, so
    # deriving it per query would be both slower and — worse — a different coordinate per question,
    # which cannot be compared across answers ([[two-frames-at-different-k-must-not-couple]]).
    _proj = _seam("projection")
    _M, _names, _contexts = _proj.read_cloud(ro, C)
    _B = optics().principal_directions(_M) if _M is not None else None
    if _B is not None and (_B.ndim != 2 or _B.shape[1] < 1):
        _B = None
    _coord = (_M @ _B) if _B is not None else None
    _idx = {u: i for i, u in enumerate(_names)}
    # Units grouped by surface length, built once with the basis. The grounding null draws from
    # these so a draw can be MATCHED to the query's own seed lengths — see the null below.
    _by_len = {}
    for _u, _i in _idx.items():
        _by_len.setdefault(len(surface(_u)), []).append(_i)
    _lens = sorted(_by_len)
    if _B is not None:
        say("   basis      %d mode(s) over %d unit(s) x %d context(s)  <- the READING's coordinate"
            % (_B.shape[1], len(_names), len(_contexts)))

    # A collection with no `observed` edge to stand on cannot ground ANY query, and the per-query
    # refusal below would report that as a fact about the question ("no unit of this query was
    # formed by the reading") when it is a fact about the collection. Same rule as the instrument
    # slots: a capacity fact must never be published as a measurement. Checked once, by one indexed
    # lookup, not per query.
    _any = ro.execute("SELECT 1 FROM edge WHERE label IN ('observed','observed_alone') "
                      "AND dst LIKE ? LIMIT 1", (C + ":span:%",)).fetchone()
    if not _any:
        why = ("the collection %r holds no observed edge — nothing has been read into it, so the "
               "neighbourhood has nowhere to stand for ANY query. This is a statement about the "
               "collection, not about the question (set READ_COLLECTION to a collection that has "
               "been read)." % C)
        say("   (nothing) %s" % why)
        for q in queries:
            yield {"query": q, "answer": None, "cited": [], "grounded": False, "why": why}
        return

    for q in queries:
        ts = time.perf_counter()
        out = {"query": q, "answer": None, "cited": [], "grounded": False, "why": None}
        got = reach(ro, q)
        say("")
        say("Q %r" % q)
        if got is None:
            out["why"] = ("no unit of this query was formed by the reading, or it sits in no "
                          "context — the neighbourhood has nowhere to stand")
            say("   (nothing) %s" % out["why"])
            yield out
            continue
        seeds, seed_ids, ctx, held, units = got
        # How much of the query was recognised is part of the answer. A single character is a
        # legitimate artifact here, so excluding short seeds would be a rule about what may count;
        # instead the coverage is stated (characters recognised over query length). Thin grounding
        # stays visible rather than being dressed up as an answer ([[false-grounding-on-fragments]]).
        cov = sum(len(x) for x in seeds) / max(len(q), 1)
        say("   recognised %s   coverage %d/%d chars = %.2f"
              % (seeds, sum(len(x) for x in seeds), len(q), cov))
        say("   neighbourhood   %d context(s), %d unit(s)   <- what the QUERY reached, not the corpus"
              % (len(ctx), len(units)))

        # The coupling runs in the collection's own basis, derived from everything that was read
        # rather than from what one query reached: contexts x sqrt(bits) through
        # `projection.read_cloud`. A per-query co-presence matrix built only from what the query
        # reached would resolve too few modes to be more than nominally full rank, absorbing
        # everything handed to it regardless of query, which discriminates nothing. The basis is a
        # property of the reading, so it is computed once for all queries here, and the frame a
        # query couples in already resolves without widening.
        idx = _idx
        coord = _coord
        B = _B
        if B is None:
            out["why"] = ("the reading's own coordinate resolved no mode above the neighbourhood's "
                          "floor, so there is no basis to couple in")
            say("   %s (%.1fs)" % (out["why"], time.perf_counter() - ts))
            yield out
            continue
        units = [u for u in units if u in idx]
        held = {o: [u for u in us if u in idx] for o, us in held.items()}
        say("   modes      %d" % B.shape[1])

        # couple the query against each context's resolved band — the neighbourhood's own read
        bases = {}
        for o in ctx:
            if not held[o]:
                continue
            M = np.stack([coord[idx[u]] for u in held[o]])
            Bo = optics().principal_directions(M)
            if Bo is not None and Bo.shape[1] > 0:
                bases[o] = Bo
        # `query_vector` sums over the seeds that have a coordinate in the reading, and names the
        # rest. `unseen` is measured against the COLLECTION's index, so it means "not in the
        # reading" rather than "outside this neighbourhood" — see `query_vector`. A partially-seen
        # question cannot look like a fully-seen one either way.
        qv, used, unseen = query_vector(seeds, idx, coord, B.shape[1])
        if unseen:
            # ASCII on the output path: this line runs under consoles whose encoding cannot
            # represent arbitrary glyphs, and it is the one line that reports a partially-seen
            # query, so it must not itself be able to fail to print.
            say("   (!) outside    %s -- not in this collection's coordinate, so they do not seed"
                % unseen)
        if not used or not np.any(qv):
            out["why"] = "none of this query's units are visible from the neighbourhood it opened"
            say("   (nothing) %s" % out["why"])
            yield out
            continue
        rows = np.vstack([qv, qv])

        # The incident energy, so what each element absorbed is reported as the scale-free fraction
        # rather than a raw magnitude. Absorbed energy scales with the magnitude of the query
        # vector, so a raw weight ranks a high-energy draw above a specific low-energy question no
        # matter how relevant it is — measured, ||qv||^2 of 1.4 for `enzyme` against 14962 for
        # `qzlkvn`, whose seeds are common single characters with dense coordinates. Dividing by
        # the incident makes every weight the `A^2` of the same `A^2 + T^2 = 1` split the rest of
        # the module reads with, and comparable between queries.
        _incident = float((np.abs(rows) ** 2).sum()) or 1.0
        attended, residual, fired = [], rows, []
        while True:
            hop = optics().next_by_coupling(residual, bases, fired=tuple(fired))
            if not hop or hop.get("tekton") is None:
                break
            nm = hop["tekton"]
            fired.append(nm)
            attended.append((nm, float(hop.get("absorbed_energy") or 0.0) / _incident))
            residual = np.asarray(hop.get("transmitted"), float)
            if not np.any(residual):
                break
        if not attended:
            out["why"] = "nothing couples in this neighbourhood"
            say("   %s (%.1fs)" % (out["why"], time.perf_counter() - ts))
            yield out
            continue

        # Summing the coupling over every context holding a unit would rank units by how many
        # attended contexts hold them — degree, not relevance — and a unit present in every
        # attended context discriminates nothing, since it is true of all of them and says nothing
        # about which one was attended. The coupling is therefore carried in proportion to how rare
        # the unit is across the collection, which is the same measured degree that chooses the
        # seeds and orders the widening hop. One discriminator, three places. Nothing is excluded;
        # a common unit is still present, just quieter.
        #
        # The degrees are fetched for the neighbourhood's units in a single indexed read, one query
        # rather than one per unit, and counted in Python rather than with `count(*)`
        # ([[count-star-dereferences-every-record]]).
        _want = {u for nm, _w in attended for u in held.get(nm, ()) if u not in seed_ids}
        _deg = collections.Counter()
        _w = sorted(_want)
        for i in range(0, len(_w), 400):
            chunk = _w[i:i + 400]
            # Named `_sql`, not `q`: `q` is the caller's query and is read below for `coverage`.
            # Shadowing it here divides the recognised-character count by the length of this SQL
            # string instead of the query's.
            _sql = ("SELECT dst FROM edge WHERE label IN ('observed','observed_alone') "
                    "AND dst IN (%s)" % ",".join("?" * len(chunk)))
            for (d,) in ro.execute(_sql, chunk):
                _deg[d] += 1

        # A unit's own share of what its context absorbed breaks the tie that `absorbed_energy`
        # alone would leave: `absorbed_energy` is a property of the context, so it weights every
        # unit in it equally on its own. The neighbourhood also publishes the context's resolved band —
        # `bases[nm]` — and how much of a unit lies in that band is a per-unit measurement: the
        # projection of its coordinate onto the band.
        #
        # This is not similarity to the query — ranking by closeness to the question would be
        # retrieval wearing completion's clothes. What is measured is how much each unit contributes
        # to the coupling that made this context attend at all.
        nxt = collections.Counter()
        for nm, w in attended:
            Bo = bases.get(nm)
            # One call to the instrument per context: the whole context's units go through
            # `absorb_transmit` as a single frame, and each row's absorbed energy is its share of
            # the band. `sqrt` because the share is an amplitude and `‖row‖²` is the energy.
            _share = {}
            _us = [u for u in held.get(nm, ()) if u in idx]
            if Bo is not None and _us:
                _res = optics().absorb_transmit(np.stack([coord[idx[u]] for u in _us]), basis=Bo)
                if _res is not None:
                    _ab = _res[0]
                    _e = (np.abs(_ab) ** 2).sum(axis=1)
                    _share = {u: float(np.sqrt(_e[j])) for j, u in enumerate(_us)}
            for u in held.get(nm, ()):
                if u in seed_ids:
                    continue
                n = _deg.get(u, 0)
                if not n:
                    continue
                # `absorb_transmit(frame, basis=Bo)` is the projection onto the band and carries
                # the conservation a hand-rolled norm would drop. Computed once per context above,
                # not per unit — calling the instrument in an inner loop is a cost regression.
                share = _share.get(u, 1.0)
                nxt[u] += (w / n) * share
        # Co-presence is not predication, and the answer must say which it is: a span that shares
        # a paragraph with the query term can describe a different subject in that same paragraph.
        # The distance in characters from the query term does not weight the coupling —
        # deciding that "about" means "near" is a modelling choice, and a paragraph is a coherent
        # unit — it is reported instead, so a span that is merely co-present cannot be read as a
        # predication without the reader seeing the gap.
        _seed_txt = seeds[0] if seeds else ""
        _near = {}
        _bodies = {}
        for nm, _w in attended:
            row = ro.execute("SELECT doc FROM vertex WHERE id = ?", (nm,)).fetchone()
            try:
                body = (json.loads(row[0]) or {}).get("content") or "" if row else ""
            except Exception:
                body = ""
            _bodies[nm] = body                    # kept: this IS the prose (see `out["answer"]`)
            qi = body.find(_seed_txt)
            if qi < 0:
                continue
            for u in held.get(nm, ()):
                si = body.find(surface(u))
                if si >= 0:
                    d = abs(si - qi)
                    if u not in _near or d < _near[u]:
                        _near[u] = d
        top = [(surface(u), round(v, 6), _near.get(u)) for u, v in nxt.most_common(8)]

        # The answer is prose, and every word of it is the book's: what is generated is the
        # selection and the order — which passages, in which sequence — and that is measured, since
        # the contexts are ordered by the energy each absorbed from the query's band, which is the
        # coupling that made them attend at all. Nothing is composed, sampled, or templated: emitting
        # the corpus's own contiguous passages is layout, not language — the words carry exactly the
        # authority of the source, and the citation beside each one is checkable.
        #
        # The evidence rides along rather than replacing the prose: `spans` keeps the maximal
        # repeats and their character distance from the query, because prose that reads well can
        # hide a span sitting far from the thing asked about — co-presence is not predication. Both
        # are in the response; neither is the other's summary.
        _passages = [{"text": _bodies.get(nm, ""), "cited": nm, "absorbed_energy": round(w, 4)}
                     for nm, w in attended if _bodies.get(nm)]   # w is a fraction of incident
        out["answer"] = "\n\n".join(p["text"] for p in _passages)
        out["passages"] = _passages
        out["spans"] = [{"span": s, "weight": w, "chars_from_query": d} for s, w, d in top]
        out["cited"] = [a for a, _ in attended]
        out["recognised"] = seeds
        # Coverage is part of the answer, not a diagnostic: a single character is a legitimate
        # artifact here, so an answer that recognised a fraction of the query and one that
        # recognised all of it must not look alike to the caller.
        out["coverage"] = round(sum(len(x) for x in seeds) / max(len(q), 1), 3)

        # `grounded` means "this query is in what I read", not merely "spans were produced" — a
        # query with no relation to the reading can still couple to common fragments and come back
        # with spans, so groundedness is measured against a matched permutation null rather than
        # inferred from a non-empty answer. The query's own coupling is compared against the same
        # construction over units drawn at random from this neighbourhood — same number of seeds, same
        # summation, same bases, same instrument. Nonsense grounds on common fragments, so its
        # coupling is what a random draw already achieves; a real question couples above every draw.
        #
        # There is no alpha: the bar is "strictly above every draw of the null", which is the null's
        # own extent rather than a level anyone chose — the same shape as `z < 0` and `PMI > 0`
        # elsewhere in this work. The draw count is a resource envelope, which is a legitimate
        # external input; the threshold is not, and there isn't one.
        #
        # The null compares the fraction absorbed, not the absorbed energy itself: absorbed energy
        # scales with the magnitude of the query vector, so a random draw that happens to pull
        # high-energy units would out-couple a specific low-energy question no matter how relevant
        # it is. The scale-free quantity is the fraction absorbed: `‖incident‖² = ‖absorbed‖² +
        # ‖residual‖²` exactly, so `absorbed/incident` is the `A²` of the same `A² + T² = 1` split
        # the organon reads every token with — how much of what the query brought did this
        # neighbourhood take, not how much it brought.
        #
        # The null is fixed to one band rather than letting the null draw run through
        # `next_by_coupling` too: if both sides were free to pick whichever context absorbed most,
        # the comparison would be max-over-bands against max-over-bands, which measures which band is
        # biggest twice and says nothing about the query. The matched null holds the band and varies
        # the content: how much of itself does this query give to the band it attended, against how
        # much a random draw gives to the same band. One thing varies, which is what makes it a
        # control.
        _band = bases.get(attended[0][0]) if attended else None

        def _fraction(vec, basis):
            _inc = float((np.abs(vec) ** 2).sum()) * 2.0     # the frame is the vector, stacked twice
            if _inc <= 0.0 or basis is None:
                return 0.0
            _r = optics().absorb_transmit(np.vstack([vec, vec]), basis=basis)
            if _r is None:
                return 0.0
            return float((np.abs(_r[0]) ** 2).sum()) / _inc

        _rng = np.random.default_rng(0)
        _real = _fraction(qv, _band)
        _null_best = 0.0

        # The draw is matched to the query's own seed lengths, because seed length is the thing that
        # separates a recognised word from an unrecognised string. `Elizabeth` is recognised as one
        # nine-character unit; `vrskw` shatters into ['v','rs','k','w']. Drawing units of any length
        # would compare four single characters against four arbitrary units — many of them long and
        # specific — and nonsense would clear the bar and ground. Holding the length profile fixed
        # leaves exactly one thing varying: whether these particular units couple here, which is the
        # question. A length with no units falls back to the nearest one that has them, so the draw
        # is always the same shape as the query.
        def _match(L):
            if L in _by_len:
                return _by_len[L]
            return _by_len[min(_lens, key=lambda x: abs(x - L))]

        _seed_lens = [len(x) for x in used] or [1]
        for _ in range(int(null_draws)):
            _pick = [int(_rng.choice(_match(L))) for L in _seed_lens]
            _nqv = coord[_pick].sum(axis=0)
            if np.any(_nqv):
                _null_best = max(_null_best, _fraction(_nqv, _band))
        # Two distinct readings, reported separately because they answer different questions:
        # recognition is "is this in what I read" (measured 79% real / 0% nonsense), coupling is
        # "does this neighbourhood absorb it specifically" (33% / 12% on the same probes).
        _rec = recognition(ro, q)
        out["recognition"] = _rec
        out["recognised_above_null"] = _rec["recognised"]
        out["grounded"] = bool(_real > _null_best)
        out["absorbed_fraction"] = round(_real, 4)
        out["absorbed_fraction_null"] = round(_null_best, 4)
        if not out["grounded"]:
            # A refusal with its reason and its numbers — never a sentence about being unable to help.
            out["why"] = ("this query couples %.1f%% of what it brought, and %d random draw(s) "
                          "from the same neighbourhood already reach %.1f%% — so what came back is what "
                          "ANY text reaches here, not what this text asked"
                          % (100.0 * _real, int(null_draws), 100.0 * _null_best))
        out["seconds"] = round(time.perf_counter() - ts, 2)
        say("   next ->    %s" % top)
        say("   attended   %d context(s), strongest %s   (%.1fs)"
            % (len(attended), attended[0][0].split(":")[-1], time.perf_counter() - ts))
        yield out


def respond(query):
    """The carrier contract aria's bff calls: `respond(q) -> dict | None`.

    This module exports; it does not serve. `lumen` may not import `aria` — enforced by
    `test_persona_isolation.py::test_no_persona_SOURCE_imports_another_persona`. The host hangs
    this on the bff in `chorus/personas.py::_wire_conversation_carrier`; the direction of the
    import is the whole point."""
    # Resolved per call, not at import. The host binds its store while loading personas, which can
    # happen after this module is imported; a path captured at import time would answer from
    # whichever store the environment pointed to first, silently.
    ro = sqlite3.connect("file:%s?mode=ro" % _db(), uri=True)
    try:
        for out in answers(ro, [query or ""]):
            return out
    finally:
        ro.close()
    return None


def main():
    t0 = time.perf_counter()
    ro = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    for _ in answers(ro, sys.argv[1:] or ["Darcy", "love", "zzqx"], say=print):
        pass
    print("")
    print("TOTAL %.1fs" % (time.perf_counter() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
