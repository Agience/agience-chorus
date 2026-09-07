"""seraph's manifest travels as a bundle, on a group not hardcoded into `prism.runner.GROUPS`.

`install` is loaded from a `bundle_spec.json` entry plus `python agience-observe/build_bundles.py`,
so prism discovers it rather than resolving it through a fixed set of names. This is the mechanism a
third-party developer uses to add a group, shown working from outside prism.

Every assertion below has a stated failure mode, because a check that cannot fail proves nothing:

  1. the load succeeds with `src/seraph/` absent from `sys.path`, after first confirming a bare
     `install` is genuinely unresolvable there, so it cannot pass vacuously;
  2. the registrars are the bundle's declared ones, matching the shipped payload's sha;
  3. one flipped byte in the payload is refused — the group being new buys no exemption;
  4. the shipped payload still matches `seraph/install.py`, the authoritative source.

1 and 3 run in subprocesses, deliberately: `_DATA_DIR` is resolved at import, the first successful
load of a group pins it for the process, and `chorus.personas._load_module` inserts persona
directories into `sys.path` when other tests boot the host — so an in-process "the dir is not on the
path" assertion would silently stop testing anything.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]            # …/agience-chorus/src
SERAPH = SRC / "seraph"
BUNDLES = SRC.parent / "bundles"          # this repository's own; chorus builds them


def _run(snippet: str, **env_extra) -> subprocess.CompletedProcess:
    """A fresh interpreter with `src` on the path and nothing else added.

    `src` is inserted inside the snippet rather than through `PYTHONPATH`, so the test does not
    depend on a hand-passed environment variable. `src/seraph/` is never added — that absence is the
    point.
    """
    import os
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", **env_extra)
    prologue = "import sys; sys.path.insert(0, %r)\n" % str(SRC)
    return subprocess.run([sys.executable, "-c", prologue + snippet],
                          capture_output=True, text=True, env=env, cwd=str(SRC))


# ── 1 · the path trick is gone ───────────────────────────────────────────────────────────────────

def test_seraph_manifest_loads_with_the_persona_dir_OFF_sys_path():
    """Pins that `seraph/manifest.py` never resolves an organon by a bare `import install`; the
    only thing that ever makes that name importable is `chorus.personas._load_module` inserting
    `src/seraph/` into `sys.path`.

    failure mode: re-introducing any bare-name organon import fails this, and so does a missing
    bundle payload. It cannot pass vacuously — `find_spec('install') is None` is asserted first, in
    the same interpreter, so a leaked path fails the test rather than satisfying it.
    """
    r = _run("""
import sys, json, pathlib
for p in list(sys.path):
    assert pathlib.Path(p).name != 'seraph', 'the persona dir leaked onto sys.path: %r' % p

# The bare name must be unresolvable here, or everything below proves nothing.
import importlib.util
BARE = ('install', 'bundling')          # both groups — a guard naming one of two
for n in BARE:                          # would go vacuous for the group it forgot
    assert importlib.util.find_spec(n) is None, 'a bare %r is importable — test is vacuous' % n

