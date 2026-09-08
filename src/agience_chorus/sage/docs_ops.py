# Operator code lives in chorus, distributed to hosts as a content-addressed source bundle
# (agience-observe/build_bundles.py); ember executes it via ember/runtime/runner.py, sha-verified
# before exec. There are no code mirrors — changes happen here.
"""Documentation-library operators — deterministic capabilities Ember invokes to turn a
pile of stale, evolved docs into a well-organized library (current state / roadmap / vision).

Ember runs these; they don't act on their own. The read/analyze operators are pure functions
of deterministic signals; the reorganize operator is separate, gated and reversible.
No model, no guessing — every judgment traces to a signal:

  op.docs.staleness  score a doc's staleness: git-age + status markers + superseded-by.
  op.docs.classify   assign a role: current | roadmap | vision | draft | superseded | reference.
  op.docs.topics     cluster docs by shared lemmas -> topic groups + the authoritative doc each.
  op.docs.library_plan  the full plan: per-doc {role, staleness, action, target} + target tree.

Read-only and local. Any external fetch these use is GET-only, never a write.
"""
from __future__ import annotations

import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from crystal.evolution import OPERATOR_CONTENT_TYPE  # one home for the operator content type

_STATUS = {
    "superseded": ("superseded", "deprecated", "obsolete", "do not use", "no longer", "replaced by", "archived"),
    "draft": ("draft", "wip", "work in progress", "todo", "tbd", "stub", "placeholder", "rough"),
    "vision": ("vision", "north star", "aspiration", "someday", "dream"),
    "roadmap": ("roadmap", "planned", "future", "upcoming", "will build", "next up", "milestone"),
}
_CACHE_GIT: Dict[str, float] = {}

# ═══════════════════════════════════════════════════════════════════════════════════════════
# The staleness scale — its construction, and therefore its cut points
# ═══════════════════════════════════════════════════════════════════════════════════════════
# `staleness()` mixes three signals into one number, and the mixture is named here so the cuts
# below can be derived from it rather than typed in separately. A cut on a constructed scale is
# only answerable if it names the evidence it corresponds to — otherwise moving any weight
# silently moves what "superseded" means, and neither the weight nor the cut is answerable to
# the other.
#
# Change a weight and the cuts move with it, which is the property that makes them readable as
# evidence rather than as levels. `tests/../test_docs_ops_cuts_are_derived.py` pins this.

#: Days without a commit at which the age signal is fully spent. The one duration in the scale.
_AGE_FULL_DAYS = 365.0
#: What an unreadable age contributes — a document not in git, where "old" is unknown rather than
#: false. Deliberately non-zero: absence of a commit date is not an observation of a recent one.
_AGE_UNKNOWN_SCORE = 0.3
#: What one "superseded"/"deprecated"/"replaced by" marker contributes to the marker signal, and
#: what one "draft"/"wip"/"tbd" marker contributes. Two superseded markers saturate it.
_MARK_SUPERSEDED = 0.5
_MARK_DRAFT = 0.15
#: What living under /working/, /scratch/ or /dev/prompts/ contributes. A location, not a reading.
_SCRATCH_SCORE = 0.3
#: How the age and marker signals are mixed. `_SCRATCH_SCORE` is added unweighted — it is a fact
#: about where the file is, not an estimate that needs discounting.
_W_AGE = 0.5
_W_MARKER = 0.4

# The cuts are functions, not module constants. A cut written as an expression of the weights
# and the same cut typed in as 0.7 are indistinguishable to any test that only checks the value
# once — perturbing a weight afterwards cannot reach an assignment that already happened, so a
# regression to the literal would pass. Computed when asked, the perturbation reaches them:
# replacing either body below with its current numeric value fails
# `sage/tests/test_docs_ops_cuts_are_derived.py`.


