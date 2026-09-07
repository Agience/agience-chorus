"""iris's manifest travels as a bundle. iris owns `comms`, a package, not a flat module — the other
converted personas (astra, seraph, lumen, sage) each own flat `.py` organons whose bundles are single
spec entries.

`prism.runner._BundleFinder` serves `pkg` as a package and `pkg.<module>` for every module in the
payload, so a bundle module's `__package__` is the bundle package and a one-level relative import
resolves inside the payload by construction. A flat payload cannot carry a sub-package (`pkg.a.b` has
nowhere to live) or a module that reads `__file__` or `__path__` (a bundle module has neither);
`iris/comms` does neither. `test_the_flattening_argument_is_FALSIFIABLE` checks exactly those two
properties of the tree, so if `comms/sub/…` or a `__file__` read is ever added, the claim in the
manifest docstring stops being true and this test says so instead of the runtime failing elsewhere.

Every assertion below states what would fail it:

  1. the load succeeds with `src/iris/` absent from `sys.path` — and the same test first proves the
     bare names are genuinely unresolvable there, so it cannot pass vacuously;
  2. the relative imports resolve inside the bundle, not to anything on `sys.path`;
  3. `comms.operators` is not `sage.operators` — the duplicate-basename substitution;
  4. one flipped byte does not verify, and does not verify before exec;
  5. the shipped payload still matches the files under `src/iris/comms/`.

1, 2, 3 and 4 run in subprocesses, deliberately. `_DATA_DIR` is resolved at import, the first
successful load of a group pins it for the process, and `chorus.personas._load_module` inserts persona
directories into `sys.path` when other tests boot the host — so an in-process "the dir is not on the
path" assertion is exactly the kind that silently stops testing anything.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]            # …/agience-chorus/src
IRIS = SRC / "iris"
COMMS = IRIS / "comms"
BUNDLES = SRC.parent / "bundles"          # this repository's own; chorus builds them

#: {payload module name: authoritative source file}. `comms` is the package `__init__` riding as the
#: entry module; the rest are its impl-internal deps.
PAYLOAD = {
    "comms":        COMMS / "__init__.py",
    "facet_nas":    COMMS / "facet_nas.py",
    "mcp_tekton":   COMMS / "mcp_tekton.py",
    "message":      COMMS / "message.py",
    "operators":    COMMS / "operators.py",
    "tekton_comms": COMMS / "tekton_comms.py",
    "wiring":       COMMS / "wiring.py",
}


def _run(snippet: str, **env_extra) -> subprocess.CompletedProcess:
    """A fresh interpreter with `src` on the path and nothing else added.

    `src` is inserted inside the snippet rather than through `PYTHONPATH`, so the subprocess
    carries no environment dependency beyond `src` itself. `src/iris/` is never added — that
    absence is the point.
    """
    import os
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", **env_extra)
    prologue = "import sys; sys.path.insert(0, %r)\n" % str(SRC)
    return subprocess.run([sys.executable, "-c", prologue + snippet],
                          capture_output=True, text=True, env=env, cwd=str(SRC))


# ── 0 · the claim in the manifest docstring, made falsifiable ────────────────────────────────────

def test_the_flattening_argument_is_FALSIFIABLE():
    """The argument, not the conclusion: `iris/comms` can travel flat because of two measurable
    properties, and both are checked here rather than believed.

      a. No sub-package. A flat payload maps one name to one source; `pkg.a.b` has nowhere to live.
      b. No `__file__` / `__path__` read. A bundle module is exec'd from text with no location, so
         either name raises `NameError` at exec — which is what genuinely stops `aria/web_bff.py`
         from travelling, and the difference between the two cases is worth being able to see.

    Fails if `comms/anything/__init__.py` is added, or any carried module reads `Path(__file__)` —
    and names the file, so the manifest's claim cannot go quietly stale.
    """
    import ast

    subpkgs = [d for d in COMMS.iterdir() if d.is_dir() and (d / "__init__.py").is_file()]
    assert not subpkgs, (
        "iris/comms grew a sub-package (%s) — a flat bundle payload cannot carry one, so the "
        "manifest's flattening argument no longer holds" % [d.name for d in subpkgs])

    for name, path in PAYLOAD.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = sorted({n.id for n in ast.walk(tree)
                      if isinstance(n, ast.Name) and n.id in ("__file__", "__path__")})
        assert not bad, (
            "%s reads %s — a bundle module is exec'd with neither, so this would NameError at exec"
            % (path, bad))
        deep = sorted({(("." * n.level) + (n.module or "")) for n in ast.walk(tree)
                       if isinstance(n, ast.ImportFrom) and n.level
                       and ((n.level > 1) or (n.module and "." in n.module))})
        assert not deep, (
            "%s uses a relative import deeper than one level (%s) — that resolves outside a flat "
            "payload" % (path, deep))


# ── 1 · the path trick is gone ───────────────────────────────────────────────────────────────────

def test_iris_manifest_loads_with_the_persona_dir_OFF_sys_path():
    """The whole point: `iris/manifest.py` resolves `comms` through the bundle, not a bare
    `from comms import register_comms_operators` — the only thing that ever makes a bare import
    resolve is `chorus.personas._load_module` inserting `src/iris/` into `sys.path`, and this loads
    with that insertion absent.

    Fails if the bare-name package import is reintroduced, and so does a missing payload. It cannot
    pass vacuously — every carried name is proved unresolvable first.
    """
    r = _run("""
