"""Templates — categories that resolve from the meaning-mass, with no forcing code.

Category/region generalization is a persona (reasoning) definition, not grounding. Its sole
consumer is the conversation tekton's `_region` (`lumen/conversation.py`). It reads the shared
meaning-geometry gauge-neutrally through `crystal.ontology.geometry`/`crystal.ontology.driver`
(persona→store; the meaning geometry and its driver live with the corpus they read).


A template is a region in the Jiang-Conrath meaning-geometry (geometry.py): a subsumer synset that
stands in for a clump of observed points. Nothing here is a rule, a list, or a threshold you can point
to and call a bias. The only machinery is compression:

  A clump of n members under region r costs, to describe:
        IC(r)                      name the region once
      + sum_m ( IC(m) - IC(r) )    refine each member down from r to itself   (r subsumes m, so LCS=r)
      = sum_m IC(m)  -  (n-1)*IC(r)
  Naming each member on its own costs sum_m IC(m). So a clump saves exactly

        gain(clump) = (n - 1) * IC(region)                                     [the compression]

  bigger clumps and more specific regions save more. This objective has a natural interior maximum:
  climb the hypernym tree too high and IC(region) collapses toward the root (a category so general it
  is noise); stay too low and a region covers only one point (n-1 = 0, no signal). "Signal above noise"
  and "most clumped mass" are literally where sum-of-gains peaks. The geometry's own information content
  decides the generality level — we never tell it where a category is.

Multiplicity is free: an outlier does not drag a clump up to `entity`, because two tight clumps beat
one diluted clump under the same objective. So the mass splits into several signals when the evidence
says so, and a polysemous footprint lights up several templates at once (its senses land in different
clumps). Matching returns a ranked set, never a single winner — the superposition the awake screen holds.

Forming templates is the "dreaming" pass: offline, re-cluster accumulated observations so the mass
carries fewer, clearer generators. Matching is the awake pass: a footprint resonates with the clumps.

    python -m lumen.templates      # watch categories resolve, generalize, and go plural

Nouns only, same as geometry.py: the hypernym hierarchy is where the proven meaning-geometry lives.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

from crystal.ontology import geometry as geo


# ── regions: the generalization of a set of points, straight from the spanning-tree geometry ─────
def set_lcs(synsets, ic):
    """The least common subsumer of a set on the canonical spanning tree: the deepest node shared by
    every member's tree-path, i.e. the tightest region that still covers them all. Returns (synset, IC).
    IC is high when the members are tightly related (a real category) and falls toward 0 near the root."""
    if not synsets:
        return None, 0.0
    paths = [geo.tree_path(s, ic) for s in synsets]
    common = set(n.name() for n in paths[0])
    for p in paths[1:]:
        common &= set(n.name() for n in p)
    best, best_ic = None, -1.0
    for p in paths:                                   # recover a synset object for the max-IC common name
        for node in p:
            if node.name() in common:
                v = geo.ic_of(node, ic)
                if v > best_ic:
                    best, best_ic = node, v
    return best, max(best_ic, 0.0)


def _clump_gain(members, ic) -> float:
    """(n-1) * IC(region) — the bits saved by describing these members as one region. 0 for a singleton.

    No explicit `if len(members) < 2: return 0.0` guard is needed: at n = 1 the factor `(n - 1)` is
    zero, and at n = 0 `set_lcs` returns IC 0.0, so both cases return 0.0 without being told to. Such
    a guard would restate what the expression below it already computes, reading as a minimum-sample
    rule that a later change to the formula could silently disagree with."""
    _, r_ic = set_lcs(members, ic)
    return (len(members) - 1) * r_ic


def _total_gain(clumps, ic) -> float:
    return sum(_clump_gain(c, ic) for c in clumps)


# ── the dreaming pass: resolve clumps by maximizing total compression ────────────────────────────
class Template:
    """A resolved category: a region synset covering its member points. Carried opaquely alongside are
    the relation/objects it was observed with — no code branches on them, so they add no bias; they are
    just what the region tends to relate to (the other side of the triple)."""

    def __init__(self, region, region_ic, members, relation=None, objects=None):
        self.region = region
        self.region_ic = region_ic
        self.members = list(members)
        self.relation = relation
        self.objects = list(objects or [])

    def label(self) -> str:
        return self.region.name() if self.region is not None else "·"

    def __repr__(self):
        rel = f" --{self.relation}-->" if self.relation else ""
        return (f"<Template {self.label()} (IC={self.region_ic:.2f}, n={len(self.members)}){rel} "
                f"[{', '.join(m.name() for m in self.members)}]>")


def form_templates(points, ic=None, relation=None, objects=None) -> List[Template]:
    """Agglomerate `points` into the partition that maximizes total compression. Start every point as its
    own clump; repeatedly apply the single merge that most increases total gain; stop at the peak (no
    merge helps). The result is one or more templates — the mass splits itself into signals. Pure hill-
    climb on (n-1)*IC(region); the only quantity consulted is the geometry's information content."""
    ic = ic or geo.load_ic()
    clumps: List[List] = [[p] for p in points]
    while len(clumps) > 1:
        base = _total_gain(clumps, ic)
        best_delta, best_ij = 0.0, None
        for i in range(len(clumps)):
            for j in range(i + 1, len(clumps)):
                trial = [c for k, c in enumerate(clumps) if k not in (i, j)] + [clumps[i] + clumps[j]]
                delta = _total_gain(trial, ic) - base
                if delta > best_delta:
                    best_delta, best_ij = delta, (i, j)
        if best_ij is None:                            # no merge improves compression → the peak
            break
        i, j = best_ij
        merged = clumps[i] + clumps[j]
        clumps = [c for k, c in enumerate(clumps) if k not in (i, j)] + [merged]
    out = []
    for c in clumps:
        region, r_ic = set_lcs(c, ic)
        out.append(Template(region, r_ic, c, relation=relation, objects=objects))
    return sorted(out, key=lambda t: (-len(t.members), -t.region_ic))


