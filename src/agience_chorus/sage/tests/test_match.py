"""sage's operator-selection tekton — `select` + `Cascade`.

`select` picks the k nearest operators to a need by screened propagation over their offer vectors,
with separation: a near-tie reports "unavailable" rather than a fabricated winner. `Cascade` is the
propagation-in-flight termination guard. Both live in `sage/match.py`, whose sole caller is
`sage/operators.py`; they reach ember's measurement — `propagate` / `_offers` / `activation` — which
stays in ember. Invariants:

  cascade-once    an operator that fires twice in one cascade is a self-sustaining loop; `Cascade`
                  admits it once, does not admit it again, and admits nothing once stopped. Depth is
                  counted, not capped.
  wired           `select` reaches ember's measurement across the sage→ember boundary and returns a
                  well-formed result (`basis`/`matches`/`considered`) without crashing on the import
                  seam.
  honest-absence  an ungroundable need or a store with no operator offers reports
                  `basis="unavailable"` with an empty match list and `considered` still reported — a
                  measured absence, not a guessed pick.
"""
from __future__ import annotations

from agience_chorus.sage import match as M


# ── the fixture's own screening scale ──────────────────────────────────────────────────────────
# `propagate` resolves the screening length and the propagation floor from the corpus (`match.xi()` /
# `match.propagation_floor()`); an unmeasurable scale produces no matches rather than a default. On a
# synthetic fixture with no corpus, both read `None`, every offer scores 0 energy, and `select`
# returns no matches.
#
# The tests below are about the propagation geometry — is the far offer further, does a
# neighbourhood come back rather than a winner — not about where the scale came from, so the scale
# is supplied through `select`'s own `xi=`/`gap=` parameters: a caller stating the world it is
# asking about. This differs from the production path, which measures its own scale and returns no
# matches when it cannot; `test_no_measured_scale_is_an_honest_refusal` below pins that path.
_FIXTURE_XI = 1.0        # the screening length of the world this fixture describes
_FIXTURE_GAP = 0.05      # the propagation floor of that same world


def _select(store, need, **kw):
    """`M.select` with this fixture's stated scale. See the note above."""
    kw.setdefault("xi", _FIXTURE_XI)
    kw.setdefault("gap", _FIXTURE_GAP)
    return M.select(store, need, **kw)


def test_no_measured_scale_is_an_honest_refusal(store):
    """Keeps `_select` honest: without a scale — the real production condition on a store whose
    corpus cannot report one — selection returns no matches rather than a guess. If this starts
    returning matches, a default has been reintroduced and every `_select` call above is measuring a
    fabricated physics."""
    r = M.select(store, "a python function")          # no xi/gap: the corpus must supply them
    from ember.ontology import match as _EM
    if _EM.xi() is None or _EM.propagation_floor() is None:
        assert r["matches"] == [], (
            "no measured scale, yet %d matches came back — a default has returned"
            % len(r["matches"]))



def test_cascade_admits_an_operator_once_then_blocks():
    c = M.Cascade()
    ok, _ = c.admit("op.a")
    assert ok
    ok, why = c.admit("op.a")
    assert not ok and "already fired" in why


def test_cascade_termination_is_the_fire_once_rule_not_a_depth_cap():
    """Fire-once is the only termination bound on a cascade; depth is not capped. Many distinct
    operators (20) all admit, and every repeat of an operator is blocked.

    As a negative control, a cascade still admits a new operator no matter how many have already
    fired — the block is per-operator, not a global cutoff."""
    c = M.Cascade()
    ops = ["op.%d" % i for i in range(20)]           # more than the deleted `max_depth = 8`
    for o in ops:
        ok, why = c.admit(o)
        assert ok, "a distinct operator was refused (%s): %s" % (o, why)
    assert c.depth == len(ops), "depth must COUNT what fired, not cap it"
    for o in ops:
        ok, why = c.admit(o)
        assert not ok and "already fired" in why
    assert c.admit("op.new")[0] is True,         "a never-fired operator was refused — the cascade re-acquired a depth cap"


def test_tekton_basis_none_on_an_empty_offer():
    from ember.ontology import match as EM# the coupling-from-offer measurement lives in ember (both personas reach it)
    assert EM.tekton_basis(None) is None
    assert EM.tekton_basis([]) is None


