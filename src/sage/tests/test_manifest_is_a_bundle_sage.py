"""sage's manifest travels as bundles, and its own organon declares a seam.

sage's `canon` group declares `content_search`, because `canon.retrieve_cited` reaches sage's BM25
tekton and that module's own closure (`answer_shape`, `offer`, `condense`, `ember.signal`) would
otherwise pull the whole retrieval stack into the canon payload. The bundle declares the reach and
the host answers it or does not.

Each assertion below has a stated failure mode, because a check that cannot fail proves nothing:

  1. the load succeeds with `src/sage/` absent from `sys.path` — and the same test first proves the
     bare names are genuinely unresolvable there, so it cannot pass vacuously;
  2. the registrars are the bundles' declared ones, matching each shipped payload's sha;
  3. the declared-but-unfilled seam does not bind a planted decoy;
  4. one flipped byte in any payload is rejected, and rejected before exec;
  5. the shipped payloads still match the files under `src/sage/`, which remain authoritative.

1, 3 and 4 run in subprocesses. `_DATA_DIR` is resolved at import, the first successful load of a
group pins it for the process, and `chorus.personas._load_module` inserts persona directories into
`sys.path` when other tests boot the host — so an in-process "the dir is not on the path" assertion
would silently stop testing anything.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]            # …/agience-chorus/src
SAGE = SRC / "sage"
BUNDLES = SRC.parent / "bundles"          # this repository's own; chorus builds them

#: {group: (entry module name, its authoritative source file)} for the five groups sage rides.
GROUPS = {
    "retrieval": ("retrieval", SAGE / "retrieval.py"),
    "corpus":    ("corpus",    SAGE / "corpus.py"),
    "docs_ops":  ("docs_ops",  SAGE / "docs_ops.py"),
    "operators": ("operators", SAGE / "operators.py"),
    "canon":     ("canon",     SAGE / "canon.py"),
}


def _run(snippet: str, **env_extra) -> subprocess.CompletedProcess:
    """A fresh interpreter with `src` on the path and nothing else added.

    `src` is inserted inside the snippet rather than through `PYTHONPATH`, so the subprocess
    carries no environment dependency beyond `src` itself. `src/sage/` is never added — that
    absence is the point.
    """
    import os
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", **env_extra)
    prologue = "import sys; sys.path.insert(0, %r)\n" % str(SRC)
    return subprocess.run([sys.executable, "-c", prologue + snippet],
                          capture_output=True, text=True, env=env, cwd=str(SRC))


# ── 1 · organons resolve only through the bundle path ───────────────────────────────────────────

def test_sage_manifest_loads_with_the_persona_dir_OFF_sys_path():
    """`sage/manifest.py` reaches its five organons only through the bundle path — `import canon`,
    `import operators`, and the rest resolve only when `chorus.personas._load_module` has put
    `src/sage/` on `sys.path`, so this proves the load works with that never having happened.

    `operators` is in the vacuity guard for a second reason: two files in this workspace are named
    `operators.py`. A bare `import operators` that resolved to `iris/comms/operators.py` would be a
    silent substitution, not an error, so proving the name is unresolvable proves more here than it
    does for the others.

    Fails if any bare-name organon import is reintroduced, and fails on a missing bundle payload
    too: `find_spec(<organon>) is None` is asserted first for all five, in the same interpreter, so
    this cannot pass vacuously.
    """
    r = _run("""
import sys, json, pathlib
for p in list(sys.path):
    assert pathlib.Path(p).name != 'sage', 'the persona dir leaked onto sys.path: %r' % p

# The bare names must be unresolvable here, or everything below proves nothing.
import importlib.util
BARE = ('retrieval', 'corpus', 'docs_ops', 'operators', 'canon',
        'content', 'describe', 'code_index', 'doc_index', 'content_search')
for n in BARE:
    assert importlib.util.find_spec(n) is None, 'a bare %r is importable — test is vacuous' % n

import sage.manifest as m
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
    assert got["groups"] == list(GROUPS), got["groups"]
    assert got["bare_imported"] == [], "an organon was still reached by bare name: %s" % got
    # The count is pinned so a surface change is deliberate. It includes the canon information
    # path — `op.canon.source`, `op.canon.condense`, `op.canon.browse` — and `op.canon.light`,
    # which gives each canon section its ontology position: without a position a section cannot
    # take part in a coupling. Asserted here through the bundle path — persona dir off sys.path —
    # because that is how a host actually loads it.
    assert got["collected"] == len(got["ops"]) == 17, got
    # All five organons contributed — a group silently failing to register would otherwise be green.
    for prefix in ("op.retrieve", "op.corpus.", "op.docs.", "op.describe.", "op.knowledge.cite"):
        assert any(o.startswith(prefix) for o in got["ops"]), (prefix, got["ops"])
    assert set(got["sha"]) == set(GROUPS) and all(len(v) == 64 for v in got["sha"].values())


