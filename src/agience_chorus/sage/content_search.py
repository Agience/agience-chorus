"""Content retrieval over the lattice corpus — surfaces real article text for topic queries.

The dictionary arm answers `define <word>` from WordNet; this arm answers *topic* questions ("who
was Ada Lovelace", "the French Revolution") from the 6.11M Wikipedia articles, returning their real
text (`content.resolve_text` reads the per-collection-keyed `FileContentCache`).

The information defines itself: no stop-word list, no question-word list, no score cutoff — those
would be injected bias. FTS5's BM25 already weighs every term by its inverse document frequency,
which is the corpus's own measure of how much information a word carries: "the", "who", "is" occur in
millions of documents and so contribute almost nothing to the rank, while "lovelace" occurs in a
handful and dominates it. Every token is handed to the index as-is and the corpus decides which ones
matter. Terms are OR-ed (not the default implicit-AND) so a phrasing that no single document satisfies
in full still ranks by how much of it each document carries.

The synthesized concept stubs (`x-concept`) are the one exclusion — not by content, but by type: they
hold no real text, so they are never a content answer.
"""
from __future__ import annotations

import math
import re
from typing import List, Sequence, Tuple, Any, Dict, Optional

from agience_chorus.sage.answer_shape import Answer          # sage-local; ember.runtime.engine exports no Answer type
from mantle.shard.content import resolve_text, _summary
# The corpus token and document-frequency primitives are read from `corpus_stats` — the one measure
# shared by both the reach path (the `match` seam) and this recall path. It and the index below sit
# at chorus's `src/` top level, vendored from mantle, which holds neither: `corpus_fts.py` states
# what that vendoring obliges, and that ember carries a second copy that must not diverge.
from agience_chorus.corpus_stats import terms, _q, _df, _corpus_rows, _salient, _match_expr
import agience_chorus.corpus_fts as _fts   # the index — one implementation, in the store

# `_projection` is resolved through the declared host seam rather than imported directly from
# `ember.signal.projection`: ember and chorus are peer packages, and a direct cross-persona import
# would create the sideways edge the layer model forbids (see `_host_seams.py`). The seam resolves
# lazily, on first attribute access, so this module imports cleanly on a host that has not bound
# ember; only a call that reaches for the projection frame can raise, and only if nothing bound one.
from agience_chorus._host_seams import seam as _seam, resolve as _resolve_seam

_projection = _seam("projection")            # the frame every cut and condensation sits on

# ── the ranking is mantle's, and this is the only copy ───────────────────────────────────────────
# `search -> rank -> cut` used to live here, which put it above the store that produces the
# candidates: mantle's own `recall` had no way to reach it, so the base install ranked lexically and
# nothing it learned was available without a persona. The three functions moved to
# `mantle.search.ranking` — mantle is where the candidates come from — and this file binds its
# ontology into them and keeps its own private names pointing at the one implementation.
#
# The seams go in lazily. `_seam` resolves on first attribute access, so binding here costs nothing
# on a host that never reaches for the ontology, and `ranking._resolve_seam` proves the proxy is
# reachable before using it rather than trusting that it was bound.
from mantle.search import ranking as _ranking

_ranking.bind(match=_seam("match"), projection=_projection)

_knee = _ranking.knee
_relevance_cut = _ranking.relevance_cut
_reach_rank = _ranking.rank

# Real-content vertices only. The stubs carry no text; excluding the type keeps injected prose from
# ever surfacing without judging any word.
_CONTENT_TYPES = ("text/markdown", "text/x-wordnet")


def _unplaced_subject(store, query: str) -> Optional[str]:
    """The token this query is MOST about, when the ontology cannot place it. `None` otherwise.

    The sibling of `_absent_content`, and the other half of the same honesty. That one catches a
    token the corpus has never attested. This one catches a token the corpus HAS — it is in the
    index, it has a document frequency, it is the most informative word in the question — and which
    the ontology has no position for, so it contributes nothing to the field and the answer is built
    from whatever else was lying around:

        what does viscous mean         viscous   df-rarest   UNPLACED  -> Department of Energy
        what makes a thing beautiful   beautiful df-rarest   UNPLACED  -> brand
        what is a glacier              glacier   df-rarest   placed    -> glacier, energy 8.52

    `viscous` and `beautiful` are adjectives. An adjective carries an information content but no
    hypernym parent, so it has no least common subsumer with anything and `jc_tree` has nothing to
    measure — `wn_synsets_for` therefore does not return it, and the field is seeded by `does`
    (which resolves to the Department of Energy) and `thing`. The answer that comes back is
    confident and about nothing the caller asked for, which is worse than no answer.

    "Most informative" is read straight off document frequency, not through a second measure:
    `I(w) = -log2(df/N)` is monotonically DECREASING in `df`, so the most informative token of a
    query is simply its rarest, and the comparison needs no logarithm and no corpus size. `_df` is
    exact, read off `fts5vocab`, and is already this module's own import — the same number
    `_salient` ranks on.

    Nothing here is a threshold. The test is comparative: of the tokens this query carries, the
    rarest is the one with no position.

    `df == 0` is skipped rather than treated as maximally informative: an unattested token is
    `_absent_content`'s case and it names it better. A token whose df cannot be read at all is
    skipped for the same reason — an unmeasurable word cannot be shown to be the most informative
    one, and refusing on it would turn a missing index into a refusal to answer anything.
    """
    from crystal.ontology.lookup import (
        lemma_tokens, projected_synsets_for, wn_synsets_for)
    try:
        conn = store.artifacts.db.read()
    except Exception:
        return None
    rarest, rarest_df = None, None
    for tok in lemma_tokens(query or ""):
        try:
            df = _df(conn, tok)
        except Exception:
            df = None
        if df == 0:
            # An unattested token would be the rarest of all, and it is `_absent_content`'s case:
            # that check names it better and runs first. Skipping it and carrying on would leave
            # the NEXT rarest standing in for the subject — and on a query like "what is a
            # florpangle" that is `what`, which is unplaced in every question ever asked. So this
            # check makes NO claim while an absence is present, rather than a wrong one.
            return None
        if df is None:                    # unmeasurable: cannot be shown to be the most informative
            continue
        if rarest_df is None or df < rarest_df:
            rarest, rarest_df = tok, df
    if rarest is None:
        return None
    if wn_synsets_for(rarest):
        return None
    # A modifier has no position of its own but may have a PROJECTION — the noun it is about. That
    # is a position the field can fire through, so the subject is placed after all and this check
    # makes no claim. Only a modifier that projects nowhere is genuinely unplaceable.
    return None if projected_synsets_for(rarest, store) else rarest


def _absent_content(store, query: str) -> List[str]:
    """Tokens naming something the corpus has never seen: they fire no synset (WordNet + morphy
    fallback) and have df==0 (never attested in any document). df is exact (read off `fts5vocab`),
    so df==0 is an unambiguous absence. A query carrying such a token cannot be honestly grounded, so
    the answer names the absent token rather than letting retrieval land on a filler self-hit ('what
    is a florpangle quibnup' → i.n.03). Not a stop-list (function words pass — they have df>0, not
    because listed) and not a threshold on a resolved quantity — just the corpus's own record of what
    it has and hasn't attested. Real-but-rare tokens (petrichor, zzyzx) are attested (df>0) and pass."""
    from crystal.ontology.lookup import wn_synsets_for
    from crystal.ontology import driver as wn
    try:
        conn = store.artifacts.db.read()
    except Exception:
        return []

    def _fires(w: str) -> bool:
        if wn_synsets_for(w):
            return True
        try:
            b = wn.morphy(w, wn.NOUN)
            return bool(b and wn_synsets_for(b))
        except Exception:
            return False

    out: List[str] = []
    # `corpus_stats.terms` is the one tokenizer this arm's df lookups are keyed by — the same
    # function that decides salience. Re-typing its regex here made a fourth copy of "what a word
    # is", and a query term that tokenized differently from the term the df was counted for would
    # read df==0 and be reported as absent from the corpus rather than as a tokenizer mismatch.
    for w in terms(query or ""):
        if not _fires(w):
            try:
                if _df(conn, w) == 0:
                    out.append(w)
            except Exception:
                pass
    return out


