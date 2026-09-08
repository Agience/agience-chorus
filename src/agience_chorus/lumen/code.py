"""Code intelligence -- deterministic answers about a repository, from an AST index.

The answer acts (`answer`, `looks_code_query`, `find_definition`, `find_references`) live here:
composing "`X` is called in N place(s)" is a persona act. Extraction stays in ember --
`runner.code_index` builds the index, `mantle.shard.keyed` serves the lookup, both are grounding --
and this module reaches them.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from mantle.shard import keyed as _keyed
from prism.runner import code_index as _code_index   # the single distribution path (prism/runner.py)
# `Answer` comes from the operator bundle (`runner.answer`), not from ember.
from prism.runner import answer as _answer_mod

Answer = _answer_mod.Answer

SYMBOL_CONTENT_TYPE = _code_index.SYMBOL_CONTENT_TYPE
extract = _code_index.extract

CODE_EXT = {".py"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".mypy_cache", ".pytest_cache", "target", "site-packages", ".continue"}


def index_code(store, paths, *, author: str = "ember-local") -> int:
    """Extract symbols from every Python file under paths and upsert them as keyed
    artifacts. Returns the number of symbols indexed. Idempotent (keyed on symbol id)."""
    docs: List[dict] = []
    for root in paths:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if Path(fn).suffix.lower() not in CODE_EXT:
                    continue
                p = Path(dirpath) / fn
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                symbols, _imports = extract(p.as_posix(), text)
                for s in symbols:
                    lemmas = list(dict.fromkeys([s.name.lower(), s.qualname.lower()]))
                    docs.append({
                        "id": s.id(), "content_type": SYMBOL_CONTENT_TYPE, "state": "committed",
                        "context": s.offer(), "content": s.offer(), "created_by": author,
                        "lemmas": lemmas, "calls": [c.lower() for c in s.calls],
                        "kind": s.kind, "path": s.path, "line": s.line, "sym": s.name,
                        "qualname": s.qualname,
                    })
    return store.put_many(docs, batch=500)


def index_file(store, path: str, *, author: str = "ember-local") -> int:
    """Index one file's symbols (used by the folder-source sink for live reindex-on-change)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    docs = []
    for s in extract(p.as_posix(), text)[0]:
        docs.append({
            "id": s.id(), "content_type": SYMBOL_CONTENT_TYPE, "state": "committed",
            "context": s.offer(), "content": s.offer(), "created_by": author,
            "lemmas": list(dict.fromkeys([s.name.lower(), s.qualname.lower()])),
            "calls": [c.lower() for c in s.calls], "kind": s.kind,
            "path": s.path, "line": s.line, "sym": s.name, "qualname": s.qualname,
        })
    return store.put_many(docs, batch=500) if docs else 0


def _symbols_named(store, name: str, limit: int = 20) -> List[dict]:
    """The content-type filter runs inside the lookup itself, not as a post-filter over the page:
    symbol names are ordinary English words (`run`, `open`, `index`, `main`), so on the full corpus
    a post-filter over a page that `limit` had already been spent on would come back full of
    wikipedia and wordnet rows and filter down to `[]`, however many symbols the store actually
    held. `keyed` pushes the predicate into the seek where the backend supports it, so `limit`
    bounds the count of matching symbols, not the count of rows scanned before filtering."""
    rows, _typed = _keyed.lookup_by_lemma(
        store, name.lower(), limit=limit, content_type=SYMBOL_CONTENT_TYPE)
    return rows


def find_definition(store, name: str) -> List[dict]:
    """Exact: every symbol whose name (or qualname) is `name`."""
    return _symbols_named(store, name)


def find_references(store, name: str, limit: int = 40) -> List[dict]:
    """Exact: every symbol that calls `name` (a call site)."""
    rows, _typed = _keyed.lookup_by_list_field(
        store, "calls", name.lower(), limit=limit, content_type=SYMBOL_CONTENT_TYPE)
    return rows


# ── router hook ──────────────────────────────────────────────────────────────
_DEF = [re.compile(p) for p in (
    r"where\s+(?:is|are)\s+(?:the\s+)?[`'\"]?(\w+)[`'\"]?(?:\s+defined)?",
    r"(?:definition|def|declaration)\s+(?:of|for)\s+[`'\"]?(\w+)",
    r"find\s+(?:the\s+)?(?:definition\s+of\s+)?[`'\"]?(\w+)",
    r"where'?s\s+[`'\"]?(\w+)",
)]
_REF = [re.compile(p) for p in (
    r"what\s+calls\s+[`'\"]?(\w+)",
    r"(?:references|callers|call\s*sites|usages?)\s+(?:to|of|for)\s+[`'\"]?(\w+)",
    r"who\s+(?:calls|uses)\s+[`'\"]?(\w+)",
    r"what\s+(?:uses|calls|invokes)\s+[`'\"]?(\w+)",
)]


def looks_code_query(query: str) -> bool:
    q = query.lower()
    return any(p.search(q) for p in _DEF + _REF)


def answer(store, query: str) -> Optional[Answer]:
    q = query.lower()
    # references first (more specific verbs)
    for pat in _REF:
        m = pat.search(q)
        if m:
            name = m.group(1)
            refs = find_references(store, name)
            if not refs:
                return None
            lines = [f"- {r.get('qualname', r['id'])} — {r.get('path')}:{r.get('line')}" for r in refs[:20]]
            return Answer(text=f"`{name}` is called in {len(refs)} place(s):\n" + "\n".join(lines),
                          grounded=True, cited=[r["id"] for r in refs[:20]],
                          read={"engine": "code.references", "name": name, "count": len(refs)})
    for pat in _DEF:
        m = pat.search(q)
        if m:
            name = m.group(1)
            defs = find_definition(store, name)
            if not defs:
                return None
            lines = [f"- {d.get('kind','?')} {d.get('qualname', d['id'])} — {d.get('path')}:{d.get('line')}"
                     for d in defs]
            return Answer(text=f"`{name}` is defined at {len(defs)} location(s):\n" + "\n".join(lines),
                          grounded=True, cited=[d["id"] for d in defs],
                          read={"engine": "code.definition", "name": name, "count": len(defs)})
    return None
