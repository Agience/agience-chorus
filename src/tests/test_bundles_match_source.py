"""The shipped bundles must match the source they claim to carry.

`prism.runner._verify_sha` proves a bundle is internally consistent — that its payload hashes to the
sha it declares. It cannot prove the payload is the current source, because the bundle is the only
thing it reads. A stale bundle therefore sails through integrity verification and ships old code,
which is worse than a mismatch: the gate reports green.

`agience-observe/build_bundles.py --check` is the other half: it rebuilds from source, compares,
reports STALE, and exits 1. This test is what wires it into the suite.

Without this, a developer edits a chorus organon, the tests pass, the bundle still carries the
previous version, and every node loading that bundle runs code that no longer exists in the repo —
while `verify()` reports a valid sha.
"""

import os
import pathlib
import subprocess
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve()
_WORKSPACE = _HERE.parents[3]
_BUILDER = _WORKSPACE / "agience-observe" / "build_bundles.py"
#: The payloads are THIS repository's — chorus builds them from chorus source. The builder is a CLI
#: that still lives in agience-observe, so the two paths are deliberately unrelated: one is where
#: the output lands, the other is where the command lives.
_BUNDLES = _HERE.parents[2] / "bundles"


def _run_check():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", OPENBLAS_NUM_THREADS="1")
    return subprocess.run([sys.executable, str(_BUILDER), "--check"],
                          cwd=str(_BUILDER.parent), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)


@pytest.mark.skipif(not _BUILDER.is_file(),
                    reason="agience-observe is not checked out beside this repo")
def test_no_shipped_bundle_is_stale():
    """Every bundle's payload equals what the builder produces from current source.

    A failure here means the shipped payload and the repo have diverged. Fix it by rebuilding —
    `python agience-observe/build_bundles.py` — never by loosening this test: the whole value of a
    sha-verified bundle is that what runs is what was written.
    """
    r = _run_check()
    assert r.returncode == 0, (
        "shipped bundles no longer match chorus source:\n%s\n%s"
        % (r.stdout.strip(), r.stderr.strip()))


@pytest.mark.skipif(not _BUILDER.is_file(), reason="agience-observe is not checked out")
def test_the_check_can_actually_fail():
    """The control, and this file needs it more than most.

    The test above is a subprocess exit code. If the builder exited 0 unconditionally — or if the
    `--check` flag were silently ignored, or the path were wrong so it checked nothing — the
    assertion above would pass forever, and this file would be decoration guarding a
    known-recurring defect.

    So: corrupt a bundle's declared sha, confirm `--check` reports failure, and restore it.
    """
    import json

    bundles = sorted(_BUNDLES.glob("*.json"))
    assert bundles, "no bundles to check — the test above would pass vacuously"

    target = bundles[0]
    original = target.read_text(encoding="utf-8")
    try:
        doc = json.loads(original)
        doc["sha256"] = "0" * 64
        target.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        r = _run_check()
        assert r.returncode != 0, (
            "a bundle with a corrupted sha passed --check, so the test above proves nothing")
        assert "STALE" in r.stdout, "the drift was not reported, only detected"
    finally:
        target.write_text(original, encoding="utf-8")

    assert _run_check().returncode == 0, "the control did not restore the bundle it corrupted"
