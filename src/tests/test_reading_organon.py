"""The reading path, pinned — the modules the higher-level suites do not cover directly.

By-hand verification of the read path cannot show failure: a run grepped for `next ->` lines shows
whether they were produced, but a traceback does not produce one, so a crash and a success both read
as silence. These tests exercise the modules directly so a regression fails the suite instead.

The fixtures reproduce degenerate shapes, not tidy ones — a fixture faithful to the model hides the
defect it exists to catch ([[fixture-faithful-to-model-not-corpus]]) — so the instrument fixture
deliberately places two of a query's units in different neighbourhoods and includes a unit that
occurs exactly once.

The failure modes these watch for, stated first so they can fire:
  - a maximal repeat that is not maximal (extendable without losing an occurrence);
  - the decomposition cutting at every overlap, which would leave nearly one part per character
    instead of a coarse partition;
  - the reader crashing instead of reporting that a seed is outside the instrument;
  - a query the reading never formed answering anything rather than grounding out.
"""
import json
import sqlite3

import pytest

from astra.reading.overlap import decompose, shared_spans


# ── the colimit: what the text shares with itself ────────────────────────────────────────────────

def test_a_repeated_span_is_found_and_a_hapax_is_not():
    """Shared means seen twice: a span occurring once is not a repeat."""
    spans = shared_spans("the cat sat on the mat")
    assert any("the " in s for s in spans), "a span occurring twice was not found"
    assert not any("zebra" in s for s in spans)


def test_a_repeat_is_MAXIMAL_not_merely_present():
    """A maximal repeat cannot be extended without losing an occurrence. `abcX abcY` shares `abc`;
    it must not also report `ab` or `bc` as separate findings of the same structure — those are
    extendable, so they are not maximal and would inflate the lexicon with sub-parts of one fact."""
    spans = shared_spans("abcX abcY")
    assert "abc" in spans, spans
    # `ab` is a prefix, already excluded by right-maximality (the LCP boundary) regardless of
    # left-maximality, so asserting its absence would not test the left-maximality check. The
    # suffixes `bc` and `c` are what left-maximality excludes, so they are what is asserted here.
    assert "bc" not in spans, "left-maximality is not being applied — suffixes leaked in: %s" % spans
    assert "c" not in spans, spans


def test_decompose_does_not_cut_at_every_overlap():
    """The seam is where the longest cover changes, which is far coarser than cutting at every
    overlap — cutting at each overlap would give nearly one part per character."""
    text = "the cat sat on the mat and the cat ran"
    parts = decompose(text, [s for s in shared_spans(text) if len(s) >= 2])
    assert parts, "nothing decomposed"
    assert "".join(parts) == text, "the decomposition must be a partition — no text lost or added"
    assert len(parts) < len(text) / 2, (
        "cutting nearly every character again: %d parts for %d chars" % (len(parts), len(text)))


def test_a_rare_string_stays_fine_grained_and_that_is_correct():
    """What a text shares becomes a concept; what appears once stays in pieces. Flattening that
    would claim structure the reading never saw."""
    text = "aaa bbb aaa bbb Zyxwvu"
    parts = decompose(text, [s for s in shared_spans(text) if len(s) >= 2])
    assert "".join(parts) == text
    tail = "".join(p for p in parts if p.strip() and p.strip() in "Zyxwvu")
    assert len(tail) <= len("Zyxwvu")


# ── the reader: an instrument that must be able to answer nothing ──────────────────────────────────

@pytest.fixture
def shard(tmp_path):
    """A tiny lattice with the degenerate shape that crashed: two of a query's units held by
    contexts in different neighbourhoods, so opening on the rarest seed leaves the other outside."""
    db = sqlite3.connect(str(tmp_path / "l.db"))
    db.execute("CREATE TABLE vertex (id TEXT PRIMARY KEY, ct TEXT, doc TEXT, created_by TEXT)")
    db.execute("CREATE TABLE edge (src TEXT, dst TEXT, label TEXT, props TEXT, edge_key TEXT)")
    C = "read:t"

    def unit(name):
        uid = "%s:span:%s" % (C, name.encode("utf-8").hex())
        db.execute("INSERT OR REPLACE INTO vertex VALUES (?,?,?,?)",
                   (uid, "application/x-token",
                    json.dumps({"id": uid, "name": name, "content": name}), "t"))
        return uid

    def ctx(n, units, label="observed"):
        pid = "%s:para-%d" % (C, n)
        db.execute("INSERT OR REPLACE INTO vertex VALUES (?,?,?,?)",
                   (pid, "application/x-paragraph", json.dumps({"id": pid}), "t"))
        for u in units:
            db.execute("INSERT OR REPLACE INTO edge VALUES (?,?,?,?,?)",
                       (pid, unit(u), label, "{}", pid + "|" + unit(u)))

    # `far` sits only in para-2; `near` only in para-0/1 — a query of "nearfar" seeds both, and the
    # instrument opens on whichever is rarer, leaving the other outside it.
    ctx(0, ["near", "alpha", "beta"])
    ctx(1, ["near", "alpha", "gamma"])
    ctx(2, ["far", "delta"], label="observed_alone")
    db.commit()
    return str(tmp_path / "l.db"), C