def test_tekton_basis_spans_the_offer_coordinates(monkeypatch):
    """§A.2 wiring: an operator's offered synsets → their ontology coordinates → the coupling basis
    (the span of those coordinates). Injected coordinates (no substrate needed) prove this
    deterministically."""
    import numpy as np
    from prism.frames import absorb_at_tekton
    from crystal.ontology import geometry as g
    from ember.ontology import match as EM
    from crystal.ontology import driver as wn

    Fd = 16
    coords = {"a.n.01": np.eye(Fd)[0], "b.n.01": np.eye(Fd)[1]}   # two orthogonal offer directions
    monkeypatch.setattr(g, "load_ic", lambda *a, **k: object())
    monkeypatch.setattr(wn, "synset", lambda name: name)         # pass the name through as the "synset"
    monkeypatch.setattr(g, "dense_vec", lambda syn, ic, *a, **k: coords[syn])

    basis = EM.tekton_basis(["a.n.01", "b.n.01"])
    assert basis is not None and basis.shape == (Fd, 2)
    assert np.allclose(basis.T @ basis, np.eye(2), atol=1e-9)    # orthonormal span of the offer

    rng = np.random.default_rng(0)
    W = rng.standard_normal((64, 2)) @ rng.standard_normal((2, Fd)) + 0.02 * rng.standard_normal((64, Fd))
    ab, tr, k = absorb_at_tekton(W, basis=basis)                 # a frame absorbs its band at this tekton
    assert k == 2 and np.allclose(ab + tr, W, atol=1e-9)         # split exact
    assert np.allclose(tr @ basis, 0.0, atol=1e-9)              # residual ⊥ the offer — the band was taken


def test_select_is_wired_across_the_boundary_and_refuses_honestly(tmp_path):
    from mantle.db import open_lattice
    store = open_lattice(str(tmp_path / "s.db"), origin="node-71")
    store.artifacts.ensure_schema()

    r = M.select(store, "a python function")       # reaches ember propagate/_offers/activation
    assert isinstance(r, dict)
    assert r.get("basis") in ("geometric", "unavailable")
    assert "considered" in r and "matches" in r         # well-formed across the sage→ember seam
    if r["basis"] == "unavailable":                     # empty store / no substrate → a measured absence
        assert r["matches"] == []                       # never a fabricated match


# `select`/`Cascade` resolve through sage (`M`). The constants and the offer-cache invalidation they
# assert against (`GAP`/`XI`/`signal_offers`/`invalidate`) are ember's measurement surface and are
# reached as `EM`: the tool is sage's, the physics is ember's.
import math

import pytest

from ember.ontology import match as EM

OT = "application/vnd.agience.operator+json"

PANEL = [
    ("op.describe.markdown", "describes markdown prose documents and text"),
    ("op.describe.python", "describes python source code modules and functions"),
    ("op.source.wikipedia", "ingests encyclopedia articles about the world"),
    ("op.health", "reports node health status and disk memory"),
]


class _FakeStore:
    """The in-memory stand-in these tests were written against (ember `tests/_fakes.py`). Copied,
    not imported: ember's test helpers are not an importable surface for another repo's suite."""

    class _Arts:
        def __init__(self):
            self.d = {}

        def put_artifact(self, doc):
            self.d[doc["id"]] = dict(doc)
            return doc

        def get_artifact(self, aid):
            a = self.d.get(aid)
            return dict(a) if a else None

        def list_artifacts(self, *, content_type=None, state=None, collection_id=None,
                           created_by=None, limit=None, skip=0):
            for a in self.d.values():
                if content_type and a.get("content_type") != content_type:
                    continue
                if state and a.get("state") != state:
                    continue
                yield dict(a)

        def count(self, *, state=None):
            return sum(1 for a in self.d.values() if state is None or a.get("state") == state)

        def put_many(self, docs, *, batch=500):
            for d in docs:
                self.put_artifact(d)
            return len(list(docs)) if hasattr(docs, "__len__") else 0

    def __init__(self):
        self.artifacts = _FakeStore._Arts()
        self.graph = None
        self.content = None
        self.keys_dir = None



def _index_is_usable(wn) -> bool:
    """`wn._INDEX is not None` is a presence check, not a usability one: `select` against an empty
    lattice store leaves `wn._INDEX` built with 0 synsets — not None, and useless. A fixture that
    short-circuits on `is not None` would hand every geometric test an empty index, and all of them
    would read `basis == "unavailable"` for a reason that has nothing to do with what they
    assert."""
    idx = getattr(wn, "_INDEX", None)
    if not idx or not idx[0]:
        return False
    return len(idx[0]) > 1000        # a real WordNet is ~117k synsets; 0 or a handful is a stub


