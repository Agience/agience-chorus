"""Read by paragraph, chop by what they share — the overlap is the colimit, taken with math.

What two artifacts share is itself an artifact. A paragraph arrives whole; the substring two
paragraphs have in common is their intersection, and an intersection is a colimit computed rather
than a rule about words applied. Nothing here knows what a word is.

What they share is exact, so there is nothing to threshold. A maximal repeat occurs at least twice
and cannot be extended without losing an occurrence:

    occurrences >= 2                     shared at all — once is a hapax, not a repeat
    extending left loses an occurrence   and extending right does too   → maximal

Extend it and it stops being shared; shorten it and it is not maximal. No minimum length, no
frequency bar, no vocabulary size, no merge count. On 60,000 characters of Pride & Prejudice this
finds 15,248 maximal repeats in 0.7s, of which 2,957 are alphabetic and longer than two characters —
`red`, `Darcy`, `Elizabeth`, `sister`, and `love` among them.

This agrees with the bottom-up route: iterating the organon's own PMI junction rule over its output
(`t`+`h`+`e` → `the`, closing after 7 passes) forms the same words from the opposite direction. Two
independent derivations converging is evidence; either alone is a method.

Degrees of freedom are a measurement, not a label. A paragraph covered by many overlapping shared
spans can be decomposed many ways and is flexible; one covered by few is rigid. On the same window,
the median is 53 spans per paragraph (min 0, max 550). It is written onto the paragraph artifact
because it is a property the reading measured, not a category assigned to it.
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional, Sequence, Tuple

TOKEN_CT = "application/x-token"
PARA_CT = "application/x-paragraph"
#: What separates two paragraphs in the incoming text. Named once so `read` and `main` cannot come to
#: disagree about where a paragraph ends — an off-by-one there misaligns every `meta` entry after it.
PARA_SEP = "\n\n"
# The edge is the triple: `src` is the context, `label` is the operator, `dst` is the content. A
# vertex carries no separate `context`/`operator` fields, because a span occurs in many paragraphs —
# the context is a property of each occurrence, and the occurrence is exactly `src --label--> dst`.
#
# The operator distinguishes two acts: a span this paragraph shares with others, and a part that is
# unique to it. Those are the two halves of the decomposition and they mean opposite things — one is
# what the reading has seen elsewhere, the other is what only this paragraph says.
OBSERVED = "observed"        # this context observed this span. That is the whole act.

# There is one operator, not two. A second operator meaning "this part occurs nowhere else" would
# assert a fact about the whole corpus and freeze it into a single occurrence's edge — but the
# reading accumulates, so the next batch can falsify that assertion and nothing rewrites it. It
# would also duplicate the graph: whether a span is shared is its in-degree, and a stored count
# alongside the graph is a second source of truth that can diverge from it. And it would not be an
# act: the triple is `context --operator--> content`, and both "shared" and "occurs nowhere else"
# are the same act of observing — "alone" is a count of everyone else, not a way of observing.
#
# Sharedness is measured where it is asked, by `read_basis.unit_contexts` — derived, self-updating,
# one implementation.
#
# Readers accept both labels: `query_neighbourhood`, `organon_reader` and `read_basis` all match
# `label IN ('observed','observed_alone')`, because some collections on disk hold `observed_alone`
# edges from an earlier writer. Narrowing the readers to `observed` alone would silently drop that
# history, so both labels are honoured on read — this module writes only `OBSERVED`.
SHARED = OBSERVED            # aliases — both name the one operator
ALONE = OBSERVED


def _suffix_array(s: str) -> Tuple[List[int], List[int]]:
    """Order every suffix — prefix doubling, O(n log^2 n)."""
    n = len(s)
    k = 1
    rank = [ord(c) for c in s]
    tmp = [0] * n
    sa = list(range(n))
    while True:
        key = lambda i: (rank[i], rank[i + k] if i + k < n else -1)
        sa.sort(key=key)
        tmp[sa[0]] = 0
        for i in range(1, n):
            tmp[sa[i]] = tmp[sa[i - 1]] + (key(sa[i - 1]) < key(sa[i]))
        rank = tmp[:]
        if rank[sa[-1]] == n - 1:
            break
        k <<= 1
    return sa, rank


def _lcp(s: str, sa: List[int], rank: List[int]) -> List[int]:
    """Kasai: longest common prefix of adjacent suffixes."""
    n = len(s)
    out = [0] * n
    h = 0
    for i in range(n):
        if rank[i] > 0:
            j = sa[rank[i] - 1]
            while i + h < n and j + h < n and s[i + h] == s[j + h]:
                h += 1
            out[rank[i]] = h
            if h:
                h -= 1
        else:
            h = 0
    return out


def shared_spans(text: str) -> Dict[str, int]:
    """Every maximal repeat, with how many adjacent-suffix boundaries witnessed it.

    The count is a witness count, not an occurrence count: it is how many times the span appeared at
    an LCP boundary, which is a lower bound on its occurrences."""
    sa, rank = _suffix_array(text)
    lcp = _lcp(text, sa, rank)
    out: Dict[str, int] = {}
    for i in range(1, len(text)):
        L = lcp[i]
        if L <= 0:
            continue
        a, b = sa[i - 1], sa[i]
        # Left-maximal: the preceding characters differ, so extending left loses an occurrence.
        # Right-maximality is already carried by the LCP boundary.
        if a > 0 and b > 0 and text[a - 1] == text[b - 1]:
            continue
        span = text[b:b + L]
        out[span] = out.get(span, 0) + 1
    return out


def shared_cover(text: str):
    """The longest maximal repeat covering each position, computed in one pass over the text.

    The suffix array already knows where every span occurs: `a` and `b` in the LCP walk are
    occurrences, so marking the cover as they are found costs one pass, and every paragraph is then a
    slice of it rather than a per-span, per-paragraph `str.find` search.

    Returns a list where `cover[i]` is `(start, end)` of the longest shared span covering `i`, or
    None where nothing shared covers it — that position is the text's own.
    """
    sa, rank = _suffix_array(text)
    lcp = _lcp(text, sa, rank)
    n = len(text)
    cover = [None] * n
    best = [0] * n
    for i in range(1, n):
        L = lcp[i]
        if L < 2:
            continue
        a, b = sa[i - 1], sa[i]
        if a > 0 and b > 0 and text[a - 1] == text[b - 1]:
            continue                       # not left-maximal
        for start in (a, b):
            end = min(start + L, n)
            if L > best[start]:
                for k in range(start, end):
                    if L > best[k]:
                        best[k] = L
                        cover[k] = (start, end)
    return cover


def cut_by_cover(text: str, cover, base: int) -> List[str]:
    """The parts of `text` (which begins at `base` in the covered document) — a slice, not a search."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = i + 1
        c = cover[base + i] if base + i < len(cover) else None
        while j < n and (cover[base + j] if base + j < len(cover) else None) == c:
            j += 1
        out.append(text[i:j])
        i = j
    return out


