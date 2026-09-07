"""astra's market ingest.

The writers take astra's create/find callables rather than owning HTTP, so the whole thing is testable
without a network.
"""
import json

import pytest

from astra import market_ingest as mi

ROWS = [
    {"ts": "2026-06-01T00:00:00+00:00", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0},
    {"ts": "2026-06-01T00:15:00+00:00", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 12.0},
]
COLS = ("ts", "open", "high", "low", "close", "volume")


class _Recorder:
    """Stands in for astra's transport. Records what would be written."""

    def __init__(self, existing=None):
        self.created = []
        self._existing = existing

    async def find_child(self, container_id, name, content_type):
        return self._existing

    async def create_artifact(self, container_id, context, content):
        self.created.append({"container": container_id, "context": context, "content": content})
        return {"id": "art-%d" % len(self.created)}


# ── the no-numeric-embedding property (the reason bars are not JSON in content) ────────────────────

@pytest.mark.asyncio
async def test_bars_chunk_writes_EMPTY_content_never_the_numbers():
    """chorus has no parquet writer, and putting rows into `content` would embed a numeric series and
    degrade retrieval for everything else, so a bars chunk writes empty content with honest metadata."""
    rec = _Recorder()
    await mi.push_bars_chunk("series-1", symbol="BTCUSDT", interval="15m", source="binance",
                             bar_seconds=900, rows=ROWS, columns=COLS,
                             create_artifact=rec.create_artifact)
    [written] = rec.created
    assert written["content"] == ""                       # nothing embedded
    body = json.dumps(written["context"])
    assert "1.5" not in body and "volume\": 10" not in body   # no bar values leaked into metadata


@pytest.mark.asyncio
async def test_bars_chunk_admits_its_payload_is_not_uploaded():
    """A chunk whose bytes are absent says so, rather than writing a complete-looking chunk with no
    payload that would make a series look whole when it is not."""
    rec = _Recorder()
    await mi.push_bars_chunk("s", symbol="X", interval="1h", source="binance", bar_seconds=3600,
                             rows=ROWS, columns=COLS, create_artifact=rec.create_artifact)
    assert rec.created[0]["context"]["payload"] == "pending"


def test_bars_chunk_records_column_ORDER_and_span():
    ctx = mi.bars_chunk_context("X", "15m", "binance", 900,
                                ROWS[0]["ts"], ROWS[-1]["ts"], 2, COLS)
    assert ctx["columns"] == list(COLS)                   # order, so a reader rebuilds identically
    assert ctx["bar_count"] == 2 and ctx["start"] < ctx["end"]


def test_empty_series_is_REFUSED_not_written_as_a_zero_span():
    with pytest.raises(mi.MarketIngestError, match="empty chunk"):
        mi.bars_span([])


# ── news is the opposite case, on purpose ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_news_headline_IS_the_content_so_it_embeds():
    """A headline is text; embedding it is the signal sage retrieves over — the deliberate
    asymmetry with bars, whose numeric rows never go into content."""
    rec = _Recorder()
    ids = await mi.push_news("news-col", [
        {"title": "Fed holds rates", "url": "u", "source": "d", "published_at": "p", "lang": "en"},
    ], rec.create_artifact)
    assert ids == ["art-1"]
    assert rec.created[0]["content"] == "Fed holds rates"
    assert rec.created[0]["context"]["content_type"] == mi.NEWS_CT


@pytest.mark.asyncio
async def test_headline_less_items_are_skipped_not_written_blank():
    rec = _Recorder()
    ids = await mi.push_news("c", [{"title": "   "}, {"title": "real"}], rec.create_artifact)
    assert ids == ["art-1"] and rec.created[0]["content"] == "real"


# ── idempotence: re-running an ingest must not fork the history ───────────────────────────────────

@pytest.mark.asyncio
async def test_existing_series_is_REUSED_not_duplicated():
    rec = _Recorder(existing={"id": "already-here"})
    got = await mi.ensure_series("box", symbol="BTCUSDT", interval="15m", source="binance",
                                 bar_seconds=900, find_child=rec.find_child,
                                 create_artifact=rec.create_artifact)
    assert got == "already-here"
    assert rec.created == []                              # nothing new was written


@pytest.mark.asyncio
async def test_series_is_created_when_absent_and_is_self_describing():
    rec = _Recorder(existing=None)
    got = await mi.ensure_series("box", symbol="ETHUSDT", interval="1d", source="yfinance",
                                 bar_seconds=86400, find_child=rec.find_child,
                                 create_artifact=rec.create_artifact, quote="USD")
    assert got == "art-1"
    ctx = rec.created[0]["context"]
    # self-describing: a reader needs no access to the fetcher that made it
    assert ctx["symbol"] == "ETHUSDT" and ctx["interval"] == "1d"
    assert ctx["source"] == "yfinance" and ctx["bar_seconds"] == 86400 and ctx["quote"] == "USD"
    assert ctx["content_type"] == mi.SERIES_CT


def test_series_name_matches_the_original_so_an_existing_store_is_recognised():
    assert mi.series_name("BTCUSDT", "15m") == "BTCUSDT · 15m"


def test_context_json_is_canonical_and_raw_utf8():
    """Sorted keys, no whitespace, non-ASCII raw — consistent with the RFC 8785 decision so a context
    string is stable across hosts."""
    out = mi.context_json({"b": 1, "a": "café"})
    assert out == '{"a":"café","b":1}'
