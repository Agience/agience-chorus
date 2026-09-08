"""The read corpus's coordinate, pinned — and pinned against preselection above all.

The failure these tests watch for: a width nobody measured, standing in for the width the reading
itself produced.

    one-hot over vocabulary   F=3067  T=12000   contrast 0.4671   resolved_modes  0   -> refuses
    signed hash into D=2048   F=2048  T= 3870   contrast 4.2303   resolved_modes  4   -> reads
    contexts x sqrt(bits)     F= 180  T= 3870   contrast 9.5719   resolved_modes 22   -> reads

The one-hot width grows with the vocabulary. The hashed width is chosen (`D = 2048`, of which 163
columns are live). Only the third is a count the reading produced, and the difference is not
cosmetic: dropping the chosen width more than doubles contrast and gives 5.5x the modes.

Entroptics purity forbids fixing any parameter or constant, so the tests below assert the absence
of choices, not the presence of numbers: that the width is the context count, that the amplitude is
entroptics' own information measure rather than a plausible reciprocal, and that nothing is
excluded.

Asserting "contrast > 1" on a fixture is not done here, deliberately: it would assert that a toy
resolves, which says nothing about the instrument and breaks whenever the fixture is edited.
"""
import json
import sqlite3

import numpy as np
import pytest


@pytest.fixture
def read_shard(tmp_path):
    """A tiny read collection: three contexts, overlapping units, one hub unit and one hub context."""
    db = sqlite3.connect(str(tmp_path / "l.db"))
    db.execute("CREATE TABLE vertex (id TEXT PRIMARY KEY, ct TEXT, doc TEXT, created_by TEXT)")
    db.execute("CREATE TABLE edge (src TEXT, dst TEXT, label TEXT, props TEXT, edge_key TEXT)")
    C = "read:b"

    def unit(name):
        return "%s:span:%s" % (C, name.encode("utf-8").hex())

    def ctx(n, units, label="observed"):
        pid = "%s:para-%d" % (C, n)
        db.execute("INSERT OR REPLACE INTO vertex VALUES (?,?,?,?)",
                   (pid, "application/x-paragraph", json.dumps({"id": pid}), "t"))
        for u in units:
            db.execute("INSERT OR REPLACE INTO edge VALUES (?,?,?,?,?)",
                       (pid, unit(u), label, "{}", pid + "|" + unit(u)))

    # `the` is in every context — it must be quieter, never excluded.
    ctx(0, ["the", "cat", "sat"])
    ctx(1, ["the", "cat", "ran"])
    ctx(2, ["the", "dog"], label="observed_alone")
    db.commit()
    return str(tmp_path / "l.db"), C


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def _row(M, names, C, surface):
    return M[names.index("%s:span:%s" % (C, surface.encode("utf-8").hex()))]


def test_the_width_is_the_CONTEXT_COUNT_and_nothing_chooses_it(read_shard):
    """The width must be a count the reading produced. A `d=`/`D` parameter reappearing here is the
    defect returning, so the signature is pinned too."""
    import inspect
    from agience_chorus.astra.reading import read_basis
    path, C = read_shard
    M, names, contexts = read_basis.cloud(_ro(path), C)
    assert M.shape == (len(names), len(contexts))
    assert len(contexts) == 3, contexts          # exactly the paragraphs the fixture wrote
    assert len(names) == 5, names                # the, cat, sat, ran, dog
    # no caller may state a width, and none may be defaulted in
    params = list(inspect.signature(read_basis.cloud).parameters)
    assert params == ["ro", "collection"], params
    # Scoped to the code that builds the width, not to the module: scanning the whole module's
    # source would fail on this module's own docstring, which documents the `D = 2048` defect — a
    # test that forbids describing a bug would delete the record of it.
    from agience_chorus._host_seams import seam
    body = inspect.getsource(seam("projection").read_cloud)
    assert "2048" not in body, "a chosen width came back into the coordinate"
    assert "hash" not in body.lower(), "a feature hash came back — the width is exact, not hashed"


def test_reading_MORE_grows_rows_FASTER_than_the_width(read_shard):
    """`T/F` must rise as the corpus grows — the property one-hot inverted. Units accumulate far
    faster than contexts, so adding a context that carries several new units improves the frame."""
    from agience_chorus.astra.reading import read_basis
    path, C = read_shard
    M0, n0, c0 = read_basis.cloud(_ro(path), C)
    db = sqlite3.connect(path)
    pid = "%s:para-9" % C
    for u in ["fox", "owl", "elk", "hen"]:
        uid = "%s:span:%s" % (C, u.encode("utf-8").hex())
        db.execute("INSERT OR REPLACE INTO edge VALUES (?,?,?,?,?)",
                   (pid, uid, "observed", "{}", pid + "|" + uid))
    db.commit()
    M1, n1, c1 = read_basis.cloud(_ro(path), C)
    assert len(c1) == len(c0) + 1, "one context was added"
    assert len(n1) == len(n0) + 4, "four units were added"
    assert (len(n1) / len(c1)) > (len(n0) / len(c0)), "T/F fell — the one-hot defect returning"


