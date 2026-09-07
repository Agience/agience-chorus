"""Chorus and ember are both L3 packages, and the layer model forbids a sideways edge between them
in either direction: this file asserts `chorus → ember` is 0 across non-test source, and asserts the
reverse `ember → chorus` is 0 as well, since inverting one direction into the other is not a cut.

A persona that needs recognition, screened propagation, a signal frame, or per-delegate cognition
reaches for `_host_seams.seam("<name>")` rather than importing the module that performs it; the host
(a runner) binds each name to a concrete module with `prism.runner.register_seam`, which ember calls
in `ember/runtime/seams.py`. The measurement lives in the runner, and the persona names it by name.

`node/` carries a handful of operator scripts that reach `lumen.router` behind a guard
(`try/except ImportError` raising `SystemExit`, or an explicit `sys.path.insert`); those are outside
the ratchet because they are operator tooling, not shipped persona code.

The scan reads the AST rather than grepping, so an aliased import (`import ember.ontology.match as m`)
and a lazy, function-local import are both caught, while the word "ember" in a comment or docstring is
not.

`conftest.py` counts as a test file. It imports ember on purpose: a test process has no runner, so it
stands in as the host and lets ember bind its own seams, the same role a live deployment's runner
plays.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap

SRC = pathlib.Path(__file__).resolve().parents[1]
EMBER = SRC.parents[1] / "agience-ember"

#: chorus counted as its package names — the §2 definition, so the two directions are symmetric.
CHORUS_PKGS = {"aria", "astra", "iris", "lumen", "ophan", "sage", "seraph"}


def _is_test(path: pathlib.Path) -> bool:
    return (any(p in ("tests", "test") for p in path.parts)
            or path.name.startswith("test_")
            or path.name == "conftest.py")


def _imports(path: pathlib.Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                    # pragma: no cover — a broken file is
        return set()                                       # someone else's failure, not this one's
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
    return found


def _sites(path: pathlib.Path, targets: set[str]) -> list[tuple[int, str]]:
    """(line, statement) for every import of `targets`, so the failure names the file and the line."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                    # pragma: no cover
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        roots: set[str] = set()
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            roots = {node.module.split(".")[0]}
        if roots & targets:
            out.append((node.lineno, ast.unparse(node).strip()))
    return out


def _non_test_sources(root: pathlib.Path) -> list[pathlib.Path]:
    return [p for p in sorted(root.rglob("*.py")) if not _is_test(p)]


# ── 1 · the ratchet ─────────────────────────────────────────────────────────────────────────────

def test_no_non_test_chorus_source_imports_ember():
    offenders = []
    for p in _non_test_sources(SRC):
        for line, stmt in _sites(p, {"ember"}):
            offenders.append("%s:%d  %s" % (p.relative_to(SRC).as_posix(), line, stmt))
    assert not offenders, (
        "chorus imports ember again:\n  %s\n\n"
        "ember and chorus are BOTH L3 and §2's layer model forbids the sideways edge. A measurement "
        "the runner performs is DECLARED, not imported: `_host_seams.seam(\"match\")` / "
        "\"activation\" / \"projection\" / \"delegate\", bound by the host in "
        "`ember/runtime/seams.py`. If you need a measurement that has no seam, ADD one there — do "
        "not reach for the module." % "\n  ".join(offenders))


def test_ember_does_not_import_chorus_either():
    """Cutting one direction by inverting it into the other is not a cut, so this asserts
    `ember → chorus` is 0 across `src/` and `scripts/` just as strictly as the reverse. `node/`'s
    handful of `from lumen import router` reaches are operator tooling, each already guarded, and stay
    excluded.

    Fails if a chorus→ember reach gets "solved" by moving the caller into ember, or if a script picks
    up a bare persona import.
    """
    if not EMBER.is_dir():                                 # a chorus-only checkout cannot check this
        import pytest
        pytest.skip("agience-ember is not checked out beside agience-chorus")
    offenders = []
    for root in (EMBER / "src", EMBER / "scripts"):
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            for line, stmt in _sites(p, CHORUS_PKGS):
                offenders.append("%s:%d  %s" % (p.relative_to(EMBER).as_posix(), line, stmt))
    assert not offenders, (
        "ember imports chorus:\n  %s\n\n"
        "The runner reaches a persona over the WIRE or through a sha-verified BUNDLE, never by "
        "import. Half of the L3 cycle was already 0 before D3 — keep it there." % "\n  ".join(offenders))