@pytest.fixture(scope="module")
def wn_ready():
    """The offline WordNet index — the real geometry, no live store. Skips where nltk is absent, so
    these read as skipped rather than silently passing on an empty index."""
    from crystal.ontology import driver as wn
    if _index_is_usable(wn):
        return True
    try:
        import math as _m
        from nltk.corpus import wordnet as nwn, wordnet_ic
        from nltk.corpus.reader.wordnet import information_content
    except Exception:
        pytest.skip("WordNet not available in this environment")
    wn._INDEX = None                     # drop any stub index before rebuilding
    icd = wordnet_ic.ic("ic-brown.dat")
    idx, word, missing = {}, {}, 0
    for s in nwn.all_synsets():
        try:
            v = information_content(s, icd)
            v = float(v) if _m.isfinite(v) else None
            if v is not None and v > 14.709437882542113:   # nltk's 1e300 zero-frequency sentinel
                v = None
        except Exception:
            v = None
        counts = {l.name(): int(l.count()) for l in s.lemmas()}
        idx[s.name()] = wn.Synset(s.name(), s.pos(), [h.name() for h in s.hypernyms()],
                                  [h.name() for h in s.instance_hypernyms()], v, counts)
        if v is None:
            missing += 1
        for lm in counts:
            word.setdefault((lm.lower(), s.pos()), []).append(s.name())
    for names in word.values():
        names.sort()
    # Through `install_index`, not by assigning the privates directly: this index came from nltk,
    # not from any store, so the store's write mark says nothing about whether it is current.
    # Assigning `_INDEX` directly would make it look like a derivation the freshness gate owned, and
    # the gate would then drop it on its first observation of the ambient store. See
    # `crystal.ontology.driver.install_index`.
    wn.install_index(idx, word, ic_stats={"synsets": len(idx), "with_ic": len(idx) - missing,
                                          "without_ic": missing})
    return True


@pytest.fixture()
def store(wn_ready):
    s = _FakeStore()
    for oid, offer in PANEL:
        s.artifacts.put_artifact({"id": oid, "content_type": OT, "state": "committed",
                                  "context": offer})
    EM.invalidate(s)
    return s


def test_every_match_carries_its_actual_distance(store):
    r = _select(store, "a python function")
    assert r["basis"] == "geometric"
    assert r["matches"], "nothing matched"
    for m in r["matches"]:
        assert "distance" in m and math.isfinite(m["distance"])
        assert "energy" in m and "nodes" in m


def test_the_cosine_failure_does_not_recur(store):
    """Mean-pooling offers into one direction and ranking by cosine would put `op.health` ("node
    health status and disk memory") at 0.3491 ahead of `op.describe.python` ("python source code
    modules and functions") at 0.1902 for the need "a python function": pooling smears the senses,
    and cosine alone carries no distance term to tell them apart."""
    r = _select(store, "a python function")
    ranked = [m["operator"] for m in r["matches"]]
    assert ranked[0] == "op.describe.python", ranked
    if "op.health" in ranked:
        health = next(m for m in r["matches"] if m["operator"] == "op.health")
        python = next(m for m in r["matches"] if m["operator"] == "op.describe.python")
        assert health["distance"] > python["distance"], "the far offer was not further"


def test_an_unrelated_need_selects_the_right_neighbourhood(store):
    r = _select(store, "disk and memory")
    assert r["matches"][0]["operator"] == "op.health"


def test_the_gap_is_reported_with_the_result(store):
    """The result must name the physics the verdict was reached at, not the physics it was asked
    for.

    `select` reports the caller's `xi`/`gap` arguments — `None` on every call that does not pass
    them — rather than the scale `propagate` resolves and applies internally from the corpus: the
    report says `None` about a propagation that had definite physics behind it, the same gap
    `lumen/reasoning.py` records against its own certificate ("the recorded risk level was not the
    one the verdict was reached at")."""
    r = M.select(store, "a python function")
    assert r["gap"] is None and r["xi"] is None, (
        "select now reports a resolved scale — if that is deliberate, this test should assert "
        "`r['gap'] == EM.propagation_floor()` and the note in sage/match.py should come out")
    assert r["basis"] == "geometric", "the propagation itself still ran on the measured scales"


