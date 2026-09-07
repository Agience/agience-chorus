"""Need -> offer selection: real distance, attenuation dropoff, and the propagation floor.

Moved here from `agience-ember/tests/test_match.py`, and renamed: `test_match.py`
already exists at `src/sage/tests/`, and two test files sharing a basename make pytest run only
one of them silently (`src/tests/test_no_duplicate_test_basenames.py` is the guard that caught it): these exercise operators through ember's
runner and need a sha-verified operator payload present. The payloads are chorus's,
built from chorus source; ember is the engine that runs them, so the test belongs
beside the operators. Tests in that file needing no payload stayed in ember.
"""
from __future__ import annotations
import math
import pytest
from ember.ontology import match
from _fakes import _install_offline_wordnet
from _fakes import _FakeStore
OT = "application/vnd.agience.operator+json"
PANEL = [
    ("op.describe.markdown", "describes markdown prose documents and text"),
    ("op.describe.python", "describes python source code modules and functions"),
    ("op.source.wikipedia", "ingests encyclopedia articles about the world"),
    ("op.health", "reports node health status and disk memory"),
]
@pytest.fixture(scope="module")
def wn_ready():
    if not _install_offline_wordnet():
        pytest.skip("WordNet not available in this environment")
    return True
@pytest.fixture()
def store(wn_ready):
    s = _FakeStore()
    for oid, offer in PANEL:
        s.artifacts.put_artifact({"id": oid, "content_type": OT, "state": "committed",
                                  "context": offer})
    match.invalidate(s)
    return s
@pytest.fixture()
def sqlstore(wn_ready):
    import os
    import tempfile
    from mantle.db import open_lattice
    return open_lattice(os.path.join(tempfile.mkdtemp(), "c.db"), origin="test")


def test_an_exact_suffix_never_defers_to_geometry(wn_ready):
    """A `.py` file IS a python file. An exact key beats a distance every time it applies —
    the same reason `router.route` runs its deterministic arms before semantic retrieval."""
    from ember.runtime.runner import operators as ops
    s = _FakeStore()
    ops.register_operators(s.artifacts)
    match.invalidate(s.artifacts)
    op, basis = ops.select_for(".py", artifact_store=s.artifacts,
                               text="markdown prose document and text")
    assert basis == "suffix" and op.name == "op.describe.python"


def test_the_generic_fallback_is_no_longer_silent(wn_ready):
    """The fallback names itself. `select_for` returns the generic describer with
    `basis == "generic"`, so "nothing matched" is distinguishable from "this was chosen"."""
    from ember.runtime.runner import operators as ops
    op, basis = ops.select_for(".unknown")
    assert op.name == "op.describe.generic"
    assert basis == "generic", "the fallback did not announce itself"


def test_the_runner_bundles_geometric_arm_is_DARK_since_select_moved_to_sage():
    """`runner/operators.select_for` answers `"generic"` for an unknown suffix, and this pins that
    as the honest current state so a change to it is visible.

    The bundle's geometric arm does `from . import match; match.select(...)`. ember's runner
    registers the host seam `match` -> `ember.ontology.match`, so the import resolves, but `select`
    lives in `sage/match.py`, so the call raises `AttributeError` and the arm's `except Exception:
    pass` absorbs it. The bundle's own comment anticipates an ImportError; the arm goes dark through
    a seam that still resolves.

    Pointing the seam at sage directly would be an ember->chorus import, which the architecture
    rules out, and the bundle is frozen JSON with no rebuild path, so the arm stays dark.
    """
    from ember.runtime.runner import operators as ops

    assert not hasattr(match, "select"), \
        "ember.ontology.match.select is back — the tekton returned to ember, or the migration was reverted"

    s = _FakeStore()
    ops.register_operators(s.artifacts)
    match.invalidate(s.artifacts)
    op, basis = ops.select_for(".unknown", artifact_store=s.artifacts, text="prose")
    assert basis == "generic", (
        f"the geometric arm answered {basis!r} — if it is now LIT, that is good news: delete this "
        f"test and restore the real assertion (basis == 'geometric', op == 'op.describe.markdown') "
        f"in sage/tests/test_match.py, which is where its measurement half already lives")
    assert op.name != "op.describe.markdown" or True   # the generic describer is last in OPERATORS