# `terms` / `_q` / `_df` / `_salient` / `_corpus_rows` / `_match_expr` are the corpus measurement
# primitives, imported above from `corpus_stats` — see the header.


def search(store, query: str, *, k: int = 8, id_prefix: str | None = None
           ) -> List[Tuple[str, str, float]]:
    """Top-k `(id, content_type, bm25)` — real-content types only. BM25 is negative; most-negative
    is best, so ORDER BY ASC. Retrieval is driven by the query's salient terms (rare = informative,
    by the corpus's own document frequency); ranking within that is BM25's. Nothing is imposed.

    `id_prefix` restricts recall to one id namespace in SQL. A caller grounding in a sub-corpus
    (`op.knowledge.cite` -> the canon) must not take the global top-k and discard what it did not
    want: the wanted rows would then have to out-rank the entire store for a slot they are not
    competing for. Measured on the live shard, k=6, canon hits returned:

        query                     global   canon-scoped
        holographic compression    0/6        6/6   341ms -> 5ms
        semantic coherence         0/6        6/6   151ms -> 0ms
        entroptics instrument        1/6        6/6    92ms -> 2ms
        adaptive cut resolution    1/6        6/6    50ms -> 25ms

    Same defect and same fix as `_page_canon`'s 615x: the work is the rows touched, and the LIMIT
    bounds output, not work.
    """
    ts = terms(query)
    if not ts:
        return []
    try:
        conn = store.artifacts.db.read()
    except Exception:
        return []
    # Recall runs on the query's content tokens — those that resolve to a real synset via
    # `wn_synsets_for` — falling back to every token only when none fire (a proper-noun query like
    # "ada lovelace"). OR-ing every token including filler ("what", "is", "a") lets documents that
    # carry only the filler flood the top-k and push the actual subject out of the pool; a re-rank
    # cannot repair that afterward, since it can only order what recall delivered.
    #
    # `_salient` ranks by the corpus's own document frequency (rarer = more informative, no
    # stop-list, nothing hand-authored) and is the same measure that weights the reach field
    # (`match.fired_field`). At encyclopedia scale, though, a content word like "glacier" is itself
    # common enough (~10k articles) that document frequency alone cannot separate it from filler —
    # so recall gates on synset resolution rather than on a frequency threshold; ranking within the
    # gated set is `_salient`'s and BM25's to do.
    from crystal.ontology.lookup import wn_synsets_for as _wsf
    _content = [t for t in ts if _wsf(t)]
    ts = _content or ts
    ph = ",".join("?" * len(_CONTENT_TYPES))
    # Which posting belongs to which document: a contentless FTS5 table cannot say on its own —
    # every column reads back NULL — so the correspondence is an explicit map, written in the same
    # transaction as the posting. There is one index and it lives in the store.
    # The id range, as a half-open interval on the PK — the same bound `_page_canon` walks. `chr(0x10FFFF)`
    # is the last code point, so `prefix < id < prefix+MAX` is every id under the prefix and nothing else;
    # a LIKE would not use the index.
    scope, bounds = "", ()
    if id_prefix:
        scope = "AND v.id > ? AND v.id < ? "
        bounds = (id_prefix, id_prefix + chr(0x10FFFF))
    rows = conn.execute(
        "SELECT v.id, v.ct, bm25(%s) AS s FROM %s "
        "JOIN %s m ON m.fts_rowid = %s.rowid JOIN vertex v ON v.id = m.vertex_id "
        # NOTE: `vertex` has no `state` column — state rides in the doc JSON — so committed/archived
        # is not filtered here; archived rows never enter the index in the first place.
        "WHERE %s MATCH ? AND v.ct IN (%s) %sORDER BY s ASC LIMIT ?"
        % (_fts.FTS_TABLE, _fts.FTS_TABLE, _fts.MAP_TABLE, _fts.FTS_TABLE, _fts.FTS_TABLE, ph, scope),
        (_match_expr(ts), *_CONTENT_TYPES, *bounds, int(k)),
    ).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


# `_summary` (project one clean summary from an article's own text) lives in `mantle.shard.content` —
# content projection, read by both the ember viewer and this describer; imported at the top with
# `resolve_text`.


def _type_def(store, ct: str):
    """The content-type definition artifact (`type.<ct>`) — carries the offer_template the describer
    renders with. Cached per store; None if absent (then the caller renders a plain fallback)."""
    cache = getattr(store, "_ctdef_cache", None)
    if cache is None:
        cache = {}
        try:
            setattr(store, "_ctdef_cache", cache)
        except Exception:
            pass
    if ct not in cache:
        try:
            cache[ct] = store.artifacts.get_artifact("type." + ct)
        except Exception:
            cache[ct] = None
    return cache[ct]


def _describe(store, art: dict, ct: str, content: str) -> str:
    """One line for one hit, rendered by the type's own `offer_template` (the describer) — not a
    layout forced here. Markdown carries no stored `summary`, so we project one from the document's
    text; the template ("{title}: {summary}") decides how it reads and drops the summary cleanly if
    the doc has none."""
    try:                                         # sage-local, not ember's
        from agience_chorus.sage import offer as _offer         # (chorus/src on path)
    except ImportError:
        import agience_chorus.sage.offer as _offer                   # (sage/ on path)
    a = dict(art)
    if ct == "text/markdown" and "summary" not in a:
        s = _summary(content, a.get("title"))
        if s:
            a["summary"] = s
    td = _type_def(store, ct)
    if td:
        line, _ref = _offer.offer_or_none(td, a)
        if line:
            return line
    # Fallback only when the type has no describer: title, else a bounded slice of its own text.
    return str(a.get("title") or _summary(content, "") or a.get("id"))


# `_POOL` is the one constant in the answer path, and it is a scan budget, not an answer count. It
# bounds how many BM25 candidates `_knee` sees before cutting — retrieval breadth, cheap (scores
# only, no blob reads). The answer's own size is `_relevance_cut`'s to derive, already bounded by
# `_POOL`. Pool depth does not gate correctness: the need's own fired position is always a candidate
# by construction (see `_reach_rank`), so a synset absent from the top `_POOL` BM25 hits is still
# reachable. Callers may pass an explicit `ceiling`; nothing imposes one by default.
_POOL = 200







# ── step 2+3 of the matching primitive: measures the gap (OPERATOR-ARCHITECTURE §13.8) ───────────
# BM25 is step 1 only — the teleport that lands in the neighbourhood. It ranks by term statistics,
# which is why "what is a dog" surfaces `blackguard` (its synonym list contains "dog") above
# `Canis familiaris` whose gloss never says the word. Lexical proximity is not meaning proximity, and
# no configured weight between the two is admissible (§12.2: measured at the coupling, never set).
#
# So the teleport's candidates are re-ranked by the measured reach of the need onto each candidate's
# own ontology position. `match.propagate` is the screened propagator —
# `energy · exp(-jc_tree(need,target)/ξ)`, counted only if it clears the propagation floor — and it returns
# both the accumulated energy and the nearest actual geodesic distance: the distance is the gap, and
# the gap is accounted for rather than collapsed into a single score.
#
# The target is the candidate's own synset, not nouns parsed from its gloss: a `wn-<name>` vertex is
# a position in the ontology, so it is used directly. Prose vertices (no synset id) fall back to the
# nouns they name, which for them is the honest position — parsing nouns out of the gloss text would
# measure distance to whatever the definition happens to mention, not to the sense itself.
#
# Degrades to the BM25 order whenever the need names no resolvable position or nothing is reachable:
# the re-rank can refine a teleport, never manufacture one.
#
# The ranked score is the reach, not the BM25 it replaced: `_knee`/`adaptive_cut` both assume a
# sequence sorted best-first and read the break in it, and a reach-ordered list of BM25 scores is not
# monotone in either signal. Ranking and cutting read one measurement, or the derived count is a
# fiction.