def decompose(text: str, spans) -> List[str]:
    """Break `text` where the longest covering shared span changes — the parts are its concepts.

    Each position takes the longest shared span covering it, and a run of positions under the same
    cover is one part — median 11 parts per paragraph on Pride & Prejudice, concept-sized.
    Deterministic; nothing ranked, nothing capped.

    A rare name shatters, and that is correct: `Saintsbury` comes out as `S`,`aint`,`s`,`b`,`ur`,`y`
    because the text shares almost none of it. What a paragraph shares becomes a concept; what it
    alone says stays fine-grained, and flattening that would claim structure the reading never saw.
    """
    n = len(text)
    cover = [None] * n
    best = [0] * n
    for sp in spans:
        if len(sp) < 2:
            continue
        i = text.find(sp)
        while i >= 0:
            L = len(sp)
            for k in range(i, min(i + L, n)):
                if L > best[k]:
                    best[k] = L
                    cover[k] = (i, i + L)
            i = text.find(sp, i + 1)
    out, i = [], 0
    while i < n:
        j = i + 1
        while j < n and cover[j] == cover[i]:
            j += 1
        out.append(text[i:j])
        i = j
    return out


# There is no local `witness_count` here: counting a span's citing contexts from
# `graph.neighbors(direction="in")` would be a second definition of a fact
# `ember/signal/projection.py::read_unit_contexts` already answers, and answers better — one indexed
# range over `src` for the whole collection, against one `neighbors()` call per span. A stored
# `witnesses` field or a second `observed_alone` operator would be a second source of truth about
# sharedness, alongside the graph itself; a local witness count would be the same mistake with
# better manners.
#
# Sharedness is `read_basis.unit_contexts(ro, collection)[unit_id]` — the contexts holding a unit,
# measured when asked, one implementation. `read_basis.coordinates()` is what a residual read runs on
# ("project onto the resolved basis and measure what is absorbed").


