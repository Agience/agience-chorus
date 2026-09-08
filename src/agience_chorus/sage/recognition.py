"""Recognition as tektons — the seven capabilities chorus serves over the ground plane.

A host seam only resolves in-process, so recognition over the seam alone requires chorus and ember to
share a process. The ontology store and the beam live together only in ember and chorus, so one side
must reach the other over the plane. `prism.reach` (`prism.carriers`, `prism.frames`) carries this
without a new transport, because `seeds_from_text`, `spread_seeds`, `fired_field`, and
`expand_associative` all return the same shape — `Dict[str, float]`, concept id → energy — so the
boundary between two stages is already a value the plane can carry.

    capability      measurement (in ember, reached by seam on the provider)     kind
    op.seed         activation.seeds_from_text(text)                            chain stage
    op.spread       activation.spread_seeds(seeds, spread=)                     chain stage
    op.fire         match.fired_field(text, store)                              chain stage
    op.propagate    match.propagate(fired, targets, xi=, gap=)                  chain stage
    op.frame        projection.frame(store, names, center=, energy=, …)         chain stage
    op.basis        match.tekton_basis_for(store, operator_id)                  about a field
    op.coherent     projection.coherent(store, names, …)                        about a field

`op.fire` is not `op.seed` followed by `op.spread`. `fired_field` weights each word by how much it
constrains the need (document-frequency, IDF-like); the seed→spread pair does not, and
`activation.recognize` composes a third way (`_seed_field` → `spread_seeds` → `rank_fired`). The
three paths disagree measurably (Jaccard 0.003–0.025 against a live corpus), and live call sites
choose between them by which import they reached for — `sage/match.py:82` takes seed→spread,
`sage/content_search.py:293` takes fire. They stay distinct rather than collapsing into one
capability that would turn that inconsistency into a wire contract, and
`sage/tests/test_recognition_tektons.py` asserts that they differ.

`op.spread` is exposed as a capability because `sage/match.py` is a live caller that reaches it, not
because its field answers "what this need is about": spreading a seed up its hypernym lineage to the
horizon accumulates mass at the abstract end, so its top-ranked concepts read as the ancestor chain
(`entity.n.01`, `object.n.01`, `physical_entity.n.01`).

Each measurement is written as a content-addressed artifact before it is discharged — the result, the
input it was taken from, and the scales it was measured at (`xi`, `gap`, corpus size) — so an answer
can show its work. Re-running a stage on the same input at the same scales computes the same address
and writes no second row. The address covers corpus + input + scales, so a measurement taken against
a different corpus, or at a different ξ, is a different artifact rather than a stale hit; nothing
here reads a persisted row back as an answer, because persistence is the record, never the source.

An empty `Dict[str, float]` means "nothing was recognised", which is itself a measurement, so a
tekton with nothing to measure on must not return one. In-process, a tekton raises
`RecognitionUnavailable` (or lets `OntologyStoreRequired` through) for a missing store, an unfilled
seam, or a corpus carrying no ontology at all. On the plane, a stage with nothing to measure on
discharges nothing — silence stays silence, matching how `prism.reach` already returns `None` rather
than an empty answer. Only `RecognitionUnavailable` is caught; any other exception still propagates
out of `Provider.pump`, because a crash and an unmeasured result are different events.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from prism.canonical import canonical_string as _jcs
from prism.reach import GROUND, Reactor

#: The grounding answer path. `op.ground` is `fired_field` — a text grounded into the concept
#: field it is about, weighted by how much each word constrains the need.
GROUND_CAP = "op.ground"

#: Internal stages: callable, and not published.
#:
#: Their fields measurably disagree (Jaccard 0.003-0.025 on node 71's live corpus). §5 names that
#: "a distributed inconsistency rather than a local one", and publishing all three would make the
#: disagreement a wire contract — the exact outcome the split exists to avoid.
#:
#: The disagreement is structural rather than a weighting artefact, which is why converging the
#: seeders does not remove it: `spread` climbs the hypernym lineage to the horizon, so it
#: accumulates mass at the abstract end and its top concepts are the ancestor chain. That is a real
#: operation and a useful diagnostic; it is not an answer to "what is this need about". `fire`
#: weights by constraint and stays specific, and it is the one a caller asking that question wants.
#:
#: They stay importable and callable — a stage is a legitimate thing to inspect — and out of
#: `RECOGNITION_CAPS`, so nothing advertises or serves them, and no peer can reach for one and get
#: a different answer to the same question.
SEED_CAP = "op.seed"
SPREAD_CAP = "op.spread"
FIRE_CAP = "op.fire"
PROPAGATE_CAP = "op.propagate"
FRAME_CAP = "op.frame"
BASIS_CAP = "op.basis"
COHERENT_CAP = "op.coherent"

#: Every capability this module serves. The chain stages first, in the order a field flows through
#: them; then the two that answer about a field rather than advancing one.
CHAIN_CAPS = (GROUND_CAP, PROPAGATE_CAP, FRAME_CAP)

#: The stages `op.ground` composes, kept callable for diagnostics but never advertised.
INTERNAL_STAGE_CAPS = (SEED_CAP, SPREAD_CAP, FIRE_CAP)
ABOUT_CAPS = (BASIS_CAP, COHERENT_CAP)
RECOGNITION_CAPS = CHAIN_CAPS + ABOUT_CAPS

#: The persisted-measurement artifact. A content type of its own so a reader can ask the store what
#: recognition it has already measured without walking every artifact it holds.
RECOGNITION_CT = "application/vnd.agience.recognition+json"

#: The identity of what the address below covers — the same discipline as `match.GEOMETRY_BASIS` and
#: `driver`'s `ic_basis`. A persisted reading that cannot say what produced it is not one to keep,
#: so the basis tag travels inside the addressed body: a change to what a tekton measures moves
#: every address by construction, rather than relying on someone remembering to bump a version.
RECOGNITION_BASIS = "recognition-tekton/v1"

__all__ = [
    "GROUND_CAP", "SEED_CAP", "SPREAD_CAP", "FIRE_CAP", "PROPAGATE_CAP", "FRAME_CAP", "BASIS_CAP",
    "COHERENT_CAP", "INTERNAL_STAGE_CAPS",
    "CHAIN_CAPS", "ABOUT_CAPS", "RECOGNITION_CAPS", "RECOGNITION_CT", "RECOGNITION_BASIS",
    "RecognitionUnavailable", "address", "corpus_extent", "scales",
    "seed", "spread", "fire", "propagate", "frame", "basis", "coherent",
    "recognition_handlers", "serve_recognition", "serve_recognition_on",
    "register_recognition_operators",
]


class RecognitionUnavailable(RuntimeError):
    """This node cannot take this measurement, so it reports no measurement.

    Raised at the point of use, never at import, and never in place of an answer. Modelled on
    `crystal.ontology.driver.OntologyStoreRequired`: an empty index makes every answer `[]`, which
    readers up the stack interpret as this corpus does not contain that concept — a measurement, and
    a fabricated one if the index was never real.

    Three causes, all "nothing to measure on" rather than "measured nothing":
      · no host filled the seam that names the measurement (`HostSeamUnfilled`),
      · no store was given and none is bound,
      · the store carries no ontology — `ic_coverage(...)["synsets"] == 0`.

    Not raised when a readable ontology grounds a text to nothing: that empty field is itself a
    measurement.
    """


# ── the physics, reached by name ───────────────────────────────────────────────────────────────────
def _physics(name: str):
    """The module a host bound to seam `name` — `activation`, `match`, or `projection`.

    Chorus never names ember, here or anywhere: on an ember runner the binding is
    `ember/runtime/seams.py`, but a fork, a store-only node, or a test may bind something else, and
    this file does not need to know which. `HostSeamUnfilled` is re-raised as `RecognitionUnavailable`
    rather than left as-is, because it subclasses `ImportError`, which reads as "a module is missing"
    and would invite a caller to install something — the report this host gives is that it cannot
    take the measurement."""
    from agience_chorus._host_seams import HostSeamUnfilled, resolve
    try:
        return resolve(name)
    except HostSeamUnfilled as exc:
        raise RecognitionUnavailable(
            "no host filled the %r seam, so this node cannot take the recognition measurement it "
            "names. A host binds it at boot (prism.runner.register_seam); until one does there is "
            "nothing here to measure on, and an empty field would report a measurement that was "
            "never taken." % (name,)) from exc


# ── the gate: is there anything to measure on? ─────────────────────────────────────────────────────
def corpus_extent() -> int:
    """How many concepts the ontology carries, raising when it carries none.

    `driver.ic_coverage` raises `OntologyStoreRequired` when there is no store to read at all, passed
    through unwrapped because it is already the right report; its `synsets` count is the corpus
    extent, which is also the component that makes a persisted measurement re-derive when the corpus
    grows, matching how `match._persisted_geometry` verifies `ic_basis_n`.

    This takes no store, because the ontology and the node's lattice are two different substrates:
    `match.fired_field(text, store)` resolves its senses through `offer_synsets(text)`, which passes
    no store, and uses its `store` argument only for the document-frequency counts off
    `store.artifacts.db`; `activation.seeds_from_text` takes no store at all. The ontology is resolved
    by the driver's own order (explicit → bound → the host's registered default), so this asks the
    ontology the same way the measurements downstream of it will — checking against the lattice
    instead would treat every node whose ontology is installed or bound, rather than sitting in the
    artifact table it was handed, as having none.

    Zero is an absence, not an extent: an ontology of zero concepts cannot ground anything, so every
    field taken against it would be `{}`, indistinguishable from "this need is about nothing". This
    raises instead of returning that empty field."""
    from crystal.ontology import driver as _driver
    n = int(_driver.ic_coverage().get("synsets") or 0)
    if n <= 0:
        raise RecognitionUnavailable(
            "this store carries no ontology (0 concepts), so there is nothing to recognise "
            "AGAINST. Every field taken here would be empty, which reads as 'this need is about "
            "nothing' — a measurement, and a fabricated one. Ground the corpus (WordNet/OEWN) or "
            "reach a node that has.")
    return n


def scales() -> Dict[str, Optional[float]]:
    """The corpus geometry a measurement was taken at — `{"xi", "gap"}`, measured, never defaulted.

    Both come from `match._geometry()`, so ξ and the propagation floor cannot disagree. Either may be `None`
    when this corpus reports no geometry, and `None` is recorded as `None` rather than replaced by a
    number: a scale that was not measured is not persisted as though it had been."""
    m = _physics("match")
    return {"xi": m.xi(), "gap": m.propagation_floor()}


# ── persistence: content-addressed, keyed by corpus + input + scales ───────────────────────────────
def address(capability: str, given: Any, *, scale: Dict[str, Optional[float]], corpus: int) -> str:
    """The content address of a measurement — `sha256(JCS(...))`, over everything that could change it.

    A persisted field is keyed by store + input + the scales it was measured at, because anything
    less is a wrong answer with provenance attached. `capability`, `given` (the input), `scale` (ξ and
    the gap), and `corpus` (the extent it was taken against) are all inside the hash, along with
    `RECOGNITION_BASIS`, so a change to what a tekton measures moves every address by construction.
    One canonicaliser (`prism.canonical`), the same one the reach core addresses with, so two nodes
    computing this agree byte for byte."""
    body = _jcs({"basis": RECOGNITION_BASIS, "capability": capability, "corpus": corpus,
                 "given": given, "scales": scale})
    return "rec." + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def _persist(store: Any, capability: str, given: Any, result: Any, *,
             scale: Dict[str, Optional[float]], corpus: int) -> str:
    """Write the measurement as an artifact and return its address. Idempotent, and never a cache.

    Idempotent by address rather than by a dedup pass: the same input at the same scales against the
    same corpus hashes to the same id, so the row is written once and re-running writes no second
    one — `StoreCarrier.put`'s discipline applied to the measurement instead of the envelope.

    Nothing reads this back as an answer. It is the record of a measurement, the thing that lets a
    chain show its work, not a lookup that could serve a stale field to a caller who asked for a
    fresh one.

    Best-effort on the write only: a read-only store still gets its measurement, the same degradation
    as `match._persist_geometry`. The address is returned either way, because it is derived from the
    input and does not depend on the write succeeding."""
    aid = address(capability, given, scale=scale, corpus=corpus)
    arts = getattr(store, "artifacts", store)
    if arts is None or not callable(getattr(arts, "put_artifact", None)):
        return aid
    try:
        if arts.get_artifact(aid) is not None:
            return aid                              # already measured at these scales — no second row
        arts.put_artifact({"id": aid, "content_type": RECOGNITION_CT, "state": "committed",
                           "basis": RECOGNITION_BASIS, "capability": capability,
                           "given": given, "result": result,
                           "scales": dict(scale), "corpus": corpus})
    except Exception:
        return aid                                  # the measurement still stands for this caller
    return aid


def _measured(store: Any, capability: str, given: Any, result: Any) -> Dict[str, Any]:
    """The evidence envelope a tekton discharges: the result, plus what it was measured at.

    `field` is the carrier key on the way out and the way in: `op.seed`'s evidence is `op.spread`'s
    need without a translation step, which is what lets the chain compose by propagation rather than
    by a caller calling five functions."""
    sc = scales()
    corpus = corpus_extent()
    env: Dict[str, Any] = {"capability": capability, "scales": sc, "corpus": corpus}
    env.update(result)
    env["tekton"] = _persist(store, capability, given, result, scale=sc, corpus=corpus)
    return env


# ── the five chain stages ──────────────────────────────────────────────────────────────────────────
def seed(text: str, *, info: Any = None) -> Dict[str, float]:
    """`op.seed` — the raw sense field a text grounds to. `activation.seeds_from_text`.

    No store parameter, because the measurement has none: `seeds_from_text(text, *, info=None)`
    reads the ontology the driver resolves, and a `store=` here that was only checked and never
    threaded would advertise a control this function does not have. The gate is `corpus_extent()`,
    which asks the ontology the same way this does."""
    corpus_extent()
    return dict(_physics("activation").seeds_from_text(str(text), info=info))


def spread(seeds: Dict[str, float], *, spread_to: Optional[int] = None) -> Dict[str, float]:
    """`op.spread` — the seed field spread through the ontology. `activation.spread_seeds`.

    Its top-ranked concepts read as the ancestor chain (`entity.n.01`, `object.n.01`,
    `physical_entity.n.01`) rather than as what the need is about, because it spreads each seed up
    its hypernym lineage to the horizon and mass accumulates at the abstract end. It is exposed here
    so `sage/match.py` can reach rather than import it.

    `spread_to` renames the underlying `spread=` keyword, which would otherwise shadow this
    function's own name at the call site."""
    corpus_extent()
    return dict(_physics("activation").spread_seeds(dict(seeds or {}), spread=spread_to))


