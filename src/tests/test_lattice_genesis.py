"""genesis.py's four store call sites, on typed methods rather than raw SQL.

Moved here from `agience-ember/tests/test_lattice_genesis.py`: these exercise operators through ember's
runner and need a sha-verified operator payload present. The payloads are chorus's,
built from chorus source; ember is the engine that runs them, so the test belongs
beside the operators. Tests in that file needing no payload stayed in ember.
"""
from __future__ import annotations
import pytest
from ember import genesis as g
lattice = pytest.importorskip("mantle.db",
                              reason="lattice store (unit L) not importable on this path")
SHARD_DONE_CT = g.SHARD_DONE_CT
ORIGIN = "test-observer"
class _Store:
    """The store faces genesis.py touches, shaped like `mantle.shard.local_store.LocalStore`."""

    def __init__(self, L):
        self.artifacts = L.artifacts
        self.graph = L.graph
        self.content = None
        self.keys_dir = None
@pytest.fixture()
def store(tmp_path):
    L = lattice.open_lattice(str(tmp_path / "lattice.db"), origin=ORIGIN)
    L.artifacts.ensure_schema()
    L.graph.ensure_schema()
    return _Store(L)
def _seed(store, *, grammar=40, world_committed=120, world_draft=30, loose=25):
    """Deliberately asymmetric: two collections of different sizes plus artifacts in no collection,
    so a per-collection count and the global count cannot coincide by accident. A symmetric fixture
    would let a global-count answer pass as a per-collection one."""
    docs = []
    for i in range(grammar):
        docs.append({"id": "g%04d" % i, "content_type": "text/markdown",
                     "collection_id": "stage.1.grammar", "state": "committed",
                     "content": "grammar", "size": 100, "lemmas": ["g%d" % i],
                     "cited_from": g.CITE_GENESIS, "provenance": g.P_HUMAN})
    for i in range(world_committed + world_draft):
        docs.append({"id": "w%04d" % i, "content_type": "text/markdown",
                     "collection_id": "stage.2.world",
                     "state": "committed" if i < world_committed else "draft",
                     "content": "world", "size": 200, "lemmas": ["w%d" % i],
                     "cited_from": g.CITE_GENESIS, "provenance": g.P_HUMAN})
    for i in range(loose):
        docs.append({"id": "op.free.%02d" % i, "content_type": g.OPERATOR_CONTENT_TYPE,
                     "state": "committed", "content": "op",
                     "cited_from": g.CITE_GENESIS, "provenance": g.P_HUMAN})
    store.artifacts.put_many(docs, batch=200)
    return len(docs)
class _Exploding:
    """A connection that raises on any use, standing in for a non-lattice connection.

    The assertions below are on the returned value rather than on the raise. Every legacy branch
    wraps its query in `except Exception`, so `_Exploding` is absorbed the same way an `[]` answer
    would be, and a `pytest.raises` here would pass while measuring nothing. Routing to a non-lattice
    connection therefore shows up as the empty or fallback answer, which is what these assertions
    pin. The store is always the SQLite lattice, so this is the guard that raw SQL never reaches
    anything else."""

    def query(self, *a, **kw):
        raise AssertionError("raw SQL reached a non-Arcade connection")

    def command(self, *a, **kw):
        raise AssertionError("raw SQL reached a non-Arcade connection")
def _last_seq(store):
    r = store.artifacts.db.read().execute(
        "SELECT last_seq FROM seq_counter WHERE origin = ?", (ORIGIN,)).fetchone()
    return int(r["last_seq"]) if r else 0


def test_nearvdup_excludes_unsigned_artifacts(store):
    """An artifact with no usable signature is excluded from comparison, so the operator reports
    nothing comparable rather than consolidating on no evidence.

    This guard carries real weight. `minhash` is never written anywhere in the tree, so every
    signature read off an artifact is all-zero, and `estimated_jaccard(zeros, zeros)` is 1.0 — an
    unguarded `apply=True` would archive the whole corpus as duplicates of one row.

    The fixture reproduces that condition exactly: no `minhash` field and no inline `content`, which
    is what a content-store-backed box holds, since `content` is popped at ingest whenever a content
    store is configured."""
    for i in range(6):
        store.artifacts.put_artifact({"id": "nc%d" % i, "content_type": "text/markdown",
                                      "collection_id": "stage.1.grammar", "state": "committed",
                                      "size": 4096,          # real bytes live in the content store
                                      "cited_from": g.CITE_GENESIS, "provenance": g.P_HUMAN})
    r = g.consolidate_nearvdup(store, content_type="text/markdown",
                               collection_id="stage.1.grammar", apply=False)
    # all six signatures are all-zero, i.e. no evidence. `estimated_jaccard(zeros, zeros)` is 1.0,
    # so an unguarded run would report one perfect group of six.
    assert r["consolidated"] == 0
    assert r["groups"] == 0
    assert r.get("skipped_no_signature") == 6
    assert "no artifact carried a usable minhash signature" in r.get("reason", "")
    # and a dry run drew no edges
    assert g._consolidated_members(store) == set()