def test_selection_returns_a_neighbourhood_not_a_winner(store):
    """D14: signals propagate, so contexts that fit and are nearby get activated too — selection
    returns a neighbourhood, not a single winner.

    The match count is `prism.resolution.signal_end` over the energy column, which returns the whole
    column when it does not separate, so it cannot clip a neighbourhood on its own. The assertion
    below reads that invariant off the thing that decides it, plus a guard that no typed page size
    has grown back — the same shape `mantle/tests/test_anchors.py:492` uses for the same reason:
    "the anchor count is not a knob anywhere"."""
    assert not hasattr(EM, "DEFAULT_K"), "a page size grew back — the count must be measured"
    r = _select(store, "an encyclopedia article about animals")
    assert len(r["matches"]) > 1, "selection collapsed to a single winner"
    # with nothing pinned, the derived count is still reported and is not silently a page size
    d = _select(store, "an encyclopedia article about animals")
    assert d["k_derived"] is True

    # `signal_end` is reported rather than applied: slicing the match list to `k` would destroy the
    # rest of a measurement to report a measurement, which is the conservation break this path
    # avoids. `k` is a reading over the returned column, so it cannot exceed the column, and the
    # column is not cut down to it. Equality between `k` and the match count is not assumed — here
    # k = 2 against 3 matches.
    assert d["k"] <= len(d["matches"]), (
        "the derived count (%s) exceeds the matches it was read from (%d) — it is not a reading of "
        "this column" % (d["k"], len(d["matches"])))
    assert len(d["matches"]) >= len(r["matches"]), "the match list was truncated to the derived count"


def test_an_ungroundable_need_reports_unavailable_not_an_empty_match(store):
    r = M.select(store, "!!!")
    assert r["basis"] == "unavailable"
    assert r["reason"]
    assert r["matches"] == []


def test_offers_that_never_grounded_are_reported_not_dropped(wn_ready):
    """"no operator matched" must stay distinguishable from "some operators could never be
    measured" — a real miss versus a blind spot."""
    s = _FakeStore()
    s.artifacts.put_artifact({"id": "op.a", "content_type": OT, "state": "committed",
                              "context": "describes python source code"})
    s.artifacts.put_artifact({"id": "op.blank", "content_type": OT, "state": "committed",
                              "context": "!!! ??? ..."})
    EM.invalidate(s)
    r = M.select(s, "python code")
    assert "op.blank" in r["unembeddable"]
    assert r["considered"] == 2


def test_no_offers_at_all_is_unavailable_not_a_confident_empty(wn_ready):
    s = _FakeStore()
    EM.invalidate(s)
    r = M.select(s, "python code")
    assert r["basis"] == "unavailable" and r["matches"] == []


def test_an_operator_fires_at_most_once_per_cascade():
    """Termination is not automatic (D14): salience decay bounds a single spread, but
    operator → artifact → operator rounds decay only if the artifacts move through meaning-space.
    Two operators regenerating each other's inputs would sustain indefinitely without fire-once."""
    c = M.Cascade()
    assert c.admit("op.a")[0] is True
    ok, why = c.admit("op.a")
    assert ok is False and "already fired" in why


def test_depth_is_a_counter_and_never_a_bound(store):
    """`depth` is reported, compared to nothing — a counter, never a bound."""
    c = M.Cascade()
    assert c.admit("op.a")[0] is True
    assert c.admit("op.b")[0] is True
    assert c.admit("op.c")[0] is True
    assert c.depth == 3 and c.stopped is None
    assert not hasattr(c, "max_depth"), "the depth cap came back"


def test_offer_cache_does_not_leak_between_stores(wn_ready):
    """An unkeyed cache serves one store's offers to another — the defect `genesis`'s
    `_ARTIFACT_COUNT_CACHE` and `_METRICS_CACHE` have."""
    a, b = _FakeStore(), _FakeStore()
    a.artifacts.put_artifact({"id": "op.only.in.a", "content_type": OT, "state": "committed",
                              "context": "describes python source code"})
    EM.invalidate(a)
    EM.invalidate(b)
    assert M.select(a, "python code")["considered"] == 1
    assert M.select(b, "python code")["considered"] == 0


def test_invalidate_picks_up_a_new_operator(wn_ready):
    s = _FakeStore()
    s.artifacts.put_artifact({"id": "op.a", "content_type": OT, "state": "committed",
                              "context": "describes python source code"})
    EM.invalidate(s)
    assert M.select(s, "python code")["considered"] == 1
    s.artifacts.put_artifact({"id": "op.b", "content_type": OT, "state": "committed",
                              "context": "describes markdown documents"})
    EM.invalidate(s)
    assert M.select(s, "python code")["considered"] == 2


