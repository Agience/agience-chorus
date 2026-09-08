"""lumen's manifest travels as bundles — the first persona whose manifest carries more than one
bundle group.

Astra's and seraph's equivalents each own one organon, so a single `BUNDLE_GROUP` covered them.
lumen owns five: `arithmetic` and `dev_ops` already had groups, and `check`, `curriculum`,
`reasoning` did not. A manifest reaching two organons through the distribution path and three by
bare name would still need `src/lumen/` on `sys.path`, proving nothing while exercising both
mechanisms — so the three missing groups were built (a `bundle_spec.json` entry plus
`python agience-observe/build_bundles.py`, no edit inside prism), and all five now arrive the same
way, with the persona directory unneeded.

Each assertion below states the failure mode it pins:

  1. the load succeeds with `src/lumen/` absent from `sys.path` — the same test first proves the
     bare names are genuinely unresolvable there, so it cannot pass vacuously;
  2. the registrars are the bundles' declared ones, matching each shipped payload's sha;
  3. one flipped byte in any of the five payloads is rejected, before exec;
  4. the shipped payloads still match the files under `src/lumen/`, which remain authoritative.

1 and 3 run in subprocesses: `_DATA_DIR` is resolved at import, the first successful load of a group
pins it for the process, and `chorus.personas._load_module` inserts persona directories into
`sys.path` when other tests boot the host — so an in-process "the dir is not on the path" assertion
would silently stop testing anything.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]            # …/agience-chorus/src/agience_chorus
LUMEN = SRC / "lumen"
BUNDLES = SRC / "bundles"                 # this repository's own; chorus builds them.
#                                          Inside the package, so the wheel carries them.

#: The organon files this persona's five groups carry, as {group: (module-name, source file)}.
GROUPS = {
    "reasoning":  ("reasoning",  LUMEN / "reasoning.py"),
    "arithmetic": ("arithmetic", LUMEN / "arithmetic.py"),
    "check":      ("check",      LUMEN / "check.py"),
    "curriculum": ("curriculum", LUMEN / "curriculum.py"),
    "dev_ops":    ("dev_ops",    LUMEN / "dev_ops.py"),
}


def _run(snippet: str, **env_extra) -> subprocess.CompletedProcess:
    """A fresh interpreter with `src` on the path and nothing else added.

    `src` is inserted inside the snippet rather than through `PYTHONPATH`, because a hand-passed
    PYTHONPATH is the pattern this conversion removes. `src/lumen/` is never added — that absence
    is the point.
    """
    import os
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", **env_extra)
    prologue = "import sys; sys.path.insert(0, %r)\n" % str(SRC)
    return subprocess.run([sys.executable, "-c", prologue + snippet],
                          capture_output=True, text=True, env=env, cwd=str(SRC))


# ── 1 · organons resolve only through the bundle path ───────────────────────────────────────────

def test_lumen_manifest_loads_with_the_persona_dir_OFF_sys_path():
    """Pins that `lumen/manifest.py` resolves its five organons without `src/lumen/` on `sys.path`.
    The organons are sibling files, not installed packages, and `chorus.personas._load_module` is
    the only mechanism that ever makes bare names like `arithmetic` or `check` resolve, by inserting
    that directory.

    Failure mode: re-introducing any bare-name organon import fails this, and so does a missing
    bundle payload. It cannot pass vacuously — `find_spec(<organon>) is None` is asserted first for
    all five, in the same interpreter, so a leaked path would fail the test rather than satisfy it.
    """
    r = _run("""
import sys, json, pathlib
for p in list(sys.path):
    assert pathlib.Path(p).name != 'lumen', 'the persona dir leaked onto sys.path: %r' % p

# The bare names must be unresolvable here, or everything below proves nothing.
import importlib.util
for n in ('reasoning', 'arithmetic', 'check', 'curriculum', 'dev_ops', 'answer', 'category'):
    assert importlib.util.find_spec(n) is None, 'a bare %r is importable — test is vacuous' % n

