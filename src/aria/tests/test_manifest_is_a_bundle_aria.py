"""aria's manifest travels as a bundle, distributed as text rather than imported from a file.

`web_bff.py` resolves `www/bff/main.py` via `Path(__file__)` inside a function rather than at module
scope: a bundle module is exec'd from distributed text whose spec has no location, so a module-scope
`__file__` read would raise `NameError` before any registrar exists. `www/bff/main.py` is a file in
the persona directory and does not travel with the bundle; a `cwd`-relative guess would silently serve
whatever tree a host happened to have, so the group declares `host_seams: ["bff_main"]` and leaves
serving to the host, per aria's `CRYSTAL` (`web.serve` is a host capability). The tests below assert
both halves: registration works from the payload with nothing bound, and serving raises with nothing
bound.

Each assertion below states its failure mode:

  1. the load succeeds with `src/aria/` absent from `sys.path`;
  2. a bundled `web_bff` can register and cannot serve, and names the two things that are missing;
  3. an unregistered `bff_main` seam raises rather than binding a planted decoy;
  4. a registered seam resolves to whatever the host named;
  5. the chorus host's own route is unchanged — `aria.web_bff.bff_app()` still loads the real file;
  6. one flipped byte is refused, before exec;
  7. the shipped payload matches `aria/web_bff.py`.

Tests 1, 2, 3, 4 and 6 run in subprocesses: `_DATA_DIR` is resolved at import and the first successful
load of a group pins it for the process, and `chorus.personas._load_module` inserts persona
directories into `sys.path` when other tests boot the host.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]            # …/agience-chorus/src
ARIA = SRC / "aria"
BUNDLES = SRC.parent / "bundles"          # this repository's own; chorus builds them


def _run(snippet: str, **env_extra) -> subprocess.CompletedProcess:
    """A fresh interpreter with `src` on the path and nothing else added.

    `src` is inserted inside the snippet rather than through `PYTHONPATH`, so the subprocess carries
    no externally set path. `src/aria/` is never added.
    """
    import os
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", **env_extra)
    prologue = "import sys; sys.path.insert(0, %r)\n" % str(SRC)
    return subprocess.run([sys.executable, "-c", prologue + snippet],
                          capture_output=True, text=True, env=env, cwd=str(SRC))


# ── 1 · the path trick is gone ───────────────────────────────────────────────────────────────────

def test_aria_manifest_loads_with_the_persona_dir_OFF_sys_path():
    """aria's manifest loads with `src/aria/` off `sys.path` — the bundle payload carries everything
    `web_bff` needs, with nothing reached by bare import.

    Re-introducing `import web_bff` fails this, and so does a missing payload. It cannot pass
    vacuously: `find_spec('web_bff') is None` is asserted first in the same interpreter.
    """
    r = _run("""
import sys, json, pathlib
for p in list(sys.path):
    assert pathlib.Path(p).name != 'aria', 'the persona dir leaked onto sys.path: %r' % p

import importlib.util
BARE = ('web_bff', 'identity')          # both groups — a guard naming only one
for n in BARE:                          # would go vacuous for the group it forgot
    assert importlib.util.find_spec(n) is None, 'a bare %r is importable — test is vacuous' % n