def fire(text: str, store: Any) -> Dict[str, float]:
    """`op.fire` — the field weighted by how much each word constrains the need. `match.fired_field`.

    The store is required here and has no default, the one signature change this module makes to
    anything it wraps. `fired_field(text, store=None)` falls back to uniform salience when it cannot
    measure document frequency (`match._CORPUS_STATS is None` → `{s: 1.0}`), returning 1–3 concepts
    with no indication that the weighting never ran — a default of `None` is what would let a caller
    reach that path without meaning to."""
    if store is None:
        raise RecognitionUnavailable(
            "op.fire needs a store: `fired_field` weights each word by how much it CONSTRAINS the "
            "need, and that weighting is a corpus measurement. Without a store it silently goes "
            "UNIFORM and returns 1-3 concepts that look like an answer (RECOGNITION-TEKTONS.md "
            "§5.1). Pass the store, or reach a node that holds one.")
    corpus_extent()
    return dict(_physics("match").fired_field(str(text), store))


def propagate(fired: Dict[str, float], targets: Sequence[str], *,
              xi: Optional[float] = None, gap: Optional[float] = None) -> Tuple[float, float]:
    """`op.propagate` — a field onto a set of targets. `(energy, nearest_distance)`. `match.propagate`.

    The one stage whose result is a scalar pair rather than a field, so it terminates a chain rather
    than advancing one. `xi`/`gap` default to the corpus's own measured geometry inside `match`;
    naming them is how a caller asks for a different screening length, and the value actually used is
    what gets persisted."""
    corpus_extent()
    e, d = _physics("match").propagate(dict(fired or {}), list(targets or []), xi=xi, gap=gap)
    return float(e), float(d)


