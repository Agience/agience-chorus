"""GENESIS P0 — schema freeze, Stage-0 ingest, and ρ metrics.

Moved here from `agience-ember/tests/test_genesis.py`: these exercise operators through ember's
runner and need a sha-verified operator payload present. The payloads are chorus's,
built from chorus source; ember is the engine that runs them, so the test belongs
beside the operators. Tests in that file needing no payload stayed in ember.
"""
import os
import pytest
from ember import genesis as g
from _fakes import _FakeArtifacts, _FakeGraph, _FakeStore  # noqa: F401
def _count_content(store, cid):
    return sum(1 for _ in store.artifacts.list_artifacts(collection_id=cid))
def _store_up():
    try:
        from mantle.shard.local_store import open_store
        return open_store().ready()
    except Exception:
        return False


def test_consolidate_nearvdup_archives_only_byte_identical():
    """Members sharing a `content_ref` are the same bytes — that is the ONLY merge authority."""
    s = _FakeStore()
    g.bootstrap(s)
    base = " ".join(f"word{i}" for i in range(60))
    # d1/d2 are BYTE-IDENTICAL: same cas ref. d3 is different content.
    for i in (1, 2):
        s.artifacts.put_artifact({"id": f"d{i}", "content_type": "text/markdown",
                                  "state": "committed", "content": base,
                                  "content_ref": "cas/" + "a" * 64,
                                  "lemmas": ["a"] if i == 1 else [], "provenance": "observed",
                                  "collection_id": "stage.1.grammar"})
    s.artifacts.put_artifact({"id": "d3", "content_type": "text/markdown", "state": "committed",
                              "content": "totally different unrelated prose about cats and hats",
                              "content_ref": "cas/" + "b" * 64,
                              "lemmas": ["x"], "collection_id": "stage.1.grammar"})
    dry = g.consolidate_nearvdup(s, collection_id="stage.1.grammar", apply=False)
    assert dry["groups"] == 1 and dry["consolidated"] == 1 and dry["applied"] is False
    assert dry["merge_basis"] == "content_ref_exact"
    # nothing changed on a dry run
    assert s.artifacts.get_artifact("d2")["state"] == "committed"
    assert not s.graph.neighbors("d1", "consolidates", direction="out")

    applied = g.consolidate_nearvdup(s, collection_id="stage.1.grammar", apply=True)
    assert applied["consolidated"] == 1
    # d1 is canonical (more keyed) -> consolidates -> d2, and d2 archived (content retained)
    assert "d2" in s.graph.neighbors("d1", "consolidates", direction="out")
    d2 = s.artifacts.get_artifact("d2")
    assert d2["state"] == "archived" and d2["consolidated_by"] == "d1" and d2["content"]


def test_nearvdup_never_archives_on_similarity_only():
    """Two docs that a 0.85 similarity threshold would flag as near-duplicates, but whose bytes
    differ, survive — and are recorded as a `near_dup_candidate` observation instead.

    The LSH candidate-score distribution has no valley (§9), so any cut through it is ill-posed;
    the estimator's own resolution is ±0.0316 at J=0.85. Archiving on that estimate is the
    unrecoverable direction."""
    from prism import minhash
    s = _FakeStore()
    g.bootstrap(s)
    base = " ".join(f"word{i}" for i in range(200))
    near = base + " word200 word201"               # >0.85 Jaccard, but NOT the same bytes
    assert minhash.estimated_jaccard(minhash.signature(base), minhash.signature(near)) >= 0.85
    s.artifacts.put_artifact({"id": "n1", "content_type": "text/markdown", "state": "committed",
                              "content": base, "content_ref": "cas/" + "1" * 64,
                              "minhash": list(minhash.signature(base)),
                              "lemmas": ["a"], "provenance": "observed"})
    s.artifacts.put_artifact({"id": "n2", "content_type": "text/markdown", "state": "committed",
                              "content": near, "content_ref": "cas/" + "2" * 64,
                              "minhash": list(minhash.signature(near)),
                              "lemmas": [], "provenance": "observed"})
    r = g.consolidate_nearvdup(s, content_type="text/markdown", apply=True)
    assert r["consolidated"] == 0                  # nothing archived on a similarity estimate
    assert s.artifacts.get_artifact("n2")["state"] == "committed"
    assert not s.graph.neighbors("n1", "consolidates", direction="out")
    # ...but the signal is NOT thrown away — it is retained as an advisory observation.
    assert r["near_dup_candidate_edges"] == 1 and r["similarity_is_advisory"] is True
    assert "n2" in s.graph.neighbors("n1", "near_dup_candidate", direction="out")