# ── 2 · the controls — a check that cannot fail proves nothing ──────────────────────────────────

def test_the_scan_can_actually_see_an_import():
    """A scan that silently found no files, or an AST walk that missed `from x import y`, would pass
    the ratchet above forever, so this proves the corpus is non-empty, that a known-true import is
    still detected, and that the detector is not simply saying yes."""
    sources = _non_test_sources(SRC)
    assert len(sources) > 50, f"the scan found only {len(sources)} source files — it is not looking"

    prism_readers = [p for p in sources if "prism" in _imports(p)]
    assert len(prism_readers) >= 20, (
        "fewer than twenty files import prism — the seams resolve through `prism.runner`, so either "
        "the cut regressed or the detector is broken")

    lazy = ast.parse("def f():\n    from ember.ontology import activation\n")
    found = {n.module.split(".")[0] for n in ast.walk(lazy)
             if isinstance(n, ast.ImportFrom) and n.module}
    assert "ember" in found, "the AST walk misses a lazy `from ember.x import y`"

    aliased = ast.parse("import ember.ontology.match as m\n")
    found = {a.name.split(".")[0] for n in ast.walk(aliased)
             if isinstance(n, ast.Import) for a in n.names}
    assert "ember" in found, "the AST walk misses `import ember.x.y as z`"


def test_the_guard_NAMES_the_file_and_line_when_the_edge_returns():
    """Run against a real file: a seeded `from ember.X import …` is written into an actual chorus
    source, the ratchet is re-run, and the failure must name that file and its line, then the file is
    restored. Without this, `test_no_non_test_chorus_source_imports_ember` could be passing because it
    looks at the wrong tree.

    The seed goes into `src/sage/match.py` as a function-local import, the shape a grep-based guard
    would miss.

    Fails if the ratchet stays green with the seed in, or if the failure message omits the file or the
    line.
    """
    victim = SRC / "sage" / "match.py"
    original = victim.read_text(encoding="utf-8")
    seeded = original + textwrap.dedent('''

        def _d3_control_probe():                      # SEEDED BY A TEST — removed in the finally
            from ember.ontology import activation
            return activation
        ''')
    try:
        victim.write_text(seeded, encoding="utf-8")
        sites = _sites(victim, {"ember"})
        assert sites, "the seeded import was not detected at all — the ratchet is blind"
        line, stmt = sites[0]
        assert "activation" in stmt
        # and the ratchet itself must go red, naming both
        try:
            test_no_non_test_chorus_source_imports_ember()
        except AssertionError as e:
            msg = str(e)
        else:                                          # pragma: no cover — this is the failure mode
            raise AssertionError(
                "the ratchet stayed GREEN with `from ember.ontology import activation` seeded into "
                "sage/match.py — it is not measuring what it claims to")
        assert "sage/match.py" in msg, "the failure does not name the file: %s" % msg
        assert ":%d" % line in msg, "the failure does not name the line %d: %s" % (line, msg)
    finally:
        victim.write_text(original, encoding="utf-8")

    # and green again once reverted — so the control cannot leave the ratchet permanently red
    test_no_non_test_chorus_source_imports_ember()


# ── 3 · the seam — an unfilled one raises, and never binds what is lying around ──────────────────

def _run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(body)],
                          capture_output=True, text=True, cwd=str(SRC))


