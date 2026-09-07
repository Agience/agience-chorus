"""lumen's arithmetic organon (op.math.*). Every transform invokes with a proof, spot-checks hold,
and registration writes one artifact per transform through the fitness substrate."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare local import

import arithmetic  # noqa: E402


class _Capture:
    def __init__(self):
        self.docs = {}

    def get_artifact(self, aid):
        return self.docs.get(aid)

    def put_artifact(self, doc):
        self.docs[doc["id"]] = dict(doc)
        return doc


_OPERANDS = {
    "op.math.add": (2, 3), "op.math.subtract": (10, 4), "op.math.multiply": (6, 7),
    "op.math.divide": (12, 3), "op.math.floordiv": (17, 5), "op.math.modulo": (17, 5),
    "op.math.power": (2, 10), "op.math.is_prime": (7,), "op.math.factorize": (60,),
    "op.math.sqrt": (81,), "op.math.factorial": (6,), "op.math.gcd": (12, 18),
    "op.math.lcm": (4, 6),
}


def test_every_math_transform_invokes():
    assert set(_OPERANDS) == {t.name for t in arithmetic.TRANSFORMS}, \
        "a transform was added/removed without extending this invocation map"
    for name, ops in _OPERANDS.items():
        result, proof = arithmetic.invoke(name, *ops)
        assert proof, name


def test_math_spot_checks_real_numbers():
    assert arithmetic.invoke("op.math.add", 2, 3)[0] == 5
    r, proof = arithmetic.invoke("op.math.gcd", 12, 18)
    assert r == 6 and "6" in proof
    assert arithmetic.invoke("op.math.factorial", 6)[0] == 720
    assert arithmetic.invoke("op.math.is_prime", 7)[0] is True
    assert arithmetic.invoke("op.math.factorize", 60)[0] == [2, 2, 3, 5]


def test_math_registration_against_capture_store():
    cap = _Capture()
    n = arithmetic.register_transform_operators(cap)
    assert n == len(arithmetic.TRANSFORMS) == 13
    assert all(t.name in cap.docs for t in arithmetic.TRANSFORMS)
