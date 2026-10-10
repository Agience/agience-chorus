"""Two sage tools that could each tell a caller about something they may not reach.

`web_retrieve` fetches a caller-named URL. It goes through the shared egress guard, so a URL whose
host is internal is refused before any connection is opened — observed here as the absence of a
connection attempt and of any HTTP client, not inferred from an error string.

`corpus_search` answers under the caller's own grants. A candidate the caller may not read must
leave no trace in the answer: neither a count of refused candidates nor a total that includes them,
since either tells the caller that private artifacts match their query.
"""
from __future__ import annotations

import asyncio
import socket

import pytest

from agience_chorus import _persona

_sage_server = _persona.load("server", __file__)


# ── web_retrieve ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    attempts = []

    def _connect(address, *a, **k):
        attempts.append(address)
        raise AssertionError("a connection was opened to %r" % (address,))

    class _NoClient:
        def __init__(self, *a, **k):
            attempts.append("httpx.AsyncClient")
            raise AssertionError("an HTTP client was built for a refused URL")

    monkeypatch.setattr(socket, "create_connection", _connect)
    monkeypatch.setattr(_sage_server.httpx, "AsyncClient", _NoClient)
    return attempts


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8081/artifacts",
    "http://2130706433/", "http://localhost/", "file:///etc/passwd", "http://intranet.example/",
])
def test_web_retrieve_refuses_internal_targets_without_reaching_them(url, no_network, monkeypatch):
    def _gai(host, port, *a, **k):
        if host == "intranet.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]
        raise socket.gaierror(host)
    monkeypatch.setattr(socket, "getaddrinfo", _gai)
    out = asyncio.run(_sage_server.web_retrieve(url, "ws-1"))
    assert out.startswith("Error"), out
    assert no_network == []


# ── corpus_search ─────────────────────────────────────────────────────────────────────────────────

class _Store:
    class artifacts:
        @staticmethod
        def get_artifact(aid):
            return {"title": "title of %s" % aid}


@pytest.fixture
def corpus(monkeypatch):
    """A corpus of one readable artifact and two the caller may not read, all matching the query."""
    from agience_chorus.sage import content_search as _cs
    from mantle.search import ranking as _ranking
    import mantle.services.dependencies as _deps

    ranked = [("public-1", "text/plain", -2.0), ("secret-1", "text/plain", -1.5),
              ("secret-2", "text/plain", -1.0)]
    readable = {"public-1"}

    def _check(auth, aid, action, db):
        if aid not in readable:
            raise PermissionError(aid)

    monkeypatch.setattr(_sage_server._auth, "get_delegation_user_id", lambda: "user-1")
    monkeypatch.setattr(_sage_server, "_corpus", lambda: _Store())
    monkeypatch.setattr(_cs, "search", lambda store, q, k=None: [("x", 1.0)])
    monkeypatch.setattr(_ranking, "rank", lambda pool, q, store: (ranked, {"reach": "r"}, None))
    monkeypatch.setattr(_ranking, "cut_for", lambda r, query=None, store=None: len(r))
    monkeypatch.setattr(_deps, "get_store_db", lambda: iter([None]))
    monkeypatch.setattr(_deps, "check_access", _check)
    return readable


def test_refused_candidates_are_not_counted(corpus):
    out = asyncio.run(_sage_server.corpus_search("anything"))
    assert "public-1" in out
    assert "secret" not in out
    assert "refused" not in out
    assert "of 3" not in out and " 3 " not in out


def test_an_answer_of_only_refused_candidates_reads_as_no_results(corpus):
    corpus.clear()
    out = asyncio.run(_sage_server.corpus_search("anything"))
    assert out == "No results found."
