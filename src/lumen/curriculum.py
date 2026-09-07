# Authoritative home: lumen. Curriculum is lumen's declared domain — "wisdom & inference:
# reasoning, learning, curriculum, consolidation, illumination" (chorus/README.md). A certificate is
# a reasoning act (it decides whether an observer has learned a level), not a runner act — the same
# reason `enrich.py` lives here too: ember places and ingests; it does not decide that a level is
# done.
"""The curriculum certificate — a level advances on what it can answer, never on its byte count.

A level is a certificate, not a date and not a byte count: the corpus answers at that level, and
the answers are grounded (`CURRICULUM-DATA-PLAN.md` §0). Promotion in `ember/genesis.py` still
gates `stage.1.grammar` and `stage.2.world` on `have >= spec["target"]` — a row count, the one axis
the plan names as not the gate — and stage 0 promotes on source exhaustion, which is honest about
ingestion but says nothing about whether the level can answer. This module does not change that
gate; rewiring promotion is a separate, later change. What this module provides is the measurement
the gate is missing, as an operator anything can read.

── what a certificate is ─────────────────────────────────────────────────────────────────────────

Two halves, and they answer different questions (`GENESIS-EDUCATION.md`: "a stage is stable when
its entroptics read plateaus and holds on held-out queries"):

    settled   has the level's own structure stopped moving?      — the resolved rank, certified
    answers   can it answer questions it was not shown?          — held out, against the corpus's
                                                                    own labels as the oracle

Both, or the level is not certified. Either one unmeasurable is `None` — not `False` — and an
unmeasured half never certifies.

── no pass mark ──────────────────────────────────────────────────────────────────────────────────

The verdict is a conservation certificate, not a score against a chosen number: is everything the
observer said accounted for by what the corpus records? `prism.frames.offer_basis(truth)` derives
the corpus's own span (its coupling-basis construction, tolerance from shape and dtype), and
`absorb_transmit(said, basis=band)` splits what the observer said against it, conserving exactly by
orthogonal projection. `answers ⟺ transmitted residual is zero and absorbed energy is not`.

The feature axis is `(item, kind)` pairs, not kinds alone, and that pairing is what keeps the
certificate honest: the corpus's span is block-diagonal by construction, so a kind is absorbed only
when it was said about the right item. Flattened to kinds alone, the band would span every kind
mentioned anywhere, and a constant answer ("fish", said about everything) would be fully absorbed
and certify. Under `(item, kind)`, the same constant answerer reads residual > 0.

The three degenerate observers all read `answers=False` or `answers=None` with nothing typed to
catch them: saying nothing carries zero absorbed energy (unmeasured — stating nothing is not a
wrong answer, and it is not a right one either); saying one kind about everything falls outside the
block-diagonal band; saying a kind the corpus never records falls outside the span entirely.

`rate` and the exact re-paired `null` are measured and reported alongside, because they are free
and a reader wants them, but they decide nothing — evidence beside the certificate, not the
certificate.

── the oracle ────────────────────────────────────────────────────────────────────────────────────

Expected results are computed independently of the mechanism under test (paper §38: "WordNet is
the answer key"). The level-0 certificate asserts "name a thing and give its kind" (`what is a dog`
→ `Canis familiaris`); the key is the synset's own recorded hypernyms, read from the corpus and not
from the answerer, so the certificate cannot share a bug with the thing it tests, and there is no
human grading and no model in the loop (`CURRICULUM-DATA-PLAN.md` §1b: "checkable against the
corpus's own labels").

── present constraint ────────────────────────────────────────────────────────────────────────────

The settled half reads `unresolved` on ontology frames today: paper §21 measures `K_signal = 0` on
every is-a descent frame tried (`dog.n.01`, `physicist.n.01`, `bank.n.01`, 5–8 rows against
F = 2048), because ontology coordinates are sparse and a sparse frame reads as noise. A frame that
resolves nothing has no rank to settle, so `settled` returns `None` (unmeasurable), never `False`,
and never a fabricated plateau. On this corpus today, a level can be certified on the answers half
alone, with the settled half honestly reported as unmeasured — a weaker certificate than the design
asks for, and labelled as such in the result.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


# ── the eight levels: data, and nothing may read the numbers ─────────────────────────────────────
# `CURRICULUM-DATA-PLAN.md` §1 is emphatic that the word-count targets are the target a certificate
# tests, never an input to any algorithm — nothing in the code may read them. So they are not here.
# What is here is each level's assertion — what the certificate has to check — because that is the
# part a checker needs, and it carries no number at all.
LEVELS: Dict[int, str] = {
    0: "name a thing and give its kind",
    1: "compare, order, and follow a three-step chain",
    2: "explain a mechanism and cite the document it came from",
    3: "apply a method across two domains; surface a genuine contradiction without resolving it",
    4: "survey a field, locate its frontier, and state what is unreplicated",
    5: "state a novel claim, its evidence, and what would falsify it",
    6: "answer from current practice AND say when that answer last changed",
    7: "answer a question the literature cannot, and show the measurement",
}


@dataclass(frozen=True)
class Certificate:
    """One level's certificate. Every field is a measurement or an honest `None`.

    `certified` is `True` only when both halves are `True`. It is `False` when either half was
    measured and failed. It is `None` when a half could not be measured at all — because "we did
    not find out" and "we found out it is not so" are different readings, and a promotion gate that
    cannot tell them apart is the gate this module exists to replace."""
    level: int
    asserts: str
    settled: Optional[bool] = None          # the resolved rank has stopped moving, and is certified
    answers: Optional[bool] = None          # it answers questions it was not shown
    rate: Optional[float] = None            # what it scored on the held-out set
    null: Optional[float] = None            # what those same answers score against a re-paired key
    resolution: Optional[float] = None      # the smallest difference this many trials can see
    n: int = 0                              # held-out trials actually run
    coverage: Optional[float] = None        # fraction of the held-out set the observer spoke to —
                                             # reported, not gated (see the module header)
    rank: Optional[int] = None              # K_signal on the level's own accumulated frames
    interval: Optional[Tuple[int, int]] = None      # the Weyl interval for that count
    why: List[str] = field(default_factory=list)    # why a half is None or False — never inferred

    @property
    def certified(self) -> Optional[bool]:
        if self.settled is None or self.answers is None:
            return None
        return bool(self.settled and self.answers)


# ── the settled half — has the structure stopped moving? ──────────────────────────────────────────
def settled(frames: Iterable[Sequence[Sequence[float]]], n_features: int,
            *, read: Any = None) -> Dict[str, Any]:
    """Accumulate the level's own frames and ask whether its resolved rank has settled.

    There is no plateau tolerance. Comparing `K` at successive data sizes and calling it flat when
    the change is under some ε is a typed constant wearing a derivative — `reasoning.py`'s
    `_rank_curve` shows the same shape of defect: slicing the input into pieces to report a rank per
    slice decides nothing except how much work to do, and only the last slice was ever read.

    `Read.accumulated_read` answers the question directly and threshold-free: it returns the
    Weyl-certified interval `[k_lo, k_hi]` for the pooled spectrum, and `certified` is
    `k_lo == k_hi == k_signal` — the interval has collapsed onto the count. That is "the rank has
    stopped moving", stated as a property of the evidence rather than a comparison between two
    readings, and the band tightens as `1/√T` so it is a progress reading the whole way (paper §4:
    "a read certifies by accumulating").

    `K_signal == 0` is not settled and not failed — it is unmeasurable. A frame that resolves no
    modes has no rank to have stopped moving, and the two readings must never be the same answer
    (paper §21). Returns `settled=None` with the reason attached.

    `read` is the structure-read instrument — `prism.instrument.Read`, whose `accumulator` and
    `accumulated_read` this is the one caller of. Injected for the same reason `answers` takes its
    `embodiment=`: `ember` holds the instrument, and a lazy import is still an edge. It is `Read` and
    not `Embodiment`: pooling planes and reporting what the pooled spectrum resolves is a statement
    about the signal, and this function never splits one."""
    from prism.instrument import get_default as _get_default, require as _require
    # An empty iterable is a structural fact — nothing was accumulated — and a host with no
    # instrument at all answers it correctly, exactly as `answers`'s returns above its split do.
    # Peeked rather than buffered so a generator of planes still streams.
    _frames = iter(frames)
    try:
        first = next(_frames)
    except StopIteration:
        return {"settled": None, "rank": None, "interval": None,
                "why": "no frames were accumulated for this level"}
    # The point of measurement. Resolution order is `prism.instrument`'s: the `read=` keyword, then
    # the process default a host registered, then an error naming the missing member and the
    # operation. There is no fourth step — an unfilled slot never becomes an empty accumulation.
    _slot = read if read is not None else _get_default()
    _at = "curriculum.settled (pool this level's frames and read the certified rank)"
    accumulator = _require(_slot, "accumulator", contract="read", at=_at)
    accumulated_read = _require(_slot, "accumulated_read", contract="read", at=_at)

    acc = accumulator(int(n_features))
    planes = 0
    for plane in itertools.chain([first], _frames):
        try:
            acc.add(plane)
            planes += 1
        except Exception:
            continue                        # a plane this coordinate cannot take is not a verdict
    if not planes:
        return {"settled": None, "rank": None, "interval": None,
                "why": "no frames were accumulated for this level"}
    pooled = accumulated_read(acc)
    if pooled is None:
        return {"settled": None, "rank": None, "interval": None,
                "why": "the instrument returned no read over %d accumulated plane(s)" % planes}
    k = int(pooled["k_signal"])
    interval = tuple(int(v) for v in pooled["interval"])
    if k == 0:
        # Paper §21 — ontology coordinates are sparse and a sparse frame reads as noise. Reported
        # as unmeasured, because "I cannot resolve this" and "this has not settled" are different
        # claims and only one of them is about the level.
        return {"settled": None, "rank": 0, "interval": interval,
                "why": ("the instrument resolved NO modes in this level's frames (K_signal = 0) — "
                        "there is no rank to have settled, which is a reading of the coordinate "
                        "and not of the level (T=%d, F=%d)" % (pooled["T"], pooled["F"]))}
    return {"settled": bool(pooled["certified"]), "rank": k, "interval": interval,
            "why": ("" if pooled["certified"] else
                    "the certified interval %s has not collapsed onto K_signal=%d (band %.4g at "
                    "T=%d) — more evidence is owed, not a smaller tolerance"
                    % (interval, k, pooled["band"], pooled["T"]))}


# ── the answers half — can it answer what it was not shown? ───────────────────────────────────────
def answers(items: Sequence[Any],
            stated: Callable[[Any], Sequence[str]],
            key: Callable[[Any], Sequence[str]],
            *, embodiment: Any = None) -> Dict[str, Any]:
    """Is everything the observer said about the held-out items accounted for by what the corpus
    records about them? A conservation read, not a score against a mark.

    `items`         the held-out set. The observer is never shown the key.
    `stated(item)`  the kinds the observer's answer stated about this item (empty = no kinds stated).
    `key(item)`     the kinds the corpus records for it — the oracle, read from the store and not
                    from the answer path, so the certificate cannot share a bug with what it tests.
    `embodiment`    the instrument that splits the frame — `prism.embodiment.Embodiment`, whose
                    `absorb_transmit` this is the one caller of. Keyword-only, defaulting to `None`,
                    which is not "no measurement": with nothing injected and no process default
                    registered, the split raises `EmbodimentRequired` at the moment it is asked. A
                    full node injects `ember.optics`.

    `embodiment` is injected rather than imported because measuring is a host capacity, not a
    package one: `ember` holds the instrument, and importing it directly here would be an L3→L3 edge
    the layer model forbids, the same argument `crystal.Crystal` takes. Resolution is
    `prism.instrument.resolve`: the `embodiment=` keyword first, then the process default a host
    registered, then an error naming the missing member and the operation. There is no fourth step
    — an unfilled slot never becomes a zero split or a guessed basis.

    The two frames live on an `(item, kind)` feature axis — see the module header: the pairing has
    to be in the coordinate, or the corpus's band spans every kind mentioned anywhere and a constant
    answer certifies. `offer_basis` derives its own numerical null from shape and dtype, and
    `absorb_transmit` conserves exactly by orthogonal projection, so the whole verdict carries no
    decision input.

    `rate` and `null` are reported alongside and decide nothing (module header)."""
    import numpy as _np
    from prism import frames as _frames
    from prism.instrument import resolve as _resolve
    n = len(items)
    if n == 0:
        return {"answers": None, "rate": None, "null": None, "resolution": None, "n": 0,
                "why": "no held-out items were supplied — nothing was asked, so nothing is known"}
    said_sets, key_sets = [], []
    for it in items:
        try:
            said_sets.append({str(k).strip().lower() for k in (stated(it) or []) if str(k).strip()})
        except Exception:
            said_sets.append(set())         # a raise is a non-answer, not a crash of the certificate
        try:
            key_sets.append({str(k).strip().lower() for k in (key(it) or []) if str(k).strip()})
        except Exception:
            key_sets.append(set())

    # The (item, kind) feature axis is built from the union of what was said and what is recorded,
    # so a kind the corpus never records still has a column and therefore still has a residual to
    # transmit — dropping it would make a fabricated answer unmeasurable rather than scored as
    # unabsorbed.
    cols: Dict[Tuple[int, str], int] = {}
    for i in range(n):
        for k in (said_sets[i] | key_sets[i]):
            cols.setdefault((i, k), len(cols))
    if not cols:
        return {"answers": None, "rate": None, "null": None, "resolution": None, "n": n,
                "why": "neither the observer nor the corpus stated any kind for any held-out item — "
                       "there is nothing to conserve, so nothing is known"}
    said = _np.zeros((n, len(cols)), dtype=float)
    truth = _np.zeros((n, len(cols)), dtype=float)
    for i in range(n):
        for k in said_sets[i]:
            said[i, cols[(i, k)]] = 1.0
        for k in truth_k(key_sets[i]):
            truth[i, cols[(i, k)]] = 1.0

    energy = float((said ** 2).sum())
    hits = sum(1 for i in range(n) if said_sets[i] & key_sets[i])
    rate = hits / float(n)
    cross = sum(1 for s in said_sets for kk in key_sets if s & kk)
    null = cross / float(n * n)
    # Coverage is measured and reported, and it is deliberately not gated. Conservation proves the
    # observer fabricated nothing; it does not prove it answered everything, and the two are
    # different claims — an observer that answers four of eight items correctly and states nothing
    # for the other four has residual 0 and is unfabricated, which is true and is not "it can do
    # this level". The honest completion is a second number, not a second gate: requiring
    # `coverage > x` would put a pass mark back in, one field along. The certificate instead states
    # what fraction of the level the observer spoke to and lets the reader — or a promotion gate
    # that is allowed to have a policy — see it. A `coverage` of 0.125 beside `answers: True` says
    # exactly what happened and cannot be mistaken for mastery.
    coverage = sum(1 for s in said_sets if s) / float(n)
    base = {"rate": rate, "null": null, "resolution": None, "n": n, "coverage": coverage}
    if energy <= 0.0:
        return {**base, "answers": False, "residual": 0.0, "absorbed": 0.0, "energy": 0.0,
                "why": "the observer stated no kind for any held-out item — a refusal is not a "
                       "wrong answer, and it is not a right one either"}
    band = _frames.offer_basis(truth)
    if band is None:
        return {**base, "answers": None,
                "why": "the corpus records no kind for any held-out item, so there is no band to "
                       "absorb against — the oracle is missing, which is not a verdict on the observer"}
    # The point of measurement, and where the split happens. Resolved here and not at the top of
    # the function on purpose: every return above this line is a structural fact (no items, no
    # kinds stated, no band recorded) that a host with no instrument at all still answers
    # correctly. Asking for the instrument earlier would turn "the observer stated nothing" into
    # "this host cannot measure", which are different statements.
    absorb_transmit = _resolve(embodiment, "absorb_transmit",
                               at="curriculum.answers (split the stated frame against the "
                                  "corpus's band)")
    split = absorb_transmit(said, basis=band)
    if split is None:
        return {**base, "answers": None,
                "why": "the instrument could not split the stated frame against the corpus's band"}
    absorbed, transmitted, _k = split
    residual = float((transmitted ** 2).sum())
    absorbed_e = float((absorbed ** 2).sum())
    # The tolerance is the projector's own arithmetic, not a choice: an orthogonal projection
    # conserves exactly, so anything above float round-off on this frame is un-absorbed signal.
    tol = float(_np.finfo(float).eps) * max(1.0, energy) * float(max(said.shape))
    ok = residual <= tol and absorbed_e > tol
    why = ""
    if not ok:
        why = ("the corpus did not absorb everything stated: residual %.6g of %.6g total energy "
               "(absorbed %.6g, tolerance %.3g) — the observer said things this level's own records "
               "do not carry for those items" % (residual, energy, absorbed_e, tol))
    return {**base, "answers": bool(ok), "residual": residual, "absorbed": absorbed_e,
            "energy": energy, "tolerance": tol, "why": why}


def truth_k(ks):
    """Identity on a key set — a seam kept explicit so a caller can see that the oracle's kinds
    enter the truth frame unmodified. Nothing is normalised here that was not normalised on the
    stated side; both go through the same lowering in `answers`."""
    return ks


# ── the certificate ───────────────────────────────────────────────────────────────────────────────
def certify(level: int, *,
            frames: Optional[Iterable[Sequence[Sequence[float]]]] = None,
            n_features: Optional[int] = None,
            items: Optional[Sequence[Any]] = None,
            stated: Optional[Callable[[Any], Sequence[str]]] = None,
            key: Optional[Callable[[Any], Sequence[str]]] = None,
            embodiment: Any = None, read: Any = None) -> Certificate:
    """Certify one level. Both halves, or it is not certified.

    Every input is injected rather than reached, for the reason `check.py` gives about its own
    extractor seam: a certificate must be runnable where the substrate is, and must degrade
    honestly where it is not — reporting which half did not run, never reporting an unmeasured half
    as a result. Omit a half and it reads `None`, and `certified` is then `None` too.

    `embodiment` is the instrument the `answers` half splits with — see `answers()`; `read` is the
    `prism.instrument.Read` the `settled` half pools with. Two slots because they are two
    contracts: `settled` reads and never splits, `answers` splits and never reads, so a host that
    filled one and not the other gets one measured half and a named error on the other. Both are
    passed through rather than absorbed: an absent instrument is not a missing half. A half that
    did not run reads `None` with a `why`; a half that could not be measured raises, because
    reporting `answers: None` for "this host is not equipped" would put a capacity fact and a
    wiring fact into the same field."""
    asserts = LEVELS.get(int(level), "")
    why: List[str] = []
    s: Dict[str, Any] = {"settled": None, "rank": None, "interval": None,
                         "why": "no frames were supplied — the settled half did not run"}
    if frames is not None and n_features:
        s = settled(frames, int(n_features), read=read)
    if s.get("why"):
        why.append("settled: " + s["why"])
    a: Dict[str, Any] = {"answers": None, "rate": None, "null": None, "resolution": None, "n": 0,
                         "why": "no held-out probe was supplied — the answers half did not run"}
    if items is not None and stated is not None and key is not None:
        a = answers(items, stated, key, embodiment=embodiment)
    if a.get("why"):
        why.append("answers: " + a["why"])
    return Certificate(level=int(level), asserts=asserts,
                       settled=s["settled"], answers=a["answers"],
                       rate=a["rate"], null=a["null"], resolution=a["resolution"], n=a["n"],
                       coverage=a.get("coverage"),
                       rank=s["rank"], interval=s["interval"], why=why)


# ── the level-0 oracle: WordNet's own recorded kind ───────────────────────────────────────────────
def kind_of(synset_name: str) -> List[str]:
    """The kinds the corpus records for this concept — its own hypernyms' lemmas. The answer key.

    Read from `crystal.ontology.driver`, i.e. from the same corpus the answerer draws on but through
    the record rather than through the answer path, which is what makes it an oracle rather than a
    second opinion from the mechanism under test. `instance_hypernyms` are included because a named
    entity (`paris` → `national capital`) has its kind recorded on that edge and nowhere else."""
    from crystal.ontology import driver as wn
    out: List[str] = []
    try:
        s = wn.synset(synset_name)
    except Exception:
        return out
    for h in list(s.hypernyms() or []) + list(s.instance_hypernyms() or []):
        try:
            for lem in h.lemmas():
                w = str(lem.name()).replace("_", " ").strip().lower()
                if w and w not in out:
                    out.append(w)
        except Exception:
            continue
    return out


def states_the_kind(answer_text: str, synset_name: str) -> bool:
    """Did this answer state a kind the corpus itself records for this concept?

    A containment check on the answer text, because the level-0 assertion is about what was said —
    "name a thing and give its kind" — and the answer is the corpus's own gloss and relation labels
    (paper §17: the words are the corpus's). No parsing, no model, no similarity: the key is a list
    of surface forms the store holds, and either one of them is in what was said or none is."""
    if not answer_text:
        return False
    hay = " " + str(answer_text).replace("_", " ").lower() + " "
    return any((" " + k + " ") in hay or hay.strip().endswith(" " + k)
               for k in kind_of(synset_name))


# ── registration — lumen's op.curriculum.certify ──────────────────────────────────────────────────
_CURRICULUM_OPS = [
    ("op.curriculum.certify",
     "certify a curriculum LEVEL: the resolved rank has settled (the Weyl interval collapsed onto "
     "K_signal) AND the observer answers held-out questions above the exact re-paired null by more "
     "than the standard error at that sample size. No pass mark, no plateau tolerance; an "
     "unmeasured half certifies nothing"),
]


# ADDED 2026-08-26. Operators were registered with NO `collection_id`, and the content seal keys
# on a collection origin root — so they could never be sealed and
# `data_integrity_check.artifacts_holding_inline_plaintext` climbed off zero on every boot. The
# repair that first drove that count to zero gave collectionless platform vocabulary `stage.system`
# "rather than an exemption"; the writers were never changed. This is that fix reaching the writer.
# `collection_id` alone suffices — `vertex._place` writes the origin containment edge from it, in
# the same savepoint as the row. Inlined, not shared: `_persona.load()` loads these modules
# individually and cross-importing between them is the hazard that module exists to prevent.
_SYSTEM_COLLECTION = "stage.system"


def _now_iso() -> str:
    """This observer's clock reading, claimed. The store never invents one (`vertex._attribute`
    returns untouched when `created_time` is None) and it is first-write-wins."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


