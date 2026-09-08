"""GAPS 2.11 — canon recall. `op.knowledge.cite` grounds in the canon, so it must not take the
store's global top-k and discard what it did not want: a canon section would have to out-rank
every indexed document in the store — including WordNet's own entry for the query's words — for a
slot it is not competing for.

Same shape as `_page_canon`: the limit bounds output, not work.
"""
from __future__ import annotations



from agience_chorus.sage import canon, content_search  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


class _Conn:
    """Records the SQL and the parameters, and answers with rows the test chose. The store fakes in
    this suite cannot exercise FTS, so what is asserted here is the query — that the range reaches
    SQL — plus, separately, that the range is the same one `_page_canon` walks."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=()):
        self.sql, self.params = sql, tuple(params)
        return self

    def fetchall(self):
        return self.rows


class _Store:
    def __init__(self, rows=(), arts=None):
        self._conn = _Conn(list(rows))
        self._arts = arts or {}
        store = self

        class _Artifacts:
            class db:
                @staticmethod
                def read():
                    return store._conn

            @staticmethod
            def get_artifact(aid):
                return store._arts.get(aid)

        self.artifacts = _Artifacts()


def _canon_art(stem, section):
    return {"id": "canon:%s#%s" % (stem, section), "title": stem,
            "citation": {"cite_id": "canon:%s#%s" % (stem, section), "section": section,
                         "source": "agience-pharos/%s.md" % stem, "license": canon.CANON_LICENSE}}


# ── the range reaches SQL ────────────────────────────────────────────────────────────────────────

def test_cited_retrieval_scopes_the_SEARCH_not_the_result():
    """Fails if filtering happens after the LIMIT: the bound must be in the statement, or a
    Python-side drop leaves the canon competing with the whole store for k slots."""
    st = _Store()
    canon.retrieve_cited(st, "membrane gauge", k=6)
    assert "v.id > ?" in st._conn.sql and "v.id < ?" in st._conn.sql, st._conn.sql
    assert canon._CANON_ID_PREFIX in st._conn.params


def test_the_scope_is_the_SAME_range_page_canon_walks():
    """Fails if the canon's id namespace is declared twice, free to drift: both readers take it
    from `_citation`, the one builder that writes the ids."""
    assert canon._CANON_ID_PREFIX == canon._citation("", "", "", "")["cite_id"].split("#")[0]
    st = _Store()
    canon.retrieve_cited(st, "membrane", k=3)
    lo = st._conn.params[st._conn.params.index(canon._CANON_ID_PREFIX)]
    assert lo == canon._CANON_ID_PREFIX
    # the upper bound is the prefix's successor, so every canon id sorts inside it
    hi = [p for p in st._conn.params if isinstance(p, str) and p.startswith(canon._CANON_ID_PREFIX)
          and p != canon._CANON_ID_PREFIX]
    assert hi and lo < "canon:zzz#zzz" < hi[0]


def test_an_UNSCOPED_search_is_still_unscoped():
    """The control. Without it, the assertions above would pass on a `search` that always emits
    the range — which would silently scope the chat's recall to whatever prefix it was given."""
    st = _Store()
    content_search.search(st, "membrane gauge", k=6)
    assert "v.id > ?" not in st._conn.sql, "an unscoped search acquired a range predicate"


def test_the_range_is_half_open_and_index_usable():
    """Fails on `LIKE 'canon:%'`, which cannot use the PK index — the same reason `_page_canon`
    walks a range instead. The bound must be two comparisons, not a pattern."""
    st = _Store()
    content_search.search(st, "membrane", k=1, id_prefix="canon:")   # a real term: "x" yields none
    assert st._conn.sql, "the query never reached the index"
    assert "LIKE" not in st._conn.sql.upper()
    assert st._conn.sql.count("v.id > ?") == 1 and st._conn.sql.count("v.id < ?") == 1


# ── what the caller gets ─────────────────────────────────────────────────────────────────────────

def test_hits_outside_the_canon_are_still_dropped():
    """The scope narrows recall; the citation rule is unchanged. A row with no provenance is never
    cited even if it reached the result — belt and braces, because the two protect different things."""
    rows = [("canon:A#1", "text/markdown", -9.0), ("wn-membrane.n.01", "text/x-wordnet", -8.0)]
    st = _Store(rows, {"canon:A#1": _canon_art("A", "1"),
                       "wn-membrane.n.01": {"id": "wn-membrane.n.01", "title": "membrane"}})
    out = canon.retrieve_cited(st, "membrane", k=6)
    assert [h["id"] for h in out] == ["canon:A#1"]
    assert out[0]["citation"]["cite_id"] == "canon:A#1"


def test_an_empty_query_still_reaches_no_store():
    st = _Store()
    assert canon.retrieve_cited(st, "   ", k=6) == []
    assert st._conn.sql == "", "a blank query touched the index"
