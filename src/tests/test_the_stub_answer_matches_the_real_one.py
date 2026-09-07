"""Ember's stub answer type has the same surface as the operator bundle's real `Answer`.

Ember's suite must not need a chorus payload to exercise ember's own read path, so `_fakes.py`
returns a `_StubAnswer` it defines itself rather than importing the bundle's class. That is right,
and it has one failure mode: the stub silently falls behind. It did — the stub carried three fields
while the real answer had four and a `refused` property, and four tests read `refused` off it.

Ember cannot make this comparison; it has no payload. Chorus can, because the payloads are its own,
so the check lives here. It is the reason the stub is allowed to be a restatement rather than a
subclass.

If this fails, fix the stub in `agience-ember/tests/_fakes.py` — do not relax the assertion. A stub
that has drifted from the real type makes every test using it a statement about something that does
not exist.
"""

from __future__ import annotations

import dataclasses

import pytest

from ember.runtime.runner import answer as _answer_mod

try:
    from _fakes import _StubAnswer            # ember's copy, on the path via src/conftest.py
except ImportError:                            # pragma: no cover
    _StubAnswer = None

pytestmark = pytest.mark.skipif(
    _StubAnswer is None,
    reason="no agience-ember checkout beside this repo — the stub it defines is what is compared")


def _fields(cls) -> dict:
    return {f.name: str(f.type) for f in dataclasses.fields(cls)}


def test_the_stub_carries_every_field_the_real_answer_has():
    """Fields, by name. A field the real answer grows and the stub lacks reads as `AttributeError`
    in ember's suite — which is loud — but a field the STUB grows and the real one lacks is worse:
    ember's tests would assert on something no operator ever returns."""
    real, stub = _fields(_answer_mod.Answer), _fields(_StubAnswer)
    missing = sorted(set(real) - set(stub))
    extra = sorted(set(stub) - set(real))
    assert not missing, (
        "the operator bundle's `Answer` has %s and ember's `_StubAnswer` does not. Ember's tests "
        "will fail on the attribute, or worse, pass without exercising it." % missing)
    assert not extra, (
        "ember's `_StubAnswer` has %s that no real answer carries, so a test asserting on it is "
        "asserting about a shape that does not exist." % extra)


def test_the_stub_agrees_on_refused():
    """`refused` is a property on both, and it is the one piece of BEHAVIOUR the stub restates.

    Restating logic is how two implementations diverge, so the rule is checked rather than trusted:
    for every combination of `grounded`, the two must answer the same.
    """
    for grounded in (True, False):
        real = _answer_mod.Answer(text="t", grounded=grounded, cited=[], read={})
        stub = _StubAnswer(text="t", grounded=grounded, cited=[], read={})
        assert real.refused == stub.refused, (
            "grounded=%r: the bundle says refused=%r and the stub says %r"
            % (grounded, real.refused, stub.refused))


def test_the_real_answer_accepts_what_ember_produces():
    """The control for the stub's existence: ember's read path builds an answer from evidence rows,
    and the real type must accept that shape. Constructed the way `_StubAnswerer.answer` does."""
    art = _answer_mod.Answer(text="a\nb", grounded=True, cited=["id-1", "id-2"], read={})
    assert art.text == "a\nb" and art.cited == ["id-1", "id-2"] and art.refused is False