def test_an_UNFILLED_seam_RAISES_and_never_takes_a_module_lying_in_sys_modules():
    """A decoy: modules named `match`, `activation`, `projection`, and `delegate` are planted in
    `sys.modules` first. If `_host_seams` resolved a seam by its own name
    (`importlib.import_module("match")`), every one of them would bind, and a persona would measure
    with a stranger's module while every test in this file stayed green.

    Resolution goes through `prism.runner.registered_seams()` and then imports the host's dotted
    target, so `sys.path` / `sys.modules` fall-through is structurally impossible.

    Runs in a subprocess because `prism.runner._HOST_SEAMS` is process-global and something earlier in
    the suite imports ember, which binds all four; an in-process version would measure test order
    instead of this behavior.

    Fails if a decoy is bound, or if nothing is raised at all.
    """
    r = _run("""
        import sys, types
        for name in ("match", "activation", "projection", "delegate"):
            m = types.ModuleType(name); m.MARKER = "DECOY"
            m.tekton_basis_for = m.spread_seeds = m.frame = m.Delegate = "DECOY"
            sys.modules[name] = m                      # planted BEFORE anything resolves

        from prism import runner
        assert runner.registered_seams() == {}, "something bound a seam: %r" % runner.registered_seams()

        import _host_seams
        for name in ("match", "activation", "projection", "delegate"):
            try:
                mod = _host_seams.resolve(name)
            except _host_seams.HostSeamUnfilled as e:
                assert "unfilled" in str(e)
                print("RAISED", name)
            else:
                print("BOUND", name, getattr(mod, "MARKER", mod.__name__))
        """)
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stdout.strip().splitlines() if l.startswith(("RAISED", "BOUND"))]
    assert len(lines) == 4, r.stdout
    assert all(l.startswith("RAISED") for l in lines), (
        "an unfilled seam did NOT refuse — it resolved to %r" % lines)
    assert "DECOY" not in r.stdout


def test_a_REGISTERED_seam_is_what_the_persona_MEASURES_WITH():
    """The positive control: it is what makes the previous test's raise meaningful rather than a
    module that simply never works. The host binds `activation` to a module of its choosing, not
    ember's, and `lumen.conversation._A` reads that module's attributes.

    The host binds a module written by this test, so the check cannot be satisfied merely by ember
    being importable — the answer must come from the registration.

    Fails if `_A` resolves to anything but the registered module, including ember's real one, which is
    importable in this environment and would otherwise pass a weaker test.
    """
    r = _run("""
        import sys, types
        stand_in = types.ModuleType("a_host_of_my_own")
        stand_in.MARKER = "HOST-CHOSE-THIS"
        sys.modules["a_host_of_my_own"] = stand_in

        from prism import runner
        runner.register_seam("activation", "a_host_of_my_own")   # the HOST's answer

        import _host_seams
        assert _host_seams.filled("activation")
        assert _host_seams.resolve("activation").MARKER == "HOST-CHOSE-THIS"

        seam = _host_seams.seam("activation")
        assert "UNFILLED" not in repr(seam)            # repr must not resolve, and must not lie
        print("MEASURED-WITH", seam.MARKER)
        """)
    assert r.returncode == 0, r.stderr
    assert "MEASURED-WITH HOST-CHOSE-THIS" in r.stdout, r.stdout


def test_declaring_a_seam_imports_NOTHING_until_it_is_used():
    """A seam is not a dependency with better manners: `register_seam` stores a dotted string, and
    `seam(...)` resolves on first attribute access, so importing a persona module must not drag the
    host in.

    The assertion runs before the positive half: `sage.match` is imported with ember absent from
    `sys.modules` and must still import cleanly, then measuring must reach for the host. Reversed, the
    test would pass on a module that imported ember eagerly.

    Fails if importing `sage.match` pulls ember in, or if the seam then fails to resolve, which would
    make the first half vacuous.
    """
    r = _run("""
        import sys
        import sage.match as M
        print("EMBER-AFTER-IMPORT", "ember" in sys.modules)

        import _host_seams
        from prism import runner
        import types
        m = types.ModuleType("probe_match"); m.MARKER = "PROBE"
        sys.modules["probe_match"] = m
        runner.register_seam("match", "probe_match")
        print("RESOLVES", M._EM.MARKER)
        """)
    assert r.returncode == 0, r.stderr
    assert "EMBER-AFTER-IMPORT False" in r.stdout, (
        "importing `sage.match` imported ember — the seam is not lazy:\n%s" % r.stdout)
    assert "RESOLVES PROBE" in r.stdout, r.stdout