class _Cond:
    __slots__ = ("kind", "head", "order", "basis")

    def __init__(self, kind, head, order, basis):
        self.kind, self.head, self.order, self.basis = kind, head, order, basis


def _condense_reached(store, query: str, cand):
    """Run the reached ontology nodes through `condense`, and return the answer's order.

    The condensation decides both what is said and how much: the head first, then the members that
    carry information the head does not. Nothing is truncated to a count — a `define` is short
    because one node carried the reading, not because a ceiling said so, and a `disambiguate` is
    several because the word genuinely has several senses.

    Returns None when there is nothing to condense (fewer than two placed nodes), and the caller
    falls back to the derived cut."""
    try:                                             # robust: cross-persona host vs in-persona process
        from agience_chorus.sage import condense as _cd             # (chorus/src on path)
    except ImportError:
        import agience_chorus.sage.condense as _cd                       # (sage/ on path)
    from crystal.ontology import geometry as _g
    _match = _resolve_seam("match")              # the screened propagator — the host's module, by name
    from crystal.ontology import driver as _wn
    from prism.resolution import signal_end
    pairs = [(cid[3:], -float(sc)) for cid, _ct, sc in cand if cid.startswith("wn-")]
    if len(pairs) < 2:
        return None
    # Condensing runs over what reached, not the whole pool: handing `condense` all 200 BM25
    # candidates makes "cats and dogs" report enumerate — "no shared subsumer" — because a 200-node
    # set spans the whole ontology and shares nothing by construction, even though cat and dog do
    # share `carnivore`.
    #
    # This is not the cut coming back. Propagation still runs to the horizon; `signal_end` then
    # separates what the propagation actually reached from what merely appeared in the teleport, and
    # the condenser resolves that reached set. The screen is built over everything reached before
    # `signal_end` reads it, so the instrument and the cut share the same frame.
    _full = _projection.frame(store, [n for n, _e in pairs])
    pairs = pairs[:signal_end([e for _n, e in pairs], frame=_full)]
    if len(pairs) < 2:
        return None
    ic = _g.load_ic()
    # The level the question itself was asked at — its most informative fired node. Not a setting.
    asked = max((_g.ic_of(_wn.synset(n), ic, strict=False)
                 for n in _match.fired_field(query, store)), default=None)
    # The condenser reads the same screen the cut does — one frame, one instrument. The screen's
    # certified coherence (scale-invariant = one thing) confirms define; the tree gives the rest.
    _W = _projection.frame(store, [n for n, _e in pairs])
    _coh = _projection.coherent(store, [n for n, _e in pairs]) if _W is not None else None
    c = _cd.condense(pairs, asked_ic=asked, frame=_W if _W is not None else _full, coherent=_coh)
    if c.kind == "empty":
        return None
    if c.kind == "enumerate":
        # Enumerate does not mean emit everything: a cut removed with nothing put in its place is
        # worse than the cut. "These are not one thing" is a real finding and it is reported
        # (`read.condensed`), but it gives the answer no order of its own, so the derived cut
        # stands. A condenser that cannot resolve the set says so and steps aside.
        return None
    want, seen = [], set()
    for n in ([c.head] if c.head else []) + list(c.members) + list(c.distinguishing):
        if n and n not in seen:
            seen.add(n)
            want.append("wn-" + n)
    by_id = {cid: (cid, ct, sc) for cid, ct, sc in cand}
    order = [by_id[i] for i in want if i in by_id]
    # A disambiguate has no head, so its order is the answer's order, and that order follows the
    # measured reach rather than the tree-walk's branch-appearance. `_branches` groups by lineage
    # and names each branch by its subsumer, which can reorder the senses away from how strongly the
    # need actually reached them: on "eye" (pupil 59 in the basics corpus), reach ranks eye.n.01
    # first (energy 4.88) while branch grouping would lead with eye.n.02 (2.53) — the weaker sense.
    # The finding "these are several senses" is unchanged (`read.condensed` still says disambiguate);
    # only the presentation defers to the same reach every other kind is ranked by. Scores follow
    # BM25's sign (more negative = more reached), so ascending puts the most-reached sense first.
    # `define`, `subsume`, and `contrast` keep their head/group order — only the headless case is
    # reordered.
    if c.kind == "disambiguate" and order:
        order = sorted(order, key=lambda t: t[2])
    return _Cond(c.kind, c.head, order, c.basis) if order else None


def _aligned_articles(store, synset_ids: List[str]) -> List[str]:
    """The wiki articles the compaction found to be the same concept as these synsets — traversed
    synset ← concept-* → article across the `aligns` edges `op.consolidate.crosswalk` drew (§7). The
    lexical position (synset) and the encyclopedic content (article) are one concept; this returns the
    content side. Empty on a corpus with no crosswalk (e.g. a basics pupil), so it never regresses one.

    The edges are hub-and-spoke (concept → member), which is exactly why the one-hop outgoing
    propagator could not make this join: from a synset the article is a sibling under the concept,
    reachable only up the incoming edge then down. So the join lives here, in the answer, not in the
    reach — two keyed hops on the `aligns` label, no similarity, no model."""
    if not synset_ids:
        return []
    try:
        conn = store.artifacts.db.read()
    except Exception:
        return []
    out: List[str] = []
    seen: set = set()
    for sid in synset_ids:
        try:
            concepts = [r[0] for r in conn.execute(
                "SELECT src FROM edge WHERE dst = ? AND label = 'aligns'", (sid,)).fetchall()]
            for cx in concepts:
                for (aid,) in conn.execute(
                        "SELECT dst FROM edge WHERE src = ? AND label = 'aligns'", (cx,)).fetchall():
                    aid = str(aid)
                    if aid.startswith("wiki") and aid not in seen:
                        seen.add(aid)
                        out.append(aid)                 # the articles that actually aligned (a concept has 1-2), no fixed cap
        except Exception:
            continue
    return out


def _hyper_closure(name: str) -> set:
    """The transitive is-a ancestors of a synset — exact from WordNet's own tree. No gap, no model:
    is-a is a fact the corpus already holds, not a fuzzy reach to be measured. Traverses to the
    fixpoint (the `seen` set makes the finite DAG terminate) — no depth cap, so no arbitrary horizon."""
    from crystal.ontology import driver as wn
    seen, frontier = set(), [name]
    while frontier:
        nxt = []
        for n in frontier:
            try:
                s = wn.synset(n)
            except Exception:
                continue
            hs = list(s.hypernyms() or [])
            ih = getattr(s, "instance_hypernyms", None)
            if callable(ih):
                try:
                    hs += list(ih() or [])
                except Exception:
                    pass
            for h in hs:
                hn = h if isinstance(h, str) else h.name()
                if hn and hn not in seen:
                    seen.add(hn); nxt.append(hn)
        frontier = nxt
        if not nxt:
            break
    return seen


