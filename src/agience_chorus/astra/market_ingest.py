"""Market ingest — series, bars and news as first-class Agience artifacts (astra's writer half).

Astra acts as the caller: every write carries `_user_headers()`, so provenance is the person and
authorization is their grant, rather than a long-lived container-scoped key. Writers are async
functions, matching astra's own transport (httpx). Artifacts are parented via `container_id`, mantle's
current artifact-parenting field.

A bars chunk is written as metadata with empty inline content, and its payload upload is left to the
parquet/S3 flow (see `push_bars_chunk`): chorus has no parquet writer, and putting the rows in
`content` would embed a numeric series into the meaning manifold, degrading retrieval for everything
else. News is the opposite case, deliberately: a headline is text, so it is embedded — that is the
signal sage retrieves over.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

COLLECTION_CT = "application/vnd.agience.collection+json"
SERIES_CT = "application/vnd.agience.market-series+json"
BARS_CT = "application/vnd.agience.market-bars+json"
NEWS_CT = "application/vnd.agience.market-news+json"


class MarketIngestError(RuntimeError):
    """A write that could not be completed. Never swallowed — a partial ingest that reports success
    would leave a series that looks whole and is not."""


def series_name(symbol: str, interval: str) -> str:
    """The series collection's name — `SYMBOL · interval`, matching the original so an existing store
    is recognised rather than duplicated."""
    return "%s · %s" % (symbol, interval)


def series_context(symbol: str, interval: str, source: str, bar_seconds: int,
                   quote: Optional[str] = None, venue: Optional[str] = None) -> Dict[str, Any]:
    """Context for a `market-series` collection: what these bars are, so the series is
    self-describing without consulting the fetcher that made it."""
    ctx: Dict[str, Any] = {
        "content_type": SERIES_CT,
        "title": series_name(symbol, interval),
        "description": "%s %s OHLCV from %s" % (symbol, interval, source),
        "symbol": symbol,
        "interval": interval,
        "source": source,
        "bar_seconds": int(bar_seconds),
    }
    if quote:
        ctx["quote"] = quote
    if venue:
        ctx["venue"] = venue
    return ctx


def bars_chunk_context(symbol: str, interval: str, source: str, bar_seconds: int,
                       start: str, end: str, bar_count: int,
                       columns: Sequence[str]) -> Dict[str, Any]:
    """Context for one immutable OHLCV chunk.

    `columns` is recorded because column order is part of the contract — a reader must rebuild the
    frame identically without guessing. `bar_count`/`start`/`end` make a gap detectable without
    downloading the payload.
    """
    return {
        "content_type": BARS_CT,
        "title": "%s %s %s..%s" % (symbol, interval, start[:10], end[:10]),
        "symbol": symbol,
        "interval": interval,
        "source": source,
        "bar_seconds": int(bar_seconds),
        "start": start,
        "end": end,
        "bar_count": int(bar_count),
        "columns": list(columns),
        "payload": "pending",   # honest: the chunk exists, its bytes are not uploaded yet
    }


def news_context(item: Dict[str, str], tickers: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Context for one `market-news` item. The headline goes in content (it is text, and the embedding
    is the signal); everything else is metadata here.

    `tickers` is in the spec's context schema for this type (`market-data-on-mantle.md`) and is what
    links a headline to the series it bears on — omitting it would leave the news corpus unjoinable to
    the bars. GDELT's doc API does not supply it, so it is a caller-supplied association: absent by
    default rather than guessed from the headline text.
    """
    ctx: Dict[str, Any] = {
        "content_type": NEWS_CT,
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "published_at": item.get("published_at", ""),
        "lang": item.get("lang", ""),
    }
    if tickers:
        ctx["tickers"] = list(tickers)
    return ctx


def bars_span(rows: Sequence[Dict[str, Any]]) -> tuple:
    """`(start, end, count)` over fetched rows. Raises on an empty series rather than returning a
    zero-length span that would later read as a real (empty) chunk."""
    if not rows:
        raise MarketIngestError("no bars to ingest — refusing to write an empty chunk")
    return rows[0]["ts"], rows[-1]["ts"], len(rows)


# ── the writers (async; each takes astra's own create/find callables so this module stays testable
#    and holds no HTTP of its own — the persona owns the transport) ─────────────────────────────────

async def ensure_series(container_id: str, *, symbol: str, interval: str, source: str,
                        bar_seconds: int, find_child, create_artifact,
                        quote: Optional[str] = None, venue: Optional[str] = None) -> str:
    """Find or create the `market-series` collection for symbol×interval. Idempotent: an existing
    series is reused, so re-running an ingest does not fork the history."""
    name = series_name(symbol, interval)
    existing = await find_child(container_id, name, SERIES_CT)
    if existing:
        return str(existing.get("id") or existing.get("_key"))
    ctx = series_context(symbol, interval, source, bar_seconds, quote=quote, venue=venue)
    created = await create_artifact(container_id, ctx, "")
    got = created.get("id") or created.get("_key")
    if not got:
        raise MarketIngestError("series created but no id returned: %r" % (created,))
    return str(got)


async def push_bars_chunk(series_id: str, *, symbol: str, interval: str, source: str,
                          bar_seconds: int, rows: Sequence[Dict[str, Any]],
                          columns: Sequence[str], create_artifact) -> str:
    """Write one immutable OHLCV chunk as metadata with empty content.

    The bytes are not uploaded here, and the context says so (`payload: "pending"`). Putting the rows
    in `content` instead would embed a numeric series into the meaning manifold and corrupt retrieval
    for everything else.

    `market-bars` may not be directly creatable in mantle: unlike `market-news`, its documented path is
    the upload flow — `POST /artifacts/{id}/op/upload-url` → PUT the parquet bytes → `POST
    /artifacts/{series_id}/op/commit`. This function issues a plain create against `series_id`
    instead, which does not follow that path.
    """
    start, end, count = bars_span(rows)
    ctx = bars_chunk_context(symbol, interval, source, bar_seconds, start, end, count, columns)
    created = await create_artifact(series_id, ctx, "")      # content empty, deliberately
    got = created.get("id") or created.get("_key")
    if not got:
        raise MarketIngestError("bars chunk created but no id returned: %r" % (created,))
    return str(got)


async def commit_series(series_id: str, commit_artifact) -> Dict[str, Any]:
    """Commit a series — draft to immutable and indexed.

    An uncommitted series is not indexed, so it is invisible to retrieval — a silent half-ingest that
    looks like a write succeeded. Committing is therefore part of the ingest, not an optional tidy-up
    step, which is why it lives here rather than being left to the caller.
    """
    return await commit_artifact(series_id)


async def push_news(container_id: str, items: Sequence[Dict[str, str]],
                    create_artifact, tickers: Optional[Sequence[str]] = None) -> List[str]:
    """Write news items — headline as content so it is embedded (that is the signal sage retrieves).

    Reports per-item outcomes by returning the ids actually created; an item that fails does not abort
    the batch, because a half-ingested news feed is normal and a lost batch is not.
    """
    out: List[str] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue                                        # no headline, no signal
        created = await create_artifact(container_id, news_context(item, tickers), title)
        got = created.get("id") or created.get("_key")
        if got:
            out.append(str(got))
    return out


def context_json(ctx: Dict[str, Any]) -> str:
    """mantle takes `context` as a JSON string (see astra's `_create_workspace_artifact`)."""
    return json.dumps(ctx, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