def frame(store: Any, names: Sequence[str], *, center: Any = None, energy: Any = None,
          corpus_basis: bool = True, k: Optional[int] = None):
    """`op.frame` — the ordered `(T, F)` screen for these concepts. `projection.frame`.

    Order is the signal: `entroptics`' Screen is ordered and a shuffle destroys coherence, so
    `names` travels as a list across the plane and is never normalised into a set on the way.

    Returns the frame, or `None` when the projection cannot be read. `None` means unreadable, which
    the caller keeps apart from a frame of zeros."""
    corpus_extent()
    return _physics("projection").frame(store, list(names or []), center=center, energy=energy,
                                        corpus_basis=corpus_basis, k=k)


# ── the two that answer about a field ──────────────────────────────────────────────────────────────
def basis(store: Any, operator_id: str):
    """`op.basis` — a registered tekton's coupling basis. `match.tekton_basis_for`.

    `None` when that operator has no grounded offer here, which is a real answer about this node
    rather than a failure: it is what `Provider._route_next` needs in order to decline to route."""
    corpus_extent()
    return _physics("match").tekton_basis_for(store, str(operator_id))


def coherent(store: Any, names: Sequence[str], *, center: Any = None,
             corpus_basis: bool = True, k: Optional[int] = None) -> Optional[bool]:
    """`op.coherent` — is this reached set one coherent, scale-invariant thing? `projection.coherent`.

    Three-valued: `None` means unreadable, a different answer from `False` ("read, and it is not one
    thing"), and the caller keeps them apart. Collapsing `None` into `False` anywhere on this path
    would report an unmeasured frame as a measured incoherent one."""
    corpus_extent()
    return _physics("projection").coherent(store, list(names or []), center=center,
                                           corpus_basis=corpus_basis, k=k)