# ── the awake pass: a footprint resonates with the resolved clumps (ranked, plural) ──────────────
def resonance(point, template: Template, ic) -> float:
    """How deep `point` sits inside a template's region: IC(LCS(point, region)) / IC(region), in (0, 1].
    1.0 when the region subsumes the point (it is in the category — including points never observed, so
    this is exactly generalization). Falls off as the point's shared meaning with the region shrinks."""
    if template.region is None or template.region_ic <= 0.0:
        return 0.0
    shared = geo.tree_lcs_ic(point, template.region, ic)
    return max(0.0, min(1.0, shared / template.region_ic))


def match(footprint, templates: Sequence[Template], ic=None) -> List[Tuple[Template, float]]:
    """Match a footprint (a synset, or several sense-synsets for an ambiguous token) against the templates.
    Returns a ranked set of (template, resonance) — the K signals above noise, not one winner. Pass all
    senses of a polysemous token and each sense resonates with its own clump: the multiplicity the screen
    keeps until the moment of action collapses it.

    K is read from the resonances themselves (`prism.resolution.signal_end`), which is what "above
    noise" means — there is no fixed top-N parameter, on either the template side or the corpus
    side."""
    ic = ic or geo.load_ic()
    senses = footprint if isinstance(footprint, (list, tuple)) else [footprint]
    scored = []
    for t in templates:
        r = max((resonance(s, t, ic) for s in senses), default=0.0)   # best-resonating sense wins the slot
        if r > 0.0:
            scored.append((t, r))
    scored.sort(key=lambda x: -x[1])
    if not scored:
        return scored
    from prism.resolution import signal_end
    return scored[: signal_end([r for _t, r in scored])]


# ── self-check: watch categories resolve, generalize, and go plural ──────────────────────────────
def _syn(name, ic):
    from crystal.ontology import driver as wn
    try:
        return wn.synset(name)
    except Exception:
        return None


def _demo():
    from crystal.ontology import driver as wn
    ic = geo.load_ic()

    print("=" * 78)
    print("1. A CATEGORY RESOLVES — and an outlier SPLITS OFF (signal above noise)")
    print("-" * 78)
    names = ["dog.n.01", "cat.n.01", "bird.n.01", "shark.n.01", "oak.n.01", "rose.n.01"]
    pts = [s for s in (_syn(n, ic) for n in names) if s is not None]
    print("observed points:", ", ".join(p.name() for p in pts))
    templates = form_templates(pts, ic)
    print("\nresolved templates (the mass found its own clumps — no list told it 'animal'/'plant'):")
    for t in templates:
        print("   ", t)
    print("\ntotal compression at the peak: "
          f"{_total_gain([t.members for t in templates], ic):.2f} bits saved")

    print()
    print("=" * 78)
    print("2. GENERALIZATION — a never-observed point falls into the right clump")
    print("-" * 78)
    for probe in ["wolf.n.01", "eagle.n.01", "maple.n.02"]:
        s = _syn(probe, ic)
        if s is None:
            continue
        ranked = match(s, templates, ic)
        shown = ", ".join(f"{t.label()}={r:.2f}" for t, r in ranked)
        print(f"   {probe:14s} -> {shown}")
    print("   (wolf/eagle never taught, yet land in the animal clump at resonance 1.0 — the category,")
    print("    not a lookup, is what recognizes them.)")

    print()
    print("=" * 78)
    print("3. MULTIPLICITY — one footprint, several signals (a polysemous token)")
    print("-" * 78)
    # add an artifact clump so an ambiguous token has two homes to light up
    art_names = ["hammer.n.02", "knife.n.01", "car.n.01", "piano.n.01"]
    art_pts = [s for s in (_syn(n, ic) for n in art_names) if s is not None]
    all_templates = templates + form_templates(art_pts, ic)
    print("templates in play:", ", ".join(t.label() for t in all_templates))
    for token in ["seal", "bat", "crane"]:
        senses = wn.synsets(token, pos=wn.NOUN)
        ranked = match(senses, all_templates, ic)   # K is derived, not chosen
        shown = "  ".join(f"{t.label()}={r:.2f}" for t, r in ranked)
        print(f"   '{token}' ({len(senses)} senses) -> {shown}")
    print("   (the footprint doesn't resolve to ONE template — it holds a weighted set. Context, not a")
    print("    rule, is what would later tip which signal you're in.)")
    print("=" * 78)


if __name__ == "__main__":
    _demo()
