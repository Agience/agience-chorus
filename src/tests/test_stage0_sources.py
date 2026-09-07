"""Stage-0 source ingesters (runbook §H1) — OEWN 2024, CILI, ConceptNet 5.7, OMW.

Moved here from `agience-ember/tests/test_stage0_sources.py`: these exercise operators through ember's
runner and need a sha-verified operator payload present. The payloads are chorus's,
built from chorus source; ember is the engine that runs them, so the test belongs
beside the operators. Tests in that file needing no payload stayed in ember.
"""
import gzip
import io
import sys
import types
import pytest
from ember import genesis as g
from ember.corpus import stage0_sources as s0
from _fakes import _FakeGraph, _FakeStore
class _PropsGraph(_FakeGraph):
    def __init__(self):
        super().__init__()
        self.props = []                     # (from, to, label, props)

    def add_edge(self, from_id, to_id, label, props=None):
        super().add_edge(from_id, to_id, label, props)
        self.props.append((from_id, to_id, label, dict(props or {})))

    def add_edges(self, edges, *, batch=500):
        n = 0
        for e in edges:
            self.add_edge(*e)
            n += 1
        return n
def _store():
    s = _FakeStore()
    s.graph = _PropsGraph()
    return s
WN_ROW_KEYS = {"id", "content_type", "state", "title", "gloss", "content", "examples",
               "lemmas", "word", "pos",
               "collection_id", "collections", "cited_from", "via", "operator", "provenance",
               "created_by", "created_time"}
_LMF = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE LexicalResource SYSTEM "http://globalwordnet.github.io/schemas/WN-LMF-1.3.dtd">
<LexicalResource xmlns:dc="https://globalwordnet.github.io/schemas/dc/">
  <Lexicon id="oewn" label="Open English Wordnet" language="en" version="2024"
           license="https://creativecommons.org/licenses/by/4.0">
    <LexicalEntry id="oewn-dog-n">
      <Lemma writtenForm="dog" partOfSpeech="n"/>
      <Sense id="oewn-dog__1.05.00.." synset="oewn-02086723-n"/>
    </LexicalEntry>
    <LexicalEntry id="oewn-domestic_dog-n">
      <Lemma writtenForm="domestic_dog" partOfSpeech="n"/>
      <Sense id="oewn-domestic_dog__1.05.00.." synset="oewn-02086723-n"/>
    </LexicalEntry>
    <LexicalEntry id="oewn-animal-n">
      <Lemma writtenForm="animal" partOfSpeech="n"/>
      <Sense id="oewn-animal__1.03.00.." synset="oewn-00015568-n"/>
    </LexicalEntry>
    <LexicalEntry id="oewn-good-a">
      <Lemma writtenForm="good" partOfSpeech="a"/>
      <Sense id="oewn-good__3.00.00.." synset="oewn-01123148-a">
        <SenseRelation relType="antonym" target="oewn-bad__3.00.00.."/>
      </Sense>
    </LexicalEntry>
    <LexicalEntry id="oewn-bad-a">
      <Lemma writtenForm="bad" partOfSpeech="a"/>
      <Sense id="oewn-bad__3.00.00.." synset="oewn-01125429-a"/>
    </LexicalEntry>
    <Synset id="oewn-02086723-n" ili="i46360" partOfSpeech="n">
      <Definition>a domesticated carnivorous mammal</Definition>
      <Example>the dog barked</Example>
      <SynsetRelation relType="hypernym" target="oewn-00015568-n"/>
      <SynsetRelation relType="mero_member" target="oewn-99999999-n"/>
    </Synset>
    <Synset id="oewn-00015568-n" ili="i11115" partOfSpeech="n">
      <Definition>a living organism</Definition>
    </Synset>
    <Synset id="oewn-01123148-a" ili="i9997" partOfSpeech="a">
      <Definition>having desirable qualities</Definition>
    </Synset>
    <Synset id="oewn-01125429-a" ili="i9998" partOfSpeech="a">
      <Definition>having undesirable qualities</Definition>
    </Synset>
  </Lexicon>
</LexicalResource>
"""
_TTL = """@prefix\tili:\t<http://globalwordnet.github.io/ili/> .
@prefix\tskos:\t<http://www.w3.org/2004/02/skos/core#> .
@prefix pwn30: <http://wordnet-rdf.princeton.edu/wn30/> .