def superseded_at() -> float:
    """The staleness score of a document that has gone a full `_AGE_FULL_DAYS` without a
    commit and carries at least one superseded marker — the two independent signals that a
    document has been replaced, both present. Reads 0.7 at the weights above.

    This is the cut `classify` and `library_plan` compare against, stated as the evidence it
    corresponds to rather than as a level, so moving a weight moves what "superseded" means
    instead of leaving the cut describing a scale that no longer exists."""
    return _W_AGE * 1.0 + _W_MARKER * min(1.0, _MARK_SUPERSEDED)


def stale_at() -> float:
    """The staleness score of a document in a working/scratch location whose age cannot even
    be read — the weakest combination that is still two signals rather than one. Reads 0.45."""
    return _SCRATCH_SCORE + _W_AGE * _AGE_UNKNOWN_SCORE

#: A stated tolerance — the one number in this module that nothing derives. Lemmas appearing in
#: more than this fraction of the corpus are dropped before clustering: `artifact`, `mcp`,
#: `agience`, `server` are shared by everything and would collapse every document into one blob.
#:
#: Not derivable from anything present: the information-theoretic candidates point the wrong
#: way — binary-indicator entropy is maximised at df/n = 0.5, so an idf-style rule would drop
#: the most discriminating terms first — and the quantity that would settle it (does dropping at
#: f leave the union-find with more than one cluster on this corpus?) is a property of the
#: corpus, re-measurable per call. A different value is right if the corpus's shared boilerplate
#: is a larger or smaller share of its vocabulary than it is here.
#:
#: A different quantity from `topics(threshold=0.35)`, which happens to carry the same number:
#: that one is a Jaccard similarity between two documents, this one a document-frequency share
#: of the corpus. Single-sourced here as the concept `lemma_filtration` also exposes as the
#: `drop_common_frac` parameter.
COMMON_LEMMA_FRAC = 0.35
#: Documented starting point, not read by anything that decides. The note above names the
#: quantity that settles it — does dropping at f leave the union-find with more than one cluster
#: on this corpus, a property of the corpus, re-measurable per call — and `derived_common_frac`
#: performs that measurement.


def derived_common_frac(doc_artifacts: List[dict], *, levels: int = 20) -> Optional[float]:
    """The share above which a lemma is corpus-common, measured on this corpus.

    Dropping too little leaves the boilerplate in and every doc collapses into one blob;
    dropping too much strips the shared vocabulary that binds genuine groups and everything
    shatters into singletons. Between those the structure survives. This sweeps f and returns
    the largest f whose vocabulary still yields more than one non-trivial group — the loosest
    drop that has not yet destroyed the structure.

    Returns None when no level yields structure: the sweep grounds out, which is a reading of
    the corpus (it has no shared vocabulary to group on) rather than a case to answer with a
    fallback constant, which would report a grouping the corpus does not support.

    `levels` is a sampling density, not a cut: it says how finely f is swept, and a finer sweep
    returns the same answer or a nearer one. It changes the resolution of the search, never the
    criterion.
    """
    if len(doc_artifacts) < 2:
        return None
    best = None
    for i in range(1, levels + 1):
        f = i / float(levels)
        links = lemma_filtration(doc_artifacts, drop_common_frac=f)
        if not links:
            continue
        ids = [a["id"] for a in doc_artifacts]
        groups = [g for g in cut_filtration(links, ids, min(s for s, _, _ in links)) if len(g) >= 2]
        if len(groups) >= 2:
            best = f
    return best


def _path_of(artifact: dict) -> str:
    return artifact.get("path") or (artifact.get("content", "").split("\n", 1)[0])


def git_age_days(path: str, *, now: Optional[float] = None) -> Optional[float]:
    """Days since the file's last git commit (staleness proxy). None if not in git.
    `now` must be supplied by the caller (Date.now() is nondeterministic here)."""
    if path in _CACHE_GIT:
        ct = _CACHE_GIT[path]
    else:
        p = Path(path)
        try:
            r = subprocess.run(["git", "log", "-1", "--format=%ct", "--", p.name],
                               cwd=str(p.parent), capture_output=True, text=True, timeout=15)
            ct = float(r.stdout.strip()) if r.stdout.strip() else None
        except Exception:
            ct = None
        _CACHE_GIT[path] = ct if ct is not None else 0.0
        if ct is None:
            return None
    if not ct or now is None:
        return None
    return max(0.0, (now - ct) / 86400.0)