import aria.manifest as m
print(json.dumps({
    "ops": sorted(d["id"] for d in m.OPERATORS),
    "groups": list(m.BUNDLE_GROUPS),
    "op_id": m.OP_WEB_BFF,
    "facet_tekton": m.FACETS[0]["bff_tekton"],
    "crystal_tekton": m.CRYSTAL["tektons"][0]["name"],
    "sha": m.bundle_sha256(),
    "origin": m.bundle_origin(),
    "collected": m.collect(),
    "bare_imported": sorted(n for n in BARE if n in sys.modules),
}))
""")
    assert r.returncode == 0, f"load FAILED with the persona dir off sys.path:\n{r.stderr}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["ops"] == ["op.identity.verify", "op.web.bff"], got
    assert got["groups"] == ["web_bff", "identity"]
    assert got["collected"] == len(got["ops"]), (
        "collect() and OPERATORS disagree — one group registered without joining the roster")
    assert got["bare_imported"] == [], "an organon was still reached by bare name"
    assert got["op_id"] == got["facet_tekton"] == got["crystal_tekton"] == "op.web.bff", (
        "the www facet or the crystal stopped pointing at the tekton the bundle declares: %s" % got)
    # Per group, and every group present: a stat keyed by group only means something if it answers
    # for each one. `origin` is required too — a sha with no provenance says which bytes ran but
    # not where they came from.
    assert sorted(got["sha"]) == sorted(got["groups"]) == sorted(got["origin"]), got
    for group, sha in got["sha"].items():
        assert len(sha) == 64, "%s published a sha that is not a sha256: %r" % (group, sha)


def test_no_organon_is_imported_by_bare_name_in_arias_manifest():
    """The static half: no sibling module in `aria/` is reached from `manifest.py` by bare name.

    Re-adding `import web_bff` fails this even if the runtime test above were somehow satisfied by a
    leaked path.
    """
    import ast
    siblings = {p.stem for p in ARIA.glob("*.py")} | {d.name for d in ARIA.iterdir() if d.is_dir()}
    siblings.discard("manifest")
    reached = set()
    for node in ast.walk(ast.parse((ARIA / "manifest.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            reached.add(node.module.split(".")[0])
    leaked = reached & siblings
    assert not leaked, (
        "aria/manifest.py imports sibling module(s) %s by bare name — that resolves only because "
        "`chorus.personas._load_module` puts the persona dir on sys.path. Take them from the bundle "
        "instead (`prism.runner.register_fns`)." % sorted(leaked))


# ── 2 · the obstacle that was actually there, and the split it forced ─────────────────────────────

def test_the_module_scope_dunder_path_that_BLOCKED_this_payload_is_gone():
    """`Path(__file__)` at module scope in a carried organon raises `NameError` at exec time, since a
    bundle module is exec'd from distributed text with no location. `web_bff.py` reads `__file__` only
    inside a function, where the bundle case can be detected and reported.

    Moving any `__file__` read back to module scope in `web_bff.py` fails this, before a deployment
    would discover it as an empty roster for aria.
    """
    import ast
    tree = ast.parse((ARIA / "web_bff.py").read_text(encoding="utf-8"))
    fn_bodies = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    inside = {id(n) for f in fn_bodies for n in ast.walk(f)}
    at_module_scope = [n for n in ast.walk(tree)
                       if isinstance(n, ast.Name) and n.id in ("__file__", "__path__")
                       and id(n) not in inside]
    assert not at_module_scope, (
        "aria/web_bff.py reads a dunder path at MODULE SCOPE again — a bundle module has neither, so "
        "the payload would NameError at exec")


def test_a_BUNDLED_web_bff_can_REGISTER_and_REFUSES_to_SERVE():
    """The tekton registration travels — it needs nothing but the payload. The facet's app does not
    travel — it is a file in the persona directory — so with no seam bound, `bff_app()` raises and
    names the two things that would fix it.

    The raise is the assertion under test: a stub app, a `cwd`-relative guess, or a silently empty
    router would each read as a working deployment while serving nothing or the wrong tree.

    If `_bff_main_path()` ever guessed a location instead of returning `None`, this test would report
    an app object and fail.
    """
    r = _run("""
import json
from prism import runner
assert runner.registered_seams() == {}, 'chorus registered a seam: %r' % runner.registered_seams()
mod = runner.load('web_bff')

capture = []
class _Store:
    def put_artifact(self, a): capture.append(a["id"]); return a
    def get_artifact(self, i): return None
n = mod.register_web_operators(_Store())

out = {"registered": n, "ids": capture, "bff_main_is_none": mod._bff_main_path() is None}
try:
    mod.bff_app()
except RuntimeError as e:
    out["serve"] = "REFUSED"; out["says_seam"] = mod.BFF_MAIN_SEAM in str(e)
    out["says_register_seam"] = "register_seam" in str(e)
except Exception as e:
    out["serve"] = "WRONG_ERROR:" + type(e).__name__