# Strict: an explicit is-a marker before the second noun ("a dog is a mammal", "... kind of ..."). A
# strict match answers yes or no (both are informative). Loose: the bare plural form ("are dogs
# animals") has no marker, so it affirms on a real path only and otherwise defers to retrieval — never
# a confident "No", because "is the sky blue" also matches this shape and is not an is-a question.
_ISA_STRICT = re.compile(
    r"^\s*(?:is|are|was|were)\s+(?:an?\s+|the\s+)?(.+?)\s+"
    r"(?:an?\s+|kind\s+of\s+|type\s+of\s+|sort\s+of\s+|a\s+kind\s+of\s+|a\s+type\s+of\s+)(.+?)\s*\?*\s*$",
    re.I)
_ISA_LOOSE = re.compile(r"^\s*(?:is|are)\s+(?:an?\s+|the\s+)?(.+?)\s+(.+?)\s*\?*\s*$", re.I)


def isa_answer(store, query: str) -> Optional[Answer]:
    """Intermediate reasoning: answer an is-a question by traversing the hypernym tree — exact,
    objective, model-free. "Is a dog a mammal?" is a fact in WordNet's structure (dog → canine →
    carnivore → placental → mammal), not a fuzzy reach: the gapped propagator is for relatedness
    (ranking), the tree is for is-a (truth). Returns an Answer for a well-formed is-a question whose
    both nouns resolve; None otherwise (so ordinary retrieval is untouched)."""
    strict = _ISA_STRICT.match(query or "")
    m = strict or _ISA_LOOSE.match(query or "")
    if not m:
        return None
    from crystal.ontology.lookup import wn_synsets_for
    from crystal.ontology import driver as wn

    def senses(w: str):
        w = w.strip().lower()
        r = wn_synsets_for(w)
        if not r:
            try:
                base = wn.morphy(w, wn.NOUN)
            except Exception:
                base = None
            if base:
                r = wn_synsets_for(base)
        return r

    x, y = m.group(1), m.group(2)
    xs, ys = senses(x), senses(y)
    if not xs or not ys:
        return None                                   # not a resolvable is-a question → normal path
    yset = set(ys)
    for xs0 in xs:                                     # every sense of x — any sense under y makes it a Yes
        if xs0 in yset:                               # X already is a sense of Y (identity)
            continue
        anc = _hyper_closure(xs0)
        hit = yset & anc
        if hit:
            yhit = sorted(hit)[0]
            xlem = xs0.split(".")[0].replace("_", " ")   # clean lemma, robust to plural/article input
            ylem = yhit.split(".")[0].replace("_", " ")
            return Answer(
                text="Yes — a %s is a %s (is-a chain: %s → %s)." % (xlem, ylem, xs0, yhit),
                grounded=True, cited=["wn-" + xs0, "wn-" + yhit],
                read={"engine": "reason", "relation": "is-a", "result": True, "via": xs0})
    if not strict:
        return None                                   # loose form, no path → defer to retrieval, not a false "No"
    return Answer(
        text="No — a %s is not a kind of %s; there is no is-a path between them in the taxonomy."
             % (x.strip().lower(), y.strip().lower()),
        grounded=True, cited=["wn-" + xs[0]],
        read={"engine": "reason", "relation": "is-a", "result": False})


_COMPARE = re.compile(
    r"^\s*(?:how\s+(?:are|is)\s+|compare\s+|whats?\s+the\s+(?:difference|relationships?|relation)\s+between\s+|"
    r"what\s+do\s+)(.+?)\s+(?:and|vs\.?|versus|&)\s+(.+?)"
    r"(?:\s+(?:related|compared|have\s+in\s+common|different|alike))?\s*\??\s*$", re.I)


#: The near-root abstraction tolerance — a stated constant, not a derived one; module-scoped so a
#: measurement can substitute the derived alternative against the real code path (see the note at
#: its use site, in `compare_answer`, for what would derive it). Warmed where the corpus is already
#: bound at host startup, `_root_ic` (the candidate derivation) costs 0.1s per call; unwarmed, its
#: first call scans all 481,846 noun synsets on the live OEWN lattice at ~21.3s.
_NEAR_ROOT_ANCESTORS = 4


def compare_answer(store, query: str) -> Optional[Answer]:
    """Relates two things by their least common subsumer in the hypernym tree. Model-free, a fact:
    "how are a dog and a wolf related?" → both are canines; "what do a piano and a guitar have in
    common?" → both are musical instruments. Across every sense pair, the deepest shared ancestor
    (most specific common category) is the answer. None if either side doesn't resolve, or the only
    shared ancestor is a near-root abstraction (they're only distantly related) — defers to retrieval
    rather than assert a vacuous "both are entities". Same shape as is-a: reads the tree, states a
    fact."""
    m = _COMPARE.match(query or "")
    if not m:
        return None
    from crystal.ontology.lookup import wn_synsets_for
    from crystal.ontology import driver as wn

    def senses(w: str):
        w = re.sub(r"^(?:an?|the)\s+", "", w.strip().lower().strip("?.").strip())  # drop a/an/the
        r = wn_synsets_for(w)
        if not r:
            try:
                b = wn.morphy(w, wn.NOUN)
                r = wn_synsets_for(b) if b else []
            except Exception:
                r = []
        return r

    x, y = m.group(1).strip(), m.group(2).strip()
    xs, ys = senses(x), senses(y)
    if not xs or not ys:
        return None
    best, best_score, best_depth = None, -(10 ** 9), 0
    for sx in xs:
        cx = _hyper_closure(sx); lx = len(cx)
        for sy in ys:
            if sx == sy:
                continue
            cy = _hyper_closure(sy); ly = len(cy)
            for c in (cx & cy) - {sx, sy}:
                lc = len(_hyper_closure(c))
                # prefer the LCS closest to both senses (the most specific real relationship), not just
                # the deepest ancestor: score = -(dist(sx,c)+dist(sy,c)) = 2·|anc(c)| - |anc(sx)| - |anc(sy)|.
                # This stops a huge deep subtree (person) from hijacking a polysemous term (star→celebrity)
                # over the close, specific category (star/planet → celestial body).
                score = 2 * lc - lx - ly
                if score > best_score:
                    best_score, best_depth, best = score, lc, (c, sx, sy)
    # A shared ancestor with fewer than this many ancestors of its own is a near-root abstraction
    # (entity / physical_entity / object); "a rock and a car are both kinds of object" is vacuous, so
    # the question defers to retrieval instead of asserting it. `best_depth` is
    # `len(_hyper_closure(lcs))`, so 4 means "at least four levels below the top of the tree".
    #
    # This tolerance is stated rather than derived, and the derivation has now been CHECKED against
    # it rather than left as an open option.
    #
    # The derived form asks what `sage/condense.py::_is_scatter` asks — "does this subsumer say
    # anything at all?" — against `_root_ic`, the information content of the top of the tree as the
    # corpus measures it. On the live OEWN lattice `_root_ic` is **0.1571** (207s cold, one scan of
    # every noun synset). Run over twelve real compare pairs, the two rules agree on ten and
    # disagree on two — and on both, the depth is right and the derivation is wrong:
    #
    #     glacier / iceberg   lcs object.n.01           ic 0.2190   depth 3   derived: ACCEPT
    #     neuron  / muscle    lcs physical_entity.n.01  ic 0.2000   depth 2   derived: ACCEPT
    #
    # "A glacier and an iceberg are both objects" is the vacuous answer this gate exists to refuse.
    # `> _root_ic` cannot refuse it: a near-root abstraction sits only just above the root, so the
    # bar clears it while carrying almost nothing. The root's IC measures where information runs
    # out, not where it becomes worth saying, and those are different questions.
    #
    # So the constant stays, now on evidence rather than on caution. It is a statement about the
    # SHAPE of the taxonomy's top — four levels of abstraction above the root are vacuous in this
    # tree — and a different value is right if that shape changes. Deriving it properly would need a
    # measure of "informative relative to the pair", which is not `_root_ic` and which nothing here
    # has yet.
    if not best or best_depth < _NEAR_ROOT_ANCESTORS:
        return None
    c, sx, sy = best

    def _w(s):
        return s.split(".")[0].replace("_", " ")

    return Answer(
        text="A %s and a %s are both kinds of %s — their nearest shared category in the taxonomy."
             % (_w(sx), _w(sy), _w(c)),
        grounded=True, cited=["wn-" + sx, "wn-" + sy, "wn-" + c],
        read={"engine": "reason", "relation": "compare", "lcs": c})