import sys, json, pathlib
for p in list(sys.path):
    assert pathlib.Path(p).name != 'iris', 'the persona dir leaked onto sys.path: %r' % p

import importlib.util
BARE = ('comms', 'facet_nas', 'mcp_tekton', 'message', 'operators', 'tekton_comms', 'wiring')
for n in BARE:
    assert importlib.util.find_spec(n) is None, 'a bare %r is importable — test is vacuous' % n

import iris.manifest as m
print(json.dumps({
    "ops": sorted(d["id"] for d in m.OPERATORS),
    "group": m.BUNDLE_GROUP,
    "mcp_call": m.MCP_CALL,
    "facet_tekton": m.FACETS[0]["bff_tekton"],
    "sha": m.bundle_sha256(),
    "origin": m.bundle_origin(),
    "collected": m.collect(),
    "bare_imported": sorted(n for n in BARE if n in sys.modules),
}))
""")
    assert r.returncode == 0, f"load FAILED with the persona dir off sys.path:\n{r.stderr}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["ops"] == ["op.comms.inbox", "op.comms.send", "op.mcp.call"], got
    assert got["group"] == "comms"
    assert got["collected"] == 3
    assert got["bare_imported"] == [], "the organon was still reached by bare name: %s" % got
    assert got["mcp_call"] == got["facet_tekton"] == "op.mcp.call", (
        "the mcp facet no longer points at the tekton the bundle declares")
    assert len(got["sha"]) == 64


def test_no_organon_is_imported_by_bare_name_in_iris_manifest():
    """The static half. `crystal`/`prism`/stdlib are installed packages; `comms` is a sibling
    directory and only ever resolved by the path trick.

    Fails if `from comms import …` is re-added, even if the runtime test above were somehow
    satisfied by a leaked path.
    """
    import ast
    siblings = {p.stem for p in IRIS.glob("*.py")} | {d.name for d in IRIS.iterdir() if d.is_dir()}
    siblings.discard("manifest")
    reached = set()
    for node in ast.walk(ast.parse((IRIS / "manifest.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            reached.add(node.module.split(".")[0])
    leaked = reached & siblings
    assert not leaked, (
        "iris/manifest.py imports sibling module(s) %s by bare name — that resolves only because "
        "`chorus.personas._load_module` puts the persona dir on sys.path. Take them from the bundle "
        "instead (`prism.runner.register_fns`)." % sorted(leaked))


# ── 2 · the package really did travel — the relative imports resolved inside the payload ─────────

def test_the_packages_relative_imports_resolved_INSIDE_the_bundle():
    """The structural claim, observed: `comms/__init__.py` does `from .message import Message` and
    `from . import wiring`; `tekton_comms.py` does `from .message import Message`. Every one of those
    lands under `_agience_bundle_comms_<sha12>` — if any escaped to `sys.path`, the conversion would
    be a path trick wearing a bundle's name.

    Fails if the finder stopped serving `pkg` as a package: the relative imports would either raise or
    resolve elsewhere; both fail here. The `Message` identity check is what catches the "resolved
    elsewhere" half, which an import-succeeded check would not.
    """
    r = _run("""