def test_nearvdup_does_not_sign_from_the_content_preview():
    """`content` is a 300-char preview on legacy rows. Signing from it compares a preview-derived
    signature against full-content ones, biasing toward false merges on exactly the templated stubs
    this operator targets (templates share their opening 300 chars by construction). An artifact
    with no stored signature is not comparable, and that is reported, never faked."""
    s = _FakeStore()
    g.bootstrap(s)
    base = " ".join(f"word{i}" for i in range(200))
    for i, ref in ((1, "1"), (2, "2")):
        s.artifacts.put_artifact({"id": f"p{i}", "content_type": "text/markdown",
                                  "state": "committed", "content": base,   # content but NO minhash
                                  "content_ref": "cas/" + ref * 64,
                                  "lemmas": [], "provenance": "observed"})
    r = g.consolidate_nearvdup(s, content_type="text/markdown", apply=True)
    assert r["skipped_no_signature"] == 2          # counted as UNMEASURED, not as dissimilar
    assert r["compared"] == 0
    assert r["near_dup_candidate_edges"] == 0              # 0 here means "could not tell", and says so
    assert r["consolidated"] == 0


def test_consolidate_colimit_draws_morphisms():
    s = _FakeStore()
    g.bootstrap(s)
    for i in (1, 2, 3):
        s.artifacts.put_artifact({"id": f"m{i}", "content_type": "text/x-wordnet",
                                  "state": "committed", "content": "dog sense", "lemmas": ["dog"]})
    r = g.consolidate_colimit(s, ["m1", "m2", "m3"], concept_lemmas=["dog"], apply=True)
    assert r["members"] == 3 and r["consolidates_edges"] == 3
    canon = r["canonical"]
    assert s.artifacts.get_artifact(canon)["content_type"] == "application/x-concept"
    assert set(s.graph.neighbors(canon, "consolidates", direction="out")) == {"m1", "m2", "m3"}


def test_define_operator_is_invokable_immediately():
    s = _FakeStore()
    g.bootstrap(s)
    # define a composition operator purely as DATA
    d = g.invoke(s, "op.operator.define", {"id": "op.test.alias", "kind": "composition",
                                           "spec": {"steps": [{"op": "op.consistency"}]},
                                           "offer": "alias for consistency"})["result"]
    assert d["defined"] and d["invokable_now"]
    a = s.artifacts.get_artifact("op.test.alias")
    assert a["kind"] == "composition" and a["spec"]["steps"][0]["op"] == "op.consistency"
    assert a["cited_from"] == g.CITE_GENESIS      # defined operators are still provenanced
    # invoke the just-defined operator — no code change, no restart
    r = g.invoke(s, "op.test.alias", {})["result"]
    assert "steps" in r and r["steps"][0]["operator"] == "op.consistency"
    # a source spec stores its declarative definition (interpreted generically at invoke)
    d2 = g.invoke(s, "op.operator.define", {"id": "op.source.mydataset", "kind": "source",
                                            "spec": {"repo": "org/ds", "config": "v1",
                                                     "stage": "staging"}})["result"]
    assert d2["defined"]
    assert s.artifacts.get_artifact("op.source.mydataset")["spec"]["repo"] == "org/ds"
    # bad kind is rejected
    assert g.invoke(s, "op.operator.define", {"id": "op.x", "kind": "bogus", "spec": {}})["result"]["defined"] is False


def test_consistency_clean_universe_passes():
    s = _FakeStore()
    g.bootstrap(s)
    c = g.consistency(s)
    assert c["all_pass"] is True and not c["anomalies"]
    names = {ch["check"] for ch in c["checks"]}
    assert {"rho_in_[0,1]", "generators_le_corpus", "provenance_invariant",
            "fitness_in_[0,1]", "mass_monotonic"} <= names


