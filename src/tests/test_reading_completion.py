"""The completion path, pinned — place, colimit, boundary, continue.

Each test's docstring states the failure mode it watches for before its assertion, so it can be
checked that the test could fire at all: a prefix-chain walk that can never reach a longer vertex it
holds, an id scheme with two encodings that a single range scan cannot see across, a screen of one
vertex called "learned" when nothing was measured, an artifact written before its edges so a failure
in between leaves an orphan, and an invented boundary standing in for a published coherence read.

The fixtures are temp sqlite, not the live shard. These pin the logic; the numbers from live runs
are recorded in the modules' own headers where they were measured.
"""
import json
import sqlite3

import numpy as np
import pytest


def _code(obj) -> str:
    """The code of a function or module, with docstrings removed.

    A source scan for a specific string can fail on prose rather than on code — a docstring
    describing a defect can contain the very substring the scan is looking for. A module must stay
    free to describe the defect it removed, or the test deletes the record of it, so docstrings are
    stripped before the code is scanned."""
    import ast
    import inspect
    import textwrap
    # `dedent`, not `cleandoc`: `cleandoc` strips the indentation of every line, which destroys a
    # function body — it is for docstrings, not source.
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body.pop(0)
    return ast.unparse(tree)


def _shard(tmp_path, collection, vertices=(), edges=()):
    """A store shaped like the lattice: `vertex(id, ct, doc, created_by)` + `edge(...)`."""
    db = sqlite3.connect(str(tmp_path / "l.db"))
    db.execute("CREATE TABLE vertex (id TEXT PRIMARY KEY, ct TEXT, doc TEXT, created_by TEXT)")
    db.execute("CREATE TABLE edge (src TEXT, dst TEXT, label TEXT, props TEXT, edge_key TEXT)")
    from astra.reading.organon_reader import _unit_id
    for surf in vertices:
        vid = _unit_id(collection, surf)
        db.execute("INSERT OR REPLACE INTO vertex VALUES (?,?,?,?)",
                   (vid, "application/x-token",
                    json.dumps({"id": vid, "name": surf, "content": surf}), "t"))
    for src, dst, label, props in edges:
        db.execute("INSERT OR REPLACE INTO edge VALUES (?,?,?,?,?)",
                   (src, dst, label, json.dumps(props), src + "|" + dst))
    db.commit()
    return sqlite3.connect("file:%s?mode=ro" % str(tmp_path / "l.db"), uri=True)


# ── placement ────────────────────────────────────────────────────────────────────────────────────

def test_place_finds_the_LONGEST_vertex_not_a_prefix_chain(tmp_path):
    """Extending only while every prefix exists stops at the first gap: `Wickham` is held, `Wic` is
    not, so a chain walk can never reach the longer vertex."""
    import reading_junction as J
    C = "read:t"
    ro = _shard(tmp_path, C, vertices=["W", "Wi", "Wickham", "c", "k", "h", "a", "m"])
    assert J.place(ro, C, "Wickham") == ["Wickham"], "placement fell back to the chain walk"


def test_place_sees_BOTH_id_encodings(tmp_path):
    """`:Lady` and `u004c+...` do not sort together, so one range scan is blind to every vertex
    whose surface carries a space or punctuation — the reader could not see what it had just
    written."""
    import reading_junction as J
    C = "read:t"
    ro = _shard(tmp_path, C, vertices=["L", "Lady", "Lady Catherine", "a", "d", "y"])
    assert J.place(ro, C, "Lady Catherine") == ["Lady Catherine"]


def test_place_advances_past_what_it_placed(tmp_path):
    """The residual re-places from its new position; a walk that did not advance would repeat."""
    import reading_junction as J
    C = "read:t"
    ro = _shard(tmp_path, C, vertices=["the ", "cat", "t", "h", "e", " ", "c", "a"])
    assert "".join(J.place(ro, C, "the cat")) == "the cat", "the walk lost or repeated characters"


def test_place_on_an_empty_ontology_places_nothing(tmp_path):
    """A reading that holds nothing recognises nothing — and says so.

    `place` must not fall back to appending a character it never confirmed the ontology holds: an
    empty store would then place a signal completely and `complete` would compute full coverage
    over letters nobody had read. A cold start is a real state, and the honest report of it is that
    nothing was recognised."""
    import reading_junction as J
    C = "read:t"
    ro = _shard(tmp_path, C, vertices=[])
    assert J.place(ro, C, "abc") == []


def test_place_reports_the_part_it_does_not_hold(tmp_path):
    """Coverage has to be able to fall below 1, or it measures nothing."""
    import reading_junction as J
    C = "read:t"
    ro = _shard(tmp_path, C, vertices=["cat "])
    placed = J.place(ro, C, "cat dog")
    assert placed == ["cat "], "a unit the reading never held was manufactured"
    assert sum(len(t) for t in placed) < len("cat dog"), "the miss did not reach coverage"


# ── the colimit, read off the measurement ────────────────────────────────────────────────────────

def test_a_junction_is_read_off_bits_saved_NOT_a_typed_label(tmp_path):
    """A typed `colimit` edge label would be a classification stamped at write time, the same defect
    `member_of` and `next` were removed for. What makes a junction a junction is that it explains its
    members for fewer bits, and `bits_saved` already carries that."""
    import inspect

    from astra.reading import compact
    from lumen.reading import complete
    src = _code(compact) + _code(complete.outgest)
    assert "'colimit'" not in src and '"colimit"' not in src, \
        "a typed colimit label came back; the reading is off `bits_saved`"
    assert "bits_saved" in _code(compact), "the saving is no longer measured"