def test_on_a_runner_the_seam_resolves_to_the_EXACT_module_the_import_named():
    """A behavior-preservation proof, and an identity rather than an assertion about outputs: on a
    host that is a runner, each seam resolves to the very module object a direct import would have
    bound, so a persona measures with the same object, not a look-alike. Comparing behavior
    test-by-test could miss a near-identical stand-in; `is` cannot.

    This test imports ember, which a test file may do and a shipped persona module may not — the cut
    is about who names the module, not whether the module is reachable in this environment.

    Fails if a seam is bound to a look-alike, a re-export shim, or a renamed module, any of which would
    keep the suite green while changing what a persona measures with.
    """
    import ember  # noqa: F401  — the host, binding its own seams
    import ember.ontology.activation
    import ember.ontology.match
    import ember.runtime.delegate
    import ember.signal.projection

    sys.path.insert(0, str(SRC)) if str(SRC) not in sys.path else None
    import _host_seams

    assert _host_seams.resolve("match") is ember.ontology.match
    assert _host_seams.resolve("activation") is ember.ontology.activation
    assert _host_seams.resolve("projection") is ember.signal.projection
    assert _host_seams.resolve("delegate") is ember.runtime.delegate

    # …and the persona modules hold those same objects behind their lazy handles.
    from sage import match as sage_match
    from lumen import conversation as lumen_conversation
    assert sage_match._EM.propagate is ember.ontology.match.propagate
    assert lumen_conversation._A.recognize is ember.ontology.activation.recognize


