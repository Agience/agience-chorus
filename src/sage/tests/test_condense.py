"""Condensation — a reached set resolves into what it is, and never into a ranked list.

These are pure: they exercise the shape logic through a stubbed ontology, so they pin the
derivations (which condenser applies, and why) rather than any particular corpus.
"""
import pytest

import condense as cd


class _Syn:
    def __init__(self, name, parent=None, ic=1.0):
        self._n, self._p, self._ic = name, parent, ic

    def name(self):
        return self._n

    def hypernyms(self):
        return [_TREE[self._p]] if self._p else []

    def instance_hypernyms(self):
        return []

    def common_hypernyms(self, _other):
        out, node = [], self
        while node._p:
            node = _TREE[node._p]
            out.append(node)
        return out


#            entity(0.03)
#         /              \
#   animal(0.5)        idea(0.5)
#    /      \              |
#  dog(0.9) cat(0.9)   theory(0.9)
_TREE = {}
for nm, par, ic in [("entity", None, 0.03), ("animal", "entity", 0.5), ("idea", "entity", 0.5),
                    ("dog", "animal", 0.9), ("cat", "animal", 0.9), ("pup", "dog", 0.97),
                    ("theory", "idea", 0.9)]:
    _TREE[nm] = _Syn(nm, par, ic)


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    """Patches the real module, not `sys.modules`: `condense` does `from crystal.ontology import
    geometry as g`, which reads the attribute off the already-imported `crystal.ontology` package —
    inserting a fake into `sys.modules` leaves that attribute untouched, so the stub would silently
    do nothing and the test would run against the real ontology while appearing to be isolated."""
    from crystal.ontology import geometry as real_g
    monkeypatch.setattr(cd, "_syn", lambda n: _TREE.get(n))
    monkeypatch.setattr(real_g, "load_ic", lambda: None)
    monkeypatch.setattr(real_g, "ic_of", lambda s, _ic, strict=True: (s._ic if s is not None else 0.0))
    monkeypatch.setattr(real_g, "canonical_parent",
                        lambda s, _ic: (_TREE[s._p] if s is not None and s._p else None))
    cd._ROOT_IC.clear()
    cd._ROOT_IC.append(0.03)                       # the root's own IC: the "says nothing" zero point
    yield


def test_one_dominant_node_DEFINES():
    c = cd.condense([("dog", 9.0), ("cat", 0.2), ("pup", 0.1), ("theory", 0.05)])
    assert c.kind == "define" and c.head == "dog"


def test_a_family_SUBSUMES_and_names_what_distinguishes():
    """The colimit: say what they all are, then only what the members add to it.

    Three near-equal members are a family, not a two-group split, even though their absolute
    difference is a fraction of a percent. `separated` compares the reading against
    `_null_separability(n)`, the identical statistic run on a featureless ramp of the same length;
    for n = 3 both numbers are 0.75. The tie-break between them (`prism/resolution.py::_tie_break`)
    is derived from float cancellation in the sum of squared deviations rather than from the number
    of terms, since `[5.0, 4.9, 4.8]` is a uniform ramp — `resolution.py`'s own canonical "nothing
    to find" case, and the chat answer path (this runs under `sage/content_search.py`) depends on it
    reading that way rather than as a contrast."""
    c = cd.condense([("dog", 5.0), ("cat", 4.9), ("pup", 4.8)])
    assert c.kind == "subsume" and c.head == "animal"
    assert set(c.distinguishing) == {"dog", "cat", "pup"}     # all more informative than `animal`


def test_A_SCATTER_IS_NOT_A_GROUP():
    """On the live corpus, every contrast condensed with one side's subsumer being the root, because
    the tail of a reached set is a grab-bag and a grab-bag's least common subsumer is always the top
    of the tree — the vacuous-head impurity one level down. The zero point is not chosen: it is the
    root's own IC, which the corpus supplies."""
    assert cd._is_scatter("entity", None) is True             # says nothing
    assert cd._is_scatter("animal", None) is False
    assert cd._is_scatter(None, None) is True


def test_DISAMBIGUATE_when_the_shared_object_is_vaguer_than_the_question():
    """The case `resolve_at` structurally cannot fix, because it only walks up. "What is a dog"
    subsumes to `physical entity`, since the reached set spans dog(animal), dog(person), andiron
    and pawl — no amount of climbing makes those one family, because the head is already more
    general than the question. The test needs no constant: when the subsumer carries less
    information than the question did, the answer is an ambiguity, not a subsumption."""
    c = cd.condense([("dog", 5.0), ("theory", 4.9)], asked_ic=0.9)
    assert c.kind == "disambiguate"
    assert set(c.members) == {"dog", "theory"}                # one per branch, not one vague head
    assert c.basis["subsumer"] == "entity"
    assert c.basis["subsumer_ic"] < c.basis["asked_ic"]


def test_the_same_set_condenses_DIFFERENTLY_for_a_vaguer_question():
    """"At my level" is not a setting. A question asked higher up subsumes where a question asked
    lower down disambiguates — the same reached set, a different reading."""
    deep = cd.condense([("dog", 5.0), ("theory", 4.9)], asked_ic=0.9)
    shallow = cd.condense([("dog", 5.0), ("theory", 4.9)], asked_ic=0.02)
    assert deep.kind == "disambiguate" and shallow.kind == "subsume"


def test_SIBLINGS_ARE_A_FAMILY_NOT_AN_AMBIGUITY():
    """"The subsumer is vaguer than the question" is not sufficient on its own: `dog` and `cat`
    subsume to `animal`, which is vaguer than a question asked at `dog`'s level — but they are
    siblings, and siblings are a family. The separating test is structural and exact rather than a
    threshold: do the members meet at the subsumer (their direct parent), or only far below their
    own parents?"""
    fam = cd.condense([("dog", 5.0), ("cat", 4.9)], asked_ic=0.9)
    assert fam.kind == "subsume" and fam.head == "animal"
    assert cd._are_siblings(["dog", "cat"], "animal", None) is True
    assert cd._are_siblings(["dog", "theory"], "entity", None) is False


def test_nothing_reached_says_nothing_reached():
    assert cd.condense([]).kind == "empty"
    assert cd.condense([("nonexistent", 1.0)]).kind == "empty"


def test_a_single_node_is_a_definition():
    assert cd.condense([("dog", 1.0)]).kind == "define"


def test_resolve_at_walks_to_the_ALTITUDE_not_a_hop_count():
    """The impurity removed from propagation, removed here too: a dense lineage and a sparse one
    must land at the same informational altitude, not the same number of steps."""
    assert cd.resolve_at("pup", 0.5) == "animal"       # closest IC to 0.5, however many hops
    assert cd.resolve_at("pup", 0.97) == "pup"         # already there