def read(store, collection: str, text: str, *, budget: float = 25.0,
         meta: Optional[Sequence[Dict[str, object]]] = None) -> Dict[str, object]:
    """Write the paragraphs and the spans they share into `collection`.

    The budget is a measurement envelope, not a cap on the answer: the span set is computed whole, and
    the budget only bounds how much of the paragraph-to-span linking is done in one call. What is
    skipped is reported in the return value rather than left silent.

    `meta` is per-paragraph provenance, one entry per paragraph, in the same order. A paragraph
    usually has facts that are true of it but are not in it: when it was published, where it came
    from, which instrument it names. Those belong on the artifact, never in the text — a timestamp
    prepended to the text is unique by construction, so every paragraph would carry an unrepeatable
    span and the residual would measure the clock rather than the news. The text must not carry
    provenance, and the artifact must, which is what `meta` is for.

    A length mismatch refuses rather than zipping short: silently zipping a short `meta` against the
    paragraphs would attach each fact to the wrong paragraph from the first gap onward, and every
    downstream time-join would be confidently wrong with nothing able to detect it later.
    """
    t0 = time.time()
    # Offsets are kept because `split` loses them, and the cover is indexed by position in the whole
    # document, so each paragraph must know where it starts.
    paras, off, _pos = [], [], 0
    for chunk in text.split(PARA_SEP):
        if chunk.strip():
            paras.append(chunk)
            off.append(_pos)
        _pos += len(chunk) + 2
    if meta is not None and len(meta) != len(paras):
        raise ValueError(
            "meta has %d entries for %d paragraphs — refusing to align them. Off by one and every "
            "paragraph after the gap carries another's provenance, which nothing downstream can "
            "detect." % (len(meta), len(paras)))
    spans = shared_spans(text)
    cover = shared_cover(text)

    # Span artifacts are written for what is cited, not for every repeat: only the spans in a
    # paragraph's cover get an edge, since `cut_by_cover` selects a decomposition, not the whole
    # repeat set. A span with no citing context can never seed an instrument read, so writing the
    # whole repeat set up front would leave most span artifacts with in-degree zero — an artifact
    # asserting a unit the graph never observed is the same defect a stored `witnesses` count or a
    # second `observed_alone` operator would be: a claim at write time the graph does not support.
    #
    # The repeat set is still the measurement that decides the cover; it is distinct from the
    # record of what was observed.
    span_rows, para_rows, edges = [], [], []
    cited: Dict[str, None] = {}

    skipped = 0
    for n, p in enumerate(paras):
        pid = "%s:para-%d" % (collection, n)
        if time.time() - t0 > budget:
            skipped = len(paras) - n
            break
        covering = cut_by_cover(p, cover, off[n])   # a slice of the global cover, not a search
        doc = {
            "id": pid, "content_type": PARA_CT, "name": "para-%d" % n,
            "collection_id": collection, "collections": [collection],
            "created_by": "ember-source",
            # A paragraph is a context, so it does not carry one — it is the `src` every occurrence
            # edge points out of, and its operator is likewise the edge's, not a field. The full
            # paragraph is stored, unabridged: truncating it would leave the distance between a query
            # term and a returned span uncomputable past the cut.
            "content": p,
            # Degrees of freedom: how many ways this artifact can be decomposed, as measured here.
            "degrees_of_freedom": len(covering), "chars": len(p)}
        if meta is not None:
            # The reading's own measurements win: caller provenance is merged under the fields
            # above, never over them, so a `meta` carrying `degrees_of_freedom` or `content` cannot
            # overwrite what this function measured. Provenance describes the paragraph; it does not
            # read it.
            doc = dict(meta[n] or {}, **doc)
        para_rows.append((pid, PARA_CT, json.dumps(doc)))
        for s in dict.fromkeys(covering):
            cid = "%s:span:%s" % (collection, s.encode("utf-8").hex())
            if s not in cited:
                cited[s] = None
                # Written here, when a context cites it — so every span artifact has at least one
                # edge by construction, so a span cited by nothing becomes an anomaly worth noticing
                # rather than the majority.
                span_rows.append((cid, TOKEN_CT, json.dumps({
                    "id": cid, "content_type": TOKEN_CT, "name": s,
                    "collection_id": collection, "collections": [collection],
                    # A span carries no `context`/`operator` of its own — it occurs in many
                    # paragraphs, so the context is a property of each occurrence, and the occurrence
                    # is exactly `src --label--> dst`. What the artifact holds is what is true of the
                    # span itself, which is its text and its length. Not its count: that is the
                    # graph's, and it changes as the reading accumulates.
                    "created_by": "ember-source", "content": s, "length": len(s)})))
            # One operator, because there is one act: this paragraph observed this span. Whether the
            # span is shared is not a property of this occurrence and is not recorded here — it is the
            # span's citing contexts, measured when someone asks (`read_basis.unit_contexts`).
            edges.append((pid, cid, OBSERVED, json.dumps({"of": "para-%d" % n})))

    # Writes go through the store, not raw SQL: `put_artifact` allocates `_seq` and stamps `_origin`
    # (proper time — without it a row can never publish and never merkle-verify); `add_edges` computes
    # the `edge_key` digest and is idempotent on it. `collection_member` is not written by hand either —
    # the artifact's own `collections` field carries it, so the side-car table cannot drift from the
    # artifact.
    #
    # `add_edges` returns the number handled, which callers use as a data-loss guard: the shortfall
    # below is checked and raised rather than left to go unnoticed.
    for _aid, _ct, _doc in span_rows + para_rows:
        store.artifacts.put_artifact(json.loads(_doc))
    handled = store.graph.add_edges([(s, d, l, json.loads(pr)) for (s, d, l, pr) in edges])
    if handled < len(edges):
        raise RuntimeError(
            "edge write shortfall: %d of %d handled — rows were LOST, not merely rejected. "
            "Refusing to report a complete read." % (handled, len(edges)))

    dof = [json.loads(r[2])["degrees_of_freedom"] for r in para_rows]
    return {"paragraphs": len(para_rows), "spans": len(span_rows), "edges": handled,
            "skipped_paragraphs": skipped,
            "dof_median": sorted(dof)[len(dof) // 2] if dof else 0,
            "seconds": round(time.time() - t0, 1)}


def main() -> int:
    import argparse
    import os
    import sys
    ap = argparse.ArgumentParser()
    # The text is a corpus file, not part of the checkout: the caller names it, as
    # `organon_reader` already requires. A default here could only be right on one box.
    ap.add_argument("--text", required=True, help="the text to read")
    ap.add_argument("--collection", default="read:overlap")
    ap.add_argument("--chars", type=int, default=60000)
    # Per-paragraph provenance: a JSON array, one object per paragraph, in the same order as the
    # text's paragraphs. What is true of a paragraph but not in it — when it was published, where it
    # came from — belongs here, never prepended to the text (see `read`'s docstring for the
    # contamination that caused).
    ap.add_argument("--meta", default=None, help="JSON array of per-paragraph provenance objects")
    a = ap.parse_args()

    # One data path: the store resolves its own location from `EMBER_SQLITE_DIR`/`EMBER_SQLITE_DB`,
    # and there is no way to hand this module a bare file to open a raw connection beside it.
    from mantle.shard.local_store import open_store
    store = open_store()

    # There is no `--reset`: deleting artifacts would leave their edges behind, pointing at spans
    # that no longer exist, and a reader walking those gets a dangling `dst` with no error. The
    # reading also accumulates rather than needing a reset to re-run: `add_edges` is idempotent on
    # `edge_key` and `put_artifact` is keyed by id, so re-reading the same text converges instead of
    # duplicating. To genuinely start over, make a new collection name — nothing is overwritten by
    # feeding more in.

    text = open(a.text, encoding="utf-8", errors="replace").read()[:a.chars]
    meta = None
    if a.meta:
        meta = json.loads(open(a.meta, encoding="utf-8").read())
        # `--chars` truncates the text, so the paragraph count can be smaller than the meta file.
        # `read` refuses a mismatch rather than zipping, so trim to the paragraphs that survive the
        # truncation — the alignment is by position and must stay exact.
        kept = len([c for c in text.split(PARA_SEP) if c.strip()])
        meta = meta[:kept]
    out = read(store, a.collection, text, meta=meta)
    for k in ("paragraphs", "spans", "edges", "skipped_paragraphs", "dof_median", "seconds"):
        print("  %-20s %s" % (k, out[k]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