def _reader(shard_path, collection, monkeypatch):
    from lumen.reading import query_neighbourhood as ap
    monkeypatch.setattr(ap, "C", collection, raising=False)
    monkeypatch.setattr(ap, "DB", shard_path, raising=False)
    return ap


def test_a_query_the_reading_never_formed_grounds_out(shard, monkeypatch):
    """An unseen query has nowhere for the instrument to stand and must answer nothing — not a
    nearest string, not a fabricated continuation."""
    path, C = shard
    ap = _reader(path, C, monkeypatch)
    ro = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    assert ap.reach(ro, "qqqzzz") is None


def test_a_unit_in_NO_context_may_not_seed(shard, monkeypatch):
    """Existence in `vertex` is not enough — a unit no context holds gives the instrument nowhere to
    stand.

    What this test does not isolate: reverting the seed check to vertex-existence also leaves this
    green, because an orphan unit has no edges and the `by_rarity` emptiness check then returns None
    anyway — the two guards are redundant for this case. What this pins is the behaviour, an orphan
    cannot seed, not which of the two guards delivers it. The seed check earns its place on a
    different case, covered by `test_BOTH_operators_are_read_not_just_the_shared_one`, where an
    `observed_alone` unit must still seed."""
    path, C = shard
    ap = _reader(path, C, monkeypatch)
    ro = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    db = sqlite3.connect(path)
    orphan = "%s:span:%s" % (C, "orphan".encode("utf-8").hex())
    db.execute("INSERT OR REPLACE INTO vertex VALUES (?,?,?,?)",
               (orphan, "application/x-token", json.dumps({"name": "orphan"}), "t"))
    db.commit()
    assert ap.reach(ro, "orphan") is None


def test_BOTH_operators_are_read_not_just_the_shared_one(shard, monkeypatch):
    """`observed` and `observed_alone` are both context->content links; the operator discriminates
    them, it does not decide which exist, so a reader that queries only `observed` silently drops
    every paragraph-unique concept."""
    path, C = shard
    ap = _reader(path, C, monkeypatch)
    ro = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    got = ap.reach(ro, "far")
    assert got is not None, "an `observed_alone` unit was invisible to the reader"
    _seeds, _ids, ctx, _held, _units = got
    assert any("para-2" in c for c in ctx)


def test_a_seed_outside_the_neighbourhood_does_not_CRASH(shard, monkeypatch):
    """The instrument opens on the rarest seed, and the query vector sums over units no context in
    that neighbourhood holds — a seed outside the index must be named as unseen, not looked up and
    crash with a KeyError.

    `query_vector` is exercised directly here, with a seed that is not in the index, which is the
    crashing shape; calling `reach()` instead would not exercise this code path at all."""
    import numpy as np

    path, C = shard
    ap = _reader(path, C, monkeypatch)
    coord = np.array([[1.0, 0.0], [0.0, 1.0]])
    idx = {ap.unit_id("near"): 0}                 # `far` is deliberately absent

    qv, used, unseen = ap.query_vector(["near", "far"], idx, coord, 2)

    assert used == ["near"]
    assert unseen == ["far"], "a seed outside the instrument must be NAMED, not dropped in silence"
    assert qv.tolist() == [1.0, 0.0]


def test_query_vector_reports_when_NOTHING_is_visible(shard, monkeypatch):
    """All seeds outside the instrument is a real state — an empty `used`, not an exception and not a
    zero vector passed off as an answer."""
    import numpy as np

    path, C = shard
    ap = _reader(path, C, monkeypatch)
    qv, used, unseen = ap.query_vector(["far"], {}, np.zeros((1, 2)), 2)
    assert used == [] and unseen == ["far"]
    assert not qv.any()


# ── source scans ───────────────────────────────────────────────────────────────────────────────
#
# These scan the source for a property rather than exercising one call path, because sampling one
# entry point can miss a site where the property is violated while scanning for the property cannot.