<https://globalwordnet.github.io/cili/ili.ttl> a voaf:Vocabulary ;
  dc:rights "Copyright Francis Bond; License CC BY" .

<Concept>\ta owl:Class .

<i1>\ta\t<Concept> ;
\tskos:definition\t"having the necessary means or skill"@en ;
\tdc:source\tpwn30:00001740-a .

<i2>\ta\t<Concept> ;
\tskos:definition\t"a concept our store does not hold"@en ;
\tdc:source\tpwn30:99999999-n .

<i3>\ta\t<Concept> .
"""
def _seed_synsets(s):
    """A PWN-3.0 spine row (no ili field — the nltk rows carry none) plus an OEWN row that
    carries the ili pivot key, exactly as op.source.oewn lands them."""
    s.artifacts.put_artifact({"id": "wn-able.a.01", "content_type": "text/x-wordnet",
                              "state": "committed", "context": "able", "content": "able",
                              "lemmas": ["able"], "collection_id": "stage.0.lexicon"})
    s.artifacts.put_artifact({"id": "wn-oewn-00001740-a", "content_type": "text/x-wordnet",
                              "state": "committed", "context": "able", "content": "able",
                              "lemmas": ["able"], "ili": "i1",
                              "collection_id": "stage.0.lexicon"})
    s.artifacts.put_artifact({"id": "wn-oewn-77777777-n", "content_type": "text/x-wordnet",
                              "state": "committed", "context": "orphan", "content": "orphan",
                              "lemmas": ["orphan"], "ili": "i3",
                              "collection_id": "stage.0.lexicon"})
_CN_LINES = [
    '/a/[x]\t/r/IsA\t/c/en/dog\t/c/en/animal\t{"weight": 2.0}',
    '/a/[x]\t/r/Antonym\t/c/ab/x\t/c/ab/y\t{"weight": 1.0}',            # non-en → skipped
    '/a/[x]\t/r/RelatedTo\t/c/en/dog/n\t/c/en/pet\t{"weight": 1.0}',
    'malformed\tline',                                                   # terminated junk → skipped
]
_CN_TAIL = '/a/[x]\t/r/UsedFor\t/c/en/pen\t/c/en/writing\t{"wei'         # CUT mid-metadata
def _gz(tmp_path, name, text):
    p = tmp_path / name
    with gzip.open(p, "wt", encoding="utf-8", newline="") as f:
        f.write(text)
    return p
class _SS:
    def __init__(self, sid, pos, ili, lemmas, defn=""):
        self.id, self.pos = sid, pos
        self._ili, self._lemmas, self._defn = ili, lemmas, defn

    @property
    def ili(self):
        return types.SimpleNamespace(id=self._ili) if self._ili else None

    def lemmas(self):
        return list(self._lemmas)

    def definition(self):
        return self._defn
def _fake_wn(index, synsets_by_pid, langs):
    wn = types.ModuleType("wn")
    wn.config = types.SimpleNamespace(index=index, data_directory="")
    wn._downloaded = []
    wn.download = lambda spec: wn._downloaded.append(spec)
    wn.lexicons = lambda lexicon=None: []

    class _W:
        def __init__(self, lexicon=None, **kw):
            self._pid = (lexicon or "").split(":")[0]

        def lexicons(self):
            return [types.SimpleNamespace(language=langs[self._pid])]

        def synsets(self):
            return synsets_by_pid[self._pid]

    wn.Wordnet = _W
    return wn
_OMW_INDEX = {
    "omw-id": {"label": "Wordnet Bahasa (Indonesian)", "language": "id",
               "versions": {"1.4": {"license": "https://opensource.org/licenses/MIT/"}}},
    "omw-pl": {"label": "plWordNet", "language": "pl",
               "versions": {"1.4": {"license": "wordnet"}}},
    "omw-nl": {"label": "Open Dutch WordNet", "language": "nl",
               "versions": {"1.4": {"license": "https://creativecommons.org/licenses/by-sa/4.0/"}}},
}
class _FakeLemma:
    def __init__(self, n): self._n = n
    def name(self): return self._n
    def antonyms(self): return []
    # Sense-level relations, read by the ingest to place adjectives and adverbs. Empty here for the
    # same reason `attributes` is on `_FakeSyn`: this fixture has one noun pair and nothing to
    # derive from, and a double missing a method the ingest calls fails as an AttributeError rather
    # than as an assertion about behaviour.
    def derivationally_related_forms(self): return []
    def pertainyms(self): return []
    def synset(self): return None
class _FakeSyn:
    def __init__(self, name, lemmas, defn, pos="n", ex=()):
        self._name, self._l, self._d, self._p, self._e = name, lemmas, defn, pos, list(ex)
    def name(self): return self._name
    def lemmas(self): return [_FakeLemma(x) for x in self._l]
    def definition(self): return self._d
    def pos(self): return self._p
    def examples(self): return self._e
    def hypernyms(self): return []
    def instance_hypernyms(self): return []
    def part_holonyms(self): return []
    # A modifier is placed along these, and the ingest reads all of them. A double that implements
    # only the subset the ingest happened to call when it was written turns the next relation added
    # into an AttributeError in a test rather than a finding — so the double covers the whole
    # `nltk.Synset` surface the ingest touches, empty where this fixture has nothing to relate.
    def attributes(self): return []
    def similar_tos(self): return []
class _FakeWN:
    """Two senses of one word, in sense order — so the recorded rank is checkable."""
    _S = [_FakeSyn("dog.n.01", ["dog", "domestic_dog"], "a domesticated canine"),
          _FakeSyn("frank.n.02", ["dog", "hotdog"], "a smooth-textured sausage")]

    def all_synsets(self): return list(self._S)

    def synsets(self, word, pos=None):
        w = str(word).replace("_", " ").lower()
        return [x for x in self._S
                if any(l.replace("_", " ").lower() == w for l in x._l)
                and (pos is None or x.pos() == pos)]
def _install_fake_nltk(monkeypatch):
    import sys, types
    wn = _FakeWN()
    corpus = types.ModuleType("nltk.corpus")
    corpus.wordnet = wn
    nltk = types.ModuleType("nltk")
    nltk.corpus = corpus
    monkeypatch.setitem(sys.modules, "nltk", nltk)
    monkeypatch.setitem(sys.modules, "nltk.corpus", corpus)
    return wn
class TestTheLexiconWriterSealsItsBodies:
    """All content goes to the CAS — including the bulk lexicon load.

    Measured 2026-08-25 on 71/home: 1,449,857 of the store's 1,457,067 inline plaintext bodies were
    written from this module. `genesis.ingest_dataset:660` has always sealed — same store, same
    helper, four lines — while this file built `"content": defn` and called `put_many`.

    `db/doc_boundary.encrypt_artifact_content` cannot close the gap: it is the entity path and goes
    through the key oracle, which needs an acting principal the bulk loader does not have, so
    moving it into `put_artifact`/`put_many` fails every ingest write. `shard.content.put_content`
    keys off the keys directory and therefore works in bulk.
    """

    @staticmethod
    def _store(with_tier=True):
        class _S:
            content = object() if with_tier else None
            keys_dir = "/keys" if with_tier else None
        return _S()

    def test_a_body_is_moved_to_the_cas_and_the_address_kept(self, monkeypatch):
        from ember.corpus import stage0_sources as s0
        from mantle.shard import content as C

        monkeypatch.setattr(C, "put_content",
                            lambda store, keys, data, collection=None: ("cas/abc", len(data)))
        docs = [{"id": "wn-x", "content": "a slowly moving mass of ice",
                 "collection_id": "stage.0.lexicon"}]
        out = s0._sealed(self._store(), docs)
        assert out[0]["content_ref"] == "cas/abc"
        assert out[0]["size"] == len(b"a slowly moving mass of ice")
        assert "content" not in out[0], "the address replaces the body; it does not join it"

    def test_the_collection_travels_with_the_bytes(self, monkeypatch):
        from ember.corpus import stage0_sources as s0
        from mantle.shard import content as C

        seen = {}

        def _put(store, keys, data, collection=None):
            seen["collection"] = collection
            return ("cas/abc", len(data))

        monkeypatch.setattr(C, "put_content", _put)
        s0._sealed(self._store(), [{"id": "x", "content": "b", "collection_id": "stage.0.lexicon"}])
        assert seen["collection"] == "stage.0.lexicon"

    def test_a_node_with_no_content_tier_keeps_the_body(self):
        """Degrade, never drop: a loader that refused because the tier was unmounted would trade a
        confidentiality property for a data one."""
        from ember.corpus import stage0_sources as s0

        docs = [{"id": "x", "content": "keep me"}]
        assert s0._sealed(self._store(with_tier=False), docs)[0]["content"] == "keep me"

    def test_an_already_sealed_doc_is_untouched(self, monkeypatch):
        """Idempotent: a re-run must not re-write what it already addressed."""
        from ember.corpus import stage0_sources as s0
        from mantle.shard import content as C

        monkeypatch.setattr(C, "put_content",
                            lambda *a, **k: pytest.fail("must not re-seal"))
        docs = [{"id": "x", "content_ref": "cas/already", "content": ""}]
        assert s0._sealed(self._store(), docs)[0]["content_ref"] == "cas/already"

    def test_one_bad_body_does_not_stop_the_load(self, monkeypatch):
        from ember.corpus import stage0_sources as s0
        from mantle.shard import content as C

        def _put(store, keys, data, collection=None):
            if data == b"bad":
                raise RuntimeError("disk full")
            return ("cas/ok", len(data))

        monkeypatch.setattr(C, "put_content", _put)
        out = s0._sealed(self._store(), [{"id": "a", "content": "bad"},
                                         {"id": "b", "content": "good"}])
        assert out[0]["content"] == "bad", "the one that failed keeps its body"
        assert out[1]["content_ref"] == "cas/ok"
class TestTheILISentinelIsNotAnIdentity:
    """`ili="in"` means "no interlingual id yet", and must not survive as one.

    WN-LMF marks a synset proposed for the interlingual index but not yet assigned one with
    `ili="in"`. Measured 2026-08-25 on 71/home: 3,216 OEWN rows carry it, and they are 3,085
    DISTINCT titles — `barely`, `accustomed to`, `unaccustomed to`, `unused to`, `exercise`.

    Carried through as written it reads downstream exactly like an ILI id. `search/ranking
    ._fold_key` uses the ILI as an IDENTITY — no different-source guard, because an ILI collision
    is not a collision — so those 3,216 unrelated concepts fold into one answer row. That is the
    single way an ILI-keyed fold can be worse than no fold at all.
    """

    def test_the_sentinel_becomes_no_id(self):
        from ember.corpus.stage0_sources import _ili_or_blank
        assert _ili_or_blank("in") == ""

    def test_a_real_ili_survives(self):
        from ember.corpus.stage0_sources import _ili_or_blank
        assert _ili_or_blank("i37653") == "i37653"

    def test_absent_is_blank(self):
        from ember.corpus.stage0_sources import _ili_or_blank
        assert _ili_or_blank(None) == "" and _ili_or_blank("") == ""

    def test_the_check_is_case_insensitive_and_trims(self):
        """A source that writes `IN ` must not slip a sentinel through as an id."""
        from ember.corpus.stage0_sources import _ili_or_blank
        assert _ili_or_blank(" IN ") == "" and _ili_or_blank("None") == ""


def test_oewn_ingest_rows_match_the_wn_row_shape(tmp_path):
    f = tmp_path / "oewn.xml"
    f.write_text(_LMF, encoding="utf-8")
    s = _store()
    r = s0.ingest_stage0_oewn(s, path=str(f))
    assert r["synsets"] == 4 and r["ingested"] == 4
    doc = s.artifacts.get_artifact("wn-oewn-02086723-n")
    assert doc is not None
    # the same shape as the existing 117,659 wn rows — plus the pivot/order keys OEWN carries
    # natively (`ili`, and `sense_ranks`: which sense of each word this synset is, §13.14).
    assert set(doc) - {"ili", "sense_ranks", "forms", "lemma_counts"} == WN_ROW_KEYS
    assert doc["content_type"] == "text/x-wordnet"
    assert doc["ili"] == "i46360"
    assert doc["word"] == "dog" and doc["pos"] == "n"
    assert doc["lemmas"] == ["dog", "domestic dog"]          # underscores → spaces, lowered
    # context is absent by design (a describer supplies it); the facts are here instead
    assert "context" not in doc
    assert doc["title"] == "dog" and doc["gloss"].startswith("a domesticated carnivorous mammal")
    assert doc["collection_id"] == "stage.0.lexicon"
    assert doc["collections"] == ["stage.0.lexicon", "source.oewn"]
    assert doc["cited_from"] == "cite.oewn"
    assert doc["via"] == "op.source.oewn" and doc["operator"] == "op.source.oewn"
    assert doc["provenance"] == "observed"
    # created_by is a vertex reference that resolves (contract §2.1), rather than the claim string
    assert s.artifacts.get_artifact(doc["created_by"]) is not None
    # the source triple exists and the source collection hangs under sources
    assert s.artifacts.get_artifact("cite.oewn") is not None
    assert s.artifacts.get_artifact("op.source.oewn") is not None
    assert "sources" in s.graph.neighbors("source.oewn", "sub_collection_of", direction="out")


def test_oewn_edges_carry_via_and_rung_and_marker_guards_rerun(tmp_path):
    f = tmp_path / "oewn.xml"
    f.write_text(_LMF, encoding="utf-8")
    s = _store()
    r = s0.ingest_stage0_oewn(s, path=str(f))
    assert r["edges"] == 2                        # hypernym + antonym (both endpoints stored)
    mine = [(a, b, l, p) for a, b, l, p in s.graph.props if a.startswith("wn-oewn-")]
    labels = {(a, b, l) for a, b, l, _p in mine}
    assert labels == {("wn-oewn-02086723-n", "wn-oewn-00015568-n", "hypernym"),
                      ("wn-oewn-01123148-a", "wn-oewn-01125429-a", "antonym")}
    for _a, _b, _l, p in mine:
        assert p == {"via": "op.source.oewn", "rung": "observed"}
    # completed → marker written → done; a re-run skips, so edges are emitted once
    assert s0.oewn_done(s)
    r2 = s0.ingest_stage0_oewn(s, path=str(f))
    assert r2.get("skipped") == 1 and r2["ingested"] == 0
    assert len([1 for a, _b, _l, _p in s.graph.props
                if a.startswith("wn-oewn-")]) == 2          # unchanged


def test_oewn_bounded_smoke_run_is_not_completion(tmp_path):
    f = tmp_path / "oewn.xml"
    f.write_text(_LMF, encoding="utf-8")
    s = _store()
    r = s0.ingest_stage0_oewn(s, path=str(f), limit=2)
    assert r["synsets"] == 2
    assert not s0.oewn_done(s)                    # a limit run never writes the marker


def test_cili_draws_pivot_edges_and_never_mints_synset_vertices(tmp_path):
    f = tmp_path / "ili.ttl"
    f.write_text(_TTL, encoding="utf-8")
    s = _store()
    g.bootstrap(s)
    _seed_synsets(s)
    n_wn = sum(1 for _ in s.artifacts.list_artifacts(content_type="text/x-wordnet"))
    resolve = lambda src: "wn-able.a.01" if src == ("00001740", "a") else None
    r = s0.ingest_stage0_cili(s, path=str(f), resolve=resolve)
    assert r["parsed"] == 3
    # i1: OEWN row + resolved PWN row → ONE typed pivot edge onto the PWN spine
    assert r["edges"] == 1 and r["ingested"] == 1
    assert ("wn-oewn-00001740-a", "wn-able.a.01", "ili") in \
        {(a, b, l) for a, b, l, _p in s.graph.props}
    props = [p for a, b, l, p in s.graph.props if l == "ili"][0]
    assert props == {"ili": "i1", "via": "op.source.cili", "rung": "observed",
                     "cited_from": "cite.cili"}
    # i2: nothing local → counted, invented nowhere; i3: one endpoint → nothing to draw
    assert r["no_local_synset"] == 1 and r["pwn_unresolved"] == 1
    assert r["single_endpoint"] == 1
    # edges only: the synset vertex count is unchanged
    assert sum(1 for _ in s.artifacts.list_artifacts(content_type="text/x-wordnet")) == n_wn
    # the open type system minted the edge-type artifact, homed in the ontology
    et = s.artifacts.get_artifact("etype.ili")
    assert et is not None and et["cited_from"] == g.CITE_GENESIS
    # completed → marker → a re-run skips
    assert s0.cili_done(s)
    assert s0.ingest_stage0_cili(s, path=str(f), resolve=resolve).get("skipped") == 1


def test_cili_format_drift_writes_no_marker(tmp_path):
    f = tmp_path / "ili.ttl"
    f.write_text("@prefix nothing: <x> .\n", encoding="utf-8")   # zero <iN> statements
    s = _store()
    g.bootstrap(s)
    r = s0.ingest_stage0_cili(s, path=str(f), resolve=lambda src: None)
    assert r["parsed"] == 0 and r["edges"] == 0
    assert not s0.cili_done(s)                    # drift is reported and the stage stays owed


def test_conceptnet_streams_lands_typed_cited_relations_and_holds_at_truncation(tmp_path):
    p = _gz(tmp_path, "cn.csv.gz", "\n".join(_CN_LINES) + "\n" + _CN_TAIL)   # no trailing \n
    s = _store()
    r = s0.ingest_stage0_conceptnet(s, path=str(p))
    # complete lines landed: dog/animal/pet concepts, is_a + related_to edges
    assert r["concepts"] == 3 and r["edges"] == 2 and r["skipped"] == 2
    dog = s.artifacts.get_artifact("cn-dog")
    assert dog["content_type"] == "application/x-concept"
    assert dog["cited_from"] == "cite.conceptnet"
    assert dog["via"] == "op.source.conceptnet" and dog["provenance"] == "observed"
    assert dog["collections"] == ["stage.0.lexicon", "source.conceptnet"]
    got = {(a, b, l) for a, b, l, _p in s.graph.props}
    assert ("cn-dog", "cn-animal", "is_a") in got and ("cn-dog", "cn-pet", "related_to") in got
    w = [p_ for a, b, l, p_ in s.graph.props if l == "is_a"][0]
    assert w == {"via": "op.source.conceptnet", "rung": "observed",
                 "cited_from": "cite.conceptnet", "weight": 2.0}
    # relation types are minted as edge-type artifacts (the open type system)
    assert s.artifacts.get_artifact("etype.is_a") is not None
    assert s.artifacts.get_artifact("etype.related_to") is not None
    # the truncated tail: reported, cursor held at it, undrained and unmarked — so a re-staged
    # complete file re-reads exactly that line and nothing is lost.
    assert r["truncated_tail"] is True and r["drained"] is False
    assert s.artifacts.get_artifact(s0.CN_CURSOR_ID)["lines_done"] == 4
    assert not s0.conceptnet_done(s)


def test_conceptnet_resume_after_restage_loses_nothing_and_duplicates_nothing(tmp_path):
    p = _gz(tmp_path, "cn.csv.gz", "\n".join(_CN_LINES) + "\n" + _CN_TAIL)
    s = _store()
    s0.ingest_stage0_conceptnet(s, path=str(p))
    # the download is re-staged COMPLETE (the tail line now whole; still no trailing \n)
    p2 = _gz(tmp_path, "cn2.csv.gz",
             "\n".join(_CN_LINES) + "\n" + '/a/[x]\t/r/UsedFor\t/c/en/pen\t/c/en/writing\t'
             '{"weight": 1.0}')
    r2 = s0.ingest_stage0_conceptnet(s, path=str(p2))
    # only the held line was read: its edge plus 2 new concepts, nothing re-ingested
    assert r2["edges"] == 1 and r2["concepts"] == 2
    assert r2["drained"] is True and s0.conceptnet_done(s)
    assert s.artifacts.get_artifact(s0.CN_CURSOR_ID)["lines_done"] == 5
    got = [(a, b, l) for a, b, l, _p in s.graph.props if a.startswith("cn-")]
    assert ("cn-pen", "cn-writing", "used_for") in got
    assert len(got) == 3 == len(set(got))         # no duplicate edges across the resume
    # drained → the marker guards any further run
    assert s0.ingest_stage0_conceptnet(s, path=str(p2)).get("skipped") == 1


def test_conceptnet_max_lines_is_a_tick_size_not_a_cap(tmp_path):
    p = _gz(tmp_path, "cn.csv.gz", "\n".join(_CN_LINES) + "\n")
    s = _store()
    r1 = s0.ingest_stage0_conceptnet(s, path=str(p), max_lines=2)
    assert r1["drained"] is False                 # budget hit, cursor carries the rest
    assert s.artifacts.get_artifact(s0.CN_CURSOR_ID)["lines_done"] == 2
    r2 = s0.ingest_stage0_conceptnet(s, path=str(p), max_lines=100)
    assert r2["drained"] is True                  # next tick finishes the file
    assert r1["edges"] + r2["edges"] == 2


def test_omw_ingests_only_allowlisted_languages_and_logs_the_skips(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EMBER_CACHE_DIR", str(tmp_path))
    fake = _fake_wn(_OMW_INDEX, {"omw-id": [
        _SS("omw-id-00001740-a", "a", "i1", ["mampu"], "dapat melakukan"),
        _SS("omw-id-55555555-n", "n", "i9", ["anjing", "anjing_kampung"]),
        _SS("omw-id-66666666-n", "n", "i8", []),           # no vocabulary → adds nothing
    ]}, {"omw-id": "id"})
    monkeypatch.setitem(sys.modules, "wn", fake)
    s = _store()
    g.bootstrap(s)
    _seed_synsets(s)                              # wn-oewn-00001740-a carries ili i1
    r = s0.ingest_stage0_omw(s)
    assert r["languages"] == 1 and r["synsets"] == 2 and r["no_words"] == 1
    assert fake._downloaded == ["omw-id:1.4"]
    # skips are reported — plWordNet ("wordnet" is a pointer rather than a license) and the
    # share-alike Dutch wordnet are both outside the allowlist and wait for clearance…
    why = {x["id"]: x["why"] for x in r["skipped"]}
    assert "allowlist" in why["omw-pl"] and "allowlist" in why["omw-nl"]
    # …and each skip is one clear log line with the license and the reason.
    out = capsys.readouterr().out
    assert "[op.source.omw] SKIPPED omw-pl (license: wordnet)" in out
    assert "[op.source.omw] SKIPPED omw-nl" in out and "by-sa" in out
    # the rows: wn shape + lang + ili, keyed by the language's OWN lemmas
    doc = s.artifacts.get_artifact("wn-omw-id-00001740-a")
    assert {"title", "gloss", "content", "lemmas", "word", "pos"} <= set(doc)
    assert "context" not in doc          # the describer supplies it (illuminate)
    assert doc["lang"] == "id" and doc["ili"] == "i1"
    assert doc["lemmas"] == ["mampu"] and doc["cited_from"] == "cite.omw"
    assert doc["collections"] == ["stage.0.lexicon", "source.omw"]
    dog = s.artifacts.get_artifact("wn-omw-id-55555555-n")
    assert dog["lemmas"] == ["anjing", "anjing kampung"]
    # expand-style: vocabulary ATTACHES to the pivot synset that carries the same ili
    assert ("wn-omw-id-00001740-a", "wn-oewn-00001740-a", "ili") in \
        {(a, b, l) for a, b, l, _p in s.graph.props}
    assert r["no_pivot"] == 1                     # i9 has no local pivot — counted, and left alone
    # per-language marker → this language ingests once; the stage stays owed while allowlisted
    # languages remain.
    assert "omw-id" in g._shards_done(s, "omw")
    assert not s0.omw_done(s)
    r2 = s0.ingest_stage0_omw(s)
    assert r2["languages"] == 0 and r2["synsets"] == 0


def test_omw_license_drift_skips_instead_of_ingesting(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EMBER_CACHE_DIR", str(tmp_path))
    drifted = {"omw-id": {"label": "Wordnet Bahasa (Indonesian)", "language": "id",
                          "versions": {"1.4": {"license": "proprietary — all rights reserved"}}}}
    fake = _fake_wn(drifted, {"omw-id": [_SS("omw-id-1-n", "n", None, ["x"])]}, {"omw-id": "id"})
    monkeypatch.setitem(sys.modules, "wn", fake)
    s = _store()
    g.bootstrap(s)
    r = s0.ingest_stage0_omw(s)
    assert r["languages"] == 0 and r["synsets"] == 0
    assert fake._downloaded == []                 # a drifted license never even downloads
    assert any("drifted" in x["why"] for x in r["skipped"])
    assert "drifted" in capsys.readouterr().out


def test_oewn_keeps_the_sources_sense_order(tmp_path):
    """LMF lists a word's senses in WordNet sense order, and that order is the only statement the
    source makes about which meaning a bare word most likely carries. Recorded at ingest as
    `sense_ranks`, it is available downstream; without it an index falls back to sorting synset
    offsets, which is arbitrary with respect to meaning — `star` lands on the network-topology
    sense."""
    f = tmp_path / "wn.xml"
    f.write_text(_LMF, encoding="utf-8")
    s = _store()
    s0.ingest_stage0_oewn(s, path=str(f))
    doc = s.artifacts.get_artifact("wn-oewn-02086723-n")
    ranks = doc.get("sense_ranks") or {}
    assert ranks, "the source's sense order must survive ingest"
    assert all(isinstance(v, int) and v >= 0 for v in ranks.values())
    # every lemma the row carries is placed — an unranked lemma falls back to offset order, which
    # carries no information about meaning.
    assert set(ranks) == set(doc["lemmas"])


def test_the_pwn_spine_writes_the_SAME_row_shape_as_oewn(monkeypatch):
    from ember import genesis as _g
    _install_fake_nltk(monkeypatch)
    s = _store()
    r = _g.ingest_stage0_wordnet(s)
    assert r["synsets"] == 2
    doc = s.artifacts.get_artifact("wn-dog.n.01")
    assert set(doc) - {"ili", "sense_ranks", "forms", "lemma_counts"} == WN_ROW_KEYS
    # observation only: structured fields. The offer comes from the describer, not from the row.
    assert "context" not in doc
    assert doc["content"] == doc["gloss"] == "a domesticated canine"
    assert "part of speech:" not in doc["content"] and "synonyms:" not in doc["content"]
    assert doc["title"] == "dog" and doc["lemmas"] == ["dog", "domestic dog"]


def test_the_pwn_spine_records_sense_order_and_bootstraps_its_type(monkeypatch):
    from ember import genesis as _g
    _install_fake_nltk(monkeypatch)
    s = _store()
    _g.ingest_stage0_wordnet(s)
    # "dog" is sense 0 of dog.n.01 and sense 1 of frank.n.02 — the rank is per word.
    assert s.artifacts.get_artifact("wn-dog.n.01")["sense_ranks"]["dog"] == 0
    assert s.artifacts.get_artifact("wn-frank.n.02")["sense_ranks"]["dog"] == 1
    # and the describer lands with the rows, so a fresh store renders them
    td = s.artifacts.get_artifact("type.text/x-wordnet")
    assert td is not None and td["offer_template"] == "{title}: {gloss}"


def test_case_survives_ingest_because_it_is_the_proper_noun_marker(monkeypatch):
    """Capitalization is the source's own proper-noun marker, so the `sense_ranks` keys carry it.

    LMF gives `mass` (the physical quantity) and `Mass` (the liturgy) separate LexicalEntries, and a
    sense number is per-entry, so both are sense 0. Folding the rank keys to lowercase collapses
    them into one `mass -> 0`; the tie then falls through to synset-offset order, and "mass physics"
    answers with the liturgy.

    `lemmas` stays lowercased — it is the keyed-lookup field — and the ontology driver matches the
    two case-insensitively."""
    f = tmp = None
    import tempfile, os as _os
    d = tempfile.mkdtemp()
    f = _os.path.join(d, "wn.xml")
    lmf = _LMF.replace('writtenForm="dog"', 'writtenForm="Dog"', 1)
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(lmf)
    s = _store()
    s0.ingest_stage0_oewn(s, path=f)
    doc = s.artifacts.get_artifact("wn-oewn-02086723-n")
    ranks = doc.get("sense_ranks") or {}
    assert "Dog" in ranks, "the written form's case was destroyed: %r" % (ranks,)
    assert doc["lemmas"] == [x.lower() for x in doc["lemmas"]], "lemmas are the lookup field"