# ── the plane face: need -> evidence, one handler per capability ───────────────────────────────────
def _field_of(need: Dict[str, Any]) -> Dict[str, float]:
    """Read the carried field off a need. `field` is the wire name; `seeds`/`fired` are accepted
    because that is what the two live call sites already call it, and a chain must not break on a
    synonym."""
    for key in ("field", "seeds", "fired"):
        v = need.get(key)
        if isinstance(v, dict):
            return {str(a): float(b) for a, b in v.items()}
    return {}


def recognition_handlers(store: Any) -> Dict[str, Callable[[Any], Any]]:
    """The seven `need -> evidence` handlers, bound to the store this node holds.

    A tekton with nothing to measure returns `None`, which discharges nothing: on the plane an
    honest null is silence, and `prism.reach` already carries that contract end to end
    (`Provider.on_leaf` discharges no evidence for a `None` absorption; `Requester.first` reports
    `None` when nothing on the ground references the need). An empty field would cross the wire
    looking exactly like a successful recognition of nothing.

    Only `RecognitionUnavailable` is caught. A `TypeError` in a measurement is a defect and must
    reach the pump, because a crash and an unmeasured result are different events, and a handler that
    swallows both makes them indistinguishable in the one place it matters."""

    def _refusable(fn: Callable[[Dict[str, Any]], Any]) -> Callable[[Any], Any]:
        def handler(need: Any):
            try:
                return fn(need if isinstance(need, dict) else {})
            except RecognitionUnavailable:
                return None                     # silence stays silence, not an empty field
            except Exception as exc:            # a driver's OntologyStoreRequired is the same report
                if type(exc).__name__ == "OntologyStoreRequired":
                    return None
                raise
        return handler

    def _seed(need):
        return _measured(store, SEED_CAP, {"text": str(need.get("text", ""))},
                         {"field": seed(need.get("text", ""))})

    def _spread(need):
        given = {"field": _field_of(need), "spread": need.get("spread")}
        return _measured(store, SPREAD_CAP, given,
                         {"field": spread(given["field"], spread_to=given["spread"])})

    def _fire(need):
        return _measured(store, FIRE_CAP, {"text": str(need.get("text", ""))},
                         {"field": fire(need.get("text", ""), store)})

    def _ground(need):
        """`op.ground` — the one grounding answer. Same measurement as the `fire` stage, under the
        name a caller should reach for, and stamped as `op.ground` so the persisted record says
        which capability answered rather than which stage happened to run."""
        return _measured(store, GROUND_CAP, {"text": str(need.get("text", ""))},
                         {"field": fire(need.get("text", ""), store)})

    def _propagate(need):
        given = {"field": _field_of(need), "targets": list(need.get("targets") or []),
                 "xi": need.get("xi"), "gap": need.get("gap")}
        e, d = propagate(given["field"], given["targets"], xi=given["xi"], gap=given["gap"])
        return _measured(store, PROPAGATE_CAP, given, {"energy": e, "distance": d})

    def _frame(need):
        from prism import frames as _frames
        given = {"names": list(need.get("names") or []), "k": need.get("k"),
                 "corpus_basis": bool(need.get("corpus_basis", True))}
        W = frame(store, given["names"], k=given["k"], corpus_basis=given["corpus_basis"])
        # `None` is unreadable and travels as such — an encoded empty frame would claim a read.
        enc = None if W is None else _frames.encode_frame(W)
        return _measured(store, FRAME_CAP, given, {"frame": enc, "readable": enc is not None})

    def _basis(need):
        from prism import frames as _frames
        given = {"operator": str(need.get("operator") or need.get("operator_id") or "")}
        B = basis(store, given["operator"])
        return _measured(store, BASIS_CAP, given,
                         {"basis": None if B is None else _frames.encode_frame(B),
                          "grounded": B is not None})

    def _coherent(need):
        given = {"names": list(need.get("names") or []), "k": need.get("k"),
                 "corpus_basis": bool(need.get("corpus_basis", True))}
        return _measured(store, COHERENT_CAP, given,
                         {"coherent": coherent(store, given["names"], k=given["k"],
                                               corpus_basis=given["corpus_basis"])})

    return {GROUND_CAP: _refusable(_ground),
            SEED_CAP: _refusable(_seed), SPREAD_CAP: _refusable(_spread),
            FIRE_CAP: _refusable(_fire), PROPAGATE_CAP: _refusable(_propagate),
            FRAME_CAP: _refusable(_frame), BASIS_CAP: _refusable(_basis),
            COHERENT_CAP: _refusable(_coherent)}