import pathlib
import re as _re

SRC = pathlib.Path(__file__).resolve().parents[1]
READING = SRC / "lumen" / "reading"

#: The placement module, which is owned by no persona and therefore does not live under `READING`.
#: Named explicitly rather than reached by a wider glob: these scans are about the reading's edge
#: queries, and a directory glob that happened to cover it would stop covering it the moment it moved
#: again. It is asserted to exist below, so this cannot silently degrade to scanning one file less.
_JUNCTION = SRC / "reading_junction.py"

#: both halves of the operator. `observed_alone` is not a lesser edge — it is the part a context holds
#: alone, and dropping it silently loses every paragraph-unique concept.
_BOTH_LABELS = "('observed','observed_alone')"


def _sources():
    assert _JUNCTION.is_file(), (
        "%s is gone — it holds the placement queries these scans exist to cover, and without it "
        "they would report clean on a file they never opened" % _JUNCTION)
    return [p for p in sorted(READING.glob("*.py")) if not p.name.startswith("_")] + [_JUNCTION]


def test_no_edge_query_reads_only_ONE_operator():
    """A query site reading only `observed` makes every paragraph-unique `observed_alone` concept
    unseedable — a single-label query is the defect wherever it appears, so the source is scanned
    for it rather than one caller sampled."""
    offenders = []
    for p in _sources():
        src = p.read_text(encoding="utf-8")
        for n, line in enumerate(src.splitlines(), 1):
            if "label" not in line or line.lstrip().startswith("#"):
                continue
            if _re.search(r"label\s*(=|==)\s*'observed'", line) or \
               _re.search(r'label\s*(=|==)\s*"observed"', line):
                offenders.append("%s:%d  %s" % (p.name, n, line.strip()))
    assert not offenders, (
        "an edge query reads only `observed`, so `observed_alone` links are invisible to it:\n  %s\n\n"
        "Both are context->content links; the OPERATOR discriminates them, it does not decide which "
        "exist. Use %s." % ("\n  ".join(offenders), _BOTH_LABELS))


def test_the_read_path_carries_no_REGEX():
    """A pattern deciding what counts as text is the one thing this organon exists not to do: what a
    unit is, is the reading's to discover, not a regex's to pre-decide.

    This file itself is excluded from the scan — it uses `re` in order to assert the rule."""
    offenders = []
    for p in _sources():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _re.search(r"\bre\.(compile|search|match|sub|findall|finditer)\b", line) or \
               _re.match(r"\s*import re\b", line):
                offenders.append("%s:%d  %s" % (p.name, n, line.strip()))
    assert not offenders, (
        "regex is back on the read path:\n  %s\n\nStripping a publisher's wrapper is a question "
        "about the DATA and is done once, outside; what a unit IS, is the reading's to discover."
        % "\n  ".join(offenders))


def test_no_count_star_on_the_read_path():
    """`count(*)` dereferences every record — a query defect, not a heap shortage, and on the live
    shard it zombies the acceptor ([[count-star-dereferences-every-record]],
    [[read-only-is-not-safe-on-71]]). To ask whether any row exists, use `LIMIT 1`, which answers in
    bounded work."""
    offenders = []
    for p in _sources():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _re.search(r"count\s*\(\s*\*\s*\)", line, _re.I):
                offenders.append("%s:%d  %s" % (p.name, n, line.strip()))
    assert not offenders, (
        "count(*) is back on the read path:\n  %s\n\nTo ask whether ANY row exists use `LIMIT 1`; to "
        "report a size, read a bounded page and say it is a lower bound."
        % "\n  ".join(offenders))


def test_no_unguarded_fetchone_subscript():
    """An aggregate query always returns a row; a row query returns `None` when nothing matches, so
    subscripting a `fetchone()` result without a guard raises whenever the underlying condition is
    the one the caller was checking for (here, an empty collection — precisely when the reader is
    meant to run). Scanned rather than sampled: subscripting `fetchone()` is the defect wherever it
    appears, and only a guarded use (`if row`, `if row is None`) is safe."""
    offenders = []
    for p in _sources():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _re.search(r"\.fetchone\(\)\s*\[", line):
                offenders.append("%s:%d  %s" % (p.name, n, line.strip()))
    assert not offenders, (
        "a fetchone() result is subscripted without a None guard:\n  %s\n\n"
        "A row query returns None when nothing matches — unlike an aggregate, which always returns a "
        "row. Bind it first and check, or the module dies on the EMPTY case."
        % "\n  ".join(offenders))