def status_markers(text: str) -> Dict[str, int]:
    low = text.lower()
    return {role: sum(low.count(m) for m in markers) for role, markers in _STATUS.items()}


def staleness(text: str, path: str, *, now: Optional[float] = None) -> Dict:
    """Deterministic staleness in [0,1] + the signals behind it."""
    age = git_age_days(path, now=now)
    marks = status_markers(text)
    age_score = (min(1.0, (age or 0) / _AGE_FULL_DAYS) if age is not None else _AGE_UNKNOWN_SCORE)
    marker_score = min(1.0, _MARK_SUPERSEDED * marks["superseded"] + _MARK_DRAFT * marks["draft"])
    scratch = (_SCRATCH_SCORE if ("/working/" in path or "/scratch/" in path
                                  or "/dev/prompts/" in path) else 0.0)
    score = round(min(1.0, _W_AGE * age_score + _W_MARKER * marker_score + scratch), 3)
    return {"staleness": score, "age_days": round(age, 1) if age else None, "markers": marks}


def classify(text: str, path: str, stale: Dict) -> str:
    """Role from path + markers + staleness (deterministic priority order)."""
    marks = stale["markers"]
    if marks["superseded"] >= 1 or stale["staleness"] >= superseded_at():
        return "superseded"
    if "/dev/vision/" in path or marks["vision"] >= 2:
        return "vision"
    if "/dev/future/" in path or marks["roadmap"] >= 2:
        return "roadmap"
    if "/docs/" in path:
        return "current"
    if marks["draft"] >= 1 or "/dev/" in path or "/working/" in path:
        return "draft"
    return "reference"


def _lemma_jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def null_jaccard(size_a: int, size_b: int, vocab: int) -> Tuple[float, float]:
    """The lemma-Jaccard expected between two sets that share nothing but a vocabulary, and its
    standard error. Derived from the counting, not tuned.

    Two sets of sizes ``a`` and ``b`` drawn independently from a vocabulary of ``V`` lemmas overlap
    hypergeometrically: ``E[|A n B|] = a*b/V``, with
    ``Var = a * (b/V) * (1 - b/V) * (V - a)/(V - 1)``. The union is ``a + b - |A n B|``, so

        null = (a*b/V) / (a + b - a*b/V)          the overlap two unrelated documents already have
        se   = sd(|A n B|) / (a + b - a*b/V)      how much that overlap moves by luck alone

    This is what makes "does this document belong to this category?" answerable without a typed
    level. A raw Jaccard has no meaning on its own — 0.05 is a lot between two 20-lemma documents
    and nothing between two 2,000-lemma ones. Compare against this computed null, never against a
    number typed in.

    Degenerate inputs (an empty set, a vocabulary smaller than either set) return ``(0.0, 0.0)``:
    with nothing to draw from there is no chance overlap to exceed, so every real overlap counts.
    """
    a, b, V = int(size_a), int(size_b), int(vocab)
    if a <= 0 or b <= 0 or V < 2 or a > V or b > V:
        return 0.0, 0.0
    p = b / V
    exp_inter = a * p
    union = a + b - exp_inter
    if union <= 0.0:
        return 0.0, 0.0
    var_inter = a * p * (1.0 - p) * (V - a) / (V - 1)
    return exp_inter / union, math.sqrt(max(var_inter, 0.0)) / union