def serve_recognition_on(reactor: Reactor, store: Any,
                         caps: Optional[Sequence[str]] = None) -> Reactor:
    """Serve the recognition capabilities on a reactor a host already holds. Returns that reactor.

    Entitlement is snapshotted in `Provider.__init__` (`lightcone.reaches(principal)`), so the grants
    naming these capabilities must exist before this is called. A grant minted afterward is invisible
    to the provider, and the symptom is silence, not an error."""
    handlers = recognition_handlers(store)
    for cap in (caps or RECOGNITION_CAPS):
        reactor.serve(cap, handlers[cap])
    return reactor


def serve_recognition(store: Any, *, root_secret: bytes, fabric: Any = None,
                      fallback: Any = None, principal: str = "sage", ground: str = GROUND,
                      reach: Optional[Callable[[Any, str], Any]] = None,
                      caps: Optional[Sequence[str]] = None) -> Reactor:
    """Stand this node up as the provider of recognition over the ground plane.

    Assembles through `reach_wiring.reactor`, chorus's one composition point for a mantle-backed
    reactor, so the light-cone rule and the key derivation stay single-homed. `fabric` is a live
    streaming fabric (`LoopbackFabric` in tests, WebRTC/QUIC/RF in production); omit it and pass a
    `fallback` carrier and the provider rides store-and-forward, which is what makes the requester
    a different process rather than a different object."""
    from agience_chorus.reach_wiring import reactor as _reactor
    rc = _reactor(store, principal, root_secret=root_secret, fabric=fabric, reach=reach,
                  ground=ground, fallback=fallback)
    return serve_recognition_on(rc, store, caps=caps)