import sys, json
from prism import runner
info = runner._load_group('comms')
pkg = info['pkg']
entry = info['entry']
carried = sorted(n for n in sys.modules if n.startswith(pkg + '.'))
print(json.dumps({
    "pkg": pkg,
    "is_package": hasattr(sys.modules[pkg], '__path__'),
    "carried": carried,
    "entry_module_name": entry.__name__,
    "message_home": entry.Message.__module__,
    "tekton_message_is_same_class": (
        sys.modules[pkg + '.tekton_comms'].Message is entry.Message),
    "wiring_home": entry.build_plane.__module__,
    "escaped": sorted(n for n in ('comms','message','wiring','operators','mcp_tekton',
                                  'facet_nas','tekton_comms') if n in sys.modules),
}))
""")
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["is_package"], "the bundle root stopped being a package — relative imports cannot work"
    assert got["escaped"] == [], "a carried module landed at a TOP-LEVEL name: %s" % got["escaped"]
    assert got["message_home"] == got["pkg"] + ".message", got
    assert got["wiring_home"] == got["pkg"] + ".wiring", got
    assert got["tekton_message_is_same_class"], (
        "two Message classes exist — `from .message import Message` resolved to different modules "
        "in the entry and in tekton_comms")
    assert set(got["carried"]) >= {got["pkg"] + "." + n for n in PAYLOAD if n != "comms"}, got


def test_comms_operators_is_NOT_sages_operators():
    """Two files in this workspace are named `operators.py`, and pytest silently substitutes one
    module for another when basenames collide. Inside the bundle, `operators` resolves under the
    bundle package name and nowhere else, so the two never collide.

    Fails if `build_bundles.py` ever resolved sources by basename, or the finder fell through to
    `sys.path`: iris would register sage's describe-operators and nothing would say so.
    """
    r = _run("""
