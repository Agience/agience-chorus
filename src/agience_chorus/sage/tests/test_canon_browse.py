"""`op.canon.browse` — the canon's own structure, and the ways reading it could lie.

The tekton answers the tree the canon already has on disk: collections (= pharos folders) -> docs ->
sections.

  1. it browses the whole markdown corpus as if it were canon (wrong discriminator)
  2. it renumbers the shelves (id order, where §10 precedes §2)
  3. it reads the nested keyset row without unwrapping it
  4. it walks past the end of the canon's id range

Each test states the failure mode it would catch, because a gate whose failure mode is unstated is
a gate nobody can tell is vacuous.
"""
from __future__ import annotations



from agience_chorus.sage import canon  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.


class _Store:
    """The narrowest store the handler actually uses: `list_artifacts(content_type=...)`.

    It ignores the content_type filter deliberately — the real store filters on it, and if the
    handler leaned on that filter alone it would pass here and browse the code docs in production.
    Making the fake permissive is what lets test 3 below have teeth.
    """

    def __init__(self, arts):
        self._arts = list(arts)

    def list_artifacts(self, *, content_type=None, **kw):
        return iter(self._arts)


def _canon_art(stem, section, *, lemmas=None):
    art = {
        "id": "canon:%s#%s" % (stem, section),
        "content_type": canon.CANON_CT,
        "knowledge": canon.CANON_KNOWLEDGE,
        "source_path": "agience-pharos/%s.md" % stem,
        "license": canon.CANON_LICENSE,
        "title": "%s — §%s" % (stem, section),
        "citation": {"cite_id": "canon:%s#%s" % (stem, section), "section": section,
                     "source": "agience-pharos/%s.md" % stem, "license": canon.CANON_LICENSE},
    }
    if lemmas is not None:
        art["lemmas"] = lemmas
    return art


CORPUS = [_canon_art("SCREEN", s) for s in ("intro", "1", "2", "10", "1.9", "1.10")] + \
         [_canon_art("MEMBRANE", s) for s in ("intro", "3")]


# ── 1 · it must not pick ─────────────────────────────────────────────────────────────────────




def test_NON_canon_markdown_is_NOT_browsed_as_canon():
    """`CANON_CT` is `text/markdown` — the whole doc corpus shares it. `knowledge == "canon"` is
    what the condensation actually stamps, so that is what must select.

    Fails if content_type is filtered alone: the fake store ignores the type filter precisely so
    that mistake shows up here instead of in production.
    """
    mixed = CORPUS + [{"id": "doc:readme", "content_type": "text/markdown",
                       "source_path": "agience-chorus/README.md"}]        # no `knowledge` stamp
    got = canon.canon_browse_handler(_Store(mixed))({})
    assert all("agience-pharos" in i["id"] for i in got["items"]), got["items"]
    assert {i["title"] for i in got["items"]} == {"SCREEN.md", "MEMBRANE.md"}


# ── 4 · it must not renumber the shelves ─────────────────────────────────────────────────────
def test_sections_come_back_in_LABEL_order_not_id_order():
    """The store returns `ORDER BY id`, and ids are `canon:<stem>#<section>` — lexicographic, so
    §10 lands before §2 and §1.10 before §1.9. A library that reorders its own shelves is worse
    than one that leaves them unsorted.

    Fails if `_section_key` is dropped and the store's order is trusted directly. Asserted against
    the lexicographic order explicitly, so the test cannot pass by accident.
    """
    got = canon.canon_browse_handler(_Store(CORPUS))(
        {"doc": "agience-pharos/SCREEN.md"})
    order = [i["citation"]["section"] for i in got["items"]]
    assert order == ["1", "1.9", "1.10", "2", "10", "intro"], order
    lexicographic = sorted(order)
    assert order != lexicographic, "the test is vacuous — label order matched id order"




def test_every_browsed_item_carries_its_LICENSE():
    """The canon is CC-BY content served by AGPL code (the two-tier policy). A view that drops the
    marker is how attribution gets lost downstream.

    Fails if the item dicts are built from a hand-picked field list that omits `license`: the page
    would render, look complete, and quietly strip the attribution from every row.
    """
    src = canon.canon_browse_handler(_Store(CORPUS))({"resolution": "source"})
    sec = canon.canon_browse_handler(_Store(CORPUS))(
        {"doc": "agience-pharos/SCREEN.md"})
    assert all(i["license"] == canon.CANON_LICENSE for i in src["items"] + sec["items"])


