"""The overlap writer, pinned — properties of the write path, each with its own failure mode.

These tests use a real store, not a raw-sqlite fixture. The other reading suite builds `vertex` /
`edge` tables by hand, which is right for testing the reader against a degenerate shape; it is wrong
here, because what is under test is the write path itself, and hand-built rows would not exercise it.
`open_store()` resolves `EMBER_SQLITE_DIR`, so each test gets its own lattice and the writes go
through `put_artifact` / `add_edges` like a real run.

The properties pinned here, and what not to reintroduce:

  · one operator          -- `observed` and `observed_alone` are the same operator; a corpus-wide
                            statistic frozen onto one occurrence's edge would rot as the reading
                            accumulates.
  · counted, not stored   -- `witnesses` on the span artifact is the same staleness one layer over.
  · cited spans only      -- every maximal repeat written as an artifact rather than only the ones
                            cited would leave units with no context edge, which can never seed a
                            read (see §0.1 elsewhere in this suite).
  · provenance in `meta`  -- the publish time must never be prepended to the text itself: an
                            unrepeatable span in every paragraph would make the residual measure the
                            clock, not the news.
"""
import sqlite3

import pytest

from agience_chorus.astra.reading import overlap


# Two paragraphs share "the market moved"; each also says something only it says. Deliberately not a
# tidy fixture: para 3 repeats a span inside itself, which is the shape that made the old label and
# the edge count answer different questions.
TEXT = "\n\n".join([
    "the market moved sharply today",
    "the market moved again on volume",
    "bitcoin bitcoin and nothing else here",
])
META = [
    {"published_at": "2026-08-07T10:00:00Z", "source": "a.com", "feed": "test"},
    {"published_at": "2026-08-07T10:15:00Z", "source": "b.com", "feed": "test"},
    {"published_at": "2026-08-07T10:30:00Z", "source": "c.com", "feed": "test"},
]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real lattice of this test's own, written through mantle exactly as a run does.

    The keys dir is provisioned rather than auto-created, because the store refuses to `mkdir` one:
    an empty keys dir would let the first write mint a key no peer holds, leaving this node's content
    undecryptable fleet-wide while every health metric stays green. The fixture provisions the key so
    it exercises the store a real deployment has, not one whose refusal was silenced.
    """
    keys = tmp_path / "keys"
    keys.mkdir()
    from cryptography.fernet import Fernet
    (keys / "content.key").write_bytes(Fernet.generate_key())
    monkeypatch.setenv("EMBER_SQLITE_DIR", str(tmp_path))
    monkeypatch.setenv("EMBER_STORE_KEYS_DIR", str(keys))
    # The store also refuses to mint a lattice implicitly — a wrong `EMBER_SQLITE_DIR` would
    # otherwise create an empty one and the node would report ready() while serving nothing. A fresh
    # shard is a deliberate act, so the fixture opts in explicitly.
    monkeypatch.setenv("EMBER_SQLITE_CREATE", "1")
    import ember  # noqa: F401 — binds the host seams; without it every seam(...) raises
    from mantle.shard.local_store import open_store
    return open_store()


def _read(store, collection="read:t", text=TEXT, meta=None):
    return overlap.read(store, collection, text, meta=meta)


def _arts(store, collection, ct):
    return [a for a in store.artifacts.list_artifacts(collection_id=collection)
            if a.get("content_type") == ct]


def _contexts(collection="read:t"):
    """unit -> the contexts holding it, through the one implementation.

    Not a local in-degree count: sharedness has exactly one definition,
    `ember/signal/projection.py::read_unit_contexts`, and `read_basis` is how a persona reaches it. A
    second count kept anywhere else would diverge from this one as the reading accumulates.
    """
    from agience_chorus.astra.reading import read_basis
    ro = sqlite3.connect(read_basis._db())
    try:
        return {u: set(c) for u, c in read_basis.unit_contexts(ro, collection).items()}
    finally:
        ro.close()


# ── one operator ─────────────────────────────────────────────────────────────────────────────────

def test_only_ONE_operator_is_written(store):
    """A second operator would encode "occurs nowhere else" — a fact about the whole corpus — onto a
    single occurrence, and the next batch could falsify it with nothing to rewrite it."""
    _read(store)
    labels = set()
    for p in _arts(store, "read:t", overlap.PARA_CT):
        for e in store.graph.edges_of(p["id"]):
            if e["src"] == p["id"]:
                labels.add(e["label"])
    assert labels == {overlap.OBSERVED}, labels


def test_the_legacy_aliases_name_the_same_operator(store):
    """`SHARED`/`ALONE` are still importable so nothing breaks, but they must not resurrect the
    distinction. If these ever differ again, every edge written through them splits back in two."""
    assert overlap.SHARED == overlap.ALONE == overlap.OBSERVED


# ── sharedness is counted, not stored ────────────────────────────────────────────────────────────

def test_no_span_artifact_carries_a_frozen_count(store):
    """A `witnesses` field would be the occurrence count at write time, and a store whose residual is
    recalled in later calls cannot carry a number that stops being true."""
    _read(store)
    for s in _arts(store, "read:t", overlap.TOKEN_CT):
        assert "witnesses" not in s, "a span is carrying a stored count again: %r" % s.get("name")


def test_the_writer_holds_no_second_count_of_its_own(store):
    """Sharedness has one implementation. A helper here that counted citing contexts would be a
    second, and two counts of one fact can diverge as the reading accumulates."""
    assert not hasattr(overlap, "witness_count"), (
        "overlap has grown its own witness counter again — use read_basis.unit_contexts")


def test_witness_count_counts_DISTINCT_contexts(store):
    """`bitcoin` occurs twice inside one paragraph, so it is a maximal repeat, but only a single
    context has ever met it. One paragraph is one witness however often it says the word."""
    _read(store)
    spans = {s["content"]: s["id"] for s in _arts(store, "read:t", overlap.TOKEN_CT)}
    ctx = _contexts()
    inner = [txt for txt in spans if txt.strip() == "bitcoin"]
    assert inner, "fixture no longer contains a span repeated inside one paragraph: %s" % list(spans)
    assert len(ctx.get(spans[inner[0]], ())) == 1


def test_accumulating_FORMS_a_longer_shared_unit(store):
    """What accumulation does: a span's own witness count does not rise when a context repeats.
    Instead, when the same text arrives again, the colimit forms a longer unit that spans the
    repetition, and the shared structure moves to that new unit. The old fragments keep their single
    witness because the cover no longer decomposes the paragraph that way.

    On `the market moved` + `something else entirely`, then the first repeated::

        ' m'   1 -> 1        the fine-grained pieces are unchanged
        'ark'  1 -> 1
        'oved' 1 -> 1
        'the market m'  (absent) -> 2      a longer unit formed, witnessed twice

    That is the colimit doing its job — a unit is formed when the junction explains its members more
    cheaply than they explain themselves — which is why the count must be measured rather than
    stored: the number that matters belongs to a unit that did not exist when the first batch was
    written.
    """
    base = "the market moved" + overlap.PARA_SEP + "something else entirely"
    _read(store, text=base)
    c0 = _contexts()
    before = {s["content"]: len(c0.get(s["id"], ()))
              for s in _arts(store, "read:t", overlap.TOKEN_CT)}
    assert before, "the first read produced no spans"

    _read(store, text=base + overlap.PARA_SEP + "the market moved")
    c1 = _contexts()
    after = {s["content"]: len(c1.get(s["id"], ()))
             for s in _arts(store, "read:t", overlap.TOKEN_CT)}

    formed = {t: n for t, n in after.items() if t not in before}
    assert formed, "no new unit formed when a context repeated"
    shared = {t: n for t, n in formed.items() if n >= 2}
    assert shared, (
        "a unit formed but no context shares it — the repetition produced no shared structure: %s"
        % formed)
    # The formed unit spans the repetition, so it is longer than what it replaced.
    assert max(len(t) for t in shared) > max(len(t) for t in before), (
        "the formed unit is no longer than the fragments it supersedes: %s" % shared)
    # A count that dropped would mean an earlier observation was lost.
    for t, n in before.items():
        if t in after:
            assert after[t] >= n, "witness_count fell for %r: %d -> %d" % (t, n, after[t])


# ── span artifacts are written for what is cited ─────────────────────────────────────────────────

def test_every_span_artifact_has_at_least_one_edge(store):
    """Only spans cited by a context are written as artifacts. A span with no context edge could
    exist while the instrument correctly refuses to seed on it, because with no context edge nothing
    may seed (see §0.1 elsewhere in this suite)."""
    _read(store)
    ctx = _contexts()
    for s in _arts(store, "read:t", overlap.TOKEN_CT):
        assert len(ctx.get(s["id"], ())) >= 1, (
            "span %r was written with no context citing it" % s.get("name"))


def test_the_edges_still_reach_real_artifacts(store):
    """The other direction of the same property: no edge may point at a span that was never
    written."""
    _read(store)
    ids = {a["id"] for a in store.artifacts.list_artifacts(collection_id="read:t")}
    for p in _arts(store, "read:t", overlap.PARA_CT):
        for e in store.graph.edges_of(p["id"]):
            if e["src"] == p["id"]:
                assert e["dst"] in ids, "edge points at a missing span: %s" % e["dst"]


# ── provenance rides on the artifact, never in the text ──────────────────────────────────────────

def test_meta_lands_on_the_paragraph(store):
    """Without this the paragraphs are unplaceable in time and cannot be joined to any series."""
    _read(store, meta=META)
    paras = sorted(_arts(store, "read:t", overlap.PARA_CT), key=lambda a: a["name"])
    assert [p.get("published_at") for p in paras] == [m["published_at"] for m in META]
    assert paras[0].get("source") == "a.com"


def test_meta_CANNOT_overwrite_what_the_reading_measured(store):
    """Provenance describes a paragraph; it does not read it. A `meta` carrying `degrees_of_freedom`
    or `content` must not replace the decomposition this function performed — the artifact would
    then report a reading nobody did."""
    poisoned = [dict(m, degrees_of_freedom=999, content="LIES", chars=1) for m in META]
    _read(store, meta=poisoned)
    for p in _arts(store, "read:t", overlap.PARA_CT):
        assert p["degrees_of_freedom"] != 999
        assert p["content"] != "LIES"
        assert p["chars"] != 1


def test_a_meta_LENGTH_MISMATCH_refuses(store):
    """Zipping a short `meta` attaches each fact to the wrong paragraph from the first gap onward,
    and every downstream time-join would then be confidently wrong with nothing able to detect it —
    so a length mismatch must fail here or not at all."""
    with pytest.raises(ValueError) as e:
        _read(store, meta=META[:2])
    assert "refusing to align" in str(e.value)


def test_the_text_carries_no_provenance(store):
    """A timestamp in the text is unique by construction, so every paragraph would carry an
    unrepeatable span and the residual would measure the clock rather than the news. The
    paragraph's stored content must be exactly what was read."""
    _read(store, meta=META)
    paras = sorted(_arts(store, "read:t", overlap.PARA_CT), key=lambda a: a["name"])
    assert paras[0]["content"] == TEXT.split(overlap.PARA_SEP)[0]
    assert "2026-08-07" not in paras[0]["content"]


# ── the CLI offers no destructive verb ────────────────────────────────────────────────────────────

def test_reset_is_gone_from_the_cli():
    """The reading is meant to accumulate — `add_edges` is idempotent on `edge_key`, so re-reading
    converges without a `--reset` verb, which would delete artifacts and leave their edges behind."""
    import inspect
    # Comments are stripped first: the removal is explained in a comment that names `--reset`, so a
    # naive substring scan would match the explanation itself and fail forever.
    code = "\n".join(ln.split("#", 1)[0] for ln in inspect.getsource(overlap.main).splitlines())
    assert "--reset" not in code
    assert "delete_artifact" not in code, (
        "the writer's CLI can delete again — a new collection name is how you start over")