import json
from prism import runner
c = runner._load_group('comms')
s = runner._load_group('operators')
cm = __import__(c['pkg'] + '.operators', fromlist=['x'])
sm = __import__(s['pkg'] + '.operators', fromlist=['x'])
print(json.dumps({
    "same_object": cm is sm,
    "comms_fns": sorted(n for n in vars(cm) if n.startswith('register_')),
    "sage_fns": sorted(n for n in vars(sm) if n.startswith('register_')),
}))
""")
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["same_object"] is False, "iris's and sage's `operators` are ONE module — substituted"
    assert got["comms_fns"] == ["register_comms_operators"], got
    assert got["sage_fns"] == ["register_operators"], got


def test_iris_registrars_are_the_bundles_own_declared_register_fns():
    """The manifest transcribes no function name: `register_fns` reads them from the bundle manifest
    that travelled with the code, and both of iris's registrars come from the one group.

    Fails if the registrars are hardcoded back into the manifest: that passes the operator assertion
    but breaks the identity check against `prism.runner`'s pinned bundle.
    """
    import iris.manifest as m
    from prism import runner

    shipped = json.loads((BUNDLES / "comms.json").read_text(encoding="utf-8"))
    assert m.bundle_sha256() == shipped["sha256"], "running bytes differ from the shipped payload"
    assert [f.__name__ for f in m.REGISTRARS] == shipped["register_fns"]
    assert shipped["register_fns"] == ["register_comms_operators", "register_mcp_operators"]
    assert runner.loaded()["comms"]["sha256"] == shipped["sha256"]
    assert shipped["entry_module"] == "comms"
    assert set(shipped["modules"]) == set(PAYLOAD), (
        "the payload's module set changed — %s" % sorted(set(shipped["modules"]) ^ set(PAYLOAD)))


def test_the_iris_manifest_surface_is_unchanged_for_the_host():
    """`chorus.personas._persona_manifest` reads `OPERATORS` and `facets()`; `crystal.host` calls
    `collect` and routes on the facet `subdomains`. The bundle conversion changed where the
    manifest's data comes from, not the contract it presents.

    Fails if `facets`/`collect` are dropped: that strands the host→facet router and the registration
    path.
    """
    import iris.manifest as m
    assert callable(m.collect) and callable(m.operators) and callable(m.facets)
    assert m.operators() == m.OPERATORS
    assert m.collect() == len(m.OPERATORS) == 3
    (mcp,) = m.facets()
    assert mcp["name"] == "mcp" and mcp["subdomains"] == ["mcp", "iris"]
    assert mcp["bff_tekton"] == m.MCP_CALL


# ── 3 · the integrity gate ───────────────────────────────────────────────────────────────────────

def test_a_TAMPERED_comms_bundle_is_REFUSED():
    """A package-shaped payload buys no exemption. One flipped byte in a non-entry module —
    `message`, the deepest thing the relative imports reach — and the load does not verify.

    The tamper is a semantic no-op (two added spaces), and verification is proved to happen before
    exec: the tampered source appends `sys.modules['IRIS_TAMPER_RAN']`, so its absence is what makes
    "not executed" an observation rather than an assumption.

    Fails if `_verify_sha` covered only the entry module: tampering with `message` would then go
    through.
    """
    import tempfile
    good = json.loads((BUNDLES / "comms.json").read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(good))
    anchor = "from __future__ import annotations"
    text = bad["modules"]["message"]
    assert anchor in text, "no inert anchor to nudge"
    bad["modules"]["message"] = text.replace(anchor, anchor + "  ", 1) + (
        "\nimport sys as _s; _s.modules['IRIS_TAMPER_RAN'] = True\n")
    assert bad["modules"]["message"] != good["modules"]["message"], "the tamper changed nothing"
    assert bad["sha256"] == good["sha256"], "the tamper must leave the CLAIMED sha in place"

    tmp = tempfile.mkdtemp()
    Path(tmp, "comms.json").write_text(json.dumps(bad), encoding="utf-8")
    r = _run("""
import sys
from prism import runner
try:
    runner.register_fns('comms')
except runner.BundleIntegrityError:
    print('REFUSED', 'EXECUTED' if 'IRIS_TAMPER_RAN' in sys.modules else 'NOT_EXECUTED')
else:
    print('ACCEPTED')
""", AGIENCE_BUNDLE_ROOT=tmp)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "REFUSED NOT_EXECUTED", (
        "a tampered payload was EXEC'd — the integrity gate is not holding:\n%s" % r.stdout)


# ── 4 · the source of truth has not drifted ──────────────────────────────────────────────────────

def test_the_shipped_comms_bundle_still_matches_iris_authoritative_sources():
    """The files under `src/iris/comms/` remain the source of truth; the bundle is built from them.

    Fails if any carried module is edited without rebuilding — the reminder is intentional, since the
    runtime reads only the bundle payload, never these files directly.
    """
    shipped = json.loads((BUNDLES / "comms.json").read_text(encoding="utf-8"))
    for name, path in PAYLOAD.items():
        on_disk = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert shipped["modules"][name] == on_disk, (
            "%s has drifted from the shipped `comms` bundle — run "
            "`python agience-observe/build_bundles.py comms`" % path)