def test_registering_control_operators_twice_allocates_nothing_the_second_time(store):
    """`_seq` is this observer's proper time, and a write that changes nothing consumes none of it.
    Counting allocations is the measurement itself rather than a proxy for it."""
    g.register_control_operators(store)
    first_alloc = _last_seq(store)
    assert first_alloc >= len(g.CONTROL_OPS), "the first registration must write"
    assert g._CONTROL_OPS_WRITTEN["last"] == len(g.CONTROL_OPS)

    for _ in range(5):
        assert g.register_control_operators(store) == len(g.CONTROL_OPS)
    assert _last_seq(store) == first_alloc, "re-registration allocated proper time"
    assert g._CONTROL_OPS_WRITTEN["last"] == 0


def test_created_time_is_set_once_and_never_re_read(store):
    """`created_time` is set once. Contract §2.2: the value is a claim about one observer's clock at
    creation, so re-reading it from the clock on every call would both churn the row and describe
    something other than creation."""
    g.register_control_operators(store)
    name = g.CONTROL_OPS[0][0]
    first = store.artifacts.get_artifact(name)["created_time"]
    g.register_control_operators(store)
    assert store.artifacts.get_artifact(name)["created_time"] == first


def test_a_changed_definition_IS_rewritten(store):
    """A real change is written. Skipping unchanged writes only holds if a changed definition still
    lands; otherwise the operator artifact stops tracking the code."""
    g.register_control_operators(store)
    settled = _last_seq(store)
    name, offer = g.CONTROL_OPS[0]

    doc = store.artifacts.get_artifact(name)
    doc["context"] = "something a previous release wrote"
    store.artifacts.put_artifact(doc)
    drifted = _last_seq(store)
    assert drifted > settled

    g.register_control_operators(store)
    assert _last_seq(store) > drifted, "a drifted definition must be repaired"
    assert store.artifacts.get_artifact(name)["context"] == offer
    assert g._CONTROL_OPS_WRITTEN["last"] == 1, "only the drifted one, not all 14"


def test_accrued_fitness_still_survives_re_registration(store):
    """`preserve_fitness` is what makes re-registration safe, and it still holds when a definition
    changes and the write does land."""
    from ember.runtime.runner import evolution
    g.register_control_operators(store)
    name = g.CONTROL_OPS[0][0]
    evolution.record_invocation(store.artifacts, name, verified=True)
    assert store.artifacts.get_artifact(name)["invocations"] == 1

    g.register_control_operators(store)
    assert store.artifacts.get_artifact(name)["invocations"] == 1
    assert g._CONTROL_OPS_WRITTEN["last"] == 0, "recorded fitness is not a definition change"


def test_run_task_does_not_republish_operator_definitions(store):
    """End to end, through the real `genesis.invoke`. Registration is reached indirectly on every
    task the pool executes, so its cost is only visible from a task run: unconditional rewriting
    costs 15 `_seq` allocations per `run_task` — 14 operator rewrites plus the one task-status
    update — for a successful run, and the same 15 for one that failed.

    The assertion is on the allocation count rather than a call count. `put_artifact` is idempotent
    by id, so writing the same bytes again leaves the row correct and would satisfy any assertion
    about the row, while still consuming proper time, vacating the old seq and churning a merkle
    leaf. The question is whether the content changed, not whether put was called."""
    from ember.runtime import pool

    g.bootstrap(store)
    g.register_control_operators(store)

    for i, (op, expect_ok) in enumerate([("op.consistency", True),
                                         ("op.no.such.operator", False)]):
        pool.enqueue(store, op, {}, key="r-%d" % i)
        t = pool.claim(store, "w-R")
        assert t is not None
        before = _last_seq(store)
        res = pool.run_task(store, t)
        spent = _last_seq(store) - before

        assert res["ok"] is expect_ok
        # Checked here rather than assumed: an `{"error": ...}` envelope from `genesis.invoke` is a
        # failure. Were it not, the retry/backoff/dead-letter ladder would be unreachable and the
        # measurement below would be measuring a successful no-op.
        assert g._CONTROL_OPS_WRITTEN["last"] == 0, (
            "run_task rewrote %d operator artifacts" % g._CONTROL_OPS_WRITTEN["last"])
        assert spent <= 2, (
            "%r allocated %d _seq; the task-status update is the only authored event a "
            "no-side-effect operator is entitled to" % (op, spent))

    dead = store.artifacts.get_artifact("task-r-1")
    assert dead["attempts"] == 1 and dead["status"] == "pending", "retry ladder is unreachable"