def test_the_amplitude_is_ENTROPTICS_INFORMATION_not_a_hand_rolled_reciprocal(read_shard):
    """A plausible reciprocal like `1/degree` has no owner and would stand in for the measure
    entroptics already publishes. This pins the source, not a computed number: the cell must be
    `sqrt(self_information_bits(deg, total))` read through the instrument."""
    from agience_chorus._host_seams import seam
    from agience_chorus.astra.reading import read_basis
    path, C = read_shard
    M, names, contexts = read_basis.cloud(_ro(path), C)
    # `dog` sits in exactly one context (para-2, which holds 2 units); total incidences = 8.
    bits = seam("optics").self_information_bits(2.0, 8.0)
    assert np.abs(_row(M, names, C, "dog")).max() == pytest.approx(np.sqrt(bits))
    # The scan follows the seam, not a path: the construction lives in the host (lumen needs the
    # same measurement and may not import astra), so scanning astra's own module would scan a
    # delegating stub and pass while testing nothing. Scanning whatever the host bound is what the
    # persona actually calls.
    src = __import__("inspect").getsource(seam("projection").read_cloud)
    assert "self_information_bits" in src, "the instrument's information read was bypassed"
    assert "1.0 / float(deg" not in src, "the hand-rolled reciprocal came back"


def test_a_CROWDED_context_arrives_QUIETER_and_nothing_is_excluded(read_shard):
    """Not a stop-list: a context holding more units narrows less, so it carries fewer bits and
    arrives at lower amplitude — and is still there.

    `the` is not compared against `dog` here because both sit in para-2, so both would take its
    amplitude and the maxima would tie exactly — two units sharing their heaviest context cannot
    measure a per-context weight. `sat` and `dog` have disjoint contexts, so they can."""
    from agience_chorus.astra.reading import read_basis
    path, C = read_shard
    M, names, _ = read_basis.cloud(_ro(path), C)
    sat = np.abs(_row(M, names, C, "sat")).max()      # only para-0, which holds 3 units
    dog = np.abs(_row(M, names, C, "dog")).max()      # only para-2, which holds 2
    assert sat < dog, (sat, dog)
    assert np.any(_row(M, names, C, "the")), "the hub unit was excluded rather than quietened"


def test_an_empty_read_REFUSES_rather_than_returning_a_basis(tmp_path):
    """[[absence-is-not-an-affirmative-claim]] — a collection nothing was read into has no basis, and
    saying so is not the same as returning an empty one."""
    from agience_chorus.astra.reading import read_basis
    db = sqlite3.connect(str(tmp_path / "e.db"))
    db.execute("CREATE TABLE vertex (id TEXT PRIMARY KEY, ct TEXT, doc TEXT, created_by TEXT)")
    db.execute("CREATE TABLE edge (src TEXT, dst TEXT, label TEXT, props TEXT, edge_key TEXT)")
    db.commit()
    ro = _ro(str(tmp_path / "e.db"))
    M, names, contexts = read_basis.cloud(ro, "read:nothing")
    assert M is None and names == [] and contexts == []
    assert read_basis.derive(ro, "read:nothing") is None


def test_the_coordinate_is_DETERMINISTIC_across_processes(read_shard):
    """No seed, no hash, no dict-order dependence — two observers derive the same cloud. A basis
    nobody else can reproduce is not a corpus property."""
    from agience_chorus.astra.reading import read_basis
    path, C = read_shard
    a, na, ca = read_basis.cloud(_ro(path), C)
    b, nb, cb = read_basis.cloud(_ro(path), C)
    assert na == nb and ca == cb
    assert np.array_equal(a, b)


def test_the_cloud_is_read_on_an_INDEXED_range_not_a_table_scan(read_shard):
    """Cost is a property of the question: `src LIKE 'read:x:%'` cannot use the index the way a
    range can, so this pins the range form to keep the basis derivation from quietly turning into a
    full scan of the lattice."""
    import inspect

    from agience_chorus._host_seams import seam
    src = inspect.getsource(seam("projection").read_unit_contexts)
    # The SQL is scanned, not the prose: scanning the whole source would fail on this function's own
    # docstring, which says "never a `LIKE`" — a test that forbids describing the defect would
    # delete the record of it.
    sql = [ln for ln in src.splitlines() if "SELECT" in ln.upper()]
    assert sql, "the unit->context read no longer issues a SELECT this test can see"
    assert not any("LIKE" in ln.upper() for ln in sql), "the read went back to a LIKE scan: %s" % sql
    assert ">= ?" in src and "< ?" in src, "the indexed range bound is gone"
