"""Pins `_root_ic` to find the taxonomy's root rather than its loudest orphan.

`_root_ic` scans noun synsets with no hypernym and takes the maximum information content, calling
that the corpus's zero point for "this says nothing"; `_is_scatter` then refuses any subsumer at or
below it. This is unsafe against a corpus where most parentless synsets are orphans rather than
roots: an isolated synset has maximal information content, so "parentless, take the max" returns a
value at or near 1.0 and the gate refuses every set.

Open Multilingual WordNet families can land with no hypernym edges at all, producing exactly this
shape, while a taxonomy like the English WordNet has an intact hierarchy with only a couple of
parentless synsets. The fixture in this file includes an orphan alongside a real root, because a
fixture that cannot reproduce that shape cannot guard against it.

`_root_ic`'s own comment records the symmetric failure this test also checks: a fabricated `0.0`
would permanently open the gate, and a poisoned max would permanently close it. Same function, two
opposite failure modes, both covered here.
"""
import pytest

from sage import condense as cd


class _Syn:
    def __init__(self, name, parent, ic):
        self._name, self._p, self._ic = name, parent, ic

    def name(self):
        return self._name

    def hypernyms(self):
        return [_TREE[self._p]] if self._p else []

    def instance_hypernyms(self):
        return []


#             entity(0.03)                    <- the real root: parentless and has children
#          /              \
#    animal(0.5)       idea(0.5)
#      |
#   dog(0.9)
#
#   orphan-xx(1.0)   orphan-yy(1.0)           <- parentless and childless: not roots
_TREE = {}
for nm, par, ic in [("entity", None, 0.03), ("animal", "entity", 0.5), ("idea", "entity", 0.5),
                    ("dog", "animal", 0.9),
                    ("omw-xx-0001-n", None, 1.0), ("omw-yy-0002-n", None, 1.0)]:
    _TREE[nm] = _Syn(nm, par, ic)

NOUN = "n"


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    """Patches the real module attribute rather than `sys.modules`, since `_root_ic` does its imports
    inside the function body (`from crystal.ontology import driver as wn`) and reads the attribute at
    call time. The sibling fixture in `test_condense.py` does the same.

    `_ROOT_IC` is not pre-seeded here: pre-seeding it would make `_root_ic` never get called, which
    is what kept this defect unreachable in other test files.
    """
    from crystal.ontology import driver as real_wn
    from crystal.ontology import geometry as real_g
    monkeypatch.setattr(real_wn, "all_synsets", lambda pos=None, **kw: list(_TREE.values()))
    monkeypatch.setattr(real_wn, "NOUN", NOUN, raising=False)
    monkeypatch.setattr(real_g, "ic_of", lambda s, _ic, strict=True: (s._ic if s is not None else 0.0))
    monkeypatch.setattr(cd, "_syn", lambda n: _TREE.get(n))
    cd._ROOT_IC.clear()
    yield
    cd._ROOT_IC.clear()


def test_the_fixture_actually_contains_an_orphan():
    """The control: without an orphan present, every test below would pass against a broken
    implementation too, and this file would be decoration guarding a defect it cannot see."""
    parentless = [s for s in _TREE.values() if not s.hypernyms() and not s.instance_hypernyms()]
    assert len(parentless) == 3, "expected the root plus two orphans, got %r" % [s.name() for s in parentless]
    children = {s._p for s in _TREE.values() if s._p}
    orphans = [s for s in parentless if s.name() not in children]
    assert len(orphans) == 2, "the orphans are not parentless-and-childless; the hazard is absent"
    assert max(s._ic for s in orphans) > max(
        s._ic for s in parentless if s.name() in children), (
        "the orphans do not out-score the root, so 'take the max' would pass anyway")


def test_root_ic_returns_THE_ROOT_not_the_loudest_orphan():
    """Scanning `not s.hypernyms()` and taking the max returns the orphan's IC (1.0 on this fixture)
    rather than the root's — `_root_ic` must not do that."""
    assert cd._root_ic(None) == pytest.approx(0.03), (
        "_root_ic returned the orphan's IC, not the root's. 'No parents' is not 'is the root' — a "
        "root is the top OF something, so it must have descendants.")


def test_the_gate_still_DISCRIMINATES():
    """A zero point that refuses everything is not a zero point. Both directions asserted."""
    assert cd._is_scatter("entity", None) is True, "the root must read as saying nothing"
    assert cd._is_scatter("animal", None) is False, "a real category must not read as a grab-bag"
    assert cd._is_scatter("dog", None) is False
    assert cd._is_scatter(None, None) is True


def test_a_tree_with_no_root_RAISES_rather_than_fabricating_a_zero():
    """A corpus with no root must say so, not fall back to a fabricated `0.0` — a fixed zero point
    would permanently open the gate."""
    global _TREE
    saved = _TREE
    try:
        _TREE = {"a": _Syn("a", None, 1.0), "b": _Syn("b", None, 1.0)}   # all orphans, no tree
        cd._ROOT_IC.clear()
        with pytest.raises(ValueError, match="no taxonomy root"):
            cd._root_ic(None)
    finally:
        _TREE = saved
        cd._ROOT_IC.clear()