# ── advertisement: the capability is an artifact ───────────────────────────────────────────────────
#: What each capability offers, in the prose an offer artifact carries. These are what `need → offer`
#: matching reads, and what `tekton_basis_for` grounds into a coupling subspace — so the wording is
#: the capability's coordinate, not documentation.
_RECOGNITION_OFFERS = [
    (GROUND_CAP, "grounds a text into the concept field it is about, weighted by how much each "
                 "word constrains the need"),
    (PROPAGATE_CAP, "propagates a concept field onto target concepts, reporting energy and distance"),
    (FRAME_CAP, "projects concepts into the ordered screen frame their coordinates span"),
    (BASIS_CAP, "reports the coupling basis a registered operator offers in this corpus"),
    (COHERENT_CAP, "reports whether a reached set of concepts is one coherent scale-invariant thing"),
]

OPERATOR_CONTENT_TYPE = "application/vnd.agience.operator+json"


def register_recognition_operators(store: Any, *, author: str = "chorus") -> int:
    """Mint the offer artifact for each recognition capability into `store`.

    A capability is an artifact, matched by propagation rather than by set membership — this is what
    makes `op.basis` able to answer at all: `tekton_basis_for` reads the offer's grounded synsets out
    of the store and returns `None` for an operator that has none here.

    Not wired into `sage/manifest.py`. Sage's registrars come from its five bundle groups
    (`prism.runner.register_fns`), so advertising these through the manifest means a new bundle
    group and a `bundle_spec.json` entry, not a new list element; a host that wants the offers
    advertised calls this directly."""
    from crystal import evolution
    arts = getattr(store, "artifacts", store)
    for name, offer in _RECOGNITION_OFFERS:
        arts.put_artifact(evolution.preserve_fitness(arts, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": "recognition tekton %s: %s" % (name, offer),
            "created_by": author}))
    return len(_RECOGNITION_OFFERS)
