"""Condensation — what a tekton does to a reached set.

Propagation is bounded only by physics (§13.22): a signal travels until attenuation drops it below
the propagation floor, or until the structure runs out. So the answer cannot come from cutting what was
reached — a derived cut (`signal_end`) is still a cut, selecting a prefix and discarding the rest.

A condenser does not select. It resolves. The reached set is not a list of candidates to rank; it is
a diagram, and the answer is its colimit — the one object the whole diagram maps into, with branches
surviving only where they carry what that object does not.

Facet conducts, tekton condenses, organon is invoked by the condensation (§12).

── the basic condensers ────────────────────────────────────────────────────────────────────────
Five, and they are not a taxonomy someone invented — each is what a reached set of a particular
shape already is. The shape is measured, never guessed:

    define        one node dominates                        -> say what it is
    disambiguate   the shared object is vaguer than the ask  -> the word has several senses
    subsume        one tight family                          -> say what they all are, then what distinguishes them
    contrast       two separated groups                      -> say the difference
    enumerate      no structure at all                       -> say so, and list, honestly
    empty          nothing reached                           -> say nothing was reached

Which condenser applies is derived, not dispatched on a guess: `prism.resolution.partition` reports
whether the reached energies separate and where, and the ontology reports whether the members share
a subsumer and how informative it is. There is no rule table keyed on something like
"if len(results) > 5".

── at the asker's level ────────────────────────────────────────────────────────────────────────
The asker's own words sit somewhere in the ontology, and that position has an information content.
Answering far above it is vague ("a dog is an entity"); far below it is pedantic (a list of breeds).
So the resolution target is the asker's own IC — not a level anyone configured. `resolve_at` walks
the subsumer chain to the ancestor whose IC sits closest to what the question already carried.

That is why this is not "summarise the top N": the same reached set condenses differently for a
question asked at a different level, because the question moved the target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class Condensation:
    """What a reached set resolved to. Carries its own evidence, so a reader can always see why
    this shape was chosen rather than trusting that it was."""
    kind: str                                   # define | subsume | contrast | enumerate | empty
    head: Optional[str] = None                  # the object the diagram maps into
    members: List[str] = field(default_factory=list)
    distinguishing: List[str] = field(default_factory=list)
    basis: Dict[str, Any] = field(default_factory=dict)


def _syn(name: str):
    from crystal.ontology import driver as wn
    try:
        return wn.synset(name)
    except Exception:
        return None


def subsumer(names: Sequence[str]) -> Optional[str]:
    """The least common subsumer of a set — the taxonomic colimit.

    The object every member maps into, and the most informative such object: of the ancestors they
    all share, the one with the highest IC is the tightest statement true of all of them. Returns
    None when they share nothing, which is a real answer about a scattered set."""
    from crystal.ontology import geometry as g
    names = [n for n in names if _syn(n) is not None]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    ic = g.load_ic()
    common: Optional[set] = None
    for n in names:
        s = _syn(n)
        anc = {a.name() for a in s.common_hypernyms(s)} if s is not None else set()
        anc.add(n)
        common = anc if common is None else (common & anc)
        if not common:
            return None
    return max(common, key=lambda a: (g.ic_of(_syn(a), ic, strict=False), a))


def resolve_at(name: str, target_ic: float) -> str:
    """Walk `name` up to the ancestor whose IC sits closest to `target_ic` — the asker's level.

    Not "go up N levels": the chain is walked and the closest rung is taken, so a dense lineage and
    a sparse one both land at the same informational altitude rather than the same hop count. The
    same impurity §13.22 removed from propagation, removed here."""
    from crystal.ontology import geometry as g
    s = _syn(name)
    if s is None:
        return name
    ic = g.load_ic()
    best, best_gap = name, abs(g.ic_of(s, ic, strict=False) - target_ic)
    node = s
    while True:
        p = g.canonical_parent(node, ic)
        if p is None:
            return best
        gap = abs(g.ic_of(p, ic, strict=False) - target_ic)
        if gap < best_gap:
            best, best_gap = p.name(), gap
        elif g.ic_of(p, ic, strict=False) < target_ic:
            return best                       # past the target and still climbing: stop
        node = p


def _root_ic(ic) -> float:
    """The information content of the top of the tree — the corpus's own zero point for "this says
    nothing". Not a chosen floor: the root is the statement true of everything, so its IC is what
    "no information" measures as in this corpus. Measured 0.1571 on the live OEWN lattice."""
    from crystal.ontology import geometry as g
    from crystal.ontology import driver as wn
    # A store fault during the root scan must raise rather than be swallowed into a fabricated zero:
    # a fabricated 0.0, memoized for the process lifetime, would permanently open the gate whose
    # whole job is to reject grab-bags (`_is_scatter` tests `ic <= _ROOT_IC[0] + 1e-12`, which
    # nothing would then satisfy). A caller that cannot read the tree cannot decide what says
    # nothing in it.
    #
    # A synset with no parents is not necessarily a root — it may be an orphan. Every Open
    # Multilingual WordNet family lands with no hypernym edges at all, while the English taxonomy's
    # own roots are rare and genuinely parentless. An isolated synset with no structure has maximal
    # information content, so scanning "parentless" alone and taking the max would poison the zero
    # point to 1.0 and the gate would then refuse every set — the opposite failure from the
    # fabricated-zero case above, and both are invisible against a small fixture ontology where
    # every parentless synset really is a root.
    #
    # The discriminator is descendants, and it is structural rather than chosen: a root is the top
    # of something. `Synset` exposes only upward edges, so the child relation is recovered by
    # inverting them once. Restricted this way, a root must be both parentless and have children.
    #
    # `hypernyms()` is called once per synset, not twice: building `has_children` and then asking
    # `if s.hypernyms()` again would call the edge accessor twice for every noun in the corpus, and
    # this function sits on a query path where that cost is felt on every first use.
    has_children = set()
    parentless = []
    for s in wn.all_synsets(pos=wn.NOUN):
        parents = s.hypernyms() + s.instance_hypernyms()
        if parents:
            for h in parents:
                has_children.add(h.name())
        else:
            parentless.append(s)
    best = 0.0
    seen = False
    for s in parentless:
        if s.name() not in has_children:      # parentless and childless == an orphan, not a root
            continue
        seen = True
        best = max(best, g.ic_of(s, ic, strict=False))
    if not seen:
        # Let it raise rather than return a fabricated zero point — the same reason the comment
        # above gives for deleting `except Exception: return 0.0`. A tree with no root is not a
        # tree, and a caller that cannot find one cannot decide what says nothing in it.
        raise ValueError(
            "no taxonomy root: every noun synset is either parented or childless, so there is no "
            "'says nothing' to measure against. The ontology is not a tree in this store.")
    return best


_ROOT_IC: List[float] = []


def _is_scatter(name: Optional[str], ic) -> bool:
    """Does this subsumer say anything at all? A set whose least common subsumer is the root is not
    a family — it is a grab-bag that happens to share existence."""
    from crystal.ontology import geometry as g
    if name is None:
        return True
    if not _ROOT_IC:
        _ROOT_IC.append(_root_ic(ic))
    return g.ic_of(_syn(name), ic, strict=False) <= _ROOT_IC[0] + 1e-12


def _are_siblings(names: Sequence[str], head: str, ic) -> bool:
    """Do these members meet at the subsumer — i.e. is it their direct parent?

    Siblings under one parent are a family (say what they all are). Members that meet only far
    below their own parents are separate branches of a word (say which sense). Structural and
    exact: no distance, no threshold, no tuning."""
    from crystal.ontology import geometry as g
    for n in names:
        s = _syn(n)
        if s is None or s.name() == head:
            continue
        p = g.canonical_parent(s, ic)
        if p is None or p.name() != head:
            return False
    return True


def _branches(names: Sequence[str], head: str, ic) -> List[str]:
    """The distinct families within a reached set — one per branch under `head`.

    Each member is walked up until the step before `head`; members sharing that step are one sense.
    The branch's own subsumer names it. Ordered by first appearance, so the strongest sense leads."""
    from crystal.ontology import geometry as g
    groups: Dict[str, List[str]] = {}
    order: List[str] = []
    for n in names:
        node = _syn(n)
        if node is None:
            continue
        last = n
        while node is not None and node.name() != head:
            p = g.canonical_parent(node, ic)
            if p is None:
                break
            if p.name() == head:
                break
            last, node = p.name(), p
        if last not in groups:
            groups[last] = []
            order.append(last)
        groups[last].append(n)
    return [subsumer(groups[k]) or k for k in order]


