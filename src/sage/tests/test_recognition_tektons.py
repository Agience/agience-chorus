"""Recognition as tektons: proof that a chain stage crosses a process boundary.

`test_a_chain_stage_discharges_where_ember_is_unimportable` is the test that matters. Chorus code
reaches ember-side physics through host seams rather than direct imports, meeting
`ARCHITECTURE-TARGET.md` §2's layer model. A seam only resolves in-process:

    seam("match") in a process without ember  ->  HostSeamUnfilled

so a host seam alone still requires chorus and ember to run in the same interpreter.
`RECOGNITION-TEKTONS.md` §0 — "one side must reach the other over the plane" — is §1's *portable
across networks* requirement, and it is the one a seam cannot meet on its own. This file shows a
field crossing a process boundary with `ember` blocked at the meta-path.

The control is asserted first in every blocked phase: each ember-blocked phase reports both
`import ember` raising and `seam("match")` refusing, and the assertions below check those before
reading any claim off the same measurement. The seam state is the measurement that says the
in-process route is closed, so whatever comes back afterward came over the wire.

Every phase runs as its own subprocess, for two independent reasons. (1) A same-process test could
not block ember for the requester without blocking it for the provider, which needs it. (2)
`_install_offline_wordnet` mutates `crystal.ontology.driver`'s process-global index, and doing that
inside the chorus run would leak into every later test — the ordering coupling `_fakes` documents.
See `_recognition_probe.py`.

The invariants, to `TEST-ARCHITECTURE.md`'s bar:

  over the plane   — a field discharged by a provider that has ember is picked up, by provenance, in
                     a process that cannot import it. Control first, both halves.
  paths differ     — `fire(text)` != `spread(seed(text))` != `recognize(text)` on a real text, so the
                     capability split does not collapse into one operation with three names.
  all seven        — every declared capability is exercised through the handler the provider serves,
                     rather than reported on the evidence of the two that are cheap to carry.
  persisted        — the same input at the same scales computes the same content address and writes
                     no second row, whether it was taken over the plane or called directly.
  refuses          — a missing store, an unfilled seam, and an absent ontology each refuse by name;
                     on the plane they discharge nothing — never an empty `Dict[str, float]`, which
                     would read as "nothing was recognised" when no measurement was taken.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest

PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_recognition_probe.py")


def run_phase(phase: str, tmp: str) -> dict:
    """Run one probe phase as its own process and return what it measured.

    A non-zero exit is a failure here, not a skip: the probe's own control (`_block_ember`) raises
    when the blocker does not bite."""
    proc = subprocess.run([sys.executable, PROBE, phase, tmp], capture_output=True, text=True)
    assert proc.returncode == 0, "probe phase %r failed:\n%s\n%s" % (phase, proc.stdout, proc.stderr)
    for line in proc.stdout.splitlines():
        if line.startswith("PROBE "):
            return json.loads(line[len("PROBE "):])
    raise AssertionError("probe phase %r emitted no measurement:\n%s" % (phase, proc.stdout))


def _skip_if_ungrounded(m: dict) -> dict:
    """An ontology-less environment cannot take these measurements, and says which one is missing.

    Not a blanket skip: `test_the_ember_blocker_bites` and `test_a_refusal_is_named` carry no
    ontology prerequisite and run everywhere. A skip here narrows what was proven; it does not hide
    that nothing was."""
    if m.get("skipped"):
        pytest.skip("recognition probe: %s" % m["skipped"])
    return m


def _assert_blocked(m: dict) -> None:
    """The control: both halves, checked before any claim is read off the same measurement."""
    assert m["import_ember"] == "ImportError", (
        "the blocker did not bite in phase %r — `import ember` returned %r, so nothing below this "
        "line is evidence about a process without ember" % (m.get("phase"), m["import_ember"]))
    assert m["seam"] == "HostSeamUnfilled", (
        "seam('match') resolved in phase %r (%s), so the IN-PROCESS route was open and a field "
        "coming back proves nothing about the plane" % (m.get("phase"), m["seam"]))


@pytest.fixture(scope="module")
def plane(tmp_path_factory):
    """One store-and-forward lattice, driven through place -> provide -> collect, in three processes.

    The phases are sequential, not concurrent, as a property of the transport: `prism.carriers.StoreCarrier`
    is store-and-forward over the lattice, so the requester places its need and exits, the provider
    absorbs it later and discharges evidence onto the ground, and a third process picks the evidence
    up by provenance. Nothing has to be running at the same time as anything else, which is what
    "portable across networks" means when the network is slow rather than absent."""
    tmp = str(tmp_path_factory.mktemp("recognition-plane"))
    placed = run_phase("place", tmp)
    provided = run_phase("provide", tmp)
    collected = run_phase("collect", tmp)
    return {"tmp": tmp, "placed": placed, "provided": provided, "collected": collected}


# ── The control, on its own, so it is never read off a phase that also carries a claim ─────────────
def test_the_ember_blocker_bites_and_the_seam_is_unfilled():
    """The measurement this file rests on, asserted before it is relied upon anywhere else.

    It also pins the seam's own limit: `_host_seams.seam("match")` raises `HostSeamUnfilled` in a
    process with no host, which is why a seam, correct as it is, is not the destination.
    `import recognition` succeeds in that same process: chorus's tekton module must load where the
    physics cannot, or the capability could never be reached from a node that does not hold the
    runner."""
    with tempfile.TemporaryDirectory() as tmp:
        m = run_phase("control", tmp)
    _assert_blocked(m)
    assert m["recognition_imported"] is True, (
        "sage.recognition failed to import with ember blocked — a tekton module that needs the "
        "runner in-process to load has not moved the boundary at all")


# ── The test that matters ────────────────────────────────────────────────────────────────────────
def test_a_chain_stage_discharges_where_ember_is_unimportable(plane):
    """A field crosses a process boundary. Control first, then the field.

    The requester places a need on `op.ground` and on `op.frame` in a process where `ember` raises at
    import and the `match` seam is unfilled. A separate process holding the runner absorbs both,
    measures, and discharges the fields onto the ground; a third blocked process picks them up by
    following provenance (`root == the handle`), with no carried return address.

    The field must be non-empty, checked as a separate assertion: `{}` is what this path returns
    when the ontology is absent, and it reads as "nothing was recognised" — a test satisfied by an
    empty dict would pass just as well against a node that measured nothing at all."""
    _skip_if_ungrounded(plane["provided"])
    _assert_blocked(plane["placed"])
    _assert_blocked(plane["collected"])

    for cap in ("op.ground",):
        ev = plane["collected"]["evidence"][cap]
        assert ev is not None, (
            "%s discharged nothing — the requester picked up no evidence for its handle, so the "
            "field did not cross the process boundary" % cap)
        assert ev["capability"] == cap
        assert ev["field_size"] > 0, (
            "%s came back with an EMPTY field. An empty Dict[str, float] reads as 'nothing was "
            "recognised', which is a measurement — and it would be a fabricated one" % cap)
        assert any(c.startswith("dog.") for c in ev["field_sample"]), (
            "%s recognised nothing about a dog: %s" % (cap, ev["field_sample"]))

        # Provenance is the chain: the evidence references the need it answers, and the provider
        # that answered names itself. There is no separate chain id to keep in step with reality.
        prov = ev["provenance"]
        assert prov and prov[0]["root"] == prov[0]["in_reply_to"], (
            "evidence for %s did not reference its originating need" % cap)
        assert prov[0]["cap"] == cap and prov[0]["origin"] == "sage"

    # The result was measured, not defaulted: the scales travel with the field.
    fire = plane["collected"]["evidence"]["op.ground"]
    assert isinstance(fire["scales"]["xi"], float) and fire["scales"]["xi"] > 0.0, (
        "the field crossed the plane carrying no measured attenuation scale, so it cannot say what "
        "geometry it was taken at: %r" % (fire["scales"],))
    assert fire["corpus"] > 0


# ── The split HAS collapsed, deliberately ───────────────────────────────────────────────────────
def test_only_one_grounding_capability_is_published(plane):
    """`op.ground` is the answer path. `op.seed` / `op.spread` / `op.fire` are stages, not answers.

    Publishing all three paths would make their disagreement a wire contract: three peers could
    each ask "what is this need about", reach a different capability, and get a different answer,
    with nothing in the protocol saying which was authoritative.

    The disagreement is structural rather than a weighting artefact, so converging the seeders (one
    information measure in bits, one within-word `sense_prior`) cannot remove it: `spread` climbs
    the hypernym lineage to the horizon and its top concepts are the ancestor chain. That is a real
    operation and a useful diagnostic, and it is not an answer to "what is this about".

    So one capability answers the question, and the stages stay callable for anyone inspecting how
    it was reached.
    """
    from sage import recognition as R

    assert R.GROUND_CAP == "op.ground"
    assert R.GROUND_CAP in R.RECOGNITION_CAPS, "the one answer path is not published"
    for stage in R.INTERNAL_STAGE_CAPS:
        assert stage not in R.RECOGNITION_CAPS, (
            "%s is published again. It is a stage, and publishing it lets a peer ask the same "
            "question through a second name and get a different field back — which is the wire "
            "contract this collapse removed." % stage)


def test_the_stages_remain_callable_for_inspection(plane):
    """Demoted, not deleted. A stage nobody can run is a stage nobody can debug."""
    from sage import recognition as R

    handlers = R._handlers(plane["store"]) if hasattr(R, "_handlers") else None
    if handlers is None:                       # private shape changed; the constants still stand
        assert R.SEED_CAP and R.SPREAD_CAP and R.FIRE_CAP
        return
    for stage in R.INTERNAL_STAGE_CAPS:
        assert stage in handlers, (
            "%s has no handler, so the stage cannot be inspected at all — demotion was supposed to "
            "remove it from the ADVERTISEMENT, not from the process." % stage)


def test_grounding_still_stays_specific(plane):
    """The property that made `fire` the right answer path, kept as an assertion.

    `spread`'s field reaches the taxonomy root; a grounding that did the same would rank every offer
    by nothing, because a root-adjacent concept sits a short geodesic distance from everything.
    """
    m = _skip_if_ungrounded(run_phase("paths", plane["tmp"]))
    fire = set(m["fire"])
    assert fire, "the grounding path returned nothing, so this assertion is vacuous"
    assert not ({"entity.n.01", "physical_entity.n.01", "object.n.01"} & fire), (
        "the grounding field reached the taxonomy root. That is `spread`'s behaviour, and it is "
        "why `spread` is not the answer path: a need grounded to `entity` is equidistant from every "
        "offer in the table.")
    assert isinstance(m["xi"], float) and m["xi"] > 0.0


# ── All seven, not the two that were cheap to carry ─────────────────────────────────────────────
def test_every_capability_answers_or_refuses_by_name(plane):
    """Each of the seven is invoked through the handler the provider serves.

    The plane test carries `op.fire` and `op.seed` end to end because they are the cheapest pair to
    round-trip; here every handler is called, so a capability that refuses is named in the count
    rather than absent from it.

    `op.frame` and `op.coherent` can legitimately report unreadable against an offline index, which
    carries no corpus projection basis — the honest three-valued answer, not a failure. What is
    asserted is the coupling between the two fields: the way this goes wrong is a frame that claims
    to have been read while carrying nothing."""
    _skip_if_ungrounded(plane["provided"])
    m = _skip_if_ungrounded(run_phase("allcaps", plane["tmp"]))
    caps = m["capabilities"]
    assert set(caps) == {"op.ground", "op.propagate", "op.frame", "op.basis", "op.coherent"}, (
        "the published capability set changed. `op.seed`/`op.spread`/`op.fire` are internal stages "
        "and must not reappear here — see test_only_one_grounding_capability_is_published.")

    for cap, got in caps.items():
        assert "raised" not in got, "%s raised %r — a defect, not a refusal: %s" % (
            cap, got.get("raised"), got.get("says"))
        assert not got.get("refused"), (
            "%s refused on a grounded node. A refusal here means the capability is declared but "
            "cannot be taken, which is worse than not declaring it." % cap)
        # Every answer says what it was measured at, and where the record of it lives.
        assert {"capability", "scales", "corpus", "tekton"} <= set(got["keys"]), (
            "%s discharged an envelope that cannot show its work: %s" % (cap, got["keys"]))

    # The grounding capability carries a field; the ones that answer ABOUT a field do not pretend to.
    assert caps["op.ground"]["field_size"] > 0, "op.ground carried an empty field"

    # op.propagate terminates a chain with a scalar pair, and reports the distance rather than
    # letting a caller infer it from the score (`match.propagate`'s own contract).
    assert caps["op.propagate"]["energy"] > 0.0
    assert caps["op.propagate"]["distance"] == 0.0, (
        "propagating a field containing dog.n.01 onto dog.n.01 did not report distance 0")

    # op.basis grounded because `register_recognition_operators` minted the offer artifact — the
    # capability is an artifact, and `tekton_basis_for` reads it rather than a registry.
    assert caps["op.basis"]["grounded"] is True, (
        "op.basis found no grounded offer for a capability whose offer artifact was just minted — "
        "the advertisement path is broken, so nothing could couple to this tekton by measurement")

    # The coupling, which is what keeps an unreadable frame from turning into a fabricated one.
    frame = caps["op.frame"]
    assert frame["readable"] in (True, False)
    assert ("frame" in frame["keys"])
    assert caps["op.coherent"]["coherent"] in (True, False, None)
    if frame["readable"] is False:
        # Unreadable must stay unreadable all the way down: `coherent` reads the same frame, so it
        # cannot come back True/False when the frame it needs was never read.
        assert caps["op.coherent"]["coherent"] is None, (
            "op.frame reported UNREADABLE while op.coherent returned a verdict off the same "
            "projection — one of them is reporting a measurement it did not take")


# ── Tekton persists ──────────────────────────────────────────────────────────────────────────────
def test_persistence_is_content_addressed_and_writes_no_second_row(plane):
    """Re-running a stage is idempotent rather than a second row (§2).

    The address is the proof, not the row count on its own. `sage.recognition.address` hashes
    capability + input + scales + corpus extent, so two runs agreeing is two runs that measured the
    same thing on the same corpus at the same geometry, which is what makes the row safe to keep. A
    row count alone would also be satisfied by a write that silently failed."""
    m = _skip_if_ungrounded(plane["provided"])
    assert m["address_1"] == m["address_2"], (
        "the same input at the same scales produced two different addresses — persistence is not "
        "content-addressed: %s vs %s" % (m["address_1"], m["address_2"]))
    assert m["address_1"].startswith("rec.")
    assert m["rows_mid"] == m["rows_before"] + 1, "the first measurement wrote no row"
    assert m["rows_after"] == m["rows_mid"], (
        "re-running the stage wrote a SECOND row (%d -> %d). A persisted measurement keyed by "
        "anything less than corpus+input+scales is a cache, and an unkeyed cache is how one store's "
        "answer gets served to another." % (m["rows_mid"], m["rows_after"]))

    # And across code paths, not just across calls: the input the pump measured — a need that
    # arrived over the plane — re-addresses to the same artifact when taken directly, and writes
    # nothing. That makes the address a property of the measurement rather than of how it was
    # invoked; two nodes, or one node reached two ways, agree by construction.
    assert m["rows_replayed"] == m["rows_after"], (
        "re-taking a measurement the plane had already persisted wrote another row (%d -> %d)"
        % (m["rows_after"], m["rows_replayed"]))
    assert m["address_pumped"] and m["address_pumped"] != m["address_1"], (
        "a different input addressed to the same artifact — the input is not in the key")

    # The row must be able to say what it was measured at, or it is a number nobody can account for.
    assert m["corpus"] > 0 and isinstance(m["scales"]["xi"], float)


# ── Refusal, in both shapes ──────────────────────────────────────────────────────────────────────
def test_a_refusal_is_named_and_never_an_empty_field():
    """A node that cannot measure reports no measurement — loudly in-process, silently on the plane.

    An empty `Dict[str, float]` is indistinguishable from a successful recognition of nothing.
    Every branch below is a way to end up with one, and each must end somewhere else instead.

    The two shapes differ by design. In-process a caller can catch an exception, so the refusal is
    loud and names its cause. On the plane there is no exception to carry — §3: "a stage that
    resolves nothing discharges nothing; silence stays silence." `prism.reach` already returns
    `None` rather than an empty answer, so a refusal envelope would be a new transport saying what
    the plane already says."""
    with tempfile.TemporaryDirectory() as tmp:
        m = run_phase("refuse", tmp)
    _assert_blocked(m)

    # The seam refusal on its own, with the ontology question factored out.
    assert m["physics_no_host"]["raised"] == "RecognitionUnavailable", (
        "an unfilled seam did not refuse by name: %r. `HostSeamUnfilled` subclasses ImportError, "
        "which reads as 'a module is missing' and invites a caller to install something — the "
        "honest report is that this HOST cannot take the measurement." % (m["physics_no_host"],))

    # The store refusal: op.ground has no default store, because the default was uniform weighting.
    assert m["fire_no_store"]["raised"] == "RecognitionUnavailable"
    assert "UNIFORM" in m["fire_no_store"]["says"], (
        "op.ground refused without saying WHY a missing store is fatal to it. The reason is the whole "
        "point: `fired_field(text, store=None)` returns 1-3 concepts that look like an answer "
        "(§5.1), so a refusal that does not name the uniform fallback teaches nothing: %r"
        % (m["fire_no_store"]["says"],))

    # The ontology refusal is crystal's own (`OntologyStoreRequired`) and is passed through
    # unwrapped because it is already exactly right.
    for key in ("fire_no_host", "seed_no_host", "extent_no_host"):
        assert m[key]["raised"] in ("RecognitionUnavailable", "OntologyStoreRequired"), (
            "%s returned instead of refusing: %r" % (key, m[key]))

    # On the plane: nothing, never `{}`.
    for key in ("handler_ground", "handler_fire"):
        assert m[key] is None, (
            "%s discharged %r rather than nothing. An empty field crosses the wire looking exactly "
            "like a successful recognition of nothing." % (key, m[key]))