def test_separation_is_reported_and_gates_the_basis(wn_ready):
    """The matcher reports whether its candidates separated, and that flag gates whether a geometric
    winner is served or the generic fallback is.

    `separated` is `prism.resolution.separated` over the whole energy column, against the computed
    no-structure baseline for a column of that length — a ratio of the top two readings would be a
    local statistic deciding a global question (`prism/resolution.py`'s header takes this apart).

    The invariant is falsifiable: the reported boolean must agree with the independent instrument run
    on the reported energies, not with any constant. It fails if `select` ever hand-rolls its own
    separation, and the negative control (a flat column) fails if `separated` becomes something that
    cannot say no.

    SemCor-count seeding grounds technical vocabulary — "python" resolves as source code, not the
    snake — so this need ("a source code module with functions") separates: the energy column
    [4.589, 3.337, 0.605] gives η² = 0.9056 against a null of 0.75, with the signal group resolving
    to two offers — a neighbourhood, not a winner."""
    from prism.resolution import separated as _sep
    from prism.runner import operators as ops
    s = _FakeStore()
    ops.register_operators(s.artifacts)
    EM.invalidate(s.artifacts)

    r = M.select(s.artifacts, "a source code module with functions")   # no k: the data decides
    assert r["basis"] == "geometric"
    energies = [m["energy"] for m in M.select(s.artifacts, "a source code module with functions")["matches"]]
    if len(energies) >= 3:
        # the reported flag is the instrument's read, recomputed here independently of `select`
        assert r["separated"] is _sep(energies)
        assert r["separability"] is not None and 0.0 <= r["separability"] <= 1.0
    else:
        # too short a column for the null to say anything — "not measured", never a verdict
        assert r["separated"] is None and r["separability"] is None

    # negative control: an instrument that cannot say "no" proves nothing. A flat column has no
    # structure to find, and both the boolean and the count must reflect that — all of it, uncut.
    assert EM.signal_offers([5.0, 5.0, 5.0, 5.0], considered=4) == {
        "k": 4, "separated": False, "separability": 0.0}
    # a column that does not exist is not measured — a different statement from "did not separate"
    assert EM.signal_offers([], considered=0)["separated"] is None
    # The `ops.select_for(...)` half of this test lives in ember, where its subject lives, and is
    # pinned there as dark: the runner bundle's geometric arm resolves its `match` seam to
    # `ember.ontology.match`, which has no `select`, and a bare `except Exception: pass` swallows the
    # resulting AttributeError. See `agience-ember/tests/test_match.py::
    # test_the_runner_bundles_geometric_arm_is_DARK_since_select_moved_to_sage`.


def test_a_separated_result_is_used(wn_ready):
    """A single survivor of the propagation floor is separated, and the separator is measured, not chosen:
    `propagate` reports energy only for offers that cleared the gap, and `prism.resolution.reach_limit`
    says exactly what the rest are — "a weight already below the gap cannot clear it at any distance,
    including zero". One survivor out of several considered is separated by the gap, which
    `propagation_floor()` measures. Here, "prose" leaves exactly one offer standing (op.describe.markdown,
    energy 15.09); this fails if a second offer ever clears the gap and `separated` still reads
    True."""
    from prism.runner import operators as ops
    s = _FakeStore()
    ops.register_operators(s.artifacts)
    EM.invalidate(s.artifacts)
    r = _select(s.artifacts, "prose")
    assert len(r["matches"]) == 1 and r["considered"] > 1, "no longer the single-survivor case"
    assert r["separated"] is True and r["margin"] == 1.0
    # negative control: winning uncontested is not a measurement. With nothing else considered
    # there was no gap to be separated by, and the honest report is "not measured".
    assert EM.signal_offers([15.09], considered=1)["separated"] is None
    # (the `ops.select_for` assertion lives in ember, with its subject — see the note above)
    assert r["matches"] and r["matches"][0]["operator"] == "op.describe.markdown"


def test_matches_report_what_they_grounded_to(store):
    """WordNet mis-grounds technical vocabulary, so a caller must be able to see that an offer
    landed on `python.n.01` (a snake) rather than infer trustworthiness from a score."""
    r = M.select(store, "a python function")
    for m in r["matches"]:
        assert isinstance(m["grounded"], list) and m["grounded"]
