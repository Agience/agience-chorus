"""The conversion ledger — which personas travel as bundles, and what each one rides.

A third-party tekton and a Foundation tekton travel the same path (`ARCHITECTURE-TARGET` §8): a
bundle declares `{host_seams, modules, sha256}`, the host binds the seams, and the payload is
sha-verified and exec'd. Every persona that owns a manifest travels as a bundle — astra, seraph,
lumen, sage, iris, aria — and ophan owns no manifest because it registers no operator, which this
file measures rather than assumes.

`prism.runner._BundleFinder` serves a bundle root as a package, so a one-level relative import
resolves inside the payload by construction; what a flat payload cannot carry is a sub-package, and
none of the shipped groups have one. A bundle module is exec'd from text with no location, so a
module that reads `Path(__file__)` at module scope cannot travel as one without a rewrite; aria's
`web_bff.py` needed one, and its own bundle test covers that case directly.

What this file asserts: no `manifest.py` in this repo reaches a sibling organon by bare name, every
shipped bundle group is claimed by exactly one persona, and the group list is a measurement of the
payloads present rather than a literal.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]
BUNDLES = SRC.parent / "bundles"          # this repository's own; chorus builds them

PERSONAS = ("aria", "astra", "iris", "lumen", "ophan", "sage", "seraph")

#: The personas that travel as bundles today, and the groups each rides — pinned so that adding or
#: removing a group shows up here as a diff instead of as a surprise. ophan is absent on purpose;
#: `test_ophan_has_nothing_to_bundle_and_that_is_MEASURED` keeps that assumption honest.
CONVERTED = {
    # aria's second group is `identity`: `op.identity.verify` is the organon the `login` facet asks
    # — the only reach chorus has to origin, and it never mints. The facet's organon lives with the
    # facet it serves rather than splitting one login flow across two personas. See `aria/identity.py`.
    "aria":   ("web_bff", "identity"),
    "astra":  ("fetch",),
    "iris":   ("comms",),
    "lumen":  ("reasoning", "arithmetic", "check", "curriculum", "dev_ops"),
    "sage":   ("retrieval", "corpus", "docs_ops", "operators", "canon"),
    # seraph carries the producer half: `bundling` carries `op.bundle.observe` and
    # `op.bundle.condense`. Its independent oracle lives outside chorus, in agience-cloud.
    "seraph": ("install", "bundling"),
}


def _shipped_groups() -> dict:
    if not BUNDLES.is_dir():
        pytest.skip("no agience-observe checkout beside this repo — the shipped payloads are its")
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in BUNDLES.glob("*.json")}


def _bare_name_reaches(persona: str) -> list[str]:
    """The sibling modules `<persona>/manifest.py` imports by bare name — i.e. the reaches that
    resolve only because `chorus.personas._load_module` puts the persona dir on `sys.path`.

    A directory counts as a sibling, not only a `.py` file: `iris/comms` is a package, and a check
    that considered files alone would call iris clean while it still imported `from comms import …`.
    """
    pdir = SRC / persona
    mpath = pdir / "manifest.py"
    if not mpath.is_file():
        return []
    siblings = {f.stem for f in pdir.glob("*.py")} | {d.name for d in pdir.iterdir() if d.is_dir()}
    siblings.discard("manifest")
    reached = set()
    for node in ast.walk(ast.parse(mpath.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            reached |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            reached.add(node.module.split(".")[0])
    return sorted(reached & siblings)


def _declared_groups(persona: str) -> tuple:
    """The groups `<persona>/manifest.py` names — read from the source, so a persona that stopped
    loading (a missing payload, an import error) is still measured rather than skipped."""
    mpath = SRC / persona / "manifest.py"
    if not mpath.is_file():
        return ()
    tree = ast.parse(mpath.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "BUNDLE_GROUP" in names and isinstance(node.value, ast.Constant):
            return (node.value.value,)
        if "BUNDLE_GROUPS" in names and isinstance(node.value, ast.Tuple):
            return tuple(e.value for e in node.value.elts if isinstance(e, ast.Constant))
    return ()


# ── the invariant the excuses existed to reach ───────────────────────────────────────────────────

def test_NO_persona_manifest_reaches_an_organon_by_bare_name():
    """`crystal`/`prism`/stdlib are installed packages and resolve by ordinary absolute import; an
    organon is a sibling file or directory and only resolves because `chorus.personas._load_module`
    inserts the persona dir into `sys.path`. No manifest may do that.

    Fails if a bare-name organon import appears in any manifest, and names the persona and the
    module — even if that persona's own bundle test is deleted, and even for a persona this file has
    never heard of.
    """
    offenders = {p: _bare_name_reaches(p) for p in PERSONAS if _bare_name_reaches(p)}
    assert offenders == {}, (
        "these manifests are back on the sys.path trick: %s. Take the organons from their bundle "
        "instead (`prism.runner.register_fns`)." % offenders)


def test_every_persona_that_owns_a_manifest_declares_the_groups_it_rides():
    """A manifest with no `BUNDLE_GROUP`/`BUNDLE_GROUPS` is either not converted or reaching its
    organons some third way. Both are findings.

    Fails if a persona is added with a manifest but no group declaration.
    """
    with_manifest = [p for p in PERSONAS if (SRC / p / "manifest.py").is_file()]
    assert set(with_manifest) == set(CONVERTED), (
        "the set of personas owning a manifest changed: %s" % sorted(with_manifest))
    declared = {p: _declared_groups(p) for p in with_manifest}
    assert declared == CONVERTED, declared


def test_every_declared_group_has_a_SHIPPED_PAYLOAD_and_every_payload_is_CLAIMED():
    """Checks both directions: a declared group with no payload is a persona that boots to an empty
    roster; a payload no persona claims is a group that can go stale unseen.

    Fails if renaming a group in `bundle_spec.json` without updating the manifest breaks the first
    half, or a group is built that nothing rides — and names it.
    """
    shipped = set(_shipped_groups())
    claimed = {g for groups in CONVERTED.values() for g in groups}

    missing = sorted(claimed - shipped)
    assert not missing, (
        "declared by a manifest but no payload was built: %s — run "
        "`python agience-observe/build_bundles.py`" % missing)
    orphaned = sorted(shipped - claimed)
    assert not orphaned, (
        "shipped payload(s) no persona rides: %s. Either a manifest stopped declaring one, or a "
        "group was built and never wired — an unclaimed payload is exactly what goes stale unseen."
        % orphaned)


def test_a_group_is_carried_by_EXACTLY_ONE_persona():
    """Two personas riding one group would mean one persona registering another's operators, and the
    duplicate would be invisible in `OPERATORS` because both would simply work.

    Fails if a `BUNDLE_GROUP` line is copied between manifests.
    """
    seen: dict = {}
    for persona, groups in CONVERTED.items():
        for g in groups:
            assert g not in seen, "group %r is ridden by both %s and %s" % (g, seen[g], persona)
            seen[g] = persona


# ── ophan: absence, derived rather than assumed ──────────────────────────────────────────────────

def test_ophan_has_nothing_to_bundle_and_that_is_MEASURED():
    """ophan owns no manifest, which is only a valid absence if ophan registers no operator — read
    off the tree rather than inferred from the missing file. Every organon in this repo registers
    through a `register_*_operators(store)` that upserts artifacts of `OPERATOR_CONTENT_TYPE`; ophan
    has none. Its surfaces are MCP tools on its own server, a persona's HTTP surface rather than an
    operator artifact anything can discover by need→offer match.

    `op.pay.session` is named in `ophan/server.py` and does not exist yet: the three Stripe write
    tools raise and point at it, since an outbound write must go through an organon declaring
    `net.request`. ophan's empty operator surface is a designed absence, with `op.pay.session` named
    as its successor.

    Fails, the day `op.pay.session` is built, once ophan gains a registrar — the fix is to give ophan
    a manifest and a bundle group.
    """
    ophan = SRC / "ophan"
    assert not (ophan / "manifest.py").is_file(), (
        "ophan grew a manifest.py — convert it onto `prism.runner.register_fns` and add it to "
        "CONVERTED, do not leave it on the sys.path trick")

    registrars, content_type_sites, unreadable = [], [], []
    for f in sorted(ophan.rglob("*.py")):
        if "tests" in f.parts or "scripts" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            # An unreadable file contributes no registrars and is indistinguishable from one that
            # has none, so it counts as evidence the claim is unsupported rather than as neutral.
            unreadable.append("%s (%s)" % (f.name, type(exc).__name__))
            continue
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("register_") and node.name.endswith("operators")):
                registrars.append("%s:%s" % (f.relative_to(SRC), node.name))
            if isinstance(node, ast.Name) and node.id == "OPERATOR_CONTENT_TYPE":
                content_type_sites.append(str(f.relative_to(SRC)))

    # Coverage before the verdict: an empty result from a partial scan is not a finding.
    assert not unreadable, (
        "these ophan sources could not be parsed and were therefore NOT scanned: %s. \"ophan "
        "registers nothing\" cannot rest on files the scan never read." % unreadable)
    assert registrars == [], (
        "ophan now registers operators (%s) — it owns organons and needs a manifest + a bundle "
        "group like every other persona" % registrars)
    assert content_type_sites == [], (
        "ophan now writes OPERATOR_CONTENT_TYPE artifacts (%s) — same finding" % content_type_sites)

    # The positive control: this scan would find a registrar. Without it, "ophan has none" could be
    # the scan being broken rather than ophan being empty.
    sage_hits = [n.name for n in ast.walk(ast.parse((SRC / "sage" / "canon.py").read_text("utf-8")))
                 if isinstance(n, ast.FunctionDef)
                 and n.name.startswith("register_") and n.name.endswith("operators")]
    assert sage_hits == ["register_canon_operators"], (
        "the registrar scan finds nothing even in a file that HAS one — the ophan result above is "
        "vacuous: %s" % sage_hits)


# ── the mechanism the conversions rest on ────────────────────────────────────────────────────────

def test_the_blocker_is_GONE_a_group_exists_when_its_payload_does():
    """The group list is a measurement of the payloads present in `agience-chorus/bundles/`, not a
    fixed literal — adding a group is a build, not a `prism` edit.

    Fails if `GROUPS` is hardcoded again: a group built outside a fixed list would stop being
    loadable.
    """
    from prism import runner

    old_six = {"arithmetic", "operators", "dev_ops", "docs_ops", "corpus", "fetch"}
    assert runner.GROUPS == runner.known_groups(), "GROUPS is not the measurement"
    assert set(runner.known_groups()) == set(_shipped_groups()), (
        "the group list stopped tracking the payloads in agience-chorus/bundles/")
    built_from_outside = set(runner.known_groups()) - old_six
    assert built_from_outside >= {"install", "web_bff", "comms", "canon", "retrieval",
                                  "check", "curriculum", "reasoning"}, sorted(built_from_outside)
    assert callable(runner.register_group), "the host's own door to a group is gone"


def test_EXTENSIBLE_did_not_become_ANYTHING_GOES():
    """Discovery must not turn an unknown group into a quiet success: a name nothing carries still
    raises, before any import is attempted, in the same exception family every caller already
    handles. `op_pay_session` is ophan's named, unbuilt organon — a group somebody has a reason to
    want and nobody has made yet.

    Fails if `_load_group` ever resolved an unbacked name to an empty namespace, or fell through to
    ordinary `sys.path` resolution: every conversion above would silently stop being a bundle load at
    all.
    """
    from prism import runner

    assert "op_pay_session" not in _shipped_groups(), "pick a group name that is still unbuilt"
    with pytest.raises(runner.UnknownBundleGroupError) as e:
        runner._load_group("op_pay_session")
    assert isinstance(e.value, runner.BundleIntegrityError)
    assert "op_pay_session" in str(e.value)


def test_the_declared_host_seams_are_named_exactly():
    """The seam inventory, pinned. A seam is a reach a payload cannot carry, so the set of them is the
    honest edge of what travels — a reviewer reads this rather than re-deriving it.

    Chorus's own code fills none of them: `sage/canon` falls through to its in-repo leg,
    `sage/operators` reports `basis="generic"`, and `aria/web_bff` loads the file beside itself. Each
    is the mechanism being honest about an unbound name, and each is asserted in that persona's own
    bundle test, in a subprocess.

    This test checks statically instead — chorus's source contains no `register_seam` call outside
    the tests that deliberately exercise one — rather than by an in-process call to
    `runner.registered_seams()`, because `_HOST_SEAMS` is process-global: an in-process check here
    would measure test order (whether an earlier test already imported `ember`, which binds `match`
    at import in `ember/runtime/runner.py`) rather than chorus's own source.

    Fails if a seam is added to a spec entry without being wired or documented here, or if a
    `register_seam` call appears in chorus's shipped code — and names the file.
    """
    seams = {g: tuple(b.get("host_seams", ())) for g, b in _shipped_groups().items()}
    declared = {g: s for g, s in seams.items() if s}
    assert declared == {
        "operators": ("match",),                 # sage's geometric operator-selection tekton
        "canon": ("content_search",),            # sage's BM25 tekton — closure too big to carry
        "web_bff": ("bff_main",),                # the facet's app — a file in the persona dir
    }, declared

    binders, unreadable = [], []
    for f in sorted(SRC.rglob("*.py")):
        if "tests" in f.parts:
            continue                             # the decoy/positive-control tests bind on purpose
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            # This asserts that nothing in chorus binds a seam — a claim a skipped file cannot
            # support, since an unreadable module binds nothing as far as the scan can tell.
            unreadable.append("%s (%s)" % (f.relative_to(SRC).as_posix(), type(exc).__name__))
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "register_seam"):
                binders.append(str(f.relative_to(SRC)))
    # Coverage before the verdict, for the same reason as the ophan scan above.
    assert not unreadable, (
        "these chorus sources could not be parsed and were therefore NOT scanned for seam "
        "binding: %s. An empty binder list cannot rest on files the scan never read." % unreadable)
    assert binders == [], (
        "chorus's shipped code binds a host seam (%s). Which module fills a seam is the HOST's "
        "answer, and chorus is the publisher of the bundles, not their host — ember binds `match` in "
        "`ember/runtime/runner.py`, which is where that belongs." % sorted(set(binders)))

    # The positive control: the scan would find a `register_seam` call. Without it, the empty result
    # above could be the AST walk being broken rather than chorus being clean.
    probe = ast.parse("import x\nx.runner.register_seam('a', 'b')\n")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "register_seam" for n in ast.walk(probe)), (
        "the register_seam scan cannot detect a register_seam call — the result above is vacuous")
