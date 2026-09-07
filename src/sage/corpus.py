# Operator code's authoritative home is chorus. Distributed to hosts as a content-addressed source
# bundle (agience-observe/build_bundles.py); ember executes it via ember/runtime/runner.py,
# sha-verified before exec. There are no code mirrors.
"""Corpus hygiene — deterministic operators that keep the corpus improving.

Corpus quality is its own flywheel. These operators are deterministic (hashing + set overlap; no
model):

- audit           : health report — dark matter (undescribed), by content-type, dup pressure.
- exact_duplicates: group by content hash (content-addressing). Exact clones.
- near_duplicates : Jaccard over content shingles >= threshold. "virtually the same content."
- dedup           : collapse a duplicate class to a canonical representative, archive the rest.

Category-theory framing (the organizing principle, not a new algorithm): de-dup is a quotient — an
equivalence relation ("same content") collapses each class to a canonical representative, and the
merged node preserves the morphisms (edges) of the ones it absorbs (a coequalizer / pushout).
Canonical = representative of the equivalence class.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

_SYMBOL_CT = "text/x-python-symbol"
_OP_CT = "application/vnd.agience.operator+json"
_SRC_CT = "application/vnd.agience.source+json"
_STRUCTURAL = {_SYMBOL_CT, _OP_CT, _SRC_CT}   # not content docs; excluded from dedup/dark-matter


from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type

# ── the one resolution — imported, not copied ───────────────────────────────────────────────────
#
# `exact_limit` and `signal_end` need neither numpy nor entroptics, so `prism.resolution` carries
# them in prism's dependency-free base: `agience-prism-py` installs with no dependencies at all,
# every host that runs a bundle already has it, and this module imports the one definition rather
# than keeping a standalone copy.
#
# The import is unguarded: a `try/except` fallback here would rebuild the copy this replaces, and a
# host without prism cannot verify a bundle's sha either, so failing loudly at load is the honest
# report. (`crystal.evolution` above is imported the same way, for the same reason.)
#
# `tests/test_corpus_resolution_is_not_a_second_copy.py` sweeps `prism.resolution` against an
# independent implementation over shared inputs, to catch drift between the two.
from prism.resolution import exact_limit as _exact_limit, signal_end as _signal_end

_CORPUS_OPS = [
    ("op.corpus.audit", "reports corpus health: dark matter, content-types, duplication pressure"),
    ("op.corpus.near_duplicates", "finds near-identical artifacts (shingled Jaccard) — quotient candidates"),
    ("op.corpus.dedup", "collapses a duplicate class to a canonical representative, archives the rest"),
]


def register_corpus_operators(store, *, author: str = "ember-local") -> int:
    from crystal import evolution
    for name, offer in _CORPUS_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": f"corpus operator {name}: {offer}",
            "created_by": author}))
    return len(_CORPUS_OPS)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def _shingles(text: str, k: int = 5) -> set:
    """k-word shingles — order-sensitive fingerprints, so reformatting doesn't hide a near-dup."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def audit(store) -> Dict:
    """A deterministic health report over the committed corpus.

    A full pass, deliberately: totals, per-content-type counts, and the dark-matter count are
    defined over every committed artifact, so any bound would change the answer, not just its cost.
    Not a hot path — on demand only (op.corpus.audit); nothing on the worker tick calls it."""
    by_type: Dict[str, int] = defaultdict(int)
    dark = 0            # content docs with no lemmas (undescribed -> only model-findable)
    total = 0
    for a in store.list_artifacts(state="committed"):
        total += 1
        ct = a.get("content_type", "?")
        by_type[ct] += 1
        if ct not in _STRUCTURAL and ct != "text/x-wordnet" and not a.get("lemmas"):
            dark += 1
    return {"total": total, "by_content_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
            "dark_matter_docs": dark}


def _text(bundle, a) -> str:
    """Full content — from the content store via content_ref (content is stored by reference,
    not inline). Falls back to the inline preview if there's no bundle/ref."""
    if bundle is not None:
        # Loaded two ways (bundle module vs persona-load bare name) — see the note on the same
        # import in `lumen/arithmetic.py`. Relative resolves the bundle sibling; bare resolves
        # under the persona-load convention. Bare-only silently un-bundles this module.
        try:
            from . import content as C
        except ImportError:
            import content as C
        return C.resolve_text(bundle, a)
    return a.get("content") or ""


