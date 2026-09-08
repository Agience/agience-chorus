"""Market data sources — astra's ingest organons (`net.get`).

astra is the ingest persona, so these fetchers run as organons requiring `net.get` rather than as an
external producer holding a long-lived scoped API key: they pass through the prism junction and the
discharge gate like any other world-touching capability. `net.get` is the read-only capability, which
satisfies [[read-only-external-operators-rule]] (GET-only, no outbound writes) without needing an
exemption.

Fetchers use `httpx`, since chorus ships httpx and not `requests`, and astra already uses it
everywhere; the calls are async because every other astra tool is. Bars are returned as plain dicts
rather than pandas DataFrames, since chorus does not depend on pandas and a persona is the wrong place
to acquire it — columnar form is built downstream (the parquet writer, the Screen) by whatever
actually needs it. `OHLCV_COLUMNS` fixes the column order so a downstream frame builds identically
regardless of source.

`openbb` and `polygon.io` are not implemented here: both need credentials, and credentials in this
platform are resolved by seraph from stored secrets, not read from a persona's environment — adding
either fetcher without going through that path would establish the wrong habit. GDELT and Binance are
public GET endpoints and need none.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import httpx

#: Bar intervals this ingest understands, in seconds. Not a config knob — a vocabulary.
_INTERVAL_SECONDS: Dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}

#: Column order is part of the contract — a downstream frame must build identically on any host.
OHLCV_COLUMNS: Tuple[str, ...] = ("ts", "open", "high", "low", "close", "volume")

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"


def interval_seconds(interval: str) -> int:
    """Seconds per bar. Raises on an unknown interval rather than guessing — a wrong bar width
    silently changes every downstream scale (τ, bf are measured off the bar clock)."""
    if interval not in _INTERVAL_SECONDS:
        raise ValueError("unknown interval %r; known: %s" % (interval, sorted(_INTERVAL_SECONDS)))
    return _INTERVAL_SECONDS[interval]


async def fetch_ohlcv_binance(symbol: str, interval: str = "15m", days: int = 7,
                              timeout: float = 15.0) -> List[Dict[str, Any]]:
    """Full OHLCV klines for one Binance pair, as rows `{ts, open, high, low, close, volume}`.

    `ts` is the bar open time as an ISO-8601 UTC string. Full OHLCV, not close-only: the Screen reads a
    return waterfall and throwing away the intrabar range at ingest cannot be undone later.

    Pages forward by bar time (not by offset) so a gap or a partial final bar cannot silently shift the
    series, and de-duplicates on `ts` because page boundaries overlap.
    """
    bar_ms = interval_seconds(interval) * 1000
    end_ms = int(time.time() * 1000)
    cursor = end_ms - days * 86_400_000
    rows: List[list] = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        while cursor < end_ms:
            resp = await client.get(BINANCE_KLINES, params={
                "symbol": symbol, "interval": interval, "startTime": cursor, "limit": 1000})
            if resp.status_code != 200:
                raise RuntimeError("binance %s HTTP %s: %s"
                                   % (symbol, resp.status_code, resp.text[:200]))
            batch = resp.json()
            if not batch:
                break
            rows.extend(batch)
            last_open = batch[-1][0]
            if last_open >= end_ms - bar_ms:
                break
            cursor = last_open + bar_ms

    if not rows:
        raise RuntimeError("no klines returned for %r — refusing to report an empty series as data"
                           % symbol)

    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows:                      # kline: [openTime, open, high, low, close, volume, ...]
        ts = _iso_utc_ms(int(r[0]))
        if ts in seen:
            continue
        seen.add(ts)
        out.append({"ts": ts, "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])})
    return out


#: GDELT asks for one request per 5 seconds and 429s below that, telling high-traffic users to
#: contact the project. Honoured rather than retried around: a 429 comes back as an empty batch,
#: which is indistinguishable from a quiet window and would be read as "no news happened".
GDELT_MIN_INTERVAL = 5.0

#: The doc API's hard cap per request. Not a knob — asking for more returns this many.
GDELT_MAX_RECORDS = 250


def _parse_articles(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """GDELT's `articles` → our rows. Items without a headline or a parseable publish time are
    dropped: the first carries no text signal, the second cannot be placed in time, and placing it
    anyway is how a news plane comes to describe the clock instead of the news."""
    out: List[Dict[str, str]] = []
    for a in data.get("articles", []) or []:
        title = (a.get("title") or "").strip()
        published = _iso_utc_gdelt(a.get("seendate", ""))
        if not title or not published:
            continue
        out.append({
            "title": title,
            "url": a.get("url", ""),
            "source": a.get("domain", ""),
            "published_at": published,
            "lang": a.get("language", ""),
        })
    return out


async def fetch_gdelt_news(query: str, max_records: int = 50, timeout: float = 20.0,
                           timespan: str = "3d") -> List[Dict[str, str]]:
    """Recent news items from GDELT's public doc API: `{title, url, source, published_at, lang}`.

    GDELT's doc API carries no article body, so the headline is the text signal: an empty `body`
    downstream is a property of the source, not a fetch failure.

    This makes one request, so it has one cap: `maxrecords` tops out at 250 and the sort is
    `DateDesc`, so a long `timespan` does not return a sample spread across it — it returns the most
    recent 250 and stops, which can cover a small fraction of the requested span. Use
    `fetch_gdelt_window` when the coverage matters, which is whenever the result will be placed on a
    clock.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(GDELT_DOC, params={
            "query": query, "mode": "ArtList", "maxrecords": max_records,
            "timespan": timespan, "format": "json", "sort": "DateDesc",
        }, headers={"User-Agent": "agience-astra-ingest/0.1"})
    if resp.status_code != 200:
        raise RuntimeError("gdelt HTTP %s: %s" % (resp.status_code, resp.text[:200]))
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError("gdelt returned non-JSON: %s" % resp.text[:200])
    return _parse_articles(data)