def test_consistency_flags_broken_provenance():
    s = _FakeStore()
    g.bootstrap(s)
    # an artifact with no citation violates the §12 invariant -> hard anomaly
    s.artifacts.put_artifact({"id": "orphan", "content_type": "text/markdown",
                              "state": "committed", "content": "x", "lemmas": ["x"]})
    c = g.consistency(s)
    assert c["all_pass"] is False
    assert any(a["check"] == "provenance_invariant" for a in c["anomalies"])


def test_remember_is_private_owner_scoped():
    s = _FakeStore()
    g.bootstrap(s)
    from mantle.db import access
    r = g.remember(s, "my project ships on Friday", principal="author@example.com")
    assert r["stored"] and r["private"] is True
    a = s.artifacts.get_artifact(r["id"])
    assert "owner" not in a                         # no owner FIELD — ownership is the grant
    assert a["collection_id"] == "private.author@example.com"
    assert a["provenance"] == "human_validated"     # the owner staked it — highest rung
    assert a["cited_from"] == "cite.owner.author@example.com"
    # with Garage present the index holds NO cleartext preview (content_ref only); the fake store
    # has no Garage, so content falls back inline — encryption is exercised in the live smoke path.
    assert a.get("lemmas")                          # keyed for the owner's recall either way
    # Private is a grant, not a flag: the memory carries no visibility/no_share, and `access` sees it as
    # non-public (its collection is gated by the owner's Read grant, minted by `_ensure_private`).
    assert "no_share" not in a and "visibility" not in a
    assert access.is_public(s, a) is False
    assert access.gated_collections(s) == {"private.author@example.com"}
    assert access.can_read(s, a, "author@example.com") is True
    assert access.can_read(s, a, "someone-else") is False


def test_share_requires_consent_then_stakes():
    s = _FakeStore()
    g.bootstrap(s)
    mid = g.remember(s, "a claim I might share", principal="author@example.com")["id"]
    from mantle.db import access
    # without confirm: nothing shared, nothing changes — still gated by the owner's grant
    r1 = g.share(s, mid, principal="author@example.com")
    assert r1["shared"] is False and r1["reason"] == "consent required"
    assert access.is_public(s, s.artifacts.get_artifact(mid)) is False
    # a non-owner cannot consent
    assert g.share(s, mid, principal="someone-else", confirm=True)["shared"] is False
    # #2 make public: owner consents with a stake → the same artifact is made public by a grant to the
    # public entity (no copy, no re-key). It now reads public to everyone and carries the staked claim.
    r2 = g.share(s, mid, principal="author@example.com", confirm=True, stake=2.0)
    assert r2["shared"] and r2["staked"] == 2.0 and r2["mode"] == "public" and r2["id"] == mid
    a = s.artifacts.get_artifact(mid)
    assert access.is_public(s, a) is True               # made public — readable by all + meshes out
    assert access.can_read(s, a, "anyone-at-all") is True
    assert a["staked_claim"]["by"] == "author@example.com" and a["staked_claim"]["stake"] == 2.0
    assert "subjects" in a["collections"]


def test_share_with_a_person_grants_read_without_making_public():
    """#1 — sharing with a person is a Read grant: their light-cone reaches this artifact, it stays
    private (not public), and only they gain access — not everyone."""
    s = _FakeStore()
    g.bootstrap(s)
    from mantle.db import access
    mid = g.remember(s, "for ada only", principal="author@example.com")["id"]
    assert access.can_read(s, s.artifacts.get_artifact(mid), "ada") is False   # ada cannot yet
    r = g.share(s, mid, to_principal="ada", principal="author@example.com", confirm=True)
    assert r["shared"] and r["mode"] == "grant" and r["with"] == "ada"
    a = s.artifacts.get_artifact(mid)
    assert access.can_read(s, a, "ada") is True         # ada's light-cone now reaches this artifact
    assert access.is_public(s, a) is False              # still NOT public
    assert access.can_read(s, a, "eve") is False        # and only ada, not everyone