#: Read ONCE per process, not per call. `manifest.OPERATORS = operators()` is computed at import
#: while `operators()` recomputes on demand, and `test_the_lumen_manifest_surface_is_unchanged_for_
#: the_host` asserts the two are equal — a fresh timestamp per call makes that impossible, and it
#: also makes the registered dict non-deterministic for anything that compares payloads. Reading
#: the clock at import gives one claim per process, which is what an idempotent upsert wants:
#: first-write-wins means only the first one is ever kept anyway.
_REGISTERED_AT = _now_iso()


def register_curriculum_operators(store, *, author: str = "ember-local") -> int:
    """Register lumen's curriculum operator(s). Mirrors `register_check_operators`."""
    from crystal import evolution
    from crystal.evolution import OPERATOR_CONTENT_TYPE
    for name, offer in _CURRICULUM_OPS:
        store.put_artifact(evolution.preserve_fitness(store, {
            "id": name, "content_type": OPERATOR_CONTENT_TYPE, "state": "committed",
            "context": offer, "content": "lumen curriculum operator %s: %s" % (name, offer),
            "created_by": author,
            "collection_id": _SYSTEM_COLLECTION, "created_time": _REGISTERED_AT}))
    return len(_CURRICULUM_OPS)


__all__ = ["LEVELS", "Certificate", "settled", "answers", "certify",
           "kind_of", "states_the_kind", "register_curriculum_operators"]
