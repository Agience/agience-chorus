"""The conversation tekton — the three acts (respond / think / learn / act) over the triple-transistor.

This module is the persona definition of the conversation acts: the triple-transistor
(context/operator/content), grounding a footprint into (subject, relation, object) by order, generalizing
through templates, and recording each turn private + owner-scoped. Ember is a runner: it keeps the
recognition/activation measurement layer (which concepts a signal fires — `ember.ontology.activation`: seeds,
spread, rank, recognize, activate, compose/render, the instrument read) as the grounding the runner keeps, and
reaches `op.respond`/etc. over the ground plane (`lumen/reach_provider.py`). A host with no live fabric wired
gets an honest, inactive default rather than a fabricated answer.

The recognition/rendering primitives stay in ember and are reached back through `_A` (persona to ember, both
AGPL): `_A.recognize / spread_seeds / _seed_field / seeds_from_text / vertex_field / compose /
output_membrane / _word / _tokens / _async_write`. The constants come from `prism.grounding` (the stable
Apache surface). `_ensure_private` (the grant-minter) stays `ember.genesis`.

No forcing code — the geometry decides grounding (thing/relation/hole), the hole is localized by order,
and which slot is the hole selects the triple-solve:
    response = context + operator -> content   (deduce the missing object)   object hole
    thought  = content + operator -> context   (abduce the missing subject)  subject hole
    learn    = context + content  -> operator  (induce the relation)         no hole (a statement)
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from prism.grounding import TRIPLE_TYPE, P_HUMAN, CITE_GENESIS, _now

# Recognition — grounding text into activation state over the ontology coordinate — is a measurement
# the runner performs and it does not move here: the runner reads its own `activation` from `genesis.py`,
# `signal/signal.py`, and `surface/serve.py`. `ARCHITECTURE-TARGET.md` §2 forbids a sideways edge between
# chorus and ember in either direction, so the persona declares the measurement by name and the host says
# which module answers it.
#
# `_A` reads exactly as the activation module does — every `_A.recognize(...)`, `_A._tokens(...)`,
# `_A.compose(...)` below calls straight through — but it resolves on first attribute access rather than
# at import. That is the load-bearing part: an importer of this module does not have to be a host, while
# asking it to recognise anything does, and gets `HostSeamUnfilled` (an `ImportError`) if there is none.
from _host_seams import seam as _seam

_A = _seam("activation")

# A chat turn's payload is a message (not a truth claim). A taught relation's payload is a triple
# (`TRIPLE_TYPE`, context/operator/content). Kept private + owner-scoped until an explicit op.share.
MESSAGE_TYPE = "application/vnd.agience.message+json"

# The store's id prefix for a WordNet synset. Named so the strip is `len(_WN_PREFIX)` and not a `3`
# a reader has to count characters to check — the same reason `output_screen._WN` exists. Citations
# carry artifact ids (`wn-dog.n.01`); activations carry concept names (`dog.n.01`).
_WN_PREFIX = "wn-"


#: How a bare store becomes a Delegate, when the host wants to say. `None` = nobody injected one.
#: Set by whoever assembles the process (`chorus/reach_host.py`, an ember runner); see `_as_delegate`.
_DELEGATE_RESOLVER = None


def set_delegate_resolver(fn) -> None:
    """Inject `(store, person) -> Delegate`. `None` unwires it.

    The host owns cognition, so the host may name how one is obtained. Unwired is not an error — the
    fallback below still works — so this is a way to close a dependency, never a new requirement."""
    global _DELEGATE_RESOLVER
    _DELEGATE_RESOLVER = fn


def _as_delegate(target, principal: str = None):
    """Resolve to a Delegate. Constructing one is the last option, tried only once nothing cheaper answers.

    Order: an already-built Delegate, then the host's injected resolver, then the host's `delegate` seam.
    Each step is strictly more coupled than the one before, so the cheapest correct answer wins and the
    runner is reached only when nothing else can.

    The store shape is the live production path, not a legacy one: `reach_provider.store_respond`, which
    is how lumen serves `op.respond` over the plane, calls `fn(store, …)`. The Delegate branch is internal
    re-entry (`learn` → `respond`) and tests.

    Which module supplies cognition is the host's answer at every step — step 2 as an injected callable,
    step 3 as a registered module name via the host's `delegate` seam — so neither step reaches sideways
    from chorus into ember by name.

    One Delegate per process per person on the store path (`Delegate.get` is a registry). A caller
    genuinely serving multiple agents must pass a Delegate, or they share cognition — which is the single
    thing the runner's delegate module exists to prevent (pooled witnesses turn first-hand memory into
    hearsay; a busy neighbour deletes a quiet agent's memory by advancing the tick). An unfilled seam
    raises here rather than degrading: there is no honest stand-in for cognition, and inventing a per-call
    delegate would reintroduce the shared state the registry prevents."""
    from prism.delegate import is_delegate
    if is_delegate(target):
        return target                       # 1. already cognition — nothing to resolve
    if _DELEGATE_RESOLVER is not None:
        return _DELEGATE_RESOLVER(target, principal)   # 2. the host said how
    return _seam("delegate").Delegate.get(target, person=principal)   # 3. last: the host's own, by name


# ── grounding: the corpus decides each token's role — thing / relation / hole (no lists, no POS rules)
def _role_counts(tok: str) -> Tuple[int, int, bool, bool, int, int]:
    """(noun_freq, verb_freq, has_noun, has_verb, n_noun_senses, n_verb_senses).

    The first pair is SemCor sense frequency — how often this word is used as each POS — the same MFS
    currency recognize() ranks with. It is 0 across the board on a corpus enriched without lemma counts,
    so `_ground` falls back to the second pair, the sense-count ratio (how many noun vs verb readings
    WordNet lists), which the store always carries. Neither is a verb list."""
    from crystal.ontology import driver as wn
    nsyn = wn.synsets(tok, pos=wn.NOUN)
    vsyn = wn.synsets(tok, pos=wn.VERB)

    def cnt(syns):
        return max((l.count() for s in syns for l in s.lemmas()), default=0)
    return cnt(nsyn), cnt(vsyn), bool(nsyn), bool(vsyn), len(nsyn), len(vsyn)


def _ground(text: str) -> List[Dict[str, Any]]:
    """Tag each ordered token by what the corpus knows it can be — not one exclusive role. A token is
    concept-eligible if it has a meaning-coordinate (a noun sense); relation-eligible if its relational
    reading dominates (verb count > noun count); a hole if the geometry has neither. Which role it plays
    is decided in `_triple` by order, not here. Pure grounding: the corpus answers, nothing is hand-listed."""
    slots = []
    for i, tok in enumerate(_A._tokens(text)):
        nc, vc, hn, hv, nn, nv = _role_counts(tok)
        # Use the SemCor measurement when it exists, fall back to the sense-count ratio when it does not
        # (`says` 11:1, `eat` 6:0 read verb-dominant; `dog` 1:7, `woof` 0:1 read concept). Not a verb list.
        relation = bool(hv) and (vc > nc if (vc or nc) else nv > nn)
        slots.append({"pos": i, "tok": tok,
                      "concept": hn,                 # has a noun meaning-coordinate
                      "relation": relation,          # verb dominates: measured freq, else sense-count prior
                      "hole": not hn and not hv})    # ungrounded — no coordinate at all
    return slots


def _triple(text: str) -> Dict[str, Any]:
    """Read the footprint into (subject, relation, object) + where the hole is, from grounding + order.
    There is exactly one relation per predication: the first verb-dominant token that has a concept
    before it (a real subject-verb). A verb-dominant token with no concept before it is an auxiliary /
    subject-inversion marker (how a question inverts structurally) — skipped, letting the object/subject
    hole route the act. A leading relation (nothing before it) is a request/imperative. No is_question,
    no auxiliary list — order and the corpus decide."""
    slots = _ground(text)
    concepts = [s for s in slots if s["concept"]]
    rel_cands = [s for s in slots if s["relation"]]
    holes = [s for s in slots if s["hole"]]
    rel = next((r for r in rel_cands if any(c["pos"] < r["pos"] for c in concepts)),
               rel_cands[0] if rel_cands else None)
    leading = rel is not None and not any(c["pos"] < rel["pos"] for c in concepts) \
                              and not any(h["pos"] < rel["pos"] for h in holes)
    subj = obj = None
    if rel is not None:
        before = [c for c in concepts if c["pos"] < rel["pos"]]   # rel's own position excludes itself
        after = [c for c in concepts if c["pos"] > rel["pos"]]
        subj = before[-1]["tok"] if before else None
        obj = after[0]["tok"] if after else None
    topic = concepts[0]["tok"] if concepts else None
    return {"relation": rel["tok"] if rel else None, "subject": subj, "object": obj,
            "leading": leading, "topic": topic, "has_relation": rel is not None}


# ── generalization through templates: form categories from what this owner has been taught ───────
def _region(d, relation: str, side: str) -> Optional[str]:
    """The category of one side of a relation, generalized from what's been taught via templates.py.
    side='subject': what kind of thing does <relation> (dog/cat/bird -> vertebrate) — used to check a
    new subject fits the pattern. side='object': what kind of thing gets <relation>ed (woof/meow/tweet
    -> sound) — this is the predicted answer when the object is a hole. Returns a readable region word,
    or None when what has been taught does not compress into a category.

    No minimum-sample count gates this: the corpus answers it. `templates` resolves clumps by maximising
    compression, and its own measure of whether a clump is a generalisation rather than a restatement is
    the clump gain `(n - 1) · IC(region)` — the bits saved by describing the members as one region.
    Positive gain is a category formed; zero is these points being their own best description. A
    singleton falls out of that measure for free (`n - 1 = 0`), with no separate count to type."""
    try:
        from crystal.ontology import driver as wn
        try:                                              # robust: cross-persona host vs in-persona process
            from lumen import templates                   # (chorus/src on path)
        except ImportError:
            import templates                              # (lumen/ on path — moved with this tekton)
        pts = []
        for f in d.obs_matching(relation=relation):
            ss = wn.synsets(f.get(side, ""), pos=wn.NOUN)
            if ss:
                pts.append(ss[0])
        if not pts:
            return None                    # nothing taught — no measurement, so no assertion
        tmpls = templates.form_templates(pts)
        biggest = max(tmpls, key=lambda t: len(t.members))
        if biggest.region is None:
            return None
        # The corpus's own compression reading, not a count: `templates._clump_gain`'s formula.
        gain = (len(biggest.members) - 1) * float(biggest.region_ic)
        return _A._word(biggest.label()) if gain > 0.0 else None
    except Exception:
        return None



def _quantitative(text: str) -> Optional[Dict[str, Any]]:
    """Offer the need to `op.reason`. Returns a contribution, or None when there is nothing to say.

    This is the chat path's own entry to deterministic numeric reasoning: a person can paste a time
    series into the chat and have it reach `op.reason` from here, alongside whatever the ontology path
    grounds.

    `parse_trajectory` does not classify the question — it extracts the longest run of consecutive
    numeric rows actually present in the text and returns `None` when there are none. That `None` is a
    measurement over the input, not a predicate about what kind of need this is: an arm returning None
    is the honest null, distinct from an arm being skipped by a predicate.

    A contribution here does not replace the ontology path — the caller prepends it and unions the
    citations, so a turn carrying both a series and a concept says both. A non-compact read contributes
    nothing and the turn is byte-identical to one with no numeric arm: the instrument identified no
    operator, which is a reading of the data, not a trend fabricated from a spectrum that resolved none.

    Read-only. `persist_turn` is not called: chat is read-only by standing rule, and a forecast is a
    computation over what the asker supplied, not an observation of the world. Nothing is written."""
    try:
        from lumen import reasoning as _R
    except ImportError:
        import reasoning as _R
    try:
        X = _R.parse_trajectory(text or "")
        if X is None:
            return None                      # no series present — a measurement, not a refusal
        res = _R.ReasoningRouter().reason([X], X, dt=1.0)
    except Exception:
        return None                          # additive — the arm never costs the turn its answer
    if res.regime != _R.DETERMINISTIC or res.forecast is None:
        # The instrument resolved no proper compact subspace, or the operator it fitted does not
        # decay. That is the computed null for this arm, and it is reported rather than inferred
        # from silence — but it says nothing to the asker, because naming the silence is itself a
        # fabrication. `why` rides along for the caller and the logs, which is where the difference
        # between "nothing resolved" and "this is a drift, not a law" is worth having.
        return {"regime": res.regime, "complexity": int(res.complexity), "text": "", "cited": [],
                "why": res.why}
    import numpy as _np
    fc = _np.asarray(res.forecast)
    rows = "; ".join("[" + ", ".join("%.4g" % v for v in r) + "]" for r in fc)
    # This cites nothing, and says what it is instead. `op.reason` is an operator artifact that may or
    # may not be registered on a given store, and even where it is, citing it would claim corpus grounding
    # for a computation over numbers the asker supplied — not an assertion the lattice attests to.
    # Downstream, the bff derives `grounded = bool(cited)`, so a turn answered only by this arm reports
    # `grounded: false` with its text — a computation offered as a computation. A turn that also resolved
    # a concept keeps the ontology leg's real citations and its grounding, because the two legs are unioned.
    #
    # The horizon is the operator's — `ℓ = ⌈ln(contrast)/(−ln|μ|)⌉`, the step at which the dominant mode
    # reaches this frame's own noise floor. It is reported at the length it was computed at.
    #
    # `|μ|` is reported beside it, because the horizon alone cannot be read. A dominant mode at
    # 0.90 and one at 0.997 are both "decaying" and both pass the gate, but the second is a mode
    # that barely decays at all — a level shift reads that way — and it buys a horizon of hundreds
    # of steps from a series that may only be correlated over tens. Stating both lets the asker see
    # a long horizon for what it is rather than for confidence.
    return {"regime": res.regime, "complexity": int(res.complexity),
            "margin": res.margin, "horizon": res.horizon,
            "text": ("Deterministic read of the numeric series YOU SUPPLIED (K_signal=%d, %d modes "
                     "above the frame's own noise floor; dominant mode |mu|=%.4f, so the operator's "
                     "own horizon is %d step(s)). This is computed from that series alone "
                     "and is NOT grounded in the corpus. UNVERIFIED projection — a linear operator "
                     "was fitted and rolled forward, with no in-sample error measured — next %d "
                     "steps: %s"
                     % (res.complexity, res.complexity, res.margin if res.margin is not None else
                        float("nan"), res.horizon or len(fc), len(fc), rows)),
            "cited": [], "forecast": fc.tolist()}


# ── the three acts ───────────────────────────────────────────────────────────────────────────────
def respond(target, text: str, *, principal: str = None, tri: Dict[str, Any] = None) -> Dict[str, Any]:
    """Complete the open terminal by activation over the taught offers (`_answer_by_offers`
    handles deduce and abduce and verify — the transistor decides which by whichever terminal the need
    leaves open), else describe the topic (a need against the corpus offers) through the output screen.

    Recall is the activation-completed terminal (stated plainly, provenance in the citation), and
    generalization is the DAG propagation, not a template scaffold. `target` is a Delegate (preferred)
    or a store (legacy — resolves this process's delegate)."""
    d = _as_delegate(target, principal)
    store = d.store
    off = _answer_by_offers(d, text)
    if off is not None:
        # Nothing observes a concept here. What a turn observed is deposited by `compose` via
        # `_observe_field`, from the concepts it actually resolved — an offer matched here is matched
        # by word, so there is no resolved concept for this path to offer instead.
        return off
    # A need may name a signed relation — the relation carries its own `sign` and `names` (data). A
    # negative operator ("opposite") asks for the far side of the coupling: the concept the mix placed
    # at negative energy, read off the settled field. No per-relation branch — the sign is on the edge.
    from crystal.ontology.coupling import SEED_ETYPE_COUPLING
    _optoks = set(_A._tokens(text))
    if any(spec.get("sign", 0.0) < 0 and (_optoks & set(spec.get("names", [])))
           for spec in SEED_ETYPE_COUPLING.values()):
        field = _A.spread_seeds(_A._seed_field(store, text))
        poles = [(n, e) for n, e in field.items() if e < 0.0 and _A._word(n) not in _optoks]
        if poles:
            w = _A._word(min(poles, key=lambda kv: kv[1])[0]).replace("_", " ")   # the most-opposed
            _record_private(d, text, w.capitalize() + ".", [])
            return {"answer": w.capitalize() + ".", "deduced": [w], "activations": [],
                    "cited": [CITE_GENESIS]}
    tri = tri or _triple(text)
    acts = _A.recognize(store, text, d=d)
    # Describe grounds on a concept the need actually named (its word is a query token), and not on the
    # operator (you describe the things — the context/content terminals — never the gate). Fall back to
    # all if none survive.
    from crystal.ontology import driver as _wn
    _toks = set(_A._tokens(text))
    for _t in list(_toks):                               # match on the lemma too: "dogs" -> "dog"
        try:
            _b = _wn.morphy(_t, _wn.NOUN)
            if _b:
                _toks.add(_b)
        except Exception:
            pass
    _op = tri.get("relation")
    # The reasoning screen — the full field at the vertex: input signal ⊕ cooling memory ⊕ the delegate's
    # own corpus offers that attraction pulls in. Read on the full acts, before the compose filter.
    vertex = _A.vertex_field(d, acts)
    # No set-membership filter narrows this to concepts the need already named. The field is already
    # ordered by salience, so an operator or an incidental co-activation ranks itself down on its own;
    # the one rule that survives is that the answer describes the things, never the gate, so the
    # relation token is excluded here and nothing else needs to be.
    acts_for_compose = [a for a in acts if _A._word(a["concept"]) != _op] or acts
    # The resonant flood is off the answer path. `output_screen.resonant_placement` was a breadth-first
    # flood: every frontier node expanding to every hypernym, every hyponym, and every one of the 24
    # related types, round after round, until weights ground down to the corpus propagation floor — on the live
    # lexicon, seed `dog.n.01`, that reaches 64% of the ~117k synsets, and the answer text is
    # byte-identical with the flood on or off. A near-uniform field over most of the corpus is not a
    # neighbourhood; it is the graph, and its extra citations were swept up rather than selected.
    #
    # What replaces it is a read at the answer's own concepts: the leads' own incident edges are read
    # from the store (a keyed edge lookup), stacked as one ordered frame at the far endpoint's measured
    # salience, and split by `absorb_transmit` against the leads' own coupling band — what is absorbed
    # is stated. Forgetting is the screen's own job, not this walk's: decay is measured per screen and
    # verified live (`tau_fast` 0.26 / `tau_slow` 24.9, D1).
    _cont = {"placed": 0, "reached": 0, "seed": None,
             "why": "the resonant flood is off the answer path — see the note above"}
    answer, cites = _A.compose(store, text, acts_for_compose, person=d.person, delegate=d)
    # The quantitative arm — `op.reason` is offered the same need, and what it grounds propagates
    # alongside what the ontology grounded rather than replacing it: everything that grounded
    # propagates, nothing is picked. A need carrying both a pasted series and a concept says both; a
    # need carrying neither is byte-identical to one without this arm. See `_quantitative`.
    _quant = _quantitative(text)
    if _quant and _quant.get("text"):
        answer = (_quant["text"] + "\n\n" + answer) if (answer or "").strip() else _quant["text"]
        cites = list(cites) + [c for c in _quant.get("cited", []) if c not in cites]
    _record_private(d, text, answer, acts_for_compose)
    # `compose` observes the lead it actually resolved; `topic` (the first token with any noun sense,
    # which for a question is often the interrogative or copula) is not used here.
    #
    # The output screen reads the answer's concepts back through the instrument — the symmetric twin of
    # the input screen — and measures whether the concepts about to be said are one coherent, resolved
    # thing. It receives only the concepts `compose` resolved and rendered, not the whole placed field:
    # `cites` holds the artifact of every gloss `_render_concept` stated plus every endpoint
    # `_stated_relations` stated, i.e. exactly what came out. The field itself is untouched and still
    # rides out on `activations`; this is the output screen reading only the output.
    _said = {c[len(_WN_PREFIX):] if str(c).startswith(_WN_PREFIX) else str(c) for c in (cites or [])}
    _said_acts = [a for a in acts_for_compose if a.get("concept") in _said]
    return {"answer": answer, "activations": acts_for_compose, "cited": cites,
            "screen": _A.output_membrane(store, _said_acts), "vertex": vertex,
            # What the operator did, including when it did nothing — see `_with_operator_continuation`.
            # Placing nothing is a reading of this corpus, not an absence of one, so it is reported
            # rather than inferred from the answer being unchanged.
            "continuation": _cont,
            # What `op.reason` read, including its null result. `None` = no numeric series was present;
            # a dict with `regime: non_compact` = a series was present and the instrument resolved no
            # proper compact subspace. Those are different facts and only one of them is about the
            # data, so they are not both reported as absence.
            "quantitative": _quant}


def think(target, text: str, *, principal: str = None, tri: Dict[str, Any] = None) -> Dict[str, Any]:
    """Abduce context — the same transistor completion as `respond`, just the other open
    terminal. `_answer_by_offers` already reads off whichever terminal the need leaves open, so thought
    and response are one operation over the triple; kept as a named entry for `op.thought`."""
    r = respond(target, text, principal=principal, tri=tri)
    return {"thought": True, "abduced": r.get("abduced", []), "answer": r.get("answer"),
            "cited": r.get("cited", []), "activations": r.get("activations", [])}


def learn(target, text: str, *, principal: str = None, tri: Dict[str, Any] = None) -> Dict[str, Any]:
    """Induce operator. A statement with all three slots filled records the relation linking
    context->content as a private, owner-scoped observation (no_promote — a bare assertion never enters
    the shared corpus without op.share). If the exact triple was already taught, this is recognition,
    not new learning (verify): acknowledge it instead of duplicating."""
    from mantle import lattice_mint as genesis
    d = _as_delegate(target, principal)
    store, who = d.store, d.person
    tri = tri or _triple(text)
    subj, rel, obj = tri["subject"], tri["relation"], tri["object"]
    if not (subj and rel and obj):
        return respond(d, text)                                   # not a complete statement -> describe

    if d.obs_matching(relation=rel, subject=subj, obj=obj):        # this exact value is current = verify
        # Recognising an offer one already holds records nothing new, by construction.
        return {"learned": False, "verified": True,
                "answer": f"{subj.capitalize()} {rel} {obj}."}    # the resolved offer, stated; no wrapper

    # Replace old / refuted information through versioning — the offer's identity is (context, operator);
    # the content is its value. A new value for the same subject+relation is a new version of the same
    # artifact (same id), so the lattice snapshots the prior and the head is the latest.
    replaced = [f.get("object") for f in d.obs_matching(relation=rel, subject=subj)
                if f.get("object") != obj]

    # Load-bearing: this mints the owner's Read grant on `private.<who>`, the only thing that makes the
    # triple below non-public (no flag any more). A failure must abort, not silently leak.
    genesis._ensure_private(store, who)
    # The offer's identity is (context, operator) — the id hashes the delegate too, so two delegates of
    # one person keep separate lineages; a new object is a new version of this artifact (same id).
    oid = "obs." + hashlib.sha256((d.id + "\n" + who + subj + rel).encode()).hexdigest()[:16]
    doc = {
        "id": oid, "content_type": TRIPLE_TYPE, "state": "committed",
        # non-public via the grant on `private.<who>` (minted above); ownership = that grant, not a field
        "collection_id": f"private.{who}", "collections": [f"private.{who}"],
        "subject": subj, "relation": rel, "object": obj,
        "context": subj, "content": obj, "operator": rel,             # the triple: ctx+content -> operator
        "lemmas": [subj, obj], "via": "op.learn",
        "provenance": P_HUMAN, "cited_from": CITE_GENESIS,
        # `_author_ref(store, who)`, not the bare `who`. Contract §2.1: `created_by` is a vertex
        # reference, and `person_id` derives it as `uuid5(_USER_NS, issuer\nsub)`, so writing the raw
        # claim (e.g. an email address) would cite a vertex the canonical minting path never creates —
        # a dangling reference that does not error, so authorization stops flowing through it silently
        # while the store still reads healthy. `_author_ref` is idempotent, mints the person artifact
        # if absent, and passes a process author through unchanged (§5.7).
        # Only `created_by` moves. `who` stays the raw principal everywhere else — it names the
        # `private.<who>` collection the grant is minted on and is hashed into `oid`, so substituting the
        # derived id there would rename the collection and re-identify the artifact.
        "created_by": genesis._author_ref(store, who), "created_time": _now(),
        "delegate": d.id, "host": d.host, "authority": d.origin,      # provenance: origin/person/host
    }
    d.remember_obs(doc)                     # replaces the prior version in the in-memory field (by id)
    _A._async_write(lambda: store.artifacts.put_artifact(doc))   # same id -> the lattice versions it (head=latest)
    return {"learned": True, "triple": {"subject": subj, "relation": rel, "object": obj},
            "replaced": replaced, "answer": f"{subj.capitalize()} {rel} {obj}."}


# ── the triple as a transistor: two terminals determine the third ─────────────────────────────────
#     context + operator -> content   (deduce / respond)
#     content + operator -> context   (abduce / think)
#     context + content  -> operator  (induce / learn — a new transform; still needs slot-ID on write)
def _answer_by_offers(d, text: str):
    """Complete the triple-transistor from the taught offers, or None when nothing is reached.

    This is an activation, not a lookup. The need activates the field (its own words spread up the
    ontology via `_A._seed_field` + `_A.spread_seeds`), so a terminal is reached when the offer's
    context/content lies anywhere on the activated frontier — not only when a token matches it exactly.
    Matches are ranked by how strongly the need activated the covered terminal — the strongest path first."""
    from crystal.ontology import driver as wn
    d.load_obs()

    def vlem(w):
        try:
            return wn.morphy(w, wn.VERB) or w
        except Exception:
            return w
    toks = set(_A._tokens(text))
    named = toks | {vlem(t) for t in toks}            # the gate names: words + their verb lemmas
    # The activation frontier, folded to words (offers store the word, `spread_seeds` keys by synset).
    word_energy: Dict[str, float] = {}
    try:
        for name, e in _A.spread_seeds(_A._seed_field(d.store, text)).items():
            try:
                w = _A._word(name)
            except Exception:
                continue
            if e > word_energy.get(w, 0.0):
                word_energy[w] = float(e)
    except Exception:
        pass

    def energy(concept: str) -> float:
        if concept in toks:
            return 1.0                                # named directly by the need
        return float(word_energy.get(concept, 0.0))   # reached along a path (0 = not reached)
    with d._obs_lock:
        offers = list(d.obs)
    deduced, abduced, verified = [], [], []
    for f in offers:
        op = f.get("operator") or f.get("relation") or ""
        if not op or vlem(op) not in named:           # the gate (operator) must be named by the need
            continue
        ctx = f.get("context") or f.get("subject") or ""
        content = f.get("content") or f.get("object") or ""
        ce, one = energy(ctx), energy(content)
        if ce > 0.0 and one <= 0.0:
            deduced.append((content, ce))             # ctx reached + op -> traverse to content
        elif one > 0.0 and ce <= 0.0:
            abduced.append((ctx, one))                # content reached + op -> traverse to ctx
        elif ce > 0.0 and one > 0.0:
            verified.append((ctx, op, content, ce + one))

    def _rank(pairs):
        return [p for p, _ in sorted(dict((p, e) for p, e in pairs).items(), key=lambda kv: -kv[1])]
    if deduced:
        objs = _rank(deduced)
        ans = ", ".join(o.capitalize() for o in objs) + "."
        _record_private(d, text, ans, [])
        return {"answer": ans, "deduced": objs, "activations": [], "cited": [CITE_GENESIS]}
    if abduced:
        subs = _rank(abduced)
        ans = ", ".join(s.capitalize() for s in subs) + "."
        _record_private(d, text, ans, [])
        return {"answer": ans, "abduced": subs, "activations": [], "cited": [CITE_GENESIS]}
    if verified:
        c, o, ct, _ = max(verified, key=lambda v: v[3])
        return {"answer": f"Yes — {c} {o} {ct}.", "verified": True,
                "activations": [], "cited": [CITE_GENESIS]}
    return None


def act(target, text: str, *, principal: str = None) -> Dict[str, Any]:
    """Complete the triple-transistor. First try need->offer over the taught offers (the operator is
    named, the open terminal is read off — no grammar parse). If no taught operator is named, it is a
    describe (a need against the corpus offers) or a learn (a statement whose operator is new)."""
    d = _as_delegate(target, principal)
    tri = _triple(text)
    # A question is never stored. An interrogative grounds to no concept and no operator — it is the
    # open-terminal / need marker. Chat is read-only except for what is unambiguously a complete statement.
    has_hole = any(s["hole"] for s in _ground(text))
    if tri["has_relation"] and tri["subject"] and tri["object"] and not has_hole:
        return learn(d, text, tri=tri)
    # An open terminal -> complete it by activation over offers; nothing recalled -> describe.
    return respond(d, text, tri=tri)


def _record_private(d, query: str, answer: str, acts) -> None:
    """Record the chat turn as a message — private + owner-scoped (no_share, no_promote) until op.share.
    A message is a cooling footprint; the durable knowledge it may induce is a separate triple (learn)."""
    try:
        from mantle import lattice_mint as genesis
        store, who = d.store, d.person
        genesis._ensure_private(store, who)          # load-bearing: mints the grant that gates this
        # Hashes the delegate too — two delegates of one person holding the same exchange are two turns.
        oid = "convo." + hashlib.sha256((d.id + "\n" + who + query + answer).encode()).hexdigest()[:16]
        doc = {
            "id": oid, "content_type": MESSAGE_TYPE,
            "state": "committed", "collection_id": f"private.{who}",   # gated by the grant, not a flag
            "collections": [f"private.{who}"],
            "context": query, "content": answer,
            # The full set of concepts a turn activated, not a truncated prefix: what a turn activated
            # is a fact about the turn and has no length to declare, and the answer is composed from
            # the whole field, so recording less than that would understate the provenance a recalled
            # turn can show.
            "activated": [a["concept"] for a in acts],
            "via": "op.respond", "operator": "op.respond",
            "provenance": P_HUMAN, "cited_from": CITE_GENESIS,
            # `_author_ref`, not the bare `who` — see the fuller note in `learn` above. `who` stays raw
            # for `private.<who>` and the `oid` hash.
            "created_by": genesis._author_ref(store, who), "created_time": _now(),
            "delegate": d.id, "host": d.host, "authority": d.origin,
        }
        _A._async_write(lambda: store.artifacts.put_artifact(doc))
    except Exception:
        pass


__all__ = ["respond", "think", "learn", "act", "MESSAGE_TYPE"]
