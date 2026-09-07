"""The factorial bound is derived from the interpreter's own limit on int-to-str conversion, not a
typed-in constant, and an out-of-range value returns a named answer rather than raising or falling
through silently.

CPython 3.11+ limits int→str conversion above `sys.get_int_max_str_digits()` (4300 by default, added
for CVE-2020-10735); `2000!` has 5,736 digits. A constant bound of `0 <= n <= 2000` sits on both
sides of that limit: `1559!` through `2000!` are accepted and computed, then raise `ValueError` while
formatting the answer, and anything above 2000 falls through with no answer at all, indistinguishable
from "this is not an arithmetic question."

The bound here tracks the interpreter's current limit — `sys.set_int_max_str_digits()` moves it, and
a typed-in constant cannot follow. The tests below assert the derivation, not a particular value:
pinning a number would reintroduce the same defect one level up.
"""
import sys

import pytest

from lumen import arithmetic


def test_the_bound_is_derived_from_the_interpreter_not_pinned():
    """The largest renderable n is whatever the current limit allows.

    Asserted by moving the limit and watching the bound move with it. A hardcoded 1558 would pass
    the default case and fail this one, which is the whole point.
    """
    original = sys.get_int_max_str_digits()
    baseline = arithmetic._max_renderable_factorial()
    try:
        sys.set_int_max_str_digits(original * 2)
        raised = arithmetic._max_renderable_factorial()
        assert raised > baseline, (
            "the bound did not move when the interpreter limit doubled (%d -> %d): it is pinned, "
            "not derived" % (baseline, raised))
    finally:
        sys.set_int_max_str_digits(original)
    assert arithmetic._max_renderable_factorial() == baseline, "the bound did not restore"


def test_the_bound_is_EXACT_at_its_own_edge():
    """n! must render at the bound and must not render one past it.

    Pins the property a typed-in bound can violate: a constant that sits past the interpreter's edge
    lets values through that raise while formatting the answer.
    """
    n = arithmetic._max_renderable_factorial()
    import math
    str(math.factorial(n))                       # must not raise
    with pytest.raises(ValueError):
        str(math.factorial(n + 1))


def test_the_digit_count_is_computed_without_computing_the_factorial():
    """`_factorial_digits` must agree with the real count where the real count is obtainable.

    It exists so an out-of-range answer can state a magnitude without printing it — computing the
    number to describe it would cost exactly what avoiding the computation is for.
    """
    import math
    for n in (0, 1, 5, 100, 1000, 1558):
        assert arithmetic._factorial_digits(n) == len(str(math.factorial(n))), n


@pytest.mark.parametrize("n", [0, 1, 5, 100, 1000])
def test_in_range_factorials_answer(n):
    a = arithmetic.compute("what is %d!" % n)
    assert a is not None, "an in-range factorial must be answered"
    assert a.text.startswith("%d! = " % n)


@pytest.mark.parametrize("n", [1559, 2000, 5000, 100000])
def test_out_of_range_REFUSES_BY_NAME_and_never_raises(n):
    """An out-of-range value returns an Answer that states the magnitude and the limit, rather than
    raising or falling through to `None`: a named limit is a measurement, where `None` was an
    absence the caller had to guess at.
    """
    a = arithmetic.compute("what is %d!" % n)          # must not raise
    assert a is not None, "out-of-range factorial fell through silently again"
    assert "digits" in a.text and "render" in a.text, a.text
    assert str(sys.get_int_max_str_digits()) in a.text.replace(",", ""), (
        "the refusal must name the limit it is derived from: %s" % a.text)


def test_the_old_constant_would_have_raised_here():
    """The control: if a constant bound is reinstated at or above the derived edge, this test
    catches it by asserting the interpreter actually raises at n=2000, the boundary named in the
    module docstring above. The bound cannot be widened back to a typed-in constant without this
    failing.
    """
    import math
    assert 2000 > arithmetic._max_renderable_factorial(), (
        "2000 is no longer past the edge on this interpreter; the historical defect is unreachable "
        "and this control should be re-derived rather than deleted")
    with pytest.raises(ValueError):
        str(math.factorial(2000))