import lumen.manifest as m
print(json.dumps({
    "ops": sorted(d["id"] for d in m.OPERATORS),
    "groups": list(m.BUNDLE_GROUPS),
    "sha": m.bundle_sha256(),
    "origin": m.bundle_origin(),
    "collected": m.collect(),
    "bare_imported": sorted(n for n in
                            ('reasoning', 'arithmetic', 'check', 'curriculum', 'dev_ops',
                             'answer', 'category')
                            if n in sys.modules),
}))
""")
    assert r.returncode == 0, f"load FAILED with the persona dir off sys.path:\n{r.stderr}"
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["groups"] == list(GROUPS), got["groups"]
    assert got["bare_imported"] == [], "an organon was still reached by bare name: %s" % got
    assert got["collected"] == len(got["ops"]) == 25, got
    # The five distinct organons are all represented — a group silently failing to contribute would
    # otherwise read as green.
    for prefix in ("op.reason", "op.math.", "op.check.", "op.curriculum.", "op.dev."):
        assert any(o.startswith(prefix) for o in got["ops"]), (prefix, got["ops"])
    assert set(got["sha"]) == set(GROUPS) and all(len(v) == 64 for v in got["sha"].values())
    assert set(got["origin"].values()) <= {"store", "host", "shipped"}, got["origin"]


def test_no_organon_is_imported_by_bare_name_in_lumens_manifest():
    """The static half. `crystal`/`prism`/stdlib are installed packages and resolve by ordinary
    absolute import; an organon is a sibling file and only ever resolved by the path trick.

    Failure mode: re-adding `import reasoning` (or any other sibling) fails this even if the runtime
    test above were somehow satisfied by a leaked path.
    """
    import ast
    siblings = {p.stem for p in LUMEN.glob("*.py")} | {d.name for d in LUMEN.iterdir() if d.is_dir()}
    siblings.discard("manifest")
    reached = set()
    for node in ast.walk(ast.parse((LUMEN / "manifest.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            reached.add(node.module.split(".")[0])
    leaked = reached & siblings
    assert not leaked, (
        "lumen/manifest.py imports sibling module(s) %s by bare name — that resolves only because "
        "`chorus.personas._load_module` puts the persona dir on sys.path. Take them from the bundle "
        "instead (`prism.runner.register_fns`)." % sorted(leaked))


# ── 2 · the operators come from sha-verified bundles, not from the files next door ────────────────

def test_lumen_registrars_are_the_bundles_own_declared_register_fns():
    """The manifest transcribes no function name: `register_fns` reads them from each bundle
    manifest that travelled with the code, and the order of the five groups is preserved.

    Failure mode: hardcoding `[reasoning.register_reasoning_operators, …]` back into the manifest
    passes the operator assertion but breaks the identity check against `prism.runner`'s pinned
    bundles.
    """
    import agience_chorus.lumen.manifest as m
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


def test_the_three_groups_prism_never_declared_are_lumens_and_they_were_the_blocker():
    """`check`, `curriculum`, and `reasoning` are not among the six names `prism.runner` declares
    directly; they exist because their payloads do. Two of five groups covered would be a
    half-conversion that still needs the path trick, so all three are pinned as loadable through the
    payload mechanism alone.

    Failure mode: if prism ever goes back to a fixed list, this fails — either because the three
    stop being loadable, or because `known_groups()` stops reflecting the payloads on disk.
    """
    from prism import runner

    six = {"arithmetic", "operators", "dev_ops", "docs_ops", "corpus", "fetch"}
    new = {"check", "curriculum", "reasoning"}
    assert not (new & six), "these were supposed to be the groups prism never declared"
    assert new <= set(runner.known_groups())
    assert set(runner.known_groups()) == {p.stem for p in BUNDLES.glob("*.json")}, (
        "the group list stopped being a measurement of the payloads present")


def test_the_lumen_manifest_surface_is_unchanged_for_the_host():
    """`chorus.personas._persona_manifest` reads `OPERATORS`; `crystal.host` calls `collect`; the
    `CRYSTAL` declaration at the foot of the manifest is read by the crystal roster — a change of
    source, not of contract.

    Failure mode: dropping `collect`/`operators`/`CRYSTAL` would strand the host's registration path.
    """
    import agience_chorus.lumen.manifest as m
    assert callable(m.collect) and callable(m.operators)
    assert m.operators() == m.OPERATORS
    assert m.collect() == len(m.OPERATORS) == 25
    assert m.CRYSTAL["name"] == "lumen"
    assert {t["name"] for t in m.CRYSTAL["tektons"]} == {
        "op.respond", "op.reason", "op.math", "op.check", "op.dev"}


# ── 3 · the integrity gate holds for every one of the five ──────────────────────────────────────

def test_a_TAMPERED_bundle_is_REFUSED_for_EVERY_group_lumen_rides():
    """Five groups means five places the integrity gate has to hold: one flipped byte in each
    payload lumen depends on, one at a time, and every load must be rejected.

    Each tamper is a semantic no-op (two spaces added inside the source text), so a change that
    also broke the code would fail for the wrong reason and leave the sha gate untested — the only
    thing wrong with these payloads is that they are not the payloads that were hashed.

    The rejection is proved to precede the exec, not merely to happen: the tampered source has a
    module-scope side effect appended (`sys.modules['LUMEN_TAMPER_RAN']`), so if the runner hashed
    after executing — or fell back to a known-good copy on mismatch — the marker would be present
    even though something was raised. Absence of the marker is what makes "rejected before exec" an
    observation rather than an assumption.

    Failure mode: if `_verify_sha` were softened to a warning for any group, `register_fns` returns
    callables and this fails, naming the group.
    """
    import tempfile
    for group, (modname, _src) in GROUPS.items():
        good = json.loads((BUNDLES / f"{group}.json").read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(good))
        text = bad["modules"][modname]
        anchor = "from __future__ import annotations"
        assert anchor in text, (group, "no inert anchor to nudge")
        # Two added spaces: semantically inert, byte-different. The appended line is the exec
        # detector, not part of the tamper's meaning — it is what turns "rejected" into
        # "rejected before running anything".
        bad["modules"][modname] = text.replace(anchor, anchor + "  ", 1) + (
            "\nimport sys as _s; _s.modules['LUMEN_TAMPER_RAN'] = True\n")
        assert bad["modules"][modname] != good["modules"][modname], (group, "the tamper changed nothing")
        assert bad["sha256"] == good["sha256"], (group, "the tamper must leave the CLAIMED sha in place")

        tmp = tempfile.mkdtemp()
        # Only the tampered group goes into the alternate root; the others are still resolved from
        # the real shipped directory, so this isolates the one under test.
        for g in GROUPS:
            payload = bad if g == group else json.loads((BUNDLES / f"{g}.json").read_text(encoding="utf-8"))
            Path(tmp, f"{g}.json").write_text(json.dumps(payload), encoding="utf-8")
        r = _run("""
