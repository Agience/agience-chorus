"""The Ember cleanup agent, exercised over a fake transport — no network, no platform imports.

Proves the load-bearing behaviors: it finds exact duplicates and archives (never deletes)
all-but-one, and it has no generative path — no LLM call is reachable from any agent operation.
`test_agent_has_no_generative_path_and_never_calls_an_llm` is the strongest assertion of that: the
fake transport fails the test if any agent operation so much as touches a chat endpoint.
"""
from __future__ import annotations

import inspect

import pytest

from seraph.agent.cleanup import DocsCleanupAgent, content_hash
from seraph.agent.mantle_client import MantleClient
from seraph.agent.transport import HttpResponse


class FakeTransport:
    """Mimics the slice of Mantle HTTP the agent uses — and only that. An LLM/chat request is not
    mocked, it is a hard failure: no agent path may ever reach a model."""

    def __init__(self, artifacts: dict) -> None:
        self.artifacts = artifacts
        self.archived: list[str] = []
        self.created: list[dict] = []
        self.llm_attempts: list[str] = []

    def request(self, method, url, *, headers=None, json=None, params=None, timeout=30.0):
        if "chat/completions" in url or "/completions" in url or "/messages" in url:
            self.llm_attempts.append(url)
            raise AssertionError(f"agent attempted an LLM call — forbidden: {url}")
        if method == "GET" and url.endswith("/children"):
            return HttpResponse(200, list(self.artifacts.values()))
        if method == "POST" and url.endswith("/artifacts"):
            self.created.append(json)
            return HttpResponse(200, {"id": "new-consolidated"})
        if method == "PATCH" and "/artifacts/" in url:
            aid = url.rsplit("/", 1)[-1]
            self.archived.append(aid)
            return HttpResponse(200, {"id": aid, "state": "archived"})
        if method == "GET" and "/artifacts/" in url:
            return HttpResponse(200, self.artifacts.get(url.rsplit("/", 1)[-1]))
        return HttpResponse(404)


def _md(i, name, content):
    return {"id": i, "name": name, "content": content, "content_type": "text/markdown"}


def test_scan_finds_exact_duplicate_groups():
    arts = {
        "a": _md("a", "A", "same body"),
        "b": _md("b", "B-dupe", "same body"),   # exact dup of a
        "c": _md("c", "C", "unique body"),
    }
    agent = DocsCleanupAgent(MantleClient("http://m", "tok", FakeTransport(arts)), "col")
    plan = agent.scan()
    assert plan.total == 3
    assert len(plan.duplicate_groups) == 1
    assert set(plan.duplicate_groups[0]) == {"a", "b"}
    assert plan.duplicates == 1


def test_dedupe_archives_all_but_one_never_deletes():
    ft = FakeTransport({"a": _md("a", "A", "same"), "b": _md("b", "B", "same"),
                        "c": _md("c", "C", "same")})
    agent = DocsCleanupAgent(MantleClient("http://m", "tok", ft), "col")
    plan = agent.scan()
    rep = agent.dedupe(plan, dry_run=False)
    assert rep["archived"] == 2                 # 3 identical -> keep 1, archive 2
    assert len(ft.archived) == 2                # PATCH state=archived, not delete
    assert "a" not in ft.archived               # the first is the canonical kept


def test_dedupe_dry_run_touches_nothing():
    ft = FakeTransport({"a": _md("a", "A", "x"), "b": _md("b", "B", "x")})
    agent = DocsCleanupAgent(MantleClient("http://m", "tok", ft), "col")
    rep = agent.dedupe(agent.scan(), dry_run=True)
    assert rep["archived"] == 1 and ft.archived == []   # previewed, not applied


def test_agent_has_no_generative_path_and_never_calls_an_llm():
    """Pins that the LLM consolidation capability does not exist, rather than quietly no-op'ing: no
    `consolidate`, no reasoner to inject, and a full scan+dedupe cycle that provably never reaches a
    chat endpoint (FakeTransport raises if it does)."""
    ft = FakeTransport({"a": _md("a", "A", "alpha"), "b": _md("b", "B", "alpha")})
    agent = DocsCleanupAgent(MantleClient("http://m", "tok", ft), "col")

    # no generative method exists — a stale caller gets a loud AttributeError, not a no-op
    assert not hasattr(agent, "consolidate")
    with pytest.raises(AttributeError):
        agent.consolidate(["a", "b"], title="Merged Doc", dry_run=False)

    # and there is no reasoner seam to inject one through
    assert not hasattr(agent, "reasoner")
    assert "reasoner" not in inspect.signature(DocsCleanupAgent).parameters
    with pytest.raises(TypeError):
        DocsCleanupAgent(MantleClient("http://m", "tok", ft), None, "col")   # a 3-arg call is rejected

    # the deterministic work still runs end to end, and writes nothing generated
    rep = agent.dedupe(agent.scan(), dry_run=False)
    assert rep["archived"] == 1 and ft.archived == ["b"]
    assert ft.created == []          # no artifact is authored without a source of content
    assert ft.llm_attempts == []     # no model was contacted on any path


def test_reasoner_module_is_gone():
    """`seraph.agent.reasoner` does not exist and must not reappear: seraph has no LLM client."""
    with pytest.raises(ImportError):
        import seraph.agent.reasoner  # noqa: F401
    import seraph.agent as agent_pkg
    assert not hasattr(agent_pkg, "Reasoner") and "Reasoner" not in agent_pkg.__all__


def test_content_hash_stable():
    assert content_hash("x") == content_hash("x") != content_hash("y")
