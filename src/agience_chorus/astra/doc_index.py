# Operator code lives in chorus, the single authoritative path — no dual maintenance.
# Distributed to hosts as a content-addressed source bundle (definitions/build_bundles.py); ember
# executes it via ember/runner.py, sha-verified before exec. There are no code mirrors. Changes
# happen here.
"""Deterministic doc-lemma extraction — the prose analogue of code-symbol extraction.

A document's lemmas are its key terms, pulled out with no model: the title/name (structural
prominence, carried by order), the content words that carry at least the document's own mean
information as the corpus measures it, and domain terms (CamelCase / acronym / Capitalized project
nouns like ArcadeDB, Mantle). Writing them into the same `lemmas` field makes docs keyed —
findable exactly, joined to the code + WordNet index — and retires model2vec for docs. Terms that
are real words also link into the WordNet ontology (validation is a link, never a filter).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import List

# There is no stopword list. A stop-list asserts, by hand, that a fixed set of words carries no
# information — a claim about language, made once and applied forever, and measurably wrong on this
# corpus: a hand-authored list would exclude words like `note`, `run`, `set`, `class`, `self`,
# `return`, `import`, which are real subjects here (a document about the `class` keyword could not
# be keyed by it).
#
# Which words are informative is not a property of the words. It is a property of the corpus, and
# the corpus already measures it: IDF = log(N/df), with df exact off `fts5vocab`. So extraction does
# not filter — it extracts — and `_salient` keeps the terms carrying at least the document's own
# mean information. Self-relative, so it scales with the document and with the corpus, and nothing
# is chosen.


def _terms(text: str) -> List[str]:
    """Every content token, unfiltered. No list decides what counts."""
    return [t for t in re.findall(r"[a-z][a-z0-9_]+", text.lower()) if len(t) > 2]


def _domain_terms(text: str) -> List[str]:
    """Project nouns + identifiers: CamelCase (ArcadeDB), ACRONYMS (AGPL), Capitalized
    (Mantle), snake_case + dotted keys (env vars, config keys, function names) — so config
    / code-ish files (json/yaml/sh) key on their own identifiers, not just prose."""
    out = re.findall(r"\b[A-Z][a-z]+[A-Z][A-Za-z]+\b", text)          # CamelCase
    out += re.findall(r"\b[A-Z]{2,6}\b", text)                        # ACRONYM
    out += re.findall(r"\b[A-Z][a-z]{3,}\b", text)                    # Capitalized
    out += re.findall(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", text)         # snake_case
    out += [d.split(".")[-1] for d in re.findall(r"\b[a-z][a-z0-9_]+(?:\.[a-z][a-z0-9_]+)+\b", text)]
    return [w.lower() for w in out if len(w) > 2]


def extract_terms(path: str, text: str, *, conn=None, max_terms: int | None = None) -> List[str]:
    """A document's key terms.

    `conn` — a store connection. When given, the content words are filtered by the corpus's own
    information measure (`corpus_stats._salient`: keep what carries at least this document's mean
    IDF) instead of by a hand-authored list. When absent the terms are returned unfiltered, which
    is the honest reading: without the corpus there is nothing that says which words matter.

    `max_terms` — off by default. A cap sorted by strength discards the ambiguous and the general
    first, so it biases rather than trims; pass one only where a caller genuinely needs a window.
    """
    lines = [l.strip() for l in text.splitlines()]
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("#")),
                 (lines[0] if lines else ""))
    name = re.sub(r"[-_]", " ", path.rsplit("/", 1)[-1].rsplit(".", 1)[0])

    # No per-field weight: a boost like `freq[t] += 5` for title/name terms would be a hand-picked
    # claim about what matters, which nothing measures. It would also be redundant — the merge below
    # already emits title/name terms first by construction, so structural position is carried by
    # order, not by a magic number. Headings need no special handling either: they are part of
    # `text`, so they are counted naturally.
    freq = Counter(_terms(text))
    ranked = [w for w, _ in freq.most_common()]
    if conn is not None and ranked:
        try:
            from agience_chorus.corpus_stats import _salient
            keep = set(_salient(conn, ranked))
            ranked = [w for w in ranked if w in keep]
        except Exception:
            pass          # unmeasurable -> unfiltered, never a fallback list
    top = ranked

    # Domain terms — the identifiers (ArcadeDB, EMBER_NODE_ID, …) that join a doc to the code
    # index. `c >= 1` is a no-op: a Counter's counts are >= 1 by construction, so every one-off is
    # kept. That is deliberate — a doc that names a symbol once is still keyed by it, and this
    # module exists to make docs findable by identifier. Whether to require >= 2 is a
    # recall/precision call on a live 6M-row corpus, not a silent edit.
    dom = [w for w, _c in Counter(_domain_terms(text)).most_common()]

    seen, lemmas = set(), []
    # Domain terms rank directly after title/name, ahead of generic frequency terms: `top` can be
    # truncated at `max_terms`, so a domain term ranked after it would never survive the cut on a
    # long, term-rich document — exactly the documents where identifier keying matters most.
    for w in _terms(f"{title} {name}") + dom + top:
        if w not in seen:
            seen.add(w); lemmas.append(w)
    return lemmas[:max_terms] if max_terms else lemmas


def index_docs(store, *, content_types=("text/markdown", "text/plain"),
               only_dark: bool = True) -> int:
    """Attach lemmas to doc artifacts (content is 'path\\n<text>'). By default only those
    without lemmas (dark matter). Returns how many were keyed.

    A full pass, deliberately: this is a rebuild, run on demand (no caller on any tick path — the
    worker illuminates dark matter through describe.describe_dark, which is cursor-bounded per
    call); its contract is "key every dark doc", so a bound would silently leave docs dark. Neither
    predicate can be pushed down usefully: `lemmas IS NULL` can never be index-served (LSM
    nullStrategy is SKIP), and the content_types here are bulk values, where an indexed equality
    degenerates to a scan anyway (measured on node 71, 5,657,386 rows: text/markdown timed out at
    120s vs 0.12s for a 48-row type). state='committed' prunes nothing — nearly every row is
    committed."""
    cts = set(content_types)
    n = 0
    for a in store.list_artifacts(state="committed"):
        if a.get("content_type") not in cts:
            continue
        if only_dark and a.get("lemmas"):
            continue
        content = a.get("content") or ""
        path, _, text = content.partition("\n")
        lemmas = extract_terms(path, text or content)
        if lemmas:
            doc = dict(a); doc["lemmas"] = lemmas
            store.put_artifact(doc)
            n += 1
    return n