import sys
from prism import runner
try:
    runner.register_fns(%r)
except runner.BundleIntegrityError:
    print('REFUSED', 'EXECUTED' if 'LUMEN_TAMPER_RAN' in sys.modules else 'NOT_EXECUTED')
else:
    print('ACCEPTED')
""" % group, AGIENCE_BUNDLE_ROOT=tmp)
        assert r.returncode == 0, (group, r.stderr)
        last = r.stdout.strip().splitlines()[-1]
        assert last == "REFUSED NOT_EXECUTED", (
            "group %r: expected refusal BEFORE exec, got %r\n%s" % (group, last, r.stdout))


# ── 4 · the sources of truth have not drifted ────────────────────────────────────────────────────

def test_the_shipped_bundles_still_match_lumens_authoritative_sources():
    """The files under `src/lumen/` remain the source of truth; the bundles are built from them. If
    the two drift, the node runs bytes nobody edited.

    Failure mode: editing e.g. `lumen/curriculum.py` without rebuilding fails this — which is the
    intended reminder, since the runtime reads the bundle payloads, not these files directly.
    """
    for group, (modname, path) in GROUPS.items():
        shipped = json.loads((BUNDLES / f"{group}.json").read_text(encoding="utf-8"))
        on_disk = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert shipped["modules"][modname] == on_disk, (
            "%s has drifted from the shipped `%s` bundle — run "
            "`python agience-observe/build_bundles.py %s`" % (path.name, group, group))
