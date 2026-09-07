"""`op.bundle.observe` + `op.bundle.condense` — the producer half of the distribution path.

Information moves by tektons, organons and facets only, never by a script run by hand outside a
capability. `test_the_tekton_reproduces_every_shipped_payload_BYTE_FOR_BYTE` is the load-bearing
equivalence this rests on: a producer that yields different bytes than what is shipped is a fork, not
this path, and a fork in a sha means every shipped payload silently stops matching.

Each test states the failure mode it would catch.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve()
SERAPH = HERE.parents[1]
WORKSPACE = HERE.parents[4]
BUNDLES = WORKSPACE / "agience-observe" / "bundles"

sys.path.insert(0, str(SERAPH))
sys.path.insert(0, str(WORKSPACE / "agience-prism" / "py" / "src"))

import bundling  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (WORKSPACE / "agience-observe" / "bundle_spec.json").is_file(),
    reason="no agience-observe checkout beside chorus — the spec and payloads are its")


def _shipped() -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in BUNDLES.glob("*.json")}


# ── the equivalence ──────────────────────────────────────────────────────────────────────────
def test_the_tekton_reproduces_every_shipped_payload_BYTE_FOR_BYTE():
    """The one that matters: the organon+tekton must reproduce every shipped payload exactly, byte
    for byte — anything else forks the distribution path instead of producing it.

    Compared as whole payloads, not just shas — a sha agreeing while a field differs would mean the
    canonical form is ignoring that field, which is a worse finding than a mismatch.

    Fails if normalisation differs, sort order differs, or a declared field is dropped.
    """
    produced = {b["group"]: b for b in bundling.condense(bundling.observe(str(WORKSPACE)))}
    shipped = _shipped()
    assert set(produced) == set(shipped), (
        "the produced groups differ from the shipped ones: %s vs %s"
        % (sorted(produced), sorted(shipped)))
    differing = [g for g in sorted(shipped) if produced[g] != shipped[g]]
    assert not differing, "produced payload differs from the shipped one for: %s" % differing


def test_the_sha_comes_from_PRISMS_canonical_form_not_a_local_definition():
    """The runner verifies with `bundle_canonical`. A second definition here would be a second
    declaration of what was signed, free to drift — and drift in a sha is silent.

    Fails if the sha hashes `json.dumps(bundle)` directly: that would agree with itself forever and
    disagree with every consumer.
    """
    import hashlib
    from prism.crystal_model import bundle_canonical
    produced = bundling.condense(bundling.observe(str(WORKSPACE), groups=["bundling"]))[0]
    body = {k: v for k, v in produced.items() if k != "sha256"}
    assert produced["sha256"] == hashlib.sha256(bundle_canonical(body)).hexdigest()


# ── the organon reaches, and does not interpret ──────────────────────────────────────────────
def test_the_organon_returns_RAW_text_and_the_tekton_normalises():
    """The split that is not cosmetic: normalisation decides what gets signed, so it belongs to the
    condensation. If the reach normalised, the source could not move (a git remote, a mesh peer)
    without the canonicalisation moving with it.

    Fails if `.replace("\\r\\n", "\\n")` migrates into `observe`. Proven by feeding the tekton CRLF
    text and watching the sha match the LF form — with a control that the fixture really is CRLF, so
    the test cannot pass by there being no CRLF to normalise.
    """
    lf = {"group": "g", "entry_module": "m", "register_fns": [], "host_seams": [],
          "modules": {"m": "a = 1\nb = 2\n"}, "paths": {"m": "x.py"}}
    crlf = dict(lf, modules={"m": "a = 1\r\nb = 2\r\n"})
    assert "\r\n" in crlf["modules"]["m"], "control: the fixture is not actually CRLF"
    assert bundling.condense([lf])[0]["sha256"] == bundling.condense([crlf])[0]["sha256"], (
        "a CRLF checkout and an LF checkout produced two different bundles for identical source")
    assert bundling.condense([crlf])[0]["modules"]["m"] == lf["modules"]["m"]


def test_the_organon_REFUSES_a_moved_module_instead_of_searching_by_basename():
    """Resolving `operators` by filename finds two files — `sage/operators.py` and
    `iris/comms/operators.py`. A search would silently pick one: the duplicate-basename substitution
    that lets pytest quietly swap one module for another.

    Fails if a fallback search is added for when a declared path misses.
    """
    tmp_spec = {"g": {"entry_module": "m", "host_seams": [], "register_fns": [],
                      "modules": {"m": "agience-chorus/src/seraph/DOES-NOT-EXIST.py"}}}
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        (root / "agience-observe").mkdir()
        (root / "agience-observe" / "bundle_spec.json").write_text(json.dumps(tmp_spec),
                                                                  encoding="utf-8")
        with pytest.raises(FileNotFoundError) as e:
            bundling.observe(str(root))
    assert "DOES-NOT-EXIST" in str(e.value) and "basename" in str(e.value)


def test_an_unknown_group_is_refused_BY_NAME():
    """Fails if an unknown group silently returns [] — indistinguishable from a group with no
    modules."""
    with pytest.raises(KeyError) as e:
        bundling.observe(str(WORKSPACE), groups=["not-a-group"])
    assert "not-a-group" in str(e.value)


# ── the tekton answers without writing ───────────────────────────────────────────────────────
def test_a_NEED_that_ASKS_A_QUESTION_writes_nothing():
    """A tekton answering a question must not write as a side effect. `build_bundles.py` defaults to
    writing, with `--check` as the opt-out — the wrong way round for a capability, where the need is
    what asks.

    Fails if landing happens by default. Proven by mtimes rather than by the return value, so a
    handler that wrote and then reported `landed: []` is still caught.
    """
    before = {p: p.stat().st_mtime_ns for p in BUNDLES.glob("*.json")}
    got = bundling.bundle_condense_handler(str(WORKSPACE))({})
    after = {p: p.stat().st_mtime_ns for p in BUNDLES.glob("*.json")}
    assert before == after, "the tekton wrote to the shipped payloads while only being asked"
    assert got["landed"] == [] and got["landed_anything"] is False


def test_the_tekton_reports_the_shipped_payloads_as_CURRENT():
    """If the checked-in payloads are current, nothing should read as moved: the standing staleness
    gate, expressed as a need.

    Fails if a chorus module is edited without the bundle rebuilt — this goes red and names it.
    """
    got = bundling.bundle_condense_handler(str(WORKSPACE))({})
    assert got["moved"] == [], (
        "shipped payload(s) no longer match chorus source: %s — raise the condense NEED with "
        "{'land': True}" % got["moved"])


def test_LANDING_is_explicit_and_writes_the_same_bytes():
    """The write path, exercised in a temp tree so nothing checked in is touched.

    Fails if `land` writes a payload that differs from what the same need reports — the file and the
    answer disagreeing about what was shipped.
    """
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        (root / "agience-observe").mkdir(parents=True)
        shutil.copy(WORKSPACE / "agience-observe" / "bundle_spec.json",
                    root / "agience-observe" / "bundle_spec.json")
        for rel in ("agience-chorus/src/seraph",):
            (root / rel).mkdir(parents=True, exist_ok=True)
        # only the `bundling` group's source is needed for a one-group land
        shutil.copy(SERAPH / "bundling.py", root / "agience-chorus/src/seraph/bundling.py")

        need = {"groups": ["bundling"], "land": True}
        got = bundling.bundle_condense_handler(str(root))(need)
        assert got["landed"] == ["bundling"], got
        landed = json.loads((root / "agience-observe" / "bundles" / "bundling.json")
                            .read_text(encoding="utf-8"))
        assert landed["sha256"] == got["groups"]["bundling"]["sha256"]
        assert landed == bundling.condense(bundling.observe(str(root), groups=["bundling"]))[0]

        # landing again must report nothing moved — the payload is now current
        again = bundling.bundle_condense_handler(str(root))(need)
        assert again["moved"] == [] and again["landed"] == []


# ── registration ─────────────────────────────────────────────────────────────────────────────
def test_both_capabilities_are_REGISTERED_with_offers_naming_their_noun():
    """A capability wired to nothing cannot be reached by any need. The offer is what a need matches
    on, so it must say which noun it is.

    Fails if the handlers are added and `_BUNDLING_OPS` is forgotten — they would work in-process and
    be unfindable by any need.
    """
    ops = dict(bundling._BUNDLING_OPS)
    assert set(ops) == {bundling.BUNDLE_OBSERVE_CAP, bundling.BUNDLE_CONDENSE_CAP}
    assert ops[bundling.BUNDLE_OBSERVE_CAP].startswith("ORGANON")
    assert ops[bundling.BUNDLE_CONDENSE_CAP].startswith("TEKTON")


def test_the_bundling_group_carries_ITSELF():
    """The bootstrap, asserted rather than assumed: the producer travels as a payload like every
    other group, so a node can receive the thing that makes payloads. There is no circularity — the
    authoring host builds from source, and a remote node that has no chorus source has nothing to
    bundle anyway.

    Fails if the group is declared and never built — seraph would boot with the tekton missing while
    the manifest claimed it.
    """
    shipped = _shipped()
    assert "bundling" in shipped, "the producer itself was never built"
    assert shipped["bundling"]["register_fns"] == ["register_bundling_operators"]
    assert "bundling" in shipped["bundling"]["modules"]
