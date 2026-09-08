"""crystal.basics — the primary-school ontology crystal (the "basics" shard, shippable).

The ontology shard ships just the basics: a pupil node grounds this one crystal and is a
primary-school ember, able to answer "what is X" for the core concrete concepts, grounded in
cited WordNet structure, with the instrument as its coherence read.

What ships inside (structure travels in the crystal, state grows on the pupil):
  facets   — the concept query in, the grounded definition out.
  tekton   — `sage`: condenses a concept need into its reached, cited answer.
  organons — `op.retrieve` (the lexical+reach recall) and `op.reason` (the instrument read); both
             already exist and ship in the `lumen` py-bundle. No op.screen exists — the screen
             (`ember.signal.projection` -> `ember.optics`) is the host seam the reason organon reaches, not a
             named operator.
  lattice_seed — the 105-concept primary syllabus (`stage.0.basics`) and the basics-scoped corpus
             basis `geom.corpus-basis.basics`. The basis is carried at its measured label: k=4,
             certified band [0,272], k_certain=False — the JC `dense_vec` coordinate has no clean
             spectral rank at this (or any measured) scale, so the instrument ships in its proven
             role (the coherence-ranked cut / define read), never as a resolved basis it is not.
             No model, no forcing: the honest state is the shipped state.

The definition is data — it validates, hashes and refuses tampering through crystal_model, exactly
like crystal.comms.
"""
from __future__ import annotations

from crystal.crystal_model import crystal_artifact, validate

# The primary syllabus — curated by synset (the syllabus is a curatorial act, the teacher naming
# what "primary school" contains; not a model, not a forced sense). These are the concepts whose JC
# `dense_vec` resolved on the node-45 corpus and that back the basics basis.
SYLLABUS = [
    "wn-dog.n.01", "wn-cat.n.01", "wn-horse.n.01", "wn-cow.n.01", "wn-sheep.n.01", "wn-bird.n.01",
    "wn-fish.n.01", "wn-lion.n.01", "wn-tiger.n.01", "wn-bear.n.01", "wn-elephant.n.01",
    "wn-mouse.n.01", "wn-rabbit.n.01", "wn-frog.n.01", "wn-snake.n.01", "wn-bee.n.01", "wn-ant.n.01",
    "wn-wolf.n.01", "wn-fox.n.01", "wn-deer.n.01", "wn-duck.n.01", "wn-goat.n.01", "wn-chicken.n.02",
    "wn-hand.n.01", "wn-foot.n.01", "wn-head.n.01", "wn-eye.n.01", "wn-ear.n.01", "wn-nose.n.01",
    "wn-mouth.n.01", "wn-arm.n.01", "wn-leg.n.01", "wn-finger.n.01", "wn-hair.n.01", "wn-tooth.n.01",
    "wn-heart.n.01", "wn-blood.n.01", "wn-skin.n.01", "wn-bone.n.01", "wn-sun.n.01", "wn-moon.n.01",
    "wn-star.n.01", "wn-sky.n.01", "wn-cloud.n.01", "wn-rain.n.01", "wn-snow.n.01", "wn-wind.n.01",
    "wn-fire.n.01", "wn-water.n.06", "wn-tree.n.01", "wn-flower.n.01", "wn-grass.n.01", "wn-leaf.n.01",
    "wn-mountain.n.01", "wn-river.n.01", "wn-sea.n.01", "wn-sand.n.01", "wn-ice.n.01", "wn-bread.n.01",
    "wn-milk.n.01", "wn-egg.n.02", "wn-meat.n.01", "wn-rice.n.01", "wn-apple.n.01", "wn-fruit.n.01",
    "wn-salt.n.02", "wn-sugar.n.01", "wn-honey.n.01", "wn-mother.n.01", "wn-father.n.01",
    "wn-child.n.01", "wn-baby.n.01", "wn-man.n.01", "wn-woman.n.01", "wn-girl.n.01", "wn-family.n.01",
    "wn-friend.n.01", "wn-king.n.01", "wn-queen.n.01", "wn-house.n.01", "wn-door.n.01",
    "wn-window.n.01", "wn-book.n.01", "wn-table.n.02", "wn-chair.n.01", "wn-bed.n.01", "wn-knife.n.01",
    "wn-cup.n.01", "wn-wheel.n.01", "wn-road.n.01", "wn-boat.n.01", "wn-clock.n.01", "wn-key.n.01",
    "wn-ball.n.01", "wn-box.n.01", "wn-bell.n.01", "wn-shoe.n.01", "wn-hat.n.01", "wn-day.n.01",
    "wn-night.n.01", "wn-year.n.01", "wn-name.n.01", "wn-word.n.01", "wn-color.n.01", "wn-money.n.01",
]

BASICS = {
    "name": "crystal.basics",
    "facets": [
        # The concept conduit — a bare "what is X" need enters, its grounded definition leaves.
        {"name": "concept", "direction": "both",
         "content_type": "application/vnd.agience.wordnet+json"},   # discovery hint, never a gate
        # The read feed — the instrument's coherence/define read flowing out alongside the answer.
        {"name": "read", "direction": "out"},
    ],
    "tektons": [
        {"name": "sage", "domain": "knowledge"},     # condenses a concept need into its cited answer
    ],
    "organons": [
        {"name": "op.retrieve", "requires": ["store.read"]},        # lexical + reach recall
        {"name": "op.reason", "requires": ["compute.local"]},       # the instrument read (host screen seam)
    ],
    "lattice_seed": {
        "collections": ["stage.0.basics"],           # the primary syllabus collection
        "artifacts": SYLLABUS + ["geom.corpus-basis.basics"],       # the concepts + the basics prism
    },
    "created_by": "connect@agience.ai",
}

assert validate(BASICS) == [], validate(BASICS)


def basics_artifact() -> dict:
    """The basics crystal as a store artifact — validated, sha-stamped, refusing tampering."""
    return crystal_artifact(BASICS)


__all__ = ["BASICS", "SYLLABUS", "basics_artifact"]