def condense(reached: Sequence[Tuple[str, float]], *, asked_ic: Optional[float] = None,
             frame=None, coherent: Optional[bool] = None) -> Condensation:
    """Condense a reached set `[(synset_name, energy)]` into what it is.

    `asked_ic` is the information content the question itself carried; when given, the head is
    resolved to that altitude instead of to whatever level the members happen to sit at.

    The shape and count come from the ontology tree (subsumer / branches / siblings): the sense
    split is a graph fact. `coherent`, when supplied, is the screen's certified reading that the
    reach is one scale-invariant mode — it forces define. `frame` is accepted for callers that pass
    the screen along; the energy statistics (`partition` / `separated`) provide the fallback shape
    when no certified reading is present."""
    from prism.resolution import partition, separated, signal_end
    from crystal.ontology import geometry as g

    items = [(str(n), float(e)) for n, e in reached if _syn(str(n)) is not None]
    if not items:
        return Condensation(kind="empty", basis={"reached": 0})
    items.sort(key=lambda t: -t[1])
    names = [n for n, _e in items]
    energies = [e for _n, e in items]
    ic = g.load_ic()

    if len(items) == 1:
        head = names[0]
        return Condensation(kind="define", head=head, members=names,
                            basis={"reached": 1,
                                   "why": "a single node was reached"})

    cut, eta = partition(energies)
    is_sep = separated(energies)

    # The screen certifies one thing. The reached set's shape and count come from the tree
    # (subsumer / branches / siblings, below) because the sense split is a graph fact, not a metric
    # cluster — WordNet's coordinate is a smooth continuum, so there is no sharp integer to read off
    # it (§13.34). What the screen adds is a certified coherence: a reach whose coupling is
    # scale-invariant across the whole instrument is one thing, and that is a define regardless of what
    # the energy statistics say. `coherent` is read through the beam wrapper, never an instrument.
    if coherent is True:
        head = names[0]
        return Condensation(kind="define", head=head, members=names[:1],
                            basis={"reached": len(items), "eta": round(eta, 4),
                                   "coherent": True,
                                   "why": "the reach is one scale-invariant mode"})

    # ── define: one node carries the reading on its own ──────────────────────────────────────
    if is_sep and cut == 1:
        head = names[0]
        # The tail is energy-sorted, and its window is derived rather than a fixed count: where it
        # stops carrying signal is the same question `signal_end` answers for the cut itself, so
        # that is what bounds `distinguishing` here too.
        _tail = energies[1:]
        _d_end = (1 + signal_end(_tail)) if _tail else 1
        return Condensation(kind="define", head=head, members=names[:1],
                            distinguishing=names[1:_d_end],
                            basis={"reached": len(items), "eta": round(eta, 4),
                                   "coherent": coherent,
                                   "why": "the leading node separates from the rest on its own"})

    # ── contrast: the reached set is two groups, and the difference is the answer ─────────────
    if is_sep and cut > 1:
        top, rest = names[:cut], names[cut:]
        s_top, s_rest = subsumer(top), subsumer(rest)
        # A scatter is not a group: the tail of a reached set can be a grab-bag, and a grab-bag's
        # least common subsumer is always the top of the tree, so reporting that as one half of a
        # contrast would be a vacuous head one level down. A group is only a group if what it shares
        # says something, and the zero point for "says something" is not a chosen IC — it is the
        # root's own IC, which the corpus supplies. Below or at it, the set is scattered, not bound.
        if _is_scatter(s_top, ic) or _is_scatter(s_rest, ic):
            names, energies = top, energies[:cut]      # the tail is scatter: subsume what is bound
            s_top = s_rest = None
        if s_top and s_rest and s_top != s_rest:
            # A contrast has no head — the difference is the answer. Their joint subsumer, for two
            # genuinely unrelated groups, is typically the root, which is a true statement and a
            # useless one: an answer produced by the machinery's shape rather than by the reading.
            # What the two groups share is reported as evidence instead (`shared`, with its IC),
            # because a near-zero IC is the measurement that says "these have nothing in common",
            # which is precisely what makes the pair a contrast rather than a family.
            shared = subsumer([s_top, s_rest])
            shared_ic = g.ic_of(_syn(shared), ic, strict=False) if shared else 0.0
            # Each side is cut where its own energies stop separating, rather than taking a fixed
            # count from each: a fixed count from an energy-sorted contrast would discard exactly
            # the ambiguous middle that makes the contrast legible.
            _e_top, _e_rest = energies[:cut], energies[cut:]
            _n_top = signal_end(_e_top) if _e_top else len(top)
            _n_rest = signal_end(_e_rest) if _e_rest else len(rest)
            return Condensation(kind="contrast", head=None,
                                members=[s_top, s_rest],
                                distinguishing=top[:_n_top] + rest[:_n_rest],
                                basis={"reached": len(items), "cut": cut, "eta": round(eta, 4),
                                       "shared": shared, "shared_ic": round(shared_ic, 4),
                                                                              "why": "two groups separated, under different subsumers"})
        names, energies = top, energies[:cut]      # one group after all: subsume it

    # ── disambiguate: the set is not one thing at the level the question was asked ────────────
    # `resolve_at` cannot fix this case because it only walks up: a reached set spanning several
    # unrelated senses of a word subsumes to something already more general than the question, and
    # no amount of climbing makes those senses one family.
    #
    # That comparison is the whole test, and it needs no constant: when the subsumer carries less
    # information than the question already did, the answer is not a subsumption, it is an
    # ambiguity. Saying "a dog is a physical entity" to someone who asked what a dog is would be
    # true, vacuous, and produced by the machinery rather than by the reading.
    head = subsumer(names)
    if head is not None and asked_ic is not None:
        # "Vaguer than the question" is not sufficient on its own: `dog` and `cat` subsume to
        # `animal`, which is vaguer than a question asked at `dog`'s level, but they are siblings,
        # and siblings are a family, not an ambiguity. The distinction is structural and exact, so
        # it needs no threshold: members whose canonical parent is the subsumer meet at it (one
        # family, one step); members that meet only far below their own parents are separate
        # branches (distinct senses).
        if g.ic_of(_syn(head), ic, strict=False) < asked_ic and not _are_siblings(names, head, ic):
            senses = _branches(names, head, ic)
            if len(senses) > 1:
                return Condensation(kind="disambiguate", head=None, members=senses,
                                    distinguishing=names[:len(senses)],
                                    basis={"reached": len(items), "eta": round(eta, 4),
                                           "subsumer": head, "asked_ic": round(asked_ic, 4),
                                           "subsumer_ic": round(g.ic_of(_syn(head), ic,
                                                                        strict=False), 4),
                                                                                      "why": "the shared object is LESS informative than the "
                                                  "question: several distinct senses were reached"})

    # ── subsume: they share a subsumer, so say what they all are ─────────────────────────────
    if head is not None:
        head_ic = g.ic_of(_syn(head), ic, strict=False)
        if asked_ic is not None:
            head = resolve_at(head, asked_ic)
            head_ic = g.ic_of(_syn(head), ic, strict=False)
        # A member is distinguishing when it says something the head does not — i.e. it carries
        # more information than the head. Derived from IC, not from position in a list, and not
        # truncated to a fixed count: a truncation would narrow a genuinely wide subsumption back
        # to a guess.
        distinguishing = [n for n in names
                          if g.ic_of(_syn(n), ic, strict=False) > head_ic]
        return Condensation(kind="subsume", head=head, members=names,
                            distinguishing=distinguishing,
                            basis={"reached": len(items), "eta": round(eta, 4),
                                   "separated": is_sep, "head_ic": round(head_ic, 4),
                                   "asked_ic": (None if asked_ic is None else round(asked_ic, 4)),
                                                                      "why": "every member maps into one object"})

    # ── enumerate: nothing binds them, and saying so is the answer ───────────────────────────
    return Condensation(kind="enumerate", head=None, members=names,
                        basis={"reached": len(items), "eta": round(eta, 4),
                               "separated": is_sep,
                                                              "why": "the reached set shares no subsumer: it is not one thing"})


__all__ = ["Condensation", "condense", "subsumer", "resolve_at"]