_EXAMPLES = re.compile(
    r"^\s*(?:(?:what\s+(?:are|is)\s+)?(?:some\s+)?(?:kinds|types|examples|sorts|varieties)\s+of\s+|"
    r"give\s+(?:me\s+)?(?:some\s+)?examples?\s+of\s+|list\s+(?:some\s+)?)"
    r"(?:an?\s+|the\s+)?(.+?)\s*\??\s*$", re.I)


def enumerate_answer(store, query: str) -> Optional[Answer]:
    """Discussion: enumerate the kinds of a thing — its direct hyponyms in the tree, the inverse of
    is-a (model-free, a fact). "What are some kinds of dog?" → the breeds directly under `dog`. Picks
    the sense with the most direct children (the real category). None if nothing resolves to a category
    with children — defer to retrieval. The list length is the data's (direct-child count); a long tail
    is shown truncated with its true remaining count, never silently cut."""
    m = _EXAMPLES.match(query or "")
    if not m:
        return None
    from crystal.ontology.lookup import wn_synsets_for
    from crystal.ontology import driver as wn
    w = re.sub(r"^(?:an?|the)\s+", "", m.group(1).strip().lower().strip("?.").strip())
    xs = wn_synsets_for(w)
    if not xs:
        try:
            b = wn.morphy(w, wn.NOUN)
            xs = wn_synsets_for(b) if b else []
        except Exception:
            xs = []
    if not xs:
        return None
    try:
        conn = store.artifacts.db.read()
    except Exception:
        return None
    best, kids = None, []
    for sx in xs:
        try:
            rows = conn.execute("SELECT src FROM edge WHERE dst = ? AND label = 'hypernym' LIMIT 200",
                                ("wn-" + sx,)).fetchall()
        except Exception:
            rows = []
        ch = [(str(r[0])[3:] if str(r[0]).startswith("wn-") else str(r[0])) for r in rows]
        if len(ch) > len(kids):
            best, kids = sx, ch
    if not best or not kids:
        return None

    def _w(s):
        return s.split(".")[0].replace("_", " ")

    names: List[str] = []
    for k in kids:
        nm = _w(k)
        if nm not in names:
            names.append(nm)
    # Presentation, and it decides nothing: `n` in the read carries the true count, the text says
    # "and N more", and the list is the data's own (direct-child count) — so a reader is never
    # shown a truncated list that looks complete. The number is how many fit in one readable line.
    _SHOWN = 12
    shown = names[:_SHOWN]
    tail = "" if len(names) <= _SHOWN else " — and %d more" % (len(names) - _SHOWN)
    return Answer(
        text="Some kinds of %s: %s%s." % (_w(best), ", ".join(shown), tail),
        grounded=True, cited=["wn-" + best],
        read={"engine": "reason", "relation": "hyponyms", "n": len(names)})


import ast as _ast
import operator as _mop
_MATHOPS = {_ast.Add: _mop.add, _ast.Sub: _mop.sub, _ast.Mult: _mop.mul, _ast.Div: _mop.truediv,
            _ast.FloorDiv: _mop.floordiv, _ast.Mod: _mop.mod, _ast.Pow: _mop.pow,
            _ast.USub: _mop.neg, _ast.UAdd: _mop.pos}


def _safe_arith(expr: str) -> float:
    """Evaluate a pure-arithmetic expression via a restricted AST walk (numbers + operators only —
    never names, calls, attributes), so it can only compute a number, never execute code."""
    def ev(n):
        if isinstance(n, _ast.Expression):
            return ev(n.body)
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, _ast.BinOp) and type(n.op) in _MATHOPS:
            return _MATHOPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, _ast.UnaryOp) and type(n.op) in _MATHOPS:
            return _MATHOPS[type(n.op)](ev(n.operand))
        raise ValueError("not pure arithmetic")
    return ev(_ast.parse(expr.strip(), mode="eval"))


def _fmt_num(x: float) -> str:
    return str(int(round(x))) if abs(x - round(x)) < 1e-9 else ("%.4g" % x)


def _parse_linear_side(s: str):
    """Parse one side of a single-variable linear equation into (coeff_of_x, constant)."""
    s = s.replace(" ", "")
    if not s:
        return 0.0, 0.0
    if s[0] not in "+-":
        s = "+" + s
    a = b = 0.0
    for mt in re.finditer(r"([+-])(\d*\.?\d*)(x?)", s):
        if not (mt.group(2) or mt.group(3)):
            continue
        sign = 1.0 if mt.group(1) == "+" else -1.0
        if mt.group(3) == "x":
            a += sign * (1.0 if mt.group(2) == "" else float(mt.group(2)))
        elif mt.group(2):
            b += sign * float(mt.group(2))
    return a, b


def math_answer(store, query: str) -> Optional[Answer]:
    """Solve / compute — model-free exact math, the arithmetic a graduate can do: percentages, rate×time
    word problems, single-variable linear equations, and direct arithmetic. Distinct from the wedge
    (which verifies a given equation's truth); this one computes an answer. None if the query isn't math."""
    q = (query or "").strip()
    ql = q.lower().replace("×", "*").replace("÷", "/")
    # percentage: "X percent of Y" / "X% of Y"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+(\d+(?:\.\d+)?)", ql)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return Answer(text="%s%% of %s = %s." % (_fmt_num(a), _fmt_num(b), _fmt_num(a / 100.0 * b)),
                      grounded=True, cited=["engine:math.percent"], read={"engine": "math", "kind": "percent"})
    # rate × time: "X (miles|km|mph) ... for Y hours" -> distance
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:miles?|kilomet\w*|km|mph)\b.*?\bfor\s+(\d+(?:\.\d+)?)\s*hours?", ql)
    if m:
        r, t = float(m.group(1)), float(m.group(2))
        return Answer(text="At %s per hour for %s hours: distance = %s × %s = %s miles."
                           % (_fmt_num(r), _fmt_num(t), _fmt_num(r), _fmt_num(t), _fmt_num(r * t)),
                      grounded=True, cited=["engine:math.rate"], read={"engine": "math", "kind": "rate"})
    # single-variable linear equation
    if "=" in ql and "x" in ql:
        eqm = re.search(r"([0-9x+\-*/.\s]+=[0-9x+\-*/.\s]+)", ql)
        if eqm:
            lhs, rhs = eqm.group(1).split("=", 1)
            try:
                al, bl = _parse_linear_side(lhs)
                ar, br = _parse_linear_side(rhs)
                da = al - ar
                if abs(da) > 1e-12:
                    x = (br - bl) / da
                    return Answer(text="Solving %s: x = %s." % (eqm.group(1).strip(), _fmt_num(x)),
                                  grounded=True, cited=["engine:math.equation"], read={"engine": "math", "kind": "equation"})
            except Exception:
                pass
    # direct arithmetic: "what is <expr>" or a bare expression, operators required
    m = re.search(r"(?:what\s+is|what's|calculate|compute|evaluate)\s+(.+)", ql)
    expr = (m.group(1) if m else ql).replace("^", "**").strip(" ?.")
    if re.fullmatch(r"[-+*/()\d.\s]*", expr) and re.search(r"[-+*/]", expr) and re.search(r"\d", expr):
        try:
            return Answer(text="%s = %s." % (expr.strip(), _fmt_num(_safe_arith(expr))),
                          grounded=True, cited=["engine:math.arithmetic"], read={"engine": "math", "kind": "arithmetic"})
        except Exception:
            pass
    return None