def test_nearvdup_never_consolidates_private():
    """The private artifact shares `content_ref` with the public one on purpose.

    Merge authority is exact `content_ref` identity, so a private artifact with different bytes
    would be excluded for the wrong reason and this test would pass even with the privacy filter
    deleted — a test that cannot fail. Giving them the same ref means the only thing standing
    between them and a merge is the privacy check, which is what this test verifies. The control
    below proves the setup would otherwise consolidate."""
    s = _FakeStore()
    g.bootstrap(s)
    base = " ".join(f"tok{i}" for i in range(60))
    REF = "cas/" + "c" * 64
    s.artifacts.put_artifact({"id": "pub", "content_type": "text/markdown", "state": "committed",
                              "content": base, "content_ref": REF,
                              "lemmas": ["a"], "provenance": "observed"})
    # a private memory with BYTE-IDENTICAL content must NOT be pulled into consolidation
    from mantle.db import access
    g.remember(s, base, principal="author@example.com")
    priv = [a for a in s.artifacts.list_artifacts()
            if a.get("collection_id") == "private.author@example.com"
            and a.get("content_type") == "text/markdown" and not access.is_public(s, a)]
    assert priv, "setup failed: remember() produced no private (grant-gated) artifact to exclude"
    for a in priv:
        a["content_ref"] = REF
        a["content_type"] = "text/markdown"
        s.artifacts.put_artifact(a)
    r = g.consolidate_nearvdup(s, content_type="text/markdown", apply=True)
    assert r["consolidated"] == 0                    # private excluded from the scope
    assert s.artifacts.get_artifact("pub")["state"] == "committed"

    # CONTROL: identical setup minus the privacy marking DOES consolidate — so the assertion
    # above is load-bearing rather than incidental.
    s2 = _FakeStore()
    g.bootstrap(s2)
    for i in ("pub", "other"):
        s2.artifacts.put_artifact({"id": i, "content_type": "text/markdown", "state": "committed",
                                   "content": base, "content_ref": REF,
                                   "lemmas": ["a"] if i == "pub" else [], "provenance": "observed"})
    assert g.consolidate_nearvdup(s2, content_type="text/markdown", apply=True)["consolidated"] == 1


def test_candidate_edges_are_budgeted_and_the_drop_is_REPORTED():
    """LSH candidate pairs scale ~n^1.83, not linearly: doubling the corpus multiplies candidate
    pairs by 3.2-4.0x, so the 6.11M-blob corpus implies ~2e7 pairs — against a graph holding
    273,000 real edges. Emitting one edge each would be a 70x explosion of derived data that LSH
    can regenerate on demand.

    The budget exists because the honest number is large; this test exists because a cap that does
    not say what it dropped turns a partial run into one that reads as complete."""
    from prism import minhash
    s = _FakeStore()
    g.bootstrap(s)
    base = " ".join(f"word{i}" for i in range(200))
    # four mutually-similar docs -> several candidate pairs, but a budget of 1
    for i in range(4):
        txt = base + (" extra%d" % i)
        s.artifacts.put_artifact({"id": f"c{i}", "content_type": "text/markdown",
                                  "state": "committed", "content": txt,
                                  "content_ref": "cas/" + str(i) * 64,
                                  "minhash": list(minhash.signature(txt)),
                                  "lemmas": ["a"] if i == 0 else [],
                                  "provenance": "observed"})
    r = g.consolidate_nearvdup(s, content_type="text/markdown", apply=True,
                               max_candidate_edges=1)
    assert r["near_dup_edge_budget"] == 1
    assert r["near_dup_candidate_edges"] <= 1
    # the whole point: what LSH found is reported, not just what was written
    assert r["near_dup_candidates_found"] >= r["near_dup_candidate_edges"]
    assert (r["near_dup_candidates_dropped"]
            == r["near_dup_candidates_found"] - r["near_dup_candidate_edges"])
    # and nothing was archived on similarity regardless of budget
    assert r["consolidated"] == 0
    for i in range(4):
        assert s.artifacts.get_artifact(f"c{i}")["state"] == "committed"