else:
    out["serve"] = "SERVED"
print(json.dumps(out))
""")
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["registered"] == 1 and got["ids"] == ["op.web.bff"], (
        "registration did NOT travel — that is the half that must work from the payload alone: %s" % got)
    assert got["bff_main_is_none"] is True, "a bundled copy guessed a path for the bff app"
    assert got["serve"] == "REFUSED", (
        "a bundled web_bff served an app it cannot have: %s" % got)
    assert got["says_seam"] and got["says_register_seam"], (
        "the refusal did not say how to fix it — %s" % got)


def test_the_web_bff_bundle_DECLARES_the_host_reach_it_cannot_carry():
    """The declaration itself: a host reach that is real must be visible in the bundle spec.

    Dropping `host_seams` from the spec entry makes the reach invisible in the payload while
    `_load_bff_module` still attempts it — this fails and names it.
    """
    b = json.loads((BUNDLES / "web_bff.json").read_text(encoding="utf-8"))
    assert b["host_seams"] == ["bff_main"], b["host_seams"]
    assert list(b["modules"]) == ["web_bff"], b["modules"].keys()
    assert "bff_main" in b["modules"]["web_bff"], (
        "the payload no longer reaches the seam it declares — drop the declaration or restore it")


# ── 3 · seams ────────────────────────────────────────────────────────────────────────────────────

def test_an_UNREGISTERED_bff_main_seam_RAISES_and_never_takes_a_sys_path_module():
    """A bundle declaring a seam nobody registers raises rather than silently reaching for a module it
    was not given. A decoy named `bff_main` is planted in `sys.modules` first; if the loader let an
    unresolved seam fall through to ordinary absolute-import resolution, the bundle would bind the
    decoy and aria would mount a stranger's app. Seams resolve under the bundle package name, so
    `sys.path` fall-through is structurally impossible.

    The test fails if the decoy is reached, and it fails if nothing is raised at all.
    """
    r = _run("""
import sys, types, importlib
decoy = types.ModuleType('bff_main'); decoy.MARKER = 'DECOY'; decoy.app = 'DECOY-APP'
sys.modules['bff_main'] = decoy                   # planted before anything loads

from prism import runner
assert runner.registered_seams() == {}, 'chorus registered a seam: %r' % runner.registered_seams()
info = runner._load_group('web_bff')
assert 'bff_main' in info['bundle']['host_seams'], 'the web_bff bundle stopped declaring the seam'
try:
    mod = importlib.import_module(info['pkg'] + '.bff_main')
except ModuleNotFoundError as e:
    print('RAISED', e)
else:
    print('BOUND', getattr(mod, 'MARKER', mod.__name__))
""")
    assert r.returncode == 0, r.stderr
    last = r.stdout.strip().splitlines()[-1]
    assert last.startswith("RAISED"), (
        "an unregistered seam did NOT fail loudly — it resolved to %r" % last)
    assert "DECOY" not in r.stdout


def test_a_REGISTERED_bff_main_seam_is_what_the_bundled_bff_app_SERVES():
    """The positive control, end to end. The host binds `bff_main` to a module of its own choosing and
    the bundled `bff_app()` returns that module's `app` — the bundle asked for a name and got the
    host's answer.

    The host binds a module written in the test, not aria's real bff, so the identity check cannot be
    satisfied by the file-beside-this-one route: there is no file beside a bundle.

    If `_load_bff_module` ignored the seam, this returns aria's own app (or raises) and the identity
    check fails.
    """
    import tempfile, textwrap
    tmp = tempfile.mkdtemp()
    Path(tmp, "hostbff.py").write_text(
        textwrap.dedent("""
            app = 'THE-HOSTS-OWN-APP'
        """), encoding="utf-8")
    r = _run("""
import sys, json
sys.path.insert(0, %r)
from prism import runner
runner.register_seam('bff_main', 'hostbff')        # the HOST's answer
mod = runner.load('web_bff')
app = mod.bff_app()
print(json.dumps({"app": app,
                  "cached_under_the_host_name": sys.modules['aria_www_bff_main'].app}))