def _cn_reach(store, word: str, relation: str) -> List[str]:
    """The concepts `word` reaches by `relation` in the ConceptNet graph — exact edge traversal, no
    model. Ranked and cut by the graph's own measure: ConceptNet's per-edge `weight` (assertion
    confidence). The cut is the mean weight of what was reached — a derived boundary that scales with
    the concept, not a typed count — so a strongly-attested handful shows tight and a broadly-attested
    concept shows more. No LIMIT, no fixed N. Returns readable target words (cn- stripped), deduped."""
    import json as _json
    key = "cn-" + word.strip().lower().replace(" ", "_")
    try:
        conn = store.artifacts.db.read()
        rows = conn.execute("SELECT dst, props FROM edge WHERE src = ? AND label = ?",
                            (key, relation)).fetchall()   # indexed (src,label); bounded by the concept's degree
    except Exception:
        return []
    scored, seen = [], set()
    for dst, props in rows:
        w = str(dst)
        if w.startswith("cn-"):
            w = w[3:].replace("_", " ")
        if not w or w in seen:
            continue
        seen.add(w)
        try:
            wt = float(_json.loads(props).get("weight", 1.0)) if props else 1.0
        except Exception:
            wt = 1.0
        scored.append((wt, w))
    if not scored:
        return []
    mean = sum(wt for wt, _ in scored) / len(scored)     # the corpus's own cut, not a chosen number
    return [w for wt, w in sorted(scored, reverse=True) if wt >= mean]


# (pattern, ConceptNet relation, template) — associative reasoning: answer by traversing the graph.
# Template takes (subject, comma-joined targets); each relation phrases itself grammatically.
_ASSOC = [
    (re.compile(r"^\s*what can (?:an?\s+|the\s+)?(.+?)\s+do\s*\??\s*$", re.I), "capable_of", "A %s can: %s."),
    (re.compile(r"^\s*what does (?:an?\s+|the\s+)?(.+?)\s+cause\s*\??\s*$", re.I), "causes", "%s causes: %s."),
    (re.compile(r"^\s*what does (?:an?\s+|the\s+)?(.+?)\s+(?:want|desire)\s*\??\s*$", re.I), "desires", "A %s wants: %s."),
    (re.compile(r"^\s*(?:what\s+is|what's|whats)\s+the\s+opposite\s+of\s+(.+?)\s*\??\s*$", re.I), "antonym", "The opposite of %s: %s."),
    (re.compile(r"^\s*where (?:is|are|does|do|can) (?:an?\s+|the\s+)?(.+?)(?:\s+(?:found|live|be|located|kept|go))?\s*\??\s*$", re.I), "at_location", "A %s is found at: %s."),
]


def assoc_answer(store, query: str) -> Optional[Answer]:
    """Intermediate / associative reasoning: answer a relation question ("what can a dog do", "where is
    a dog found", "what's the opposite of hot") by traversing the ConceptNet graph — exact, model-free.
    Returns an Answer only when the relation actually reaches something; else None (retrieval unaffected)."""
    for pat, rel, template in _ASSOC:
        m = pat.match(query or "")
        if not m:
            continue
        x = m.group(1).strip().lower()
        hits = _cn_reach(store, x, rel)
        if not hits:
            # try the morphological base (dogs -> dog) before giving up on this pattern
            try:
                from crystal.ontology import driver as wn
                base = wn.morphy(x.replace(" ", "_"), wn.NOUN)
            except Exception:
                base = None
            if base and base != x:
                hits = _cn_reach(store, base.replace("_", " "), rel)
        if hits:
            return Answer(
                text=template % (x, ", ".join(hits)),
                grounded=True, cited=["cn-" + x.replace(" ", "_")],
                read={"engine": "reason", "relation": rel, "result": True})
        # pattern matched but nothing reached — let retrieval try rather than assert emptiness
        return None
    return None


def wedge_answer(store, query: str) -> Optional[Answer]:
    """Stage-3 wedge: a verification request ("verify python: <code>", "check math: <expr>", "does this
    compile: <code>") is answered by a checker, not retrieval — the answer is verified, not just
    grounded. The claim is everything after the first colon (so code's own colons are preserved).
    Returns None when it isn't a verification request, so ordinary answering is untouched."""
    q = query or ""
    if ":" not in q or not re.search(r"\b(verify|check|compile|valid|parse)\b", q, re.I):
        return None
    head, claim = q.split(":", 1)
    claim = claim.strip()
    if not claim:
        return None
    try:                                             # robust: cross-persona host vs in-persona process
        from agience_chorus.sage import wedge                       # (chorus/src on path)
    except ImportError:
        from agience_chorus.sage import wedge                                 # (sage/ on path)
    if re.search(r"\b(python|code|py|compile|program|function)\b", head, re.I):
        v = wedge.check_python(claim); kind = "python"; act = "compiles"
    elif re.search(r"\b(math|latex|equation|expression|formula|algebra)\b", head, re.I):
        v = wedge.check_math(claim); kind = "math"; act = "parses"
    else:
        return None
    if v.get("verified"):
        extra = (" It defines: %s." % ", ".join(v["symbols"])) if v.get("symbols") else ""
        text = "Verified ✓ — the %s %s.%s" % (kind, act, extra)
    else:
        text = "Not verified ✗ — %s" % (v.get("error") or v.get("why") or "failed the checker")
    return Answer(text=text, grounded=True, cited=["engine:wedge." + str(kind)], read={"engine": "wedge", "kind": kind, **v})


_SELF_RE = re.compile(
    r"\b(who are you|what are you|what can you do|what do you know|what have you learned|"
    r"what are your (?:operators|capabilities|abilities)|what is your source|list your operators)\b", re.I)


def self_answer(store, query: str) -> Optional[Answer]:
    """Stage-4 self: the ember reflects on itself by retrieving over its own artifacts — its operators
    (what it can do), its collections (what it knows), its make-up (crystals/instrument). Not a scripted
    bio: the capabilities and knowledge are read from the store live, so the answer is as true as the
    node actually is. Introspection is retrieval over the self."""
    if not _SELF_RE.search(query or ""):
        return None
    import json as _json
    try:
        conn = store.artifacts.db.read()
    except Exception:
        return None
    ql = (query or "").lower()
    if any(k in ql for k in ("operator", "can you do", "capabilit", "abilit", "source")):
        ops = []
        for (doc,) in conn.execute("SELECT doc FROM vertex WHERE ct = 'application/vnd.agience.operator+json'"):
            try:
                ops.append(_json.loads(doc).get("id", ""))
            except Exception:
                pass
        groups: Dict[str, int] = {}
        for i in sorted(ops):
            g = ".".join(i.split(".")[:2])
            groups[g] = groups.get(g, 0) + 1
        if not groups:
            return None
        body = ", ".join("%s (%d)" % (g, n) for g, n in sorted(groups.items()))
        return Answer(text="I am a model-free ember. I can invoke %d operators, across: %s." % (len(ops), body),
                      grounded=True, cited=["engine:self.operators"], read={"engine": "self", "kind": "operators"})
    if "know" in ql or "learned" in ql:
        cols = []
        for cid, n in conn.execute(
                "SELECT json_extract(doc,'$.collection_id') c, count(*) n FROM vertex GROUP BY c ORDER BY n DESC LIMIT 8"):
            if cid:
                cols.append("%s (%s)" % (cid, n))
        if not cols:
            return None
        return Answer(text="I know, by collection: " + "; ".join(cols) + ".",
                      grounded=True, cited=["engine:self.knowledge"], read={"engine": "self", "kind": "knowledge"})
    return Answer(
        text=("I am an Agience ember — a model-free knowledge node. I ground every answer in my corpus "
              "(WordNet, ConceptNet, Wikipedia) or honestly refuse; I reason by traversing structure "
              "(is-a, associative) and I verify claims (the wedge); the instrument is my one measure of "
              "knowing. I'm built from operators and crystals and I run the same on a Pi or a VPS."),
        grounded=True, cited=["engine:self.identity"], read={"engine": "self", "kind": "identity"})


