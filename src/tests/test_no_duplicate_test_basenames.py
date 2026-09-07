"""Two test files with the same basename silently substitute for each other under pytest. Guard it.

Each persona's `tests/` directory has an `__init__.py`, while the persona directory itself does
not, so the dotted module name stops at `tests`: `sage/tests/test_reach_provider.py` and
`lumen/tests/test_reach_provider.py` both resolve to the module name `tests.test_reach_provider`.
pytest imports the first one and reuses it for the second — under `--import-mode=importlib` that
is not an error, so one persona's node id can collect a sibling's test names while its own tests
never run, and the collected count still looks plausible. A vanished test reads as green, which is
why a basename check has to exist rather than trusting the run to notice on its own.

This is deliberately a basename check, not a count check: a count assertion would need the sum of
every persona's own pytest invocation to compare against, which a test cannot do honestly from
inside one of them, whereas the basename collision is the cause and is measurable directly.

Same family as guarding against a permanent skip standing in for a passing test — a verification
that never exercises its own detector proves nothing, which is why this file also tests itself.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]          # agience-chorus/src

assert (SRC / "sage").is_dir(), (
    f"SRC resolved to {SRC}, which holds no personas — this file moved and parents[] is now wrong")


def _test_files():
    for p in SRC.rglob("test_*.py"):
        if "__pycache__" in p.parts or "node_modules" in p.parts:
            continue
        yield p


def test_no_two_test_files_share_a_basename():
    by_name = defaultdict(list)
    for p in _test_files():
        by_name[p.name].append(p.relative_to(SRC).as_posix())

    clashes = {n: sorted(v) for n, v in by_name.items() if len(v) > 1}
    assert not clashes, (
        "test files share a basename, so pytest will silently substitute one for the other and the "
        "duplicates will NOT run:\n"
        + "\n".join(f"  {n}:\n" + "\n".join(f"    - {q}" for q in v) for n, v in sorted(clashes.items()))
        + "\n\nRename them to be unique per persona (e.g. `test_reach_provider_sage.py`). Do NOT "
          "'fix' this by running the persona suites separately — separate runs HIDE the collision "
          "rather than avoid it, which is exactly how it went unnoticed.")


def test_the_guard_can_actually_fail():
    """A guard that cannot fail proves nothing — prove the detector catches a seeded collision."""
    seeded = defaultdict(list)
    for q in ("sage/tests/test_x.py", "lumen/tests/test_x.py", "aria/tests/test_y.py"):
        seeded[Path(q).name].append(q)
    clashes = {n: v for n, v in seeded.items() if len(v) > 1}
    assert set(clashes) == {"test_x.py"}, "the collision detector missed a seeded duplicate"


def test_it_is_actually_scanning_something():
    """The other vacuous-pass mode: a glob that matches nothing reports no clashes and looks green."""
    found = list(_test_files())
    assert len(found) > 50, f"only {len(found)} test files found under {SRC} — the scan is not running"