async def fetch_gdelt_window(query: str, start: str, end: str, *, slice_hours: float = 6.0,
                             timeout: float = 60.0,
                             pace: float = GDELT_MIN_INTERVAL) -> List[Dict[str, str]]:
    """The same feed, covering a window instead of sampling its tail — one request per time slice.

    `fetch_gdelt_news` cannot cover a window: the 250-record cap plus `DateDesc` sort means everything
    returned clusters at the most recent end. A reader that then zero-fills the rest of the window
    would read the world as silent for the uncovered span, when the truth is only that it was not
    fetched — absence read as quiet.

    Slicing moves the cap from the window to the slice: 250 per slice rather than 250 per request. On
    a 6-hour slice, roughly 100 articles come back for a typical query, well under the cap, so the
    slice covers its span rather than truncating it — the property that makes the result placeable in
    time.

    `slice_hours` is a caller-supplied width, not a derived bound: the width that keeps a slice under
    the cap depends on the query's own volume, since a broad query saturates a window a narrow one
    leaves half empty. The function reports saturation per slice instead of silently truncating: any
    slice returning `GDELT_MAX_RECORDS` has unknown coverage, and the caller is told which, so it can
    narrow the slice rather than trust the total.

    The rate limit is honoured rather than retried around: GDELT allows one request per 5 seconds. A
    429 returns no articles, and an empty batch is indistinguishable from a genuinely quiet slice, so
    a run that raced the limit would silently record silence instead. Slices are spaced by
    `GDELT_MIN_INTERVAL`, and a 429 raises rather than being absorbed.
    """
    import asyncio

    t0, t1 = epoch_of(start), epoch_of(end)
    if t1 <= t0:
        raise ValueError("end %r is not after start %r" % (end, start))
    step = float(slice_hours) * 3600.0
    if step <= 0:
        raise ValueError("slice_hours must be positive, got %r" % (slice_hours,))

    seen: set = set()
    out: List[Dict[str, str]] = []
    saturated: List[str] = []
    cursor = t0
    first = True
    async with httpx.AsyncClient(timeout=timeout) as client:
        while cursor < t1:
            hi = min(cursor + step, t1)
            if not first:
                await asyncio.sleep(pace)
            first = False
            # A 429 retries the same slice; it is never skipped and never counted as empty. The limit
            # is enforced server-side against recent traffic, so even the first slice can be refused
            # because of a request made before this call started. Backing off and re-asking keeps the
            # window covered; moving on would leave a hole that later reads see as quiet. The attempt
            # count is bounded so a persistent refusal surfaces instead of looping.
            resp = None
            for attempt in range(6):
                resp = await client.get(GDELT_DOC, params={
                    "query": query, "mode": "ArtList", "maxrecords": GDELT_MAX_RECORDS,
                    "format": "json", "sort": "DateDesc",
                    "startdatetime": _gdelt_stamp(cursor), "enddatetime": _gdelt_stamp(hi),
                }, headers={"User-Agent": "agience-astra-ingest/0.1"})
                if resp.status_code != 429:
                    break
                await asyncio.sleep(pace * (attempt + 2))
            if resp.status_code != 200:
                raise RuntimeError("gdelt HTTP %s on slice %s..%s: %s"
                                   % (resp.status_code, _gdelt_stamp(cursor), _gdelt_stamp(hi),
                                      resp.text[:200]))
            try:
                batch = _parse_articles(resp.json())
            except ValueError:
                raise RuntimeError("gdelt returned non-JSON on slice %s: %s"
                                   % (_gdelt_stamp(cursor), resp.text[:200]))
            if len(batch) >= GDELT_MAX_RECORDS:
                saturated.append(_gdelt_stamp(cursor))
            for item in batch:
                # Slice edges overlap by a second on some queries; dedupe on the pair that identifies
                # an article, never on the URL alone (the same story is syndicated under many).
                key = (item["url"], item["published_at"])
                if key not in seen:
                    seen.add(key)
                    out.append(item)
            cursor = hi

    out.sort(key=lambda i: i["published_at"])      # arrival order — the causality every read needs
    if saturated:
        # Not an exception: the data is real, only its coverage is unknown. Silence here would let a
        # saturated run be read as complete.
        print("⚠ gdelt: %d slice(s) returned the %d-record cap, so their coverage is unknown — "
              "narrow slice_hours. First: %s" % (len(saturated), GDELT_MAX_RECORDS, saturated[0]))
    return out