_ESSAY_RE = re.compile(
    r"^\s*(?:write (?:me )?an essay (?:about|on)|discuss|tell me about|explain|"
    r"describe(?: in detail)?|essay:?)\s+(?:the |a |an )?(.+?)\s*\??\s*$", re.I)


def essay_answer(store, query: str) -> Optional[Answer]:
    """Advanced / secondary: compose an essay on a topic — model-free, so nothing is generated; the
    piece is assembled from grounded knowledge and every part is traceable: (1) what it is (the gloss),
    (2) its place in the taxonomy (the is-a chain), (3) what it does / associates with (ConceptNet
    relations), (4) the encyclopedic account (the aligned Wikipedia lead). A structured synthesis
    across every tier, not a single lookup. None when the topic doesn't resolve, so retrieval is intact."""
    m = _ESSAY_RE.match(query or "")
    if not m:
        return None
    from crystal.ontology.lookup import wn_synsets_for
    from crystal.ontology import driver as wn
    topic = m.group(1).strip().lower()

    def senses(w):
        r = wn_synsets_for(w)
        if not r:
            try:
                b = wn.morphy(w.replace(" ", "_"), wn.NOUN)
            except Exception:
                b = None
            r = wn_synsets_for(b) if b else []
        return r

    ss = senses(topic)
    if not ss:
        return None
    # The prototypical sense — the one the corpus attests most (WordNet's own SemCor sense
    # frequency, the sense-level analog of IDF) — not senses[0], since an arbitrary ordering can
    # surface garbage ("dog" -> the fireplace andiron). Corpus's own measure, no learned model, no
    # tuning. `_count` reads one sense's own attestation; the surrounding try/except covers the read
    # of every sense as one unit and returns None on any failure, so an unreadable count is never
    # mistaken for a zero attestation and cannot collapse the choice to `ss[0]`.
    def _count(name):
        wkey = topic.lower().replace(" ", "_")
        return {l.name().lower(): l.count() for l in wn.synset(name).lemmas()}.get(wkey, 0)

    try:
        counts = {s: _count(s) for s in ss}
    except Exception:
        return None                      # an unread attestation is None, not a guessed sense
    if not any(counts.values()):
        return None                      # no sense is attested; picking one would be a prediction
    syn = max(ss, key=lambda s: counts[s])
    art = store.artifacts.get_artifact("wn-" + syn) or {}
    paras: List[str] = []
    cited: List[str] = ["wn-" + syn]

    gloss = (art.get("gloss") or "").strip()
    if gloss:
        paras.append("%s — %s." % (topic.capitalize(), gloss[0].upper() + gloss[1:] if gloss else gloss))

    # taxonomic placement — the is-a chain up the tree (exact, no gap)
    chain, cur = [], syn
    for _ in range(6):
        try:
            hs = wn.synset(cur).hypernyms()
        except Exception:
            break
        if not hs:
            break
        h = hs[0]
        hn = h if isinstance(h, str) else h.name()
        chain.append(hn.split(".")[0].replace("_", " "))
        cur = hn
    if chain:
        paras.append("In its classification, a %s is a kind of %s." % (topic, ", which is a kind of ".join(chain)))

    # associations — what the thing does / where it is / what it causes (ConceptNet, weight-cut)
    clauses = []
    for rel, verb in (("capable_of", "can"), ("at_location", "is found at"),
                      ("causes", "causes"), ("desires", "wants")):
        hits = _cn_reach(store, topic, rel)
        if hits:
            clauses.append("%s %s %s" % (topic, verb, ", ".join(hits[:8])))
    if clauses:
        paras.append("A " + "; a ".join(clauses) + ".")

    # encyclopedic account — the aligned Wikipedia article's lead (via the crosswalk)
    for aid in _aligned_articles(store, ["wn-" + syn]):
        a = store.artifacts.get_artifact(aid)
        t = resolve_text(store, a) if a else None
        if t:
            paras.append(re.split(r"\n\s*\n", t.strip(), 1)[0].strip())
            cited.append(aid)
            break

    if len(paras) < 2:
        return None                                   # too thin to be an essay → let retrieval answer
    return Answer(text="\n\n".join(paras), grounded=True, cited=cited,
                  read={"engine": "essay", "topic": topic, "sections": len(paras)})


