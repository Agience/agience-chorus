"""astra's manifest travels as a bundle — the gate on the mechanism, not on the wording.

`agience-prism/py/src/prism/runner.py` and `ember/runtime/runner.py` describe a distribution
path: a bundle declares `{host_seams, modules, sha256}`, the host binds each seam name to its own
module, and the payload is sha-verified before any exec. astra is chorus's worked example of
the mechanism — chorus is what a third-party developer copies, so it needs a persona that rides
bundles rather than the bare-name import path.

Each assertion below has a stated failure mode, because a check that cannot fail proves nothing:

  1. the load succeeds with `src/astra/` absent from `sys.path` — and the same test proves the bare
     name is genuinely unresolvable there, so it is not passing on a path that happens to be set;
  2. a bundle declaring a seam nobody registered raises, and does not quietly bind a same-named
     module sitting on `sys.path` — asserted with a decoy module planted under that exact name;
  3. a registered seam resolves to whatever the host named, proving the loader holds no opinion;
  4. one flipped byte in the payload is rejected.

1, 2, 3 and 4 run in subprocesses. Seam registration and `attach()` are process-lifetime and
ordered ("register at boot, before the first load"), `_DATA_DIR` is resolved at import, and the
first successful load of a group pins it. An in-process version of any of these would pass or fail
on test order — and `chorus.personas._load_module` inserts persona directories into `sys.path`
when other tests boot the host, so an in-process "the dir is not on the path" assertion would
silently stop testing anything.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]            # …/agience-chorus/src
ASTRA = SRC / "astra"
BUNDLES = SRC.parent / "bundles"          # this repository's own; chorus builds them


def _run(snippet: str, **env_extra) -> subprocess.CompletedProcess:
    """A fresh interpreter with `src` on the path and nothing else added.

    `src` is inserted inside the snippet rather than through `PYTHONPATH`, so the subprocess
    carries no environment dependency beyond `src` itself. `src/astra/` is never added — that
    absence is the point.
    """
    import os
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", **env_extra)
    prologue = "import sys; sys.path.insert(0, %r)\n" % str(SRC)
    return subprocess.run([sys.executable, "-c", prologue + snippet],
                          capture_output=True, text=True, env=env, cwd=str(SRC))


# ── 1 · the path trick is gone ───────────────────────────────────────────────────────────────────

def test_manifest_loads_with_the_persona_dir_OFF_sys_path():
    """`astra/manifest.py` reaches its organon only through the bundle path — `import fetch`
    resolves only when `chorus.personas._load_module` has put `src/astra/` on `sys.path`, so this
    proves the load works with that never having happened.

    Fails if anything reintroduces a bare-name organon import, or if the bundle payload cannot be
    found. It cannot pass vacuously — the second assertion below proves the bare name really is
    unresolvable in the interpreter that just loaded the manifest.
    """
    r = _run("""
import sys, json, pathlib
for p in list(sys.path):
    assert not pathlib.Path(p).name == 'astra', 'the persona dir leaked onto sys.path: %r' % p

# The bare name MUST be unresolvable here, or the test above proves nothing.
import importlib.util
assert importlib.util.find_spec('fetch') is None, 'a bare `fetch` is importable — test is vacuous'

import astra.manifest as m
print(json.dumps({
    "ops": sorted(d["id"] for d in m.OPERATORS),
    "group": m.BUNDLE_GROUP,
    "sha": m.bundle_sha256(),
    "origin": m.bundle_origin(),
    "bare_fetch_imported": "fetch" in sys.modules,
}))
""")
    assert r.returncode == 0, f"load FAILED with the persona dir off sys.path:\n{r.stderr}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["ops"] == ["op.fetch.get"], got
    assert got["group"] == "fetch"
    assert got["bare_fetch_imported"] is False, "the organon was still reached by bare name"
    assert len(got["sha"]) == 64


def test_no_organon_is_imported_by_bare_name_in_the_source():
    """The static half. `crystal`/`prism`/stdlib are installed packages and resolve by ordinary
    absolute import; an organon is a sibling file and only ever resolved by the path trick.

    Fails if `import fetch` (or any other sibling module name) is reintroduced, even if the
    runtime test above were somehow satisfied by a leaked path.
    """
    import ast
    siblings = {p.stem for p in ASTRA.glob("*.py")} | {d.name for d in ASTRA.iterdir() if d.is_dir()}
    siblings.discard("manifest")
    tree = ast.parse((ASTRA / "manifest.py").read_text(encoding="utf-8"))
    reached = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            reached.add(node.module.split(".")[0])
    leaked = reached & siblings
    assert not leaked, (
        "astra/manifest.py imports sibling module(s) %s by bare name — that resolves only because "
        "`chorus.personas._load_module` puts the persona dir on sys.path. Take them from the "
        "bundle instead (`prism.runner.register_fns`)." % sorted(leaked))


# ── 2 · the operators come from a sha-verified bundle, not from the file next door ────────────────

def test_registrars_are_the_bundles_own_declared_register_fns():
    """The manifest transcribes no function name: `register_fns` reads them from the bundle
    manifest that travelled with the code.

    Fails if `[fetch.register_fetch_operators]` is hardcoded directly into the manifest: that would
    pass the operator assertion but break the identity check against `prism.runner`'s pinned
    bundle.
    """
    import astra.manifest as m
    from prism import runner

    shipped = json.loads((BUNDLES / "fetch.json").read_text(encoding="utf-8"))
    assert m.bundle_sha256() == shipped["sha256"], "running bytes differ from the shipped payload"
    assert [f.__name__ for f in m.REGISTRARS] == shipped["register_fns"]
    assert runner.loaded()["fetch"]["sha256"] == shipped["sha256"]
    assert sorted(d["id"] for d in m.OPERATORS) == ["op.fetch.get"]


def test_the_manifest_surface_is_unchanged_for_the_host():
    """`chorus.personas._persona_manifest` reads `OPERATORS`/`FACETS`; `crystal.host` calls
    `collect`. The manifest's data comes from a bundle, but it presents that data to the host
    through the ordinary `OPERATORS`/`FACETS`/`collect`/`operators` surface.

    Fails if `collect`/`operators` is dropped: that would strand the host's registration path.
    """
    import astra.manifest as m
    assert callable(m.collect) and callable(m.operators)
    assert m.operators() == m.OPERATORS
    cap_count = m.collect()
    assert cap_count == len(m.OPERATORS) == 1


# ── 3 · seams — which module fills a seam is the host's answer, not the loader's ──────────────────
#
# astra's own group declares no seam (`fetch` reaches only the installed `crystal.evolution`), so
# the seam leg is asserted against the group that does declare one — `operators`, which names
# `match` — rather than inventing a second synthetic bundle beside the six that already exist.

def test_an_UNREGISTERED_seam_RAISES_and_never_takes_a_sys_path_module():
    """§8 of ARCHITECTURE-TARGET's assertion: a bundle declaring a seam nobody registers fails
    loudly rather than silently reaching for a module it was not given.

    A decoy module named `match` is planted in `sys.modules` first. If the loader were lax — if it
    let an unresolved seam fall through to ordinary absolute-import resolution — the bundle would
    bind the decoy without saying so.

    Fails if the decoy is reached, and fails if nothing is raised at all.
    """
    r = _run("""