def test_no_organon_is_imported_by_bare_name_in_sages_manifest():
    """The static half. `crystal`/`prism`/stdlib are installed packages and resolve by ordinary
    absolute import; an organon is a sibling file and only ever resolved by the path trick.

    Fails if `import canon` (or any other sibling) is reintroduced, even if the runtime test above
    were somehow satisfied by a leaked path.
    """
    import ast
    siblings = {p.stem for p in SAGE.glob("*.py")} | {d.name for d in SAGE.iterdir() if d.is_dir()}
    siblings.discard("manifest")
    reached = set()
    for node in ast.walk(ast.parse((SAGE / "manifest.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            reached.add(node.module.split(".")[0])
    leaked = reached & siblings
    assert not leaked, (
        "sage/manifest.py imports sibling module(s) %s by bare name — that resolves only because "
        "`chorus.personas._load_module` puts the persona dir on sys.path. Take them from the bundle "
        "instead (`prism.runner.register_fns`)." % sorted(leaked))


# ── 2 · the operators come from sha-verified bundles ─────────────────────────────────────────────

def test_sage_registrars_are_the_bundles_own_declared_register_fns():
    """The manifest transcribes no function name, and the order of the five groups is preserved.

    Fails if `[retrieval.register_retrieval_operators, …]` is hardcoded back into the manifest:
    that would pass the operator assertion but break the identity check against `prism.runner`'s
    pinned bundles.
    """
    import sage.manifest as m
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


def test_the_two_groups_prism_never_declared_are_sages_and_they_were_the_blocker():
    """`retrieval` and `canon` are not among prism's fixed group names; they are known because
    their payloads exist. Group membership is read from the payloads present, not from a
    hardcoded list.

    Fails if prism reverts to a fixed list of group names.
    """
    from prism import runner

    six = {"arithmetic", "operators", "dev_ops", "docs_ops", "corpus", "fetch"}
    new = {"retrieval", "canon"}
    assert not (new & six)
    assert new <= set(runner.known_groups())
    assert set(runner.known_groups()) == {p.stem for p in BUNDLES.glob("*.json")}, (
        "the group list stopped being a measurement of the payloads present")


def test_the_sage_manifest_surface_is_unchanged_for_the_host():
    """`chorus.personas._persona_manifest` reads `OPERATORS`; `crystal.host` calls `collect`. The
    bundle conversion changed where the manifest's data comes from, not the contract it presents.

    Fails if `collect`/`operators` is dropped: that would strand the host's registration path.
    """
    import sage.manifest as m
    assert callable(m.collect) and callable(m.operators)
    assert m.operators() == m.OPERATORS
    # The count is pinned so a surface change is deliberate. It includes the canon information
    # path — `op.canon.source` (reaches the prose), `op.canon.condense` (prose -> cited
    # artifacts), `op.canon.browse` (the library view behind the `library` facet) — and
    # `op.canon.light`, which gives each canon section its ontology position: without a position a
    # section cannot take part in a coupling.
    assert m.collect() == len(m.OPERATORS) == 17


# ── 3 · seams — reach declared outside a persona's own organon ──────────────────────────────────

def test_sages_own_bundle_DECLARES_the_reach_it_makes_outside_itself():
    """`canon` reaches `content_search`, and the bundle declares it. A reach that is real but
    undeclared is what §8's inversion exists to prevent.

    Fails if `host_seams` is dropped from the canon spec entry: that would make the reach
    invisible in the payload while `canon.py` still performs it, and this test names the gap.
    """
    canon = json.loads((BUNDLES / "canon.json").read_text(encoding="utf-8"))
    assert canon["host_seams"] == ["content_search"], canon["host_seams"]
    assert "content_search" not in canon["modules"], (
        "content_search was carried INTO the canon payload — its closure (answer_shape / offer / "
        "condense / ember.signal) is the reason it is a seam rather than a module")
    assert "content_search" in canon["modules"]["canon"], (
        "the payload no longer reaches the seam it declares — drop the declaration or restore it")


def test_an_UNREGISTERED_content_search_seam_RAISES_and_never_takes_a_sys_path_module():
    """§8's assertion, exercised here on a persona's own organon: a bundle declaring a seam nobody
    registers fails loudly rather than silently reaching for a module it was not given.

    A decoy module named `content_search` is planted in `sys.modules` first. If the loader were
    lax — if an unresolved seam fell through to ordinary absolute-import resolution — the bundle
    would bind the decoy without saying so. Seams resolve under the bundle package name, so
    `sys.path` fall-through is structurally impossible, not merely unobserved.

    Fails if the decoy is reached, and fails if nothing is raised at all.
    """
    r = _run("""
import sys, types, importlib
decoy = types.ModuleType('content_search'); decoy.MARKER = 'DECOY'
sys.modules['content_search'] = decoy              # planted before anything loads

from prism import runner
assert runner.registered_seams() == {}, 'chorus registered a seam: %r' % runner.registered_seams()
info = runner._load_group('canon')
assert 'content_search' in info['bundle']['host_seams'], 'the canon bundle stopped declaring it'

try:
    mod = importlib.import_module(info['pkg'] + '.content_search')
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


def test_a_REGISTERED_content_search_seam_resolves_to_whatever_the_HOST_named():
    """The positive control, and the reason the negative test above is not just "imports fail".

    The host binds the seam name `content_search` to `json` — a module with no relationship to
    searching at all. The bundle asks for a name and gets the host's answer: a bundle declares,
    and never imports.

    Fails if the loader resolved seams itself: that would bind sage's real module, and the
    identity check against `json` would fail.
    """
    r = _run("""
import sys, importlib, json as _json
from prism import runner
runner.register_seam('content_search', 'json')     # the host's answer — deliberately absurd
info = runner._load_group('canon')
mod = importlib.import_module(info['pkg'] + '.content_search')
print('BOUND', mod is _json)
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "BOUND True", r.stdout


# ── 4 · the integrity gate holds for every one of the five ──────────────────────────────────────

def test_a_TAMPERED_bundle_is_REFUSED_for_EVERY_group_sage_rides():
    """Five groups means five places the sha gate has to hold.

    Each tamper is a semantic no-op (two spaces added inside the source text): a change that also
    broke the code would fail for the wrong reason and leave the sha gate untested.

    The rejection is proved to precede the exec. The tampered source has a module-scope side
    effect appended (`sys.modules['SAGE_TAMPER_RAN']`); if the runner hashed after executing — or
    fell back to a known-good copy on mismatch — the marker would be present even though something
    was raised. Absence of the marker is what makes "rejected before exec" an observation.

    Fails, naming the group, if `_verify_sha` is ever softened to a warning: `register_fns` would
    return callables instead of raising.
    """
    import tempfile
    for group, (modname, _src) in GROUPS.items():
        good = json.loads((BUNDLES / f"{group}.json").read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(good))
        text = bad["modules"][modname]
        anchor = "from __future__ import annotations"
        assert anchor in text, (group, "no inert anchor to nudge")
        bad["modules"][modname] = text.replace(anchor, anchor + "  ", 1) + (
            "\nimport sys as _s; _s.modules['SAGE_TAMPER_RAN'] = True\n")
        assert bad["modules"][modname] != good["modules"][modname], (group, "tamper changed nothing")
        assert bad["sha256"] == good["sha256"], (group, "the tamper must leave the CLAIMED sha")

        tmp = tempfile.mkdtemp()
        for g in GROUPS:
            payload = bad if g == group else json.loads(
                (BUNDLES / f"{g}.json").read_text(encoding="utf-8"))
            Path(tmp, f"{g}.json").write_text(json.dumps(payload), encoding="utf-8")
        r = _run("""
import sys
from prism import runner
try:
    runner.register_fns(%r)
except runner.BundleIntegrityError:
    print('REFUSED', 'EXECUTED' if 'SAGE_TAMPER_RAN' in sys.modules else 'NOT_EXECUTED')
else:
    print('ACCEPTED')
""" % group, AGIENCE_BUNDLE_ROOT=tmp)
        assert r.returncode == 0, (group, r.stderr)
        last = r.stdout.strip().splitlines()[-1]
        assert last == "REFUSED NOT_EXECUTED", (
            "group %r: expected refusal BEFORE exec, got %r\n%s" % (group, last, r.stdout))


# ── 5 · the sources of truth have not drifted ────────────────────────────────────────────────────

def test_the_shipped_bundles_still_match_sages_authoritative_sources():
    """The files under `src/sage/` remain the source of truth; the bundles are built from them.

    Fails if e.g. `sage/canon.py` is edited without rebuilding — the intended reminder, since the
    runtime reads only the bundle payloads, never these files directly.
    """
    for group, (modname, path) in GROUPS.items():
        shipped = json.loads((BUNDLES / f"{group}.json").read_text(encoding="utf-8"))
        on_disk = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert shipped["modules"][modname] == on_disk, (
            "%s has drifted from the shipped `%s` bundle — run "
            "`python agience-observe/build_bundles.py %s`" % (path.name, group, group))