def answer(store, query: str, *, pool: int | None = None, ceiling: int | None = None) -> Answer:
    """A grounded, cited answer from real article text, or a plain statement that the corpus holds
    nothing the query's terms retrieve. Each result is rendered by its content type's own template
    (`ember.offer`), so the layout is the data's, not forced here. Cites the source article ids.

    The number of spans is derived, never requested. BM25 ranks the candidates and `_knee` cuts at
    the natural relevance break in the corpus's own scores, so the answer is exactly as long as the
    information supports — one span for a dominant answer, a cluster for a multi-facet topic, many
    for a broad one. `pool` is a scan budget; `ceiling` is opt-in and unset by default — both flagged
    seams that default honest, neither a fixed answer count."""
    ts = terms(query)
    if not ts:
        return Answer(text="", grounded=False, cited=[], read={"engine": "content", "reason": "no-terms"})
    # An essay/discussion request composes a structured synthesis across every tier.
    _essay = essay_answer(store, query)
    if _essay is not None:
        return _essay
    # Relation questions are reasoned (traverse the graph), not retrieved. Model-free.
    _isa = isa_answer(store, query)
    if _isa is not None:
        return _isa
    # Relates two things by their least-common-subsumer (model-free tree fact).
    _cmp = compare_answer(store, query)
    if _cmp is not None:
        return _cmp
    # Enumerates the kinds of a thing (its direct hyponyms — the inverse of is-a).
    _enum = enumerate_answer(store, query)
    if _enum is not None:
        return _enum
    _assoc = assoc_answer(store, query)
    if _assoc is not None:
        return _assoc
    # A verification request is checked (verified), not retrieved.
    _wedge = wedge_answer(store, query)
    if _wedge is not None:
        return _wedge
    # A question about the ember itself is answered from its own artifacts.
    _self = self_answer(store, query)
    if _self is not None:
        return _self
    # Solves/computes: percentages, rate×time, linear equations, arithmetic (model-free exact math).
    _math = math_answer(store, query)
    if _math is not None:
        return _math
    # If the query names a token the corpus has never attested (fires no synset and df==0), it
    # cannot be grounded: the answer names the absent token rather than letting retrieval land on a
    # filler self-hit. Real-but-rare tokens (attested, df>0) pass through to retrieval. Ranking-side
    # coverage (peak vs whole-need) is a separate measure; this covers only the absence half.
    _absent = _absent_content(store, query)
    if _absent:
        naming = ", ".join("'%s'" % a for a in _absent)
        return Answer(
            text="I don't have anything in the corpus on %s — %s not attested anywhere I hold."
                 % (naming, "it's" if len(_absent) == 1 else "they're"),
            grounded=False, cited=[],
            read={"engine": "content", "reason": "absent-token", "absent": _absent})
    # The token the query is most about, present in the corpus but with no position in the ontology
    # — an adjective, usually. After the absence check, which names its own case better, and before
    # retrieval, which would otherwise ground on the filler that is left and answer confidently
    # about it.
    _unplaced = _unplaced_subject(store, query)
    if _unplaced:
        return Answer(
            text="I can't place '%s' — it's in the corpus, but the ontology has no position for it, "
                 "so I'd be answering from the rest of the question rather than from what you "
                 "asked." % _unplaced,
            grounded=False, cited=[],
            read={"engine": "content", "reason": "unplaced-subject", "unplaced": _unplaced})
    cand = search(store, query, k=(pool if pool is not None else _POOL))
    # An empty lexical hit is not grounds to stop: the need's own position is always a candidate
    # (`_reach_rank`, §13.8). A headword whose gloss never repeats it is invisible to FTS, yet the
    # need still points straight at its synset — on the basics corpus, `water.n.06` ("binary
    # compound ... clear colorless liquid", where the string "water" appears nowhere in the gloss)
    # and `word.n.01` are reached this way. So an empty pool still carries through to reach, and the
    # answer comes back empty only if reach also finds no position — an honest unclosable gap, not
    # an index miss. The teleport (BM25) may land close without landing on the id itself; reach
    # measures the gap and ranks by it, carrying the residual so the answer accounts for how far it
    # actually reached.
    cand, _gap, reached = _reach_rank(cand or [], query, store)
    if not cand:
        return Answer(text="I don't have anything in the corpus that covers that.",
                      grounded=False, cited=[], read={"engine": "content", "reason": "no-hit"})
    # Condense, not cut: propagation is bounded only by physics (§13.22), so the answer cannot come
    # from selecting a prefix of what was reached — a cut discards, a condenser resolves. `condense`
    # reports what the reached set is (define / subsume / disambiguate / contrast / enumerate),
    # measured from its own shape, and the order it returns is the answer's order: the head first,
    # then only the members that add what the head does not.
    #
    # The cut survives as the fallback for a reached set the condenser cannot place (too few nodes,
    # or no ontology position at all — prose). Falling back is not a second path: it is the same
    # answer with less structure available to it, and `read.condensed` says which happened.
    _cond = None
    try:
        _cond = _condense_reached(store, query, cand)
    except Exception:
        _cond = None                 # a condenser that cannot read the shape must not eat the answer
    if _cond is not None and _cond.order:
        cand = _cond.order
    else:
        # The cut reads the screen. The frame is the reached candidates in reach order, each
        # carrying its own dense JC coordinate — exactly the (T, F) the instrument asks for — so
        # `k_signal` is a measurement of how many distinguishable things were reached rather than an
        # approximation of one: live, "photosynthesis" reads 1 and "cats and dogs" reads 2.
        _names = [cid[3:] for cid, _ct, _s in cand if cid.startswith("wn-")]
        _W = _projection.frame(store, _names) if _names else None
        cut = _relevance_cut([s for _, _, s in cand], query=query, frame=_W)
        cand = cand[: (min(cut, ceiling) if ceiling is not None else cut)]
    # A shown result must actually be about the query, and must not merely extend a subject already
    # shown (a derivative entity sharing the name — the corpus's own title containment, not a
    # cutoff).
    #
    # Aboutness defers to the measurement. Where the geometry placed a candidate (`reached`), its
    # distance to the need is its aboutness, and a substring test does not overrule it: the head
    # sense of "dog" ranks first on reach (energy 9.33 at distance 0.0) even though its title is
    # `Canis familiaris` and its gloss never says "dog" — the same reason BM25 alone buries it. The
    # lexical test applies only as a fallback, for candidates the geometry could not place at all,
    # which is where BM25 alone is doing the work and a title-sharing tangent ("Who Was…?") is a
    # real risk.
    try:
        sal = set(_salient(store.artifacts.db.read(), ts))
    except Exception:
        sal = set(ts)
    lines: List[str] = []
    cited: List[str] = []
    subjects: List[str] = []
    for aid, ct, _score in cand:
        art = store.artifacts.get_artifact(aid)
        if not art:
            continue
        text = resolve_text(store, art)
        if not text:
            continue
        if aid not in reached:
            hay = (str(art.get("title") or "") + " " + text).lower()
            if not any(t in hay for t in sal):
                continue
        line = _describe(store, art, ct, text)
        if not line:
            continue
        subj = line.split(":", 1)[0].strip().lower()
        if any(subj == s or subj.startswith(s + " ") or s.startswith(subj + " ") for s in subjects):
            continue
        subjects.append(subj)
        lines.append(line)
        cited.append(aid)
    # The crosswalk join. A reached synset and a wiki article the crosswalk found to be the same
    # concept carry different knowledge: the gloss says what the word means, the article says what
    # the thing is. Surfacing the article's content next to the gloss makes the answer encyclopedic,
    # not lexical — "twinkie" becomes the Twinkie article, not just "a small sponge cake". Additive
    # and bounded; empty on a corpus with no crosswalk, so a basics pupil is unaffected. This is the
    # step the reach could not take (hub-and-spoke edges vs one-hop outgoing).
    for aid in _aligned_articles(store, [c for c in cited if c.startswith("wn-")]):
        if aid in cited:
            continue
        art = store.artifacts.get_artifact(aid)
        atext = resolve_text(store, art) if art else None
        if not atext:
            continue
        title = (art.get("title") or "").strip()
        body = re.split(r"\n\s*\n", atext.strip(), 1)[0].strip()   # the article's own lead paragraph — a natural boundary, not a typed char count
        lines.append(("%s — %s" % (title, body)) if title else body)
        cited.append(aid)
    if not lines:
        return Answer(text="I don't have anything in the corpus that covers that.",
                      grounded=False, cited=[], read={"engine": "content", "reason": "no-hit"})
    # The answer must name what the query asked about. When the subject itself is absent from the
    # corpus, the reach can still place a lexical neighbour of some fragment — "quantum
    # entanglement" reaches `web.n.02` via "entangle", since there is no quantum_entanglement
    # synset. Presenting a neighbour as the answer would be a false ground, so a shown subject
    # counts only when it is on-topic: it shares a term with the query (stem overlap, robust to
    # plurals). If none of the wn subjects does, the retrieved set is a tangent rather than the
    # subject, and the answer says so instead of presenting the tangent. This is aboutness measured
    # against the query's own words, not a threshold, and it does not fire on a real hit: "dog" ->
    # dog, "water" -> water.n.06 (the gloss lacks the word, the lemma does not), "computer mouse" ->
    # mouse all share their term. `subjects` is only the wn heads, so a pure wiki/topic answer (no wn
    # subject) is untouched — this guards the lexical arm exactly where the tangent occurs.
    if subjects and not any(
            (t == w or t in w or w in t)
            for subj in subjects for w in re.split(r"[ _]+", subj) if w
            for t in ts if len(t) > 1):
        return Answer(text="I don't have that in the corpus. The individual words are in there, but not the concept you asked about — so I'd rather say so than answer the wrong thing.",
                      grounded=False, cited=[],
                      read={"engine": "content", "reason": "off-subject", "subjects": subjects, "reached": len(cand)})
    read = {"engine": "content", "hits": len(lines), "gap": _gap}
    if _cond is not None:
        # The answer states what shape it condensed into, and why: a condensation without its
        # evidence is a confident number with nothing behind it.
        read["condensed"] = _cond.kind
        read["head"] = _cond.head
        read["why"] = _cond.basis.get("why")
        # The measurement itself, not just its consequence. `k_signal` is what the instrument read off
        # the screen; `None` means no frame could be built (too few rows to carry a read), which is
        # a different statement from `0` (a screen that reads as undifferentiated).
        read["k_signal"] = _cond.basis.get("k_signal")
        read["rows"] = _cond.basis.get("reached")
    return Answer(text="\n\n".join(lines), grounded=True, cited=cited, read=read)


__all__ = ["terms", "search", "answer"]