def test_no_handrolled_decomposition_where_the_instrument_has_one():
    """A raw span (`np.linalg.qr` over a context's own vectors) is full-rank, so it absorbs 100% of
    any query and the coupling says nothing -- the winning coupler always comes out at the full
    coordinate dimension, byte-identical in absorbed energy regardless of the query.

    `absorb_transmit`'s own contract is what to use instead: the coupled band is the projection onto
    the resolved subspace (`principal_directions` -- the k modes standing above the instrument's noise
    floor). Letting the instrument resolve it gives k=1 per context and the coupling discriminates
    immediately.

    `np.linalg.norm` is not covered: a vector magnitude is arithmetic, not a measurement the
    instrument publishes. What is forbidden is re-deriving a decomposition the instrument already
    performs.

    This scan is evadable by aliasing: `np` does not match inside `_np`, since underscore is a word
    character, so `import numpy.linalg as L; L.qr(...)` would slip past. It catches the ordinary
    spelling the defect is written in; it bounds the common case, not the adversarial one."""
    offenders = []
    for p in _sources():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _re.search(r"\b(?:np|numpy)\.linalg\.(qr|svd|eig|eigh|eigvals|cholesky|pinv)\b", line):
                offenders.append("%s:%d  %s" % (p.name, n, line.strip()))
    assert not offenders, (
        "a decomposition is hand-rolled where the instrument publishes one:\n  %s\n\n"
        "Bases come from `optics().principal_directions(...)` — the RESOLVED subspace. A raw span is "
        "full-rank and absorbs everything, which makes every coupling identical."
        % "\n  ".join(offenders))


def test_reading_modules_write_through_the_store_not_raw_sql():
    """A raw `INSERT OR REPLACE INTO vertex/edge` bypasses the mantle write path, which is what
    assigns `_origin`/`_seq` (proper time — without it a row can never publish and never
    merkle-verify), computes the `edge_key` as a 16-byte blake2b digest, and materialises a principal
    for `created_by`. Rows written by raw SQL are malformed in ways a green pytest run over the
    writer's own code does not reveal, because the defect is in what the code writes into, not in
    the code itself — [[node-repair-is-the-test-suite]] is what surfaces it."""
    offenders = []
    for p in _sources():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _re.search(r"INSERT\s+(OR\s+\w+\s+)?INTO\s+(vertex|edge|collection_member)", line,
                          _re.I):
                offenders.append("%s:%d  %s" % (p.name, n, line.strip()[:88]))
    assert not offenders, (
        "the reading path writes to the lattice with raw SQL:\n  %s\n\nUse the mantle store API — "
        "raw INSERT leaves rows with no proper time, a malformed edge_key, and a created_by naming "
        "no principal." % "\n  ".join(offenders))


def test_no_cosine_similarity_anywhere_on_the_read_path():
    """Cosine similarity is forbidden in this domain, and it is easy to write without naming it:
    normalising two vectors and taking their dot product (`Cn @ pn` where both are unit-normalised)
    is cosine, and squaring the result is still cosine.

    What is legitimate, and why the one surviving `linalg.norm` is not a violation: the instrument
    projects a signal onto a resolved subspace and measures how much is absorbed — `‖Bo.T @ v‖`
    where `Bo` is a basis from `principal_directions`. That is a projection onto a measured band,
    which is what `absorb_transmit` does and what conservation is stated over. An angle between two
    raw vectors is not a measurement of anything the instrument published — a basis is fine, a
    normalised pair is not."""
    offenders = []
    for p in _sources():
        text = p.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _re.search(r"cosine|cos_sim|cosine_similarity", line, _re.I):
                offenders.append("%s:%d  %s" % (p.name, n, line.strip()[:80]))
            # normalise-then-dot: `x / (norm(x) ...)` on both sides of an `@` is cosine in disguise
            if _re.search(r"/\s*\(?\s*np\.linalg\.norm\([^)]*\)[^)]*\)?\s*\)?\s*$", line) and \
               "@" in text[max(0, text.find(line) - 200):text.find(line) + 200]:
                offenders.append("%s:%d  %s   (normalise-then-dot)" % (p.name, n, line.strip()[:60]))
    assert not offenders, (
        "cosine similarity is on the read path:\n  %s\n\nProject onto a RESOLVED BASIS and measure "
        "what is absorbed (`principal_directions` + `absorb_transmit`). An angle between two raw "
        "vectors is not a measurement the instrument published." % "\n  ".join(offenders))