def exact_duplicates(store, *, content_types: Optional[Iterable[str]] = None,
                     bundle=None) -> List[List[dict]]:
    """Groups of >=2 artifacts with identical content (by hash). Uses `content_ref` when
    present (already a content-address) — exact dedup for free.

    A full pass, deliberately: a duplicate class is only knowable once every artifact has been
    hashed, so any bound would drop real duplicates, not just cost. On demand only — no tick path
    calls it. Pushing `content_types` into the query would not help either: those values are the
    bulk ones, and an indexed equality is a scan when the value matches most of the corpus (measured
    on node 71, 5,657,386 rows: text/markdown timed out at 120s, a 48-row type took 0.12s)."""
    cts = set(content_types) if content_types else None
    groups: Dict[str, List[dict]] = defaultdict(list)
    for a in store.list_artifacts(state="committed"):
        if cts is not None and a.get("content_type") not in cts:
            continue
        key = a.get("content_ref") or _content_hash(_text(bundle, a))
        groups[key].append(a)
    return [g for g in groups.values() if len(g) > 1]


def indistinguishable(union_shingles: int) -> float:
    """The Jaccard at which two documents differ by less than one shingle — i.e. the exact
    estimator cannot tell them apart from identical.

    Exact Jaccard over k-shingles has no sampling error, so its resolution is not a standard error;
    it is granularity. The smallest difference the measure can express is one shingle out of the
    union, so `1 - 1/|union|` is the point past which "similar" and "identical" are the same
    reading. Derived per pair, from the pair — nothing chosen.

    This is `prism.resolution.exact_limit`, not a restatement of it. The domain word stays here
    because "one shingle out of the union" is what `|union|` means in this operator; the arithmetic
    lives in the one place that owns it."""
    return float(_exact_limit(union_shingles))


def near_duplicates(store, *, content_types: Iterable[str], threshold: Optional[float] = None,
                    k: int = 5, bundle=None, limit: int = 3000) -> List[Tuple[dict, dict, float]]:
    """Pairs of near-identical artifacts (Jaccard over k-shingles >= threshold), within the
    given content types.

    `threshold=None` means the estimator's own resolution (`minhash.merge_boundary()`) rather than a
    chosen constant. Resolves full content (via content_ref). Pairwise (O(n^2)) — fine for a bounded
    set (docs); for whole-corpus scale, swap in MinHash-LSH (deterministic)."""
    # Streaming stops at `limit` rather than materializing the entire corpus and slicing afterward —
    # at 5M rows, materializing then slicing would take roughly 370s (~500 keyset pages at ~743ms
    # each) to keep the first 3000 matches. The stream is in id order, so breaking early keeps
    # exactly the same first `limit` artifacts a full materialize-then-slice would.
    cts = set(content_types)
    arts: List[dict] = []
    for a in store.list_artifacts(state="committed", content_type=None):
        if a.get("content_type") not in cts:
            continue
        arts.append(a)
        if len(arts) >= limit:
            break
    shs = [_shingles(_text(bundle, a), k) for a in arts]
    scored: List[Tuple[dict, dict, float, int]] = []
    for i in range(len(arts)):
        for j in range(i + 1, len(arts)):
            si, sj = shs[i], shs[j]
            union = len(si | sj)
            s = _jaccard(si, sj)
            if s > 0.0:
                scored.append((arts[i], arts[j], s, union))
    if threshold is not None:
        out = [(a, b, round(s, 3)) for a, b, s, _u in scored if s >= threshold]
        out.sort(key=lambda t: -t[2])
        return out
    scored.sort(key=lambda t: -t[2])
    # The domain fact that makes "can say no" the load-bearing property here is kept at the call
    # site because it is about this series, not about the statistic: on the real corpus, the
    # near-duplicate score distribution decays smoothly from 0.2 to 0.94 across 1,661 pairs with no
    # valley to cut at, so a rule that always returns a position (an argmax of adjacent ratios)
    # reports a break that is not there. `signal_end` gates the split on its own computed null and
    # returns the whole series when nothing separates.
    cut = _signal_end([s for _a, _b, s, _u in scored])
    return [(a, b, round(s, 3)) for a, b, s, _u in scored[:cut]]