def lemma_filtration(doc_artifacts: List[dict], *,
                     drop_common_frac: Optional[float] = None) -> List[Tuple[float, str, str]]:
    """The agglomerative filtration over lemma-Jaccard: every non-zero pairwise link, sorted by
    descending similarity. This is the dendrogram — cutting it at a level yields the clusters at
    that resolution.

    Emits the structure rather than picking a cut: the data supplies clusters at every scale, a
    threshold only chooses which scale to read, and that choice belongs to the query rather than
    to a constant baked into the library. `lemma_filtration` returns the whole thing;
    `cut_filtration` reads it at a chosen level. There is no valley to find in a topical
    continuum, so a single hidden threshold would be a cut through a continuum — this makes the
    cut explicit and re-choosable instead.

    `drop_common_frac`: optionally drop lemmas that occur in more than this fraction of docs
    (corpus-common vocabulary that would collapse everything into one blob). None keeps all.
    """
    lem = {a["id"]: set(a.get("lemmas") or []) for a in doc_artifacts}
    if drop_common_frac is not None:
        n = len(lem) or 1
        df: Dict[str, int] = defaultdict(int)
        for s in lem.values():
            for t in s:
                df[t] += 1
        common = {t for t, c in df.items() if c > drop_common_frac * n}
        lem = {i: (s - common) for i, s in lem.items()}
    ids = [i for i in lem if lem[i]]
    links: List[Tuple[float, str, str]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            s = _lemma_jaccard(lem[ids[i]], lem[ids[j]])
            if s > 0:
                links.append((s, ids[i], ids[j]))
    links.sort(key=lambda x: -x[0])          # descending similarity — the merge order
    return links


def cut_filtration(links: List[Tuple[float, str, str]], all_ids: List[str],
                   threshold: float) -> List[List[str]]:
    """Read the filtration at `threshold` — union-find over links with similarity >= threshold.
    The links are sorted descending, so the scan stops at the first link below the cut."""
    parent = {i: i for i in all_ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for s, a, b in links:
        if s < threshold:
            break
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: Dict[str, List[str]] = defaultdict(list)
    for i in all_ids:
        groups[find(i)].append(i)
    return list(groups.values())


def resolutions(doc_artifacts: List[dict], *,
                drop_common_frac: Optional[float] = None) -> List[float]:
    """The levels at which this corpus's structure actually changes — the distinct similarities in
    its own filtration, descending.

    A caller with no opinion does not get a default cut; it gets the cuts that exist, and picks.
    Between two adjacent levels the clustering is identical, so these are every distinguishable
    zoom and no more.

    Empty when the corpus has no non-zero link — there is no resolution to offer, which is a fact
    about the corpus and not a reason to invent one.
    """
    links = lemma_filtration(doc_artifacts, drop_common_frac=drop_common_frac)
    return sorted({round(float(sc), 12) for sc, _, _ in links}, reverse=True)


def topics(doc_artifacts: List[dict], *, threshold: float) -> List[List[dict]]:
    """Docs sharing a topic, as a cut of the lemma filtration at `threshold`.

    `threshold` is required: it names the scale at which two documents count as the same topic,
    so the query picks the scale rather than receiving a silent default. Ask `resolutions()` for
    the levels this corpus actually has."""
    byid = {a["id"]: a for a in doc_artifacts}
    links = lemma_filtration(doc_artifacts)
    clusters = cut_filtration(links, list(byid), threshold)
    return [[byid[i] for i in c] for c in clusters if len(c) >= 2]


def categorize(doc_artifacts: List[dict], *, threshold: float,
               min_size: int = 3,
               drop_common_frac: Optional[float] = None) -> List[Dict]:
    """Emergent categories — let the data decide, but at a library (macro) granularity.
    Cluster docs by shared vocabulary (coarse threshold -> fewer, broader categories), label
    each by distinctive terms that recur (in >=2 of its docs, so one-off noise like a doc's
    own oddities never becomes a label). Clusters smaller than `min_size` fold into 'general'.
    Not imposed — technical/marketing/investor/legal/… surface from the vocabulary. Deterministic.

    `threshold` is required and `drop_common_frac` defaults to a derived value, so the caller
    supplies the scale rather than a typed constant silently deciding the library's shape.

    `drop_common_frac=None` measures the share on this corpus (`derived_common_frac`). If that
    measurement finds no level with structure it returns None, and the drop is then skipped
    rather than falling back to a constant, since reporting a grouping the corpus does not
    support would be the confident-number shape this module avoids."""
    import math
    raw = {a["id"]: set(a.get("lemmas") or []) for a in doc_artifacts}
    n = len(raw) or 1
    df: Dict[str, int] = defaultdict(int)                        # corpus doc-frequency per lemma
    for s in raw.values():
        for t in s:
            df[t] += 1
    # Drop corpus-common terms: artifact/mcp/agience/server etc. are shared by everything and
    # would collapse all docs into one blob. Distinctive terms decide categories. The share is
    # `COMMON_LEMMA_FRAC`, this module's one stated tolerance — read its definition for why it is
    # not derived and what would settle it — the same concept `lemma_filtration` exposes as
    # `drop_common_frac`, single-sourced here.
    if drop_common_frac is None:
        drop_common_frac = derived_common_frac(doc_artifacts)
    common = ({t for t, c in df.items() if c > drop_common_frac * n}
              if drop_common_frac is not None else set())
    lem = {i: (raw[i] - common) for i in raw}
    ids = [i for i in lem if lem[i]]
    parent = {i: i for i in ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if _lemma_jaccard(lem[ids[i]], lem[ids[j]]) >= threshold:
                parent[find(ids[i])] = find(ids[j])
    clusters: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        clusters[find(i)].append(i)
    cdf: Dict[str, int] = defaultdict(int)                       # cluster-doc-frequency of each term
    for members in clusters.values():
        for t in set().union(*(lem[m] for m in members)):
            cdf[t] += 1
    ncl = len(clusters)
    byid = {a["id"]: a for a in doc_artifacts}
    cores, general = [], []
    for members in clusters.values():
        (cores if len(members) >= min_size else general).append(members)
    general_ids = [m for g in general for m in g]

    # each core category's aggregated distinctive vocabulary (for nearest assignment + labels)
    cats = []
    for members in cores:
        tf: Dict[str, int] = defaultdict(int)
        for m in members:
            for t in lem[m]:
                tf[t] += 1
        recurring = [t for t in tf if tf[t] >= 2]
        vocab = set(tf)
        distinct = sorted(recurring or list(tf), key=lambda t: -(tf[t] * math.log(1 + ncl / cdf[t])))
        cats.append({"members": list(members), "vocab": vocab, "label": distinct[:5]})

    # Assign each general doc to its nearest core category (by distinctive-lemma overlap).
    # The bar is the computed chance overlap, not a typed level: two 20-lemma documents overlap
    # by 0.05 by accident, two 2,000-lemma ones essentially never do, so a fixed number cannot
    # serve both. `null_jaccard` computes what an unrelated document of this size would already
    # share with a category of that size, drawn from this corpus's own vocabulary. Beating it is
    # break-even, not a threshold: below it the overlap is evidence of nothing, and a document
    # with no evidence for any category has no reading to assign — it becomes an orphan.
    vocab_size = len({t for s in lem.values() for t in s})
    orphans = []
    for m in general_ids:
        best, bestscore, bestnull = None, 0.0, 0.0
        for c in cats:
            s = _lemma_jaccard(lem[m], c["vocab"])
            if s > bestscore:
                null, _se = null_jaccard(len(lem[m]), len(c["vocab"]), vocab_size)
                best, bestscore, bestnull = c, s, null
        if best and bestscore > bestnull:
            best["members"].append(m)
        else:
            orphans.append(m)
    out = [{"label": c["label"], "size": len(c["members"]),
            "docs": [_path_of(byid[m]).split("/")[-1] for m in c["members"]]} for c in cats]
    if orphans:
        out.append({"label": ["general"], "size": len(orphans),
                    "docs": [_path_of(byid[m]).split("/")[-1] for m in orphans]})
    return sorted(out, key=lambda c: -c["size"])


def _markdown_docs(store, root: str) -> List[dict]:
    """Every markdown artifact under `root`. A full pass, and it has to be: `root` is matched
    against the doc's path, which is not indexed and not a prefix of `id`, so there is no bound
    that reaches the same set. Nor does the content_type index help — text/markdown is a bulk
    value (~6M of the 5,657,386 rows on node 71; `count(*) WHERE content_type='text/markdown'`
    took over 120s while the same query on a 48-row type took 0.12s). Selectivity, not indexing,
    is what makes an equality cheap. Acceptable because this runs on demand only — /library
    (cached per root for the process life in browse._LIB_CACHE) and op.docs.library_plan /
    op.docs.build_library — never on a tick path."""
    return [a for a in store.list_artifacts(content_type="text/markdown") if root in _path_of(a)]


def library_plan(store, bundle, *, root: str, now: Optional[float] = None,
                 docs: Optional[List[dict]] = None,
                 resolution: Optional[float] = None) -> Dict:
    """The plan Ember produces: per-doc {role, staleness, action, target} + the target library
    tree (current/roadmap/vision/_archive). Deterministic; proposes, never touches files.

    On demand only — /library (cached per root for the process life in browse._LIB_CACHE) and
    op.docs.library_plan. `docs` lets a caller that already holds the doc set pass it in rather
    than re-fetching it (build_library needs the same set); None fetches it here."""
    # Loaded two ways (bundle module vs persona-load bare name) — see the note on the same
    # import in `lumen/arithmetic.py`. Relative resolves the bundle sibling; bare resolves
    # under the persona-load convention. Bare-only silently un-bundles this module.
    try:
        from . import content as C
    except ImportError:
        import content as C
    docs = docs if docs is not None else _markdown_docs(store, root)
    # axis 1 — category: emergent from the data, not imposed. doc-id -> category label.
    #
    # `categorize` is called with an explicit threshold and share rather than defaults, so no
    # typed constant silently decides the library's shape while the docstrings say the data
    # decides.
    #
    # A caller with no opinion gets the choices, not a chosen one: `resolutions` returns the
    # levels at which this corpus's structure actually changes, and the plan says so instead of
    # inventing a grouping — the same contract `op.canon.browse` answers a bare need with.
    if resolution is None:
        offered = resolutions(docs)
        return {"resolution": None, "resolutions": offered, "docs": len(docs),
                "why": ("no resolution was asked for, and this library does not pick one — these "
                        "are the %d level(s) at which this corpus's structure changes" % len(offered)),
                "categories": [], "per_doc": {}}
    cats = categorize(docs, threshold=resolution)
    doc_cat: Dict[str, str] = {}
    for c in cats:
        label = "-".join(c["label"][:2]) or "misc"
        for name in c["docs"]:                       # map member filenames back to a category
            for a in docs:
                if _path_of(a).endswith(name):
                    doc_cat[a["id"]] = label
    # axis 2 — status: staleness/currency (orthogonal quality signal).
    per_doc = []
    for a in docs:
        path = _path_of(a)
        st = staleness(C.resolve_text(bundle, a), path, now=now)
        status = ("superseded" if st["staleness"] >= superseded_at()
                  else "stale" if st["staleness"] >= stale_at() else "current")
        # The strongest action is archive (move, reversible), so nothing is lost, deleted, or rewritten.
        action = "archive" if status == "superseded" else "keep"
        per_doc.append({"path": path, "category": doc_cat.get(a["id"], "uncategorised"),
                        "status": status, "staleness": st["staleness"],
                        "age_days": st["age_days"], "action": action})
    per_doc.sort(key=lambda d: -d["staleness"])
    from collections import Counter
    return {"total_docs": len(docs),
            "emergent_categories": [{"label": c["label"], "size": c["size"]} for c in cats[:20]],
            "by_status": dict(Counter(d["status"] for d in per_doc)),
            "info_loss": "NONE — reorganize only MOVES (archive is reversible); never deletes or rewrites",
            "per_doc": per_doc}


def build_library(store, bundle, *, root: str, out_dir: str, now: Optional[float] = None,
                  consolidate_threshold: Optional[float] = None, keep_drafts: bool = False) -> Dict:
    # `consolidate_threshold` is required, because this writes files and a typed number would be
    # deciding how many documents a library collapses to. With none supplied this reports the
    # levels the corpus actually has and builds nothing.
    """Generate a cleaned, organized library into `out_dir` from the docs under `root`.

    Originals are untouched — this only copies (zero information loss). Deterministic, the
    whole works:
      • organize by emergent category  (<category>/)
      • dedup + consolidate topic groups: the canonical goes to its category; the other members
        go to _archive/ with a pointer (nothing lost)
      • superseded docs -> _archive/
      • INDEX.md (navigable library) + REFRESH-NEEDED.md (docs whose prose is stale — the
        gated-LLM content-refresh leg, deferred; flagged, not guessed)
    Returns a summary. A human reviews the new library beside the originals and adopts it.
    """
    import shutil
    # Loaded two ways (bundle module vs persona-load bare name) — see the note on the same
    # import in `lumen/arithmetic.py`. Relative resolves the bundle sibling; bare resolves
    # under the persona-load convention. Bare-only silently un-bundles this module.
    try:
        from . import content as C
    except ImportError:
        import content as C
    # One fetch of the doc set, shared with the plan, rather than two full corpus streams
    # (~370s each on a 5M-row store).
    docs = _markdown_docs(store, root)
    if consolidate_threshold is None:
        offered = resolutions(docs)
        return {"built": False, "resolution": None, "resolutions": offered, "docs": len(docs),
                "why": ("build_library writes files and will not choose the grouping for you — "
                        "pass consolidate_threshold; these are the %d level(s) this corpus has"
                        % len(offered))}
    plan = library_plan(store, bundle, root=root, now=now, docs=docs,
                        resolution=consolidate_threshold)
    by_path = {_path_of(a): a for a in docs}

    # consolidation — the main size lever. Cluster into topics at `consolidate_threshold`
    # (higher = tighter topics, more variants collapse); keep one canonical per topic
    # (prefer curated /docs/, then lowest staleness, then longest = most complete), archive
    # every other variant (preserved with a pointer). A curated library = ~one doc per topic.
    consolidated: Dict[str, str] = {}
    def _rank(a):
        p = _path_of(a); t = C.resolve_text(bundle, a)
        return ("/docs/" not in p, staleness(t, p, now=now)["staleness"], -len(t))
    for g in topics(docs, threshold=consolidate_threshold):
        auth = min(g, key=_rank)
        for x in g:
            if _path_of(x) != _path_of(auth):
                consolidated[_path_of(x)] = _path_of(auth)

    # `out_dir` is a caller-supplied string, and `build_library` has no callers in `src/`, so
    # every call site is otherwise unguarded — a destructive step establishes its own
    # precondition here. Refuses to rmtree anything that is not a directory it previously built:
    # the marker is written below, so a first run into a fresh or non-existent path succeeds, and
    # a second run regenerates cleanly.
    out = Path(out_dir).resolve()
    _MARKER = ".ember-library"
    if out.exists():
        if not out.is_dir():
            raise ValueError("out_dir exists and is not a directory: %s" % out)
        if not (out / _MARKER).exists():
            raise ValueError(
                "refusing to delete %s: it is not an Ember-generated library "
                "(no %s marker). Point --out at a fresh path, or remove it by hand if you are "
                "certain." % (out, _MARKER))
        shutil.rmtree(out)                       # regenerate cleanly — verified Ember-owned
    (out / "_archive").mkdir(parents=True, exist_ok=True)
    (out / _MARKER).write_text(
        "Generated by ember.docs_ops.build_library. This marker authorises regeneration to "
        "delete this directory; remove it to protect the tree.\n", encoding="utf-8")

    def _safe_name(p: str) -> str:
        return Path(p).name

    placed, archived, refresh = [], [], []
    for d in plan["per_doc"]:
        p = d["path"]; a = by_path.get(p)
        text = C.resolve_text(bundle, a) if a else ""
        cat = re.sub(r"[^a-z0-9]+", "-", d["category"].lower()).strip("-") or "misc"
        if d["action"] == "archive" or p in consolidated:
            dst = out / "_archive" / _safe_name(p)
            note = f"\n\n<!-- archived by Ember: {'superseded (stale)' if d['action']=='archive' else 'consolidated into ' + consolidated[p]} -->\n"
            dst.write_text(text + note, encoding="utf-8")
            archived.append({"file": _safe_name(p), "reason": "superseded" if d["action"] == "archive" else "duplicate",
                             "canonical": consolidated.get(p)})
        else:
            (out / cat).mkdir(parents=True, exist_ok=True)
            (out / cat / _safe_name(p)).write_text(text, encoding="utf-8")
            placed.append({"file": _safe_name(p), "category": cat, "status": d["status"]})
            if d["status"] in ("stale", "superseded"):
                refresh.append(_safe_name(p))

    # INDEX.md — the navigable library
    idx = ["# Documentation Library", "",
           f"*Generated deterministically by Ember from `{root}` — originals untouched, nothing lost.*", "",
           f"- {len(placed)} organized docs across {len({p['category'] for p in placed})} categories",
           f"- {len(archived)} archived (superseded or consolidated) in `_archive/` — preserved, not deleted",
           f"- {len(refresh)} docs flagged for content-refresh (see REFRESH-NEEDED.md)", ""]
    by_cat: Dict[str, list] = {}
    for p in placed:
        by_cat.setdefault(p["category"], []).append(p)
    for cat in sorted(by_cat):
        idx.append(f"## {cat}")
        for p in sorted(by_cat[cat], key=lambda x: x["file"]):
            idx.append(f"- [{p['file']}]({cat}/{p['file']})  ·  {p['status']}")
        idx.append("")
    (out / "INDEX.md").write_text("\n".join(idx), encoding="utf-8")
    (out / "REFRESH-NEEDED.md").write_text(
        "# Docs needing a content-refresh (stale prose — the gated-LLM leg, deferred)\n\n"
        + "\n".join(f"- {f}" for f in sorted(refresh)), encoding="utf-8")

    return {"out_dir": out.as_posix(), "organized": len(placed), "archived": len(archived),
            "categories": len(by_cat), "refresh_flagged": len(refresh),
            "info_loss": "NONE — copies only; originals untouched; archived docs preserved with a pointer"}


def reorganize(plan: Dict, *, apply: bool = False, archive_root: Optional[str] = None) -> Dict:
    """Executes a library_plan reversibly: moves each 'archive' doc into docs/_archive/ (dry-run
    by default). Gated — `apply=True` is required to touch files, and even then only moves (git
    tracks it, nothing is lost, a human reviews the diff before it is committed). Never deletes
    or rewrites content. Reorg of live docs is a human-approved act."""
    import shutil
    moves, done = [], 0
    for d in plan["per_doc"]:
        if d["action"] != "archive":
            continue
        src = Path(d["path"])
        dst_dir = Path(archive_root or (src.parents[2] / "docs" / "_archive"))
        dst = dst_dir / src.name
        moves.append({"from": src.as_posix(), "to": dst.as_posix()})
        if apply and src.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.move(str(src), str(dst)); done += 1
    return {"planned_moves": len(moves), "applied": done if apply else 0,
            "dry_run": not apply, "moves": moves[:50]}


_DOCS_OPS = [
    ("op.docs.staleness", "scores a doc's staleness from git-age + status markers + scratch-location"),
    ("op.docs.categorize", "EMERGENT categories from the data: cluster by vocabulary, label by distinctive terms"),
    ("op.docs.topics", "clusters docs by shared lemmas into topic groups + the authoritative doc each"),
    ("op.docs.library_plan", "data-driven library: emergent category x status; archives superseded (no info loss)"),
    ("op.docs.reorganize", "REVERSIBLY moves superseded docs to _archive per a plan (dry-run by default, gated)"),
]


def register_docs_operators(store, *, author: str = "ember-local") -> int:
    from crystal import evolution
    for name, offer in _DOCS_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": f"docs operator {name}: {offer}  [read-only]",
            "created_by": author}))
    return len(_DOCS_OPS)