import seraph.manifest as m
print(json.dumps({
    "ops": sorted(d["id"] for d in m.OPERATORS),
    "groups": list(m.BUNDLE_GROUPS),
    "sha": m.bundle_sha256(),
    "origin": m.bundle_origin(),
    "collected": m.collect(),
    "bare_imported": sorted(n for n in BARE if n in sys.modules),
}))
""")
    assert r.returncode == 0, f"load FAILED with the persona dir off sys.path:\n{r.stderr}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    # `op.bundle.observe` (organon, reaches the operator source tree) and `op.bundle.condense`
    # (tekton, source -> a canonical sha-addressed payload) sit with `op.install`, the consumer,
    # because they are two halves of one act — splitting them would let the producer's contract and
    # the consumer's check drift apart.
    assert got["ops"] == ["op.bundle.condense", "op.bundle.observe", "op.install"], got
    assert got["groups"] == ["install", "bundling"]
    assert got["collected"] == len(got["ops"]) == 3
    assert got["bare_imported"] == [], "an organon was still reached by bare name"
    # Per group, and every group in both stats — a sha with no provenance says which bytes ran but
    # not where they came from.
    assert sorted(got["sha"]) == sorted(got["groups"]) == sorted(got["origin"]), got
    for group, sha in got["sha"].items():
        assert len(sha) == 64, "%s published a sha that is not a sha256: %r" % (group, sha)


def test_no_organon_is_imported_by_bare_name_in_seraphs_manifest():
    """The static half. `crystal`/`prism`/stdlib are installed packages and resolve by ordinary
    absolute import; an organon is a sibling file and only ever resolved by the path trick.

    failure mode: re-adding `import install` (or `import agent`) fails this even if the runtime test
    above were somehow satisfied by a leaked path.
    """
    import ast
    siblings = {p.stem for p in SERAPH.glob("*.py")} | {d.name for d in SERAPH.iterdir() if d.is_dir()}
    siblings.discard("manifest")
    reached = set()
    for node in ast.walk(ast.parse((SERAPH / "manifest.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            reached.add(node.module.split(".")[0])
    leaked = reached & siblings
    assert not leaked, (
        "seraph/manifest.py imports sibling module(s) %s by bare name — that resolves only because "
        "`chorus.personas._load_module` puts the persona dir on sys.path. Take them from the bundle "
        "instead (`prism.runner.register_fns`)." % sorted(leaked))


# ── 2 · the operators come from a sha-verified bundle, not from the file next door ────────────────

def test_seraph_registrars_are_the_bundles_own_declared_register_fns():
    """The manifest transcribes no function name: `register_fns` reads them from the bundle
    manifest that travelled with the code.

    failure mode: hardcoding `[install.register_install_operators]` back into the manifest passes the
    operator assertion but breaks the identity check against `prism.runner`'s pinned bundle.
    """
    import seraph.manifest as m
    from prism import runner

    expected, shas = [], {}
    for group in m.BUNDLE_GROUPS:
        shipped = json.loads((BUNDLES / f"{group}.json").read_text(encoding="utf-8"))
        expected += shipped["register_fns"]
        shas[group] = shipped["sha256"]

    assert [f.__name__ for f in m.REGISTRARS] == expected
    assert m.bundle_sha256() == shas, "running bytes differ from the shipped payloads"
    for group, sha in shas.items():
        assert runner.loaded()[group]["sha256"] == sha
    assert sorted(d["id"] for d in m.OPERATORS) == [
        "op.bundle.condense", "op.bundle.observe", "op.install"]


def test_the_group_prism_never_declared_is_the_one_seraph_runs_on():
    """`install` is not one of the six names hardcoded into `prism.runner`; it is loadable because
    its payload exists on disk.

    failure mode: if prism ever goes back to a fixed list, this fails — either because `install`
    stops being loadable, or because `known_groups()` stops reflecting the payloads on disk.
    """
    from prism import runner

    six = {"arithmetic", "operators", "dev_ops", "docs_ops", "corpus", "fetch"}
    assert "install" not in six
    assert "install" in runner.known_groups()
    assert set(runner.known_groups()) == {p.stem for p in BUNDLES.glob("*.json")}, (
        "the group list stopped being a measurement of the payloads present")


def test_the_seraph_manifest_surface_is_unchanged_for_the_host():
    """`chorus.personas._persona_manifest` reads `OPERATORS`; `crystal.host` calls `collect`. The
    conversion is a change of source, not of contract.

    failure mode: dropping `collect`/`operators` would strand the host's registration path.
    """
    import seraph.manifest as m
    assert callable(m.collect) and callable(m.operators)
    assert m.operators() == m.OPERATORS
    # The count is pinned so a surface change is deliberate — see the note in the bundle-path test
    # above for why `op.bundle.observe` and `op.bundle.condense` sit here alongside `op.install`.
    assert m.collect() == len(m.OPERATORS) == 3


# ── 3 · the integrity gate, on the new group ─────────────────────────────────────────────────────

def test_a_TAMPERED_install_bundle_is_REFUSED():
    """A new group buys no exemption. One flipped byte in the payload seraph depends on, and the
    load must refuse.

    The tamper is a semantic no-op (two spaces added inside the source text). A change that also
    broke the code would fail for the wrong reason and the sha gate would go untested. The only
    thing wrong with this payload is that it is not the payload that was hashed.

    failure mode: if `_verify_sha` were softened to a warning — or if the runner fell back to a
    known-good copy on mismatch — `register_fns` would return callables and this fails.
    """
    import tempfile
    good = json.loads((BUNDLES / "install.json").read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(good))
    bad["modules"]["install"] = bad["modules"]["install"].replace(
        "def register_install_operators", "def register_install_operators  ", 1)
    assert bad["modules"]["install"] != good["modules"]["install"], "the tamper changed nothing"
    assert bad["sha256"] == good["sha256"], "the tamper must leave the CLAIMED sha in place"

    tmp = tempfile.mkdtemp()
    Path(tmp, "install.json").write_text(json.dumps(bad), encoding="utf-8")
    r = _run("""
from prism import runner
try:
    runner.register_fns('install')
except runner.BundleIntegrityError as e:
    print('REFUSED')
else:
    print('ACCEPTED')
""", AGIENCE_BUNDLE_ROOT=tmp)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "REFUSED", (
        "a tampered bundle was EXEC'd — the integrity gate is not holding:\n%s" % r.stdout)


# ── 4 · the source of truth has not drifted ──────────────────────────────────────────────────────

def test_the_shipped_install_bundle_still_matches_seraphs_authoritative_source():
    """`seraph/install.py` remains the source of truth; the bundle is built from it. If the two
    drift, the node runs bytes nobody edited.

    failure mode: editing `seraph/install.py` without rebuilding fails this — the reminder is
    deliberate, since prism's runner loads only the shipped bundle payload, never this file
    directly.
    """
    shipped = json.loads((BUNDLES / "install.json").read_text(encoding="utf-8"))
    on_disk = (SERAPH / "install.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert shipped["modules"]["install"] == on_disk, (
        "seraph/install.py has drifted from the shipped `install` bundle — run "
        "`python agience-observe/build_bundles.py install`")