# Files that are expected to be duplicated per-repo (legal / config) — never a cleanup target.
_PER_REPO_KEEP = {"license", "license.md", "cla.md", "commercial_license.md", "notice",
                  "notice.md", "contributing.md", "code_of_conduct.md", "readme.md",
                  "changelog.md", ".gitignore", "pledge.md", "patents.md", "security.md",
                  "governance.md", "authors.md", "maintainers.md", "trademarks.md"}


def _fname(a) -> str:
    return (a.get("content", "").split("\n", 1)[0] or a.get("id", "")).split("/")[-1]


def _repo(a) -> str:
    parts = (a.get("content", "").split("\n", 1)[0]).split("/")
    for i, p in enumerate(parts):
        if p.startswith("agience-") or p.endswith(".agience.ai"):
            return p
    return "?"


def doc_cleanup_report(store, *, bundle=None, threshold: Optional[float] = None) -> Dict:
    """Categorizes the documentation for cleanup, as evidence rather than action. Deterministic;
    touches no files.

    `threshold=None` means the estimator's own resolution (`minhash.merge_boundary()`), which is
    `1 - 1/(k+1)` — derived from how many hashes the instrument computes, not a chosen sense of
    "similar enough".

    Categories:
      keep_per_repo   near-dup groups that are legal/config (LICENSE/CLA/…) — stay per-repo
      redundant       near-dup groups that are genuinely redundant docs (merge/archive candidates)
      dark            docs with no lemmas (undescribed)
    Nothing is deleted — a human reviews the report and decides."""
    near = near_duplicates(store, content_types=["text/markdown"], threshold=threshold, bundle=bundle)
    # union-find over near-dup pairs -> groups
    parent: Dict[str, str] = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    byid: Dict[str, dict] = {}
    for x, y, _s in near:
        byid[x["id"]] = x; byid[y["id"]] = y
        parent.setdefault(x["id"], x["id"]); parent.setdefault(y["id"], y["id"])
        parent[find(x["id"])] = find(y["id"])
    groups: Dict[str, List[dict]] = defaultdict(list)
    for aid in list(parent):
        groups[find(aid)].append(byid[aid])

    keep, redundant = [], []
    for g in groups.values():
        if len(g) < 2:
            continue
        entry = {"files": sorted({_fname(a) for a in g}),
                 "repos": sorted({_repo(a) for a in g}), "ids": [a["id"] for a in g],
                 "count": len(g)}
        if any(_fname(a).lower() in _PER_REPO_KEEP for a in g):
            entry["reason"] = "legal/config — belongs in every repo"
            keep.append(entry)
        else:
            entry["canonical"] = min(g, key=lambda a: (len(a["id"]), a["id"]))["id"]
            redundant.append(entry)

    # A full pass, and it must be: this is a count of markdown docs with no lemmas. `lemmas IS NULL`
    # can never be index-served (LSM nullStrategy is SKIP), and the content_type index does not save
    # it either — text/markdown is a bulk value (~6M of the 5,657,386 rows on node 71; count(*) on it
    # timed out at 120s where a 48-row type took 0.12s). Acceptable: doc_cleanup_report is on demand
    # only, and the near_duplicates call above already dominates its cost.
    dark = sum(1 for a in store.list_artifacts(content_type="text/markdown") if not a.get("lemmas"))
    return {"near_dup_groups": len(groups), "keep_per_repo": keep,
            "redundant": sorted(redundant, key=lambda e: -e["count"]), "dark_docs": dark}


def dedup(store, groups: List[List[dict]], *, apply: bool = False) -> Dict:
    """Collapse each duplicate group to a canonical representative (the shortest id — stable),
    archiving the rest. Dry-run by default. Edge-preservation (re-pointing edges to the canonical)
    is out of scope here; archived dupes keep their ids so nothing dangles."""
    archived, canonicals = 0, []
    for g in groups:
        canonical = min(g, key=lambda a: (len(a["id"]), a["id"]))
        canonicals.append(canonical["id"])
        for a in g:
            if a["id"] == canonical["id"]:
                continue
            if apply:
                doc = dict(a); doc["state"] = "archived"; doc["canonical"] = canonical["id"]
                store.put_artifact(doc)
            archived += 1
    return {"groups": len(groups), "canonicals": canonicals[:20],
            "archived": archived, "applied": apply}
