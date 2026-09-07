"""Locked-in conversational behavior of the conversation tekton — the transistor, the count seeder,
full-DAG propagation, the reasoning-screen merge, and the honest null.

The conversation acts (`act`/`learn`) live in `lumen/conversation.py`; the recognition primitives
(`_seed_field`/`spread_seeds`/`_word`) live in `ember.ontology.activation` and are reached back
through `A`. These tests run against the node's WordNet store — the SemCor `lemma_counts` landed by
op.source.wordnet are load-bearing, so a store-free run cannot exercise them — and skip cleanly
when the store is absent, since full conversation-behavior verification needs the built substrate.
Every `learn` here stubs `put_artifact`, so no test ever writes to the store.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # persona dir → bare `import conversation`

import conversation as C        # noqa: E402  (lumen-local — the conversation tekton)
from ember.ontology import activation as A# noqa: E402  (ember-side recognition primitives the tekton reaches)


@pytest.fixture(scope="module")
def store():
    """The node's real lexicon, or a skip that says what would make it run.

    `open_sqlite_store()` reads `EMBER_SQLITE_DIR` (`mantle/shard/sqlite_store.py:509`), defaulting
    to `~/genesis-shard`. A default-location store can open successfully while still not being the
    corpus — a small seed shard has a `lattice.db` and `keys/` dir but no WordNet content — so this
    fixture checks for `wn-dog.n.01` and its `lemma_counts` before yielding the store, and skips
    with a message naming the path it looked at and the variable that redirects it, rather than
    reporting an environment gap as a fact about the corpus.

    The fixture does not set `EMBER_SQLITE_DIR` itself. Pointing a test run at the live production
    shard is not free: `activation.py` can take a write lock (`BEGIN IMMEDIATE`) on the shard it
    opens, and this module's own `put_artifact` stub does not cover the delegate's screen writes
    (`delegate.save_screen`). Running these tests against the live corpus is a deliberate choice by
    whoever sets the environment variable, not a default this fixture makes for them."""
    import os
    try:
        from mantle.shard.sqlite_store import open_sqlite_store
        s = open_sqlite_store()
    except Exception as e:                                  # pragma: no cover - environment gate
        pytest.skip("lattice store unavailable (EMBER_SQLITE_DIR=%r): %s"
                    % (os.getenv("EMBER_SQLITE_DIR"), e))
    where = os.getenv("EMBER_SQLITE_DIR") or "~/genesis-shard (the default)"
    if not s.artifacts.get_artifact("wn-dog.n.01"):
        pytest.skip(
            "WordNet is not in the store at %s — this is an empty/seed shard, not the corpus. "
            "The conversation tekton's whole behavioural suite is skipping on an unset environment "
            "variable. Point EMBER_SQLITE_DIR at the node's real lexicon to run it. "
            "Known hazard: this path can take BEGIN IMMEDIATE on a production shard and block "
            "(see activation.py) — run it against a copy, or accept the lock." % where)
    if not (s.artifacts.get_artifact("wn-dog.n.01") or {}).get("lemma_counts"):
        pytest.skip("SemCor lemma_counts not enriched at %s (run op.source.wordnet). The seeder "
                    "tests below rank on lemma.count() and would measure zeros." % where)
    return s


def _delegate(store, person):
    """A throwaway delegate whose writes never reach the store."""
    from ember.runtime.delegate import Delegate
    d = Delegate.get(store, person=person, restore=False)
    store.artifacts.put_artifact = lambda *a, **k: None    # no writes, ever
    return d


def _lead(store, text):
    seeds = A._seed_field(store, text)
    return max(seeds, key=seeds.get) if seeds else None


# ── the count seeder picks the topic, never the rare-junk reading of a function word ────────────────
@pytest.mark.parametrize("text,concept", [
    ("what is a dog", "dog.n.01"),
    ("tell me about dogs", "dog.n.01"),      # regular plural via morphy
    ("what does a cat say", "cat.n.01"),
    ("tell me about a boat", "boat.n.01"),
    ("what is justice", "justice.n.01"),
])
def test_seeder_picks_topic_not_junk(store, text, concept):
    """SemCor count separates the topic (dog=42) from the rare noun reading of a function word
    (me->Maine=0, does->Department-of-Energy=0, is->ice=0)."""
    assert _lead(store, text) == concept, "seed lead for %r should be %s" % (text, concept)


def test_semcor_counts_are_present(store):
    """The load-bearing stat: `lemma.count()` returns real SemCor frequency, not 0."""
    from crystal.ontology import driver as wn
    dog = max(l.count() for l in wn.synset("dog.n.01").lemmas())
    assert dog > 0, "dog.n.01 must carry a nonzero SemCor count"


def test_named_entity_answers_the_person(store):
    """A named entity is answered as the person, not the first word (Prince Albert). The answer is
    Einstein's own definition (the source's gloss, no mold), so it is grounded on Einstein — his gloss
    names relativity. Guards the grounding, not a hand-authored prefix."""
    d = _delegate(store, "test-compound@local")
    ans = C.act(d, "who was albert einstein")["answer"].lower()
    assert "relativity" in ans, "should describe Einstein (his definition), not Prince Albert"


# ── full-DAG propagation reaches every hypernym, not only the canonical parent ──────────────────────
def test_full_dag_reaches_all_hypernyms(store):
    """A signal at `dog` must propagate to both of its hypernyms — `canine` and `domestic_animal`."""
    fired = A.spread_seeds(A._seed_field(store, "dog"))
    words = {A._word(n) for n in fired}
    assert "canine" in words and "domestic animal" in words


# ── the triple-transistor: deduce / abduce / verify, all from taught offers ─────────────────────────
def test_transistor_recall(store):
    d = _delegate(store, "test-transistor@local")
    C.learn(d, "a dog says woof")
    assert C.act(d, "what does a dog say")["answer"].lower().startswith("woof")   # deduce (content open)
    assert C.act(d, "what says woof")["answer"].lower().startswith("dog")         # abduce (context open)
    assert C.act(d, "a dog says woof").get("verified") is True                    # complete -> verify


def test_generalizes_down_the_dag(store):
    """Teach a general fact; it answers for a specific member through the hypernym path."""
    d = _delegate(store, "test-general@local")
    C.learn(d, "a canine says woof")
    assert C.act(d, "what does a dog say")["answer"].lower().startswith("woof")    # dog -> canine


# ── replace refuted / old information: a new value is a new version (the head) ───────────────────────
def test_new_value_replaces_old(store):
    """Teaching a new object for the same subject+relation is a new version of the same offer — recall
    returns the current value (the head); the prior is history, not recalled."""
    d = _delegate(store, "test-replace@local")
    C.learn(d, "a dog says woof")
    r = C.learn(d, "a dog says bark")
    assert "woof" in (r.get("replaced") or []), "the prior value should be reported as replaced"
    ans = C.act(d, "what does a dog say")["answer"].lower()
    assert ans.startswith("bark") and "woof" not in ans, "recall reads the head (bark), not the prior"


# ── the null is no outgoing signal — never a scripted refusal, never a written sentence ─────────────
def test_null_is_no_signal(store):
    d = _delegate(store, "test-null@local")
    r = C.act(d, "asdfqwer zzz plugh")
    assert not r.get("cited"), "a null must carry no citation"
    assert not (r.get("answer") or "").strip(), "nothing grounded -> no outgoing signal, not a sentence"


# ── describe is grounded and cited ──────────────────────────────────────────────────────────────────
def test_describe_states_the_source_definition_no_mold(store):
    """Describe states the source's own definition, condensed by the gauge inverse — never a
    hand-authored mold. The answer carries no em-dash frame ('Dog — <gloss>. It is a kind of X.');
    the grounded content is the WordNet gloss itself (dog's says 'genus Canis')."""
    d = _delegate(store, "test-describe@local")
    r = C.act(d, "what is a dog")
    ans = r["answer"]
    assert r.get("cited"), "a described concept must cite its source"
    assert "canis" in ans.lower(), "the answer is the source's own definition"
    assert " — " not in ans and "it is a kind of" not in ans.lower(), "no pre-conceived mold"


# ── the reasoning screen merges input ⊕ our own corpus offers (attraction) ──────────────────────────
def test_reasoning_screen_merges_corpus(store):
    """Asking about `dog` after teaching `dog -> woof` pulls `woof` onto the vertex as a corpus offer."""
    d = _delegate(store, "test-vertex@local")
    C.learn(d, "a dog says woof")
    vertex = C.act(d, "what is a dog").get("vertex") or []
    pulled = {A._word(f["concept"]) for f in vertex if f.get("source") == "corpus"}
    assert "woof" in pulled, "the taught offer's other end should be attracted onto the screen"