def test_browse_WRITES_NOTHING():
    """A tekton condenses; it does not land artifacts. The store fake has no write surface at all,
    so any attempt to persist raises `AttributeError` rather than passing unnoticed.

    Fails if a "helpful" cache or backfill is added to the browse path — e.g. writing the computed
    structure back. It would pass every other test here, because they only read the answer.

    Browse does record demand when the canon cannot answer — see
    `test_an_unanswerable_NEED_RAISES_DEMAND` — but that is not a content write: it is the
    observation that something was asked and could not be served, which is what removes the need
    for polling. This fake offers no demand cache, so the two claims stay separable and neither can
    hide the other.
    """
    store = _Store(CORPUS)
    assert not hasattr(store, "put_artifact") and not hasattr(store, "artifacts")
    for need in ({}, {"resolution": "source"},
                 {"doc": "agience-pharos/SCREEN.md"}):
        canon.canon_browse_handler(store)(need)      # would raise if it tried to write


# ── 5 · the KEYSET read, and the shape trap under it ─────────────────────────────────────────
class _Artifacts:
    """The real `vertex.page_by_id` contract: `WHERE id > ? ORDER BY id LIMIT ?`, returning the
    artifact nested under `doc` alongside the row's own columns."""

    def __init__(self, arts, *, log=None):
        self._rows = sorted(arts, key=lambda a: a["id"])
        self.log = log if log is not None else []

    def page_by_id(self, *, after="", limit=200, content_type=None):
        self.log.append(after)
        out = [a for a in self._rows if a["id"] > after][:limit]
        return [{"id": a["id"], "content_ref": None, "_origin": None, "_seq": 0, "doc": a}
                for a in out]


class _KeysetStore:
    def __init__(self, arts):
        self.artifacts = _Artifacts(arts)


def test_the_keyset_read_UNWRAPS_the_nested_doc():
    """`list_artifacts` yields the artifact flat; `page_by_id` nests it under `doc`. Yielding the
    row unchanged leaves `knowledge` unreadable, so every artifact is filtered out and the library
    reports "no canon" against a store holding 6,418 — while every other test in this file passes,
    because the fakes above exercise the flat path.

    Fails if the handler does `yield row` instead of `yield dict(doc, id=rid)`. Caught by reading
    `vertex.page_by_id`'s return statement, not by a test — so it gets one now.
    """
    got = canon.canon_browse_handler(_KeysetStore(CORPUS))({})
    assert got["observed"] is True, "the keyset path saw no canon — the doc was not unwrapped"
    assert got["extent"] == len(CORPUS)
    assert {i["title"] for i in got["items"]} == {"SCREEN.md", "MEMBRANE.md"}


def test_both_reads_agree_ARTIFACT_FOR_ARTIFACT():
    """Correctness must not depend on which read the store offers. If the fast path ever diverges
    from the streaming one, the library's answer would depend on its deployment.

    Fails if only the keyset path is optimised — adding a filter, an ordering or a projection there
    and not to the streaming one. Both would still pass their own tests; only comparing the two
    answers catches it.
    """
    need = {"doc": "agience-pharos/SCREEN.md"}
    assert canon.canon_browse_handler(_KeysetStore(CORPUS))(need) == \
           canon.canon_browse_handler(_Store(CORPUS))(need)


def test_the_walk_STOPS_at_the_end_of_the_canon_id_range():
    """Measured, and the reason the range exists: on the live shard the canon is 6,418 artifacts
    inside 316,421 `text/markdown` rows — the type filter read all of them in 36.9s, the id range
    in 0.06s. A walk that does not stop at the range's end re-reads the whole store and the saving
    is gone.

    Fails if the prefix check is dropped and the walk pages to the end of the table. The sentinel
    below sorts after the canon range, so a walk that fails to stop returns it.
    """
    beyond = dict(_canon_art("X", "1"), id="zzz:not-canon", knowledge="canon")
    store = _KeysetStore(CORPUS + [beyond])
    got = canon.canon_browse_handler(store)({})
    assert all("agience-pharos" in i["id"] for i in got["items"]), got["items"]
    assert got["extent"] == len(CORPUS)