import sys, types, importlib
decoy = types.ModuleType('match'); decoy.MARKER = 'DECOY'
sys.modules['match'] = decoy                      # planted BEFORE anything loads

from prism import runner
assert runner.registered_seams() == {}, 'chorus registered a seam: %r' % runner.registered_seams()
info = runner._load_group('operators')
assert 'match' in info['bundle']['host_seams'], 'the operators bundle stopped declaring the seam'

try:
    mod = importlib.import_module(info['pkg'] + '.match')
except ModuleNotFoundError as e:
    print('RAISED', e)
else:
    print('BOUND', getattr(mod, 'MARKER', mod.__name__))
""")
    assert r.returncode == 0, r.stderr
    last = r.stdout.strip().splitlines()[-1]
    assert last.startswith("RAISED"), (
        "an unregistered seam did NOT fail loudly — it resolved to %r. A bundle must never reach a "
        "module the host did not give it." % last)
    assert "DECOY" not in r.stdout


def test_a_REGISTERED_seam_resolves_to_whatever_the_HOST_named():
    """The positive control, and the reason the negative test above is not just "imports fail".

    The host binds the seam name `match` to `json` — a module with no relationship to matching at
    all. The bundle asks for a name and gets the host's answer: a third-party bundle declares, and
    never imports.

    Fails if the loader resolved seams on its own rather than through the host's registration:
    the identity check against `json` would fail.
    """
    r = _run("""
import json as _json, importlib
from prism import runner
runner.register_seam('match', 'json')             # at boot, BEFORE the first load
info = runner._load_group('operators')
mod = importlib.import_module(info['pkg'] + '.match')
print('IS_JSON', mod is _json, mod.__name__)
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "IS_JSON True json", r.stdout


# ── 4 · the integrity gate ───────────────────────────────────────────────────────────────────────

def test_a_TAMPERED_bundle_is_REFUSED():
    """One flipped byte in the payload the manifest depends on, and the load must be rejected.

    The tamper is a semantic no-op (two spaces added inside the source text): a change that also
    broke the code would fail for the wrong reason and leave the sha gate untested. The only thing
    wrong with this payload is that it is not the payload that was hashed.

    Fails if `_verify_sha` is ever softened to a warning — or if the runner falls back to a
    known-good copy on mismatch — `register_fns` would return callables instead.
    """
    import os, tempfile
    good = json.loads((BUNDLES / "fetch.json").read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(good))
    bad["modules"]["fetch"] = bad["modules"]["fetch"].replace(
        "def register_fetch_operators", "def register_fetch_operators  ", 1)
    assert bad["modules"]["fetch"] != good["modules"]["fetch"], "the tamper did not change anything"
    assert bad["sha256"] == good["sha256"], "the tamper must leave the CLAIMED sha in place"

    tmp = tempfile.mkdtemp()
    Path(tmp, "fetch.json").write_text(json.dumps(bad), encoding="utf-8")
    r = _run("""
from prism import runner
try:
    runner.register_fns('fetch')
except runner.BundleIntegrityError as e:
    print('REFUSED')
else:
    print('ACCEPTED')
""", AGIENCE_BUNDLE_ROOT=tmp)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "REFUSED", (
        "a tampered bundle was EXEC'd — the integrity gate is not holding:\n%s" % r.stdout)


def test_the_shipped_bundle_still_matches_astras_authoritative_source():
    """`astra/fetch.py` remains the source of truth; the bundle is built from it. If the two
    drift, the node runs bytes nobody edited.

    Fails if `astra/fetch.py` is edited without rebuilding — the intended reminder, since the
    runtime reads only the bundle payload, never this file directly.
    """
    shipped = json.loads((BUNDLES / "fetch.json").read_text(encoding="utf-8"))
    on_disk = (ASTRA / "fetch.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert shipped["modules"]["fetch"] == on_disk, (
        "astra/fetch.py has drifted from the shipped `fetch` bundle — run "
        "`python agience-observe/build_bundles.py fetch`")
