"""`sage.colimit` — records that are the same THING absorb into one junction.

Built from the case the module was written for and which nothing had ever asserted: one merge
recorded in two repos, the artifacts differing by exactly one line — the provenance header.
Before 2026-08-25 this code lived in `src/junction/`, could not import, and had no test.
"""


from agience_chorus.sage import colimit  # noqa: E402

# 2026-08-26: a dead `sys.path` insert stood here and is removed. MEASURED per file — the
# inserts were neutralised, this file's tests run, and it passed; the full chorus suite then
# confirmed no global side effect (861 passed). `pytest.ini:34` (`pythonpath = src`) is what
# puts `src` on the path. Eight sibling test files KEEP theirs and must — see
# `agience-build/tighten/STATE.json`, finding `thirty-five-dead-path-inserts`.

BODY = "Merge: chorus stops importing ember\n\nThe host owns the wire format now.\n"


def _record(rid, repo, sha):
    """A captured commit, exactly as the store holds one."""
    return {
        "id": rid,
        "kind": "commit",
        "title": "%s@%s: merge chorus/ember split" % (repo, sha),
        "content": "**%s** · `%s` · john · 2026-08-03\n\n%s" % (repo, sha, BODY),
        "context": {"repo": repo, "sha": sha},
    }


def test_the_provenance_header_does_not_enter_the_things_identity():
    """The line that differs between two copies says where the copy came from, not what it says."""
    a = _record("a1", "agience-origin", "08a37ae6")
    b = _record("b1", "agience-mantle", "1f2e3d4c")
    assert colimit.canonical_body(a["content"]) == colimit.canonical_body(b["content"])


def test_two_records_of_one_merge_condense_to_one_junction():
    js = colimit.condense([_record("a1", "agience-origin", "08a37ae6"),
                           _record("b1", "agience-mantle", "1f2e3d4c")])
    assert len(js) == 1
    assert len(js[0].sources) == 2
    assert js[0].thing_id.startswith("thing:commit:")


def test_a_lone_record_is_left_alone():
    """Emitting a junction over one record ADDS an artifact while removing none — the opposite
    of what a tekton is for."""
    assert colimit.condense([_record("a1", "agience-origin", "08a37ae6")]) == []


def test_records_that_differ_in_substance_do_not_collapse():
    """The guard that matters: absorption must not lose a distinction."""
    a = _record("a1", "agience-origin", "08a37ae6")
    b = _record("b1", "agience-mantle", "1f2e3d4c")
    b["content"] = b["content"].replace("The host owns", "The host no longer owns")
    assert colimit.condense([a, b]) == []


def test_two_observers_derive_the_same_thing_id():
    """Content-addressed, so agreement needs no conferring — the anchor rule one layer up."""
    canon = colimit.canonical_body(_record("a1", "r", "abc123")["content"])
    assert colimit.thing_id("commit", canon) == colimit.thing_id("commit", canon)
    assert colimit.thing_id("commit", canon) != colimit.thing_id("note", canon)


def test_the_junction_is_not_named_after_whichever_copy_was_read_first():
    """`agience-mantle@08a37ae6: merge ...` records which repo happened to be read first, and the
    whole point of the thing-id is that the answer does not depend on that."""
    title = colimit.thing_title(["agience-origin@08a37ae6: merge chorus/ember split",
                                 "agience-mantle@1f2e3d4c: merge chorus/ember split"])
    assert title == "merge chorus/ember split"
    assert "@" not in title


def test_the_rendered_junction_carries_every_source_in_its_body():
    """In the BODY, not only in edges: the body is what `recall` reads and what a reader is
    shown. A junction that could not say it came from two repos would be a summary."""
    js = colimit.condense([_record("a1", "agience-origin", "08a37ae6"),
                           _record("b1", "agience-mantle", "1f2e3d4c")])
    out = colimit.render(js[0])
    assert "agience-origin" in out and "agience-mantle" in out
    assert "archived, not deleted" in out