def test_the_id_prefix_is_DERIVED_from_the_citation_builder():
    """A typed-in `"canon:"` would be a second declaration of the id scheme, free to drift from
    `_citation` — and the drift would be silent: the walk would return nothing, which reads exactly
    like an empty canon.

    Fails if the prefix is hard-coded. Asserted against a freshly built citation, so changing the
    scheme moves both together or fails here.
    """
    built = canon._citation("ANY", "src.md", "1", "H")["cite_id"]
    assert built.startswith(canon._CANON_ID_PREFIX)
    assert canon._CANON_ID_PREFIX == built.split("#")[0].replace("ANY", "")


def test_the_keyset_walk_is_PAGED_and_never_asks_for_everything():
    """[[limit-bounds-output-not-work]] — the walk must advance a cursor, not request one huge page.

    Fails if `pager(after="", limit=10**9)` is called instead: the log records each cursor, and a
    single call starting from the empty string would mean the whole table was asked for.
    """
    store = _KeysetStore(CORPUS)
    canon.canon_browse_handler(store)({})
    assert store.artifacts.log, "the keyset path was never taken"
    assert store.artifacts.log[0] == canon._CANON_ID_PREFIX, (
        "the walk started at the beginning of the STORE, not of the canon: %s" % store.artifacts.log)


def test_browse_is_a_REGISTERED_capability_with_an_offer():
    """A capability wired to nothing works in-process but is unfindable by any NEED.

    Fails if the handler is added and `_CANON_OPS` is forgotten.
    """
    names = [n for n, _ in canon._CANON_OPS]
    assert canon.CANON_BROWSE_CAP in names
    offer = dict(canon._CANON_OPS)[canon.CANON_BROWSE_CAP]
    # The offer is what a NEED matches on, so it must describe the structure this tekton answers.
    assert "TEKTON" in offer and "STRUCTURE" in offer
    assert "zoom" not in offer.replace("no zoom", ""), "the offer still advertises zoom"


# ── the demand trigger — observation follows demand, nothing polls ──────────────────────────────

class _DemandStore(_Store):
    """A store that carries a demand cache, so the trigger is live rather than absent."""

    def __init__(self, arts):
        super().__init__(arts)
        rows = {}
        store = self

        class _Arts:
            @staticmethod
            def demand_get(aid):
                return dict(rows[aid]) if aid in rows else None

            @staticmethod
            def demand_set(aid, mass, ts):
                rows[aid] = {"mass": float(mass), "ts": float(ts)}

        self.artifacts = _Arts()
        self.rows = rows

    def list_artifacts(self, *, content_type=None, **kw):
        return iter(self._arts)


def test_an_unanswerable_NEED_RAISES_DEMAND():
    """An empty canon that nobody asks about stays empty; one that is asked about makes that
    measurable, and the condense runs because demand accumulated rather than because a tick fired.

    Fails if the capability is only named in `why`: that tells a human but tells the system
    nothing.
    """
    store = _DemandStore([])
    a = canon.canon_browse_handler(store)({})
    assert a["observed"] is False
    assert a["demand"] == canon.CANON_CONDENSE_CAP
    assert store.rows[canon.CANON_CONDENSE_CAP]["mass"] == 1.0


def test_demand_ACCUMULATES_across_askings():
    """Fails if 1.0 is written every time instead of accumulated — the one failure mode that empties
    the signal. `demand_set` replaces (`SET mass = excluded.mass`), so a caller that does not
    read-add-write records "asked once" forever however often it is asked."""
    store = _DemandStore([])
    h = canon.canon_browse_handler(store)
    for _ in range(3):
        h({})
    assert store.rows[canon.CANON_CONDENSE_CAP]["mass"] == 3.0


def test_an_ANSWERABLE_need_raises_NOTHING():
    """The control: without it, the assertions above would pass on a handler that raises demand on
    every read, which would make the signal mean "someone browsed" rather than "the canon could not
    answer"."""
    store = _DemandStore(CORPUS)
    a = canon.canon_browse_handler(store)({})
    assert a["observed"] is True
    assert store.rows == {}, "demand was raised for a NEED that was answered"


def test_a_store_with_NO_demand_cache_still_answers():
    """A node that cannot carry demand is a fact about the store, not a failure of the read. The
    answer is unchanged; only the `demand` field says it could not be noted."""
    a = canon.canon_browse_handler(_Store([]))({})
    assert a["observed"] is False and a["demand"] is None
    assert canon.CANON_CONDENSE_CAP in a["why"]
