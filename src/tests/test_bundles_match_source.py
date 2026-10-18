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
_BUNDLES = _HERE.parents[1] / "agience_chorus" / "bundles"
#: Inside the package, so the wheel carries them — the runtime executes the payload, so an
#: installed chorus without them could not discharge an operator.


def _run_check(builder=_BUILDER):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", OPENBLAS_NUM_THREADS="1")
    #: The builder puts its own workspace's prism on the path; a copied workspace has none, so the
    #: real one is named here.
    prism = str(_WORKSPACE / "agience-prism" / "py" / "src")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (prism, env.get("PYTHONPATH")) if p)
    return subprocess.run([sys.executable, str(builder), "--check"],
                          cwd=str(builder.parent), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)


def _copy_workspace(dest):
    """The builder, the producer, the spec, every module it declares, and the shipped payloads,
    laid out as the builder expects. The control corrupts this copy, never the checkout: other
    suites read the shipped payloads while this one runs."""
    import json
    import shutil

    bundling = _WORKSPACE / "agience-chorus" / "src" / "agience_chorus" / "seraph"
    spec_rel = "agience-chorus/src/agience_chorus/seraph/bundle_spec.json"
    spec = json.loads((_WORKSPACE / spec_rel).read_text(encoding="utf-8"))
    rels = {spec_rel, "agience-observe/build_bundles.py",
            str((bundling / "bundling.py").relative_to(_WORKSPACE).as_posix())}
    rels |= {rel for decl in spec.values() for rel in decl["modules"].values()}
    for rel in rels:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_WORKSPACE / rel, dest / rel)
    shutil.copytree(_BUNDLES, dest / _BUNDLES.relative_to(_WORKSPACE))
    return dest / "agience-observe" / "build_bundles.py"


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
def test_the_check_can_actually_fail(tmp_path):
    """The control, and this file needs it more than most.

    The test above is a subprocess exit code. If the builder exited 0 unconditionally — or if the
    `--check` flag were silently ignored, or the path were wrong so it checked nothing — the
    assertion above would pass forever, and this file would be decoration guarding a
    known-recurring defect.

    So: on a copy of the tree, confirm `--check` passes, corrupt a bundle's declared sha, and
    confirm `--check` reports it. The copy keeps the corruption out of the checkout, which other
    suites read concurrently.
    """
    import json

    builder = _copy_workspace(tmp_path)
    bundles = sorted((tmp_path / _BUNDLES.relative_to(_WORKSPACE)).glob("*.json"))
    assert bundles, "no bundles to check — the test above would pass vacuously"
    assert _run_check(builder).returncode == 0, "the copied tree does not check clean"

    target = bundles[0]
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["sha256"] = "0" * 64
    target.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    r = _run_check(builder)
    assert r.returncode != 0, (
        "a bundle with a corrupted sha passed --check, so the test above proves nothing")
    assert "STALE" in r.stdout, "the drift was not reported, only detected"