def _gdelt_stamp(epoch: float) -> str:
    """Epoch seconds → GDELT's `YYYYMMDDHHMMSS`, which is the only form its window params accept."""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(float(epoch), tz=_dt.timezone.utc).strftime("%Y%m%d%H%M%S")


def epoch_of(ts: str) -> float:
    """ISO-8601 → epoch seconds, refusing a naive stamp. A window boundary with no timezone is a
    boundary two callers will disagree about, and the disagreement is silent."""
    import datetime as _dt
    parsed = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("window bound %r has no timezone — refusing to assume UTC" % (ts,))
    return parsed.timestamp()


def _iso_utc_ms(ms: int) -> str:
    """Epoch milliseconds → ISO-8601 UTC, without pandas."""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ms / 1000.0, tz=_dt.timezone.utc).isoformat()


def _iso_utc_gdelt(seen: str) -> str:
    """GDELT's `20260611T120000Z` → ISO-8601. Returns "" when the shape is not recognised rather than
    fabricating a timestamp — an unknown publish time must stay unknown."""
    if len(seen) >= 15 and seen[8:9] == "T":
        return "%s-%s-%sT%s:%s:%sZ" % (seen[0:4], seen[4:6], seen[6:8],
                                       seen[9:11], seen[11:13], seen[13:15])
    return ""