def test_the_seams_chorus_declares_are_named_exactly():
    """The declaration inventory, pinned: the edge of what a persona cannot do alone. Chorus binds
    none of these seams itself — `test_persona_bundle_conversion_status.py` asserts that statically (no
    `register_seam` in shipped chorus code) — so this test is the other half, recording which names
    chorus asks for.

    Fails if a seam reach is added without being recorded here, and fails if one is deleted while its
    entry remains."""
    declared: dict[str, set[str]] = {}
    unreadable: list[str] = []
    for p in _non_test_sources(SRC):
        try:
            # `utf-8-sig`: some files in this workspace carry a UTF-8 BOM (origin and mantle, not
            # chorus) — a scan that cannot read one would otherwise report it as clean.
            tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            # This gate asserts an exact set of declared seams, so a file the scan cannot read
            # contributes no names and is indistinguishable from one that declares none: the assertion
            # below would then pass on a scan that never saw it. The skip is recorded and asserted
            # rather than silently continued past, the same shape `_parse_failures` in
            # `test_persona_isolation.py` closes.
            unreadable.append("%s (%s)" % (p.relative_to(SRC).as_posix(), type(exc).__name__))
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("_seam", "_resolve_seam", "seam", "resolve")
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                declared.setdefault(node.args[0].value, set()).add(p.relative_to(SRC).as_posix())

    # Coverage before the verdict: an exact-set assertion cannot be supported by a scan that skipped
    # files, so the unreadable list is asserted first — otherwise "these are exactly the seams chorus
    # declares" would describe fewer files than it read.
    assert not unreadable, (
        "these chorus sources could not be parsed and were therefore NOT scanned for seam "
        "declarations: %s. The exact-set assertion below would have covered fewer files than it "
        "claims." % unreadable)
    assert {k: sorted(v) for k, v in sorted(declared.items())} == {
        # `sage/match.py` DROPPED its `activation` declaration when operator selection moved off
        # seed→spread and onto `op.ground` (= `match.fired_field`). It reaches exactly one seam now,
        # `match`, which is why it appears below and not here. `spread_seeds` climbs the hypernym
        # lineage and returns the ancestor chain — a need grounded to `entity` is equidistant from
        # every offer in the table, so it ranked them by nothing.
        "activation": ["lumen/conversation.py"],
        "delegate":   ["lumen/conversation.py", "reach_host.py"],
        # The reader's working memory. The roster is path-keyed, so it fails when a module moves
        # without its entry being updated to match.
        "forgetting": ["astra/reading/organon_reader.py"],
        # The query-local reader reaches `principal_directions` and `next_by_coupling`, both the
        # instrument's, both by name.
        # `heldout.py` declares `optics` because it fits the ordered-stream operator it measures — the
        # completion oracle.
        # `read_basis.py` is astra's side of the read corpus's own coordinate, the one that makes the
        # reading resolve (one-hot: contrast 0.4671, 0 modes; contexts x sqrt(bits): contrast 9.5719,
        # 22 modes, same collection).
        # The six readers under `astra/reading/` reach the instrument for the one measurement that
        # decides what a unit is: `self_information_bits` (`compact`, `read_once`, `read_stream`) and
        # `position_coherence` (`resegment`). Each is a number the instrument publishes, so none of
        # them may be restated in a persona — which is the whole reason these are seams.
        # `complete.py` reaches `sequence_operator`, `absorb_transmit`, `screen_normalize`,
        # `principal_directions`, `propagate_residual` and `next_by_coupling`: the completion walk is
        # instrument arithmetic end to end, and the only thing chorus owns in it is the order.
        # `reading_junction.py` sits at `src/`, owned by no persona — see its header. Placement is
        # what both sides of the reading need, so a path-keyed roster is exactly what catches the
        # move: this entry read `lumen/reading/junction.py` while it lived there.
        "optics":     ["astra/reading/compact.py", "astra/reading/organon_reader.py",
                       "astra/reading/read_basis.py", "astra/reading/read_once.py",
                       "astra/reading/read_stream.py", "astra/reading/resegment.py",
                       "lumen/reading/complete.py", "lumen/reading/heldout.py",
                       "lumen/reading/operator_predict.py", "lumen/reading/operator_respond.py",
                       "lumen/reading/query_neighbourhood.py", "reading_junction.py"],
        # The cloud/basis construction is the host's: astra and lumen both need the same measurement,
        # so it lives in `ember/signal/projection.py` beside `build_basis`, and both personas reach it
        # by name rather than importing each other.
        # `query_neighbourhood.py` reaches `read_cloud` and `reading_junction.py` reaches
        # `read_unit_contexts` — the same construction, asked for the question rather than the corpus.
        "projection": ["astra/reading/read_basis.py", "lumen/reading/heldout.py",
                       "lumen/reading/query_neighbourhood.py", "reading_junction.py",
                       "sage/content_search.py"],
        "match":      ["lumen/reach_provider.py", "sage/content_search.py",
                       "sage/match.py", "sage/reach_provider.py"],
        # ── what the browse FACET reads off the running engine ──────────────────────────────
        #
        # `aria/facets/browse.py` moved here from `ember/facets/`. Facets are chorus's and the
        # engine is ember's, so a facet that renders what a node holds reaches the engine
        # through seams — which is what these four are. Inside the engine it imported
        # `ember.genesis`, `ember.runtime.improve`, `ember.surface.stats` and
        # `ember.runtime.pool` outright; that is the freedom living in the wrong repository
        # buys, and the reason the move is a rewrite rather than a copy.
        "genesis":    ["aria/facets/browse.py"],
        "improve":    ["aria/facets/browse.py"],
        "pool":       ["aria/facets/browse.py"],
        "stats":      ["aria/facets/browse.py"],
    }, {k: sorted(v) for k, v in sorted(declared.items())}

    # the positive control: the scan would find a declaration. Without it the dict above could be
    # empty because the AST walk is broken rather than because nothing declares.
    probe = ast.parse("_seam('probe')\n")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_seam"
               for n in ast.walk(probe)), "the declaration scan cannot detect a declaration"