def test_outgest_descends_only_edges_that_carry_a_saving(tmp_path):
    """A junction's members are the edges with a measured saving. A plain co-presence edge is not a
    membership and must not be descended, or outgest would emit the whole neighbourhood."""
    from astra.reading.organon_reader import _unit_id
    from lumen.reading import complete as C
    K = "read:t"
    j, a, b, other = (_unit_id(K, x) for x in ("cat", "ca", "t", "dog"))
    ro = _shard(tmp_path, K, vertices=["cat", "ca", "t", "dog"], edges=[
        (j, a, "observed", {"bits_saved": 2.0}),
        (j, b, "observed", {"bits_saved": 2.0}),
        (j, other, "observed", {}),            # co-presence, not a membership
    ])
    assert C.outgest(ro, K, j) == "cat", "outgest followed an edge carrying no saving"


# ── the boundary ─────────────────────────────────────────────────────────────────────────────────

def test_the_boundary_is_position_coherence_and_its_zero_is_computed():
    """A boundary invented as a novelty read — `residual > absorbed`, or the incoming residual
    against the screen's mean — would stand in for the published coherence read. This pins that
    `position_coherence` is the one used, and that nothing is compared against a typed level."""
    import inspect

    from astra.reading import resegment
    src = _code(resegment.resegment)
    assert "position_coherence" in src, "the boundary stopped using the published read"
    assert "pc < 0.0" in src, "the boundary is no longer the frame's own computed zero"
    assert "residual" not in src, "a novelty read came back in place of the coherence read"


def test_too_few_rows_to_measure_does_NOT_close_the_screen():
    """[[absence-is-not-an-affirmative-claim]] — `position_coherence` needs four rows and refuses
    below that. 'Could not measure' must not be read as 'does not belong', which is the same error
    that emptied the completion screen when no decay curve could be fitted."""
    import inspect

    from astra.reading import resegment
    src = _code(resegment.resegment)
    assert "len(rows_) < 4" in src and "continue" in src, \
        "a frame too small to measure is being treated as a boundary"


# ── continuation ─────────────────────────────────────────────────────────────────────────────────

def test_a_learned_path_is_CONTINUED_not_forecast(tmp_path):
    """The act is selected by where the hole is: completion holds the context and the operator and
    the hole is the content, so deduction applies first — the observation that held this screen also
    held what followed. Forecasting from the operator is tried only after deduction from context.

    Deduction is `walk`, which continues the placed signal along the order edges the reading itself
    witnessed; the forecast is `predict`, which rolls the dynamical operator. Both names are
    asserted to be present before their order is compared, because a scan for a name the code has
    stopped using reports the ordering claim as unmeasurable rather than as false — and an
    unmeasured claim is what this file exists to prevent."""
    import inspect

    from lumen.reading import complete as C
    src = _code(C.complete)
    assert "walk(" in src, "completion no longer deduces along the order edges"
    assert "predict(" in src, "completion no longer forecasts from the operator"
    i_ctx, i_op = src.index("walk("), src.index("predict(")
    assert i_ctx < i_op, "the forecast is being tried before the deduction again"


def test_continuation_walks_the_observation_stream_in_order(tmp_path):
    """Order comes from the observations' own ticks, not from searching the reassembled text for
    the token: `body.find(token)` returns the first occurrence, which pulls the cursor backwards
    whenever the token recurs, so the completion would re-emit part of the prefix or begin
    mid-word.

    Read on `walk`, which is the deduction `complete` calls."""
    import inspect

    from lumen.reading import complete as C
    src = _code(C.walk)
    assert "obs-" in src, "the continuation stopped reading the observation stream"
    assert "char" not in src, "a stamped position came back onto the edge"


# ── no forcings ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mod", ["astra.reading.read_once", "astra.reading.resegment",
                                 "astra.reading.compact", "reading_junction"])
def test_no_typed_levels_on_the_completion_path(mod):
    """No alpha, no cap, no chosen width: the only legitimate external inputs are a resource
    envelope and a noise provider, and a comparison against a typed level is neither. This scans the
    code, not the docstrings — a module must stay free to describe the defect it removed."""
    import importlib
    import inspect
    m = importlib.import_module(mod)
    body = "\n".join(
        inspect.getsource(f) for _n, f in vars(m).items()
        if callable(f) and getattr(f, "__module__", None) == mod)
    for bad in ("0.05", "0.5 ", "LIMIT 200", "2048", "n_max=", "far="):
        assert bad not in body, "%s carries a typed level: %r" % (mod, bad)


def test_recurrence_is_required_because_n1_is_degenerate():
    """Not a frequency filter: a pair seen once has `p(b|a) = 1` by construction, so its cost is
    maximal on no evidence — the estimator is degenerate at n=1. The second sighting is what makes
    the ratio a measurement."""
    import inspect

    from astra.reading import compact, read_once
    for src in (_code(compact.one_pass), _code(read_once.read_once)):
        assert "n < 2" in src or "n >= 2" in src, "the degeneracy guard at n=1 is gone"
