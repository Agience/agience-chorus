"""need → operator, geometrically — the operator-selection tekton.

`sage/operators.py` is the sole consumer: given a need with no exact suffix key, it propagates the need
over the registered operator offer vectors and picks the k nearest, with separation, so an unknown suffix
resolves to a measured operator instead of a lookup miss. That selection is sage's tool — it has zero ember
runtime callers ([[ember-is-a-runner]]: the tool lives in the persona, ember runs the measurement).

The split (mirrors P7): the measurement stays with the runner, and this tekton reaches it through the
declared `match` and `activation` seams (`_host_seams.seam`) — never by importing the host:
  · `match.propagate` — the screened propagator (`energy·exp(-d/XI)`, propagation floor) over `jc_tree`
    distances; the physics.
  · `match._offers` / `match.invalidate` — the per-store operator-offer table and its cache; the
    runner's `capability.register_operators` calls `invalidate`, and the runner cannot reach sage, so
    the cache and its invalidation stay there. This tekton reads the (freshly-invalidated) table.
  · `activation.spread_seeds/seeds_from_text` — grounds a phrase need into activation state.
  · `match.signal_offers` — how many ranked energies are signal and whether they separate at all,
    over `prism.resolution`, in place of a fixed page size and a top-two ratio.

ember and chorus are both L3, and `ARCHITECTURE-TARGET.md` §2 forbids the sideways edge between them, so
this tekton reaches the runner's measurement through the declared seams rather than importing it, and the
runner reads its own match and activation modules (`genesis.py`, `runtime/capability.py`,
`signal/signal.py`) rather than this file's. The tool stays in the persona, the measurement stays in the
runner, and the persona names the measurement by name.

`Cascade` (the propagation-in-flight termination guard) is standalone and rides along — it declares nothing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# `GAP` and `XI` are not importable here: `propagate` takes `xi=None` / `gap=None` and measures both
# itself (`match.xi()` / `match.propagation_floor()`), refusing where the corpus cannot report them, rather
# than this module re-exporting two numbers it does not measure and could not justify.
#
# One handle, resolved on first use: the seam is lazy, so importing `sage.match` does not require a
# host to be present — asking it to measure does.
from agience_chorus._host_seams import seam as _seam

_EM = _seam("match")


def select(store, need, *, xi: Optional[float] = None, gap: Optional[float] = None,
           content_type: str = "application/vnd.agience.operator+json",
           refresh: bool = False) -> Dict[str, Any]:
    """The k nearest operators to a need, by screened propagation through meaning-space.

    `need` may be activation state (`{synset_name: energy}` from `spread_seeds`) or a phrase.

    Each match carries both its accumulated `energy` and the actual geodesic `distance` to the
    nearest node of its offer — reporting the score without the distance is what let a cosine
    ranking look authoritative while being wrong.

    `basis` is `"geometric"` or `"unavailable"`; a caller must never have to guess whether the
    answer it got was measured.

    There is no `k` parameter and nothing is sliced: every scored offer comes back with its energy
    and distance, since the corpus is infinite and slicing on a page size is not a property of any
    need. `signal_end` is reported rather than applied: the derived count is a genuine reading — how
    many of the ranked energies stand above a column of that length with no structure — but slicing
    on it would destroy the rest, which is the conservation break this path avoids. `k` rides
    alongside as the reading, and `separated` / `separability` say whether the reading means
    anything. A caller wanting the lead takes `matches[0]`, which is what the only caller does."""
    if isinstance(need, dict):
        fired = {str(a): float(b) for a, b in need.items()}
    else:
        # Grounds through `op.ground` (`fired_field`), which weights each word by how much it
        # constrains the need and stays specific. The lineage-climbing alternative accumulates mass
        # at the abstract end, and a need grounded to `entity` sits a short geodesic distance from
        # every offer in the table, which ranks them by nothing.
        #
        # `_EM` is this module's already-resolved `match` seam: chorus names ember's measurement
        # rather than importing it.
        fired = _EM.fired_field(str(need), store)
    if not fired:
        return {"basis": "unavailable", "reason": "need did not ground (no nouns, or no geometry)",
                "matches": [], "unembeddable": [], "considered": 0}

    table = _EM._offers(store, content_type=content_type, refresh=refresh)
    if not table["nodes"]:
        return {"basis": "unavailable",
                "reason": "no operator offer grounded (%d considered)" % table["n"],
                "matches": [], "unembeddable": table["unembeddable"], "considered": table["n"]}

    # Open limitation: the `xi`/`gap` this returns are the caller's, which are `None` on every live
    # call, while `propagate` resolves and applies the corpus's measured `xi()` / `propagation_floor()`
    # internally. So the result reports `None` about a propagation that had definite physics behind
    # it — the recorded scale is not the one the verdict was reached at, which is the defect
    # `lumen/reasoning.py` is scarred for in its own certificate.
    #
    # Resolving `xi`/`gap` here and passing the resolved values down would change the measurement
    # rather than only the report: whatever `xi()` reads depends on state that `_offers` and
    # `EM.invalidate` move, so the identical-looking values, resolved one call earlier, are not
    # actually identical. An unexplained behaviour change in the propagation is a worse defect than
    # an under-reported field, so this reports what `propagate` was given, not what it resolved
    # internally, and leaves the resolution inside `propagate` where it already happens.
    scored = []
    for oid, targets in table["nodes"].items():
        energy, dist = _EM.propagate(fired, targets, xi=xi, gap=gap)
        if energy > 0.0:
            scored.append((oid, energy, dist, targets))
    scored.sort(key=lambda t: -t[1])

    # Separation, not just a ranking: if the top two are within noise of each other, there is no
    # winner and saying otherwise is fabrication. When the ontology does not contain a domain — for
    # example WordNet's most-frequent senses for technical vocabulary grounding to the everyday
    # sense of a word, or a term absent from WordNet entirely — offers ground to unrelated concepts
    # and the comparison is between two meaningless positions. The matcher is not wrong: it
    # faithfully measures distance in the ontology it was given, and the correct behaviour when the
    # ontology does not contain the domain is to refuse to pick rather than pick noise.
    #
    # What decides "separated" is not a fixed margin floor: two neighbours cannot answer a question
    # about a distribution (`prism/resolution.py`'s header takes this apart), so `signal_offers`
    # reads the whole energy column against the computed no-structure baseline for a column of that
    # length. `margin` survives as an amplitude — reported, never compared to anything.
    energies = [e for _, e, _, _ in scored]
    # `considered` is passed so the offers that scored zero can be reasoned about (they fell below
    # the propagation floor, so they are absent, not close) without being fed to the statistic — padding the
    # series with measured zeros would understate separation.
    read = _EM.signal_offers(energies, considered=table["n"])

    margin = 0.0
    if len(scored) >= 2 and scored[0][1] > 0:
        margin = (scored[0][1] - scored[1][1]) / scored[0][1]
    elif len(scored) == 1:
        margin = 1.0

    return {"basis": "geometric", "xi": xi, "gap": gap,
            # `separated` is three-valued: True / False / None = the column was too short for the
            # null to say anything (n <= 2, or no column at all). None is not False — "we could not
            # measure" is not "we measured, and they did not separate", and a caller doing
            # `if r["separated"]` correctly declines on both without conflating them.
            # Nothing here is rounded: a rounding would be a resolution claim ("the instrument
            # cannot separate two readings below this decimal") that nothing measured, and on
            # `energy` it is not cosmetic — the caller ranks on it, so quantising would manufacture
            # ties between offers the propagator had separated. Reported at the precision it was
            # measured at.
            "margin": margin, "separated": read["separated"],
            "separability": read["separability"],
            # the reading, not a cut: how many of these energies stand above the computed null.
            "k": read["k"], "k_derived": True,
            "matches": [{"operator": oid, "energy": e, "distance": d,
                         "nodes": len(t), "grounded": list(t)}
                        for oid, e, d, t in scored],
            "unembeddable": table["unembeddable"], "considered": table["n"]}


class Cascade:
    """A propagation in flight — what has already fired, so a cascade cannot sustain itself.

    Salience decay alone does not guarantee termination: a single spread attenuates with geodesic
    distance, but operator -> artifact -> operator rounds only decay if the artifacts actually move
    through meaning-space, and two operators regenerating each other's inputs at similar salience
    could sustain indefinitely. Same shape as the `_stack` guard `genesis.invoke` uses for
    composition cycles, applied to propagation instead of explicit steps.

    There is no `max_depth`: the operator set is finite and each member fires at most once, which is
    already a proof of termination, so a depth cap could only cut a legitimate cascade short before
    it naturally ended ([[no-arbitrary-caps]]: never clamp to bound runaway; the bound is derived).

    `depth` survives as a counter — reported, compared to nothing. What has fired is the invariant."""

    __slots__ = ("fired", "depth", "stopped")

    def __init__(self):
        self.fired: set = set()
        self.depth = 0
        self.stopped: Optional[str] = None

    def admit(self, operator_id: str) -> Tuple[bool, str]:
        """May this operator fire in this cascade? Terminates because the operator set is finite and
        each member is admitted at most once — not because a count ran out."""
        if self.stopped:
            return False, self.stopped
        if operator_id in self.fired:
            return False, "already fired in this cascade: %s" % operator_id
        self.fired.add(operator_id)
        self.depth += 1
        return True, "admitted"


# NOTE: `tekton_basis` / `tekton_basis_for` (a tekton's coupling basis from its offer, §A.2) live behind the
# `match` seam — they are a measurement (offer coords → subspace), read by both sage and lumen, so lumen
# need not import sage. Reach them at `_host_seams.resolve("match").tekton_basis_for(store, cap)`, which is
# what `sage/reach_provider.py` and `lumen/reach_provider.py` both do.

__all__ = ["select", "Cascade"]