""" % tmp)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["app"] == "THE-HOSTS-OWN-APP", (
        "the bundled bff_app did not serve the module the host bound: %s" % got)
    assert got["cached_under_the_host_name"] == "THE-HOSTS-OWN-APP", (
        "the seam-loaded module was not registered under `_BFF_MODULE_NAME` — `chorus/personas.py` "
        "and `chorus/live_service.py` reach the running app through that name to set its carrier")


# ── 4 · the chorus host's own route is untouched ─────────────────────────────────────────────────

def test_the_chorus_hosts_route_to_the_REAL_bff_is_unchanged():
    """`chorus/personas.py` mounts `web_bff.bff_app().router` and `chorus/live_service.py` sets the
    carrier on `sys.modules[web_bff._BFF_MODULE_NAME]`. Both reach `aria.web_bff` from its own file,
    where `__file__` exists — so this route still loads `www/bff/main.py` verbatim.

    If the lazy-path route broke the file route, the public website's bff would stop mounting while
    every bundle test above still passed.
    """
    from aria import web_bff

    assert web_bff._bff_main_path() is not None, "the file route lost its own location"
    assert web_bff._bff_main_path().is_file(), "www/bff/main.py is not where web_bff looks for it"
    mod = web_bff._load_bff_module()
    assert sys.modules[web_bff._BFF_MODULE_NAME] is mod
    app = web_bff.bff_app()
    assert app is mod.app
    paths = {r.path for r in app.routes}
    assert "/healthz" in paths and "/api/chat" in paths, sorted(paths)


# ── 5 · the integrity gate ───────────────────────────────────────────────────────────────────────

def test_a_TAMPERED_web_bff_bundle_is_REFUSED():
    """One flipped byte, and the load raises.

    The tamper is a semantic no-op (two added spaces). The raise is shown to precede the exec: the
    tampered source appends `sys.modules['ARIA_TAMPER_RAN']`, so its absence is what makes "refused
    before exec" an observation rather than an assumption.

    If `_verify_sha` were softened to a warning, `register_fns` returns callables and this fails.
    """
    import tempfile
    good = json.loads((BUNDLES / "web_bff.json").read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(good))
    anchor = "from __future__ import annotations"
    text = bad["modules"]["web_bff"]
    assert anchor in text, "no inert anchor to nudge"
    bad["modules"]["web_bff"] = text.replace(anchor, anchor + "  ", 1) + (
        "\nimport sys as _s; _s.modules['ARIA_TAMPER_RAN'] = True\n")
    assert bad["modules"]["web_bff"] != good["modules"]["web_bff"], "the tamper changed nothing"
    assert bad["sha256"] == good["sha256"], "the tamper must leave the CLAIMED sha in place"

    tmp = tempfile.mkdtemp()
    Path(tmp, "web_bff.json").write_text(json.dumps(bad), encoding="utf-8")
    r = _run("""
import sys
from prism import runner
try:
    runner.register_fns('web_bff')
except runner.BundleIntegrityError:
    print('REFUSED', 'EXECUTED' if 'ARIA_TAMPER_RAN' in sys.modules else 'NOT_EXECUTED')
else:
    print('ACCEPTED')
""", AGIENCE_BUNDLE_ROOT=tmp)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "REFUSED NOT_EXECUTED", (
        "a tampered payload was EXEC'd — the integrity gate is not holding:\n%s" % r.stdout)


# ── 6 · the source of truth has not drifted ──────────────────────────────────────────────────────

def test_the_shipped_web_bff_bundle_still_matches_arias_authoritative_source():
    """`aria/web_bff.py` is the source of truth; the bundle is built from it.

    Editing it without rebuilding fails this, since the manifest reads the bundle rather than the
    file at runtime.
    """
    shipped = json.loads((BUNDLES / "web_bff.json").read_text(encoding="utf-8"))
    on_disk = (ARIA / "web_bff.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert shipped["modules"]["web_bff"] == on_disk, (
        "aria/web_bff.py has drifted from the shipped `web_bff` bundle — run "
        "`python agience-observe/build_bundles.py web_bff`")
