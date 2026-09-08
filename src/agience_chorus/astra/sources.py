"""Sources that reach the outside world — a URL feed and a streamed dataset.

Astra owns ingestion, and these are the two sources that leave the machine: `UrlSource` polls a fixed
list of URLs and emits an observation for any whose content changed; `DatasetSource` unfolds a remote
dataset (HuggingFace parquet and the like) as a stream rather than a download.

Ember stays a runner and has no business fetching from the network: reaching HTTP is a domain act with
a licence, a rate limit and an outage, so it lives here in astra rather than in ember. The disk watcher
(`FolderSource` / `SourceRuntime` — a node observing itself) belongs to ember instead, since it observes
the runner's own disk rather than reaching out.

The shared contract (`Observation`, `Source`) lives in `prism.source`, which lets these two sources
depend on the dataclass without depending on the disk watcher.

The fetch itself is an operator, not a library call. `UrlSource.poll` reaches `op.fetch.get` through
the sha-verified bundle path, so what leaves the machine is governed by the same operator contract as
everything else — not an inline `requests.get` nobody can audit.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from prism.source import Observation, Source, _OBSERVED

#: suffix -> content type. Carried with `_ct_from_response`, its only user: the suffix is what wins
#: when a server sends a generic `text/plain` for a file whose extension says otherwise.
_EXT_CT = {".py": "text/x-python", ".md": "text/markdown", ".txt": "text/plain",
           ".json": "application/json", ".toml": "text/x-toml", ".yaml": "text/yaml",
           ".yml": "text/yaml", ".ts": "text/x-typescript", ".js": "text/javascript"}

__all__ = ["UrlSource", "DatasetSource"]


def _ct_from_response(http_ct: str, url: str) -> str:
    """Map an HTTP content-type (+ URL suffix fallback) onto our internal content-type, so a
    fetched resource is routed to the right describe-operator just like a local file."""
    base = (http_ct or "").split(";")[0].strip().lower()
    if base in {"text/markdown", "text/x-markdown"}:
        return "text/markdown"
    if base in {"text/html", "application/xhtml+xml"}:
        return "text/html"
    if base and base != "text/plain":
        return base
    suf = Path(urlparse(url).path).suffix.lower()      # header was plain/empty -> trust the suffix
    return _EXT_CT.get(suf, "text/plain")


class UrlSource:
    """Observe external http(s) resources read-only, via `op.fetch.get`. Seeded with a fixed list
    of URLs; each poll GETs them and emits an Observation for any whose content changed since the
    last poll (content-hash, since a URL has no mtime). GET-only by construction — this source can
    fetch a paper or a doc page but never writes to a remote (see fetch.py's hard-locked verb and
    SSRF guard). Provenance is grounded in ember having fetched the bytes, never a caller assertion
    — the same no-back-doors discipline as FolderSource. It is the coalgebra that unfolds the open
    web (read-only) into keyed local artifacts."""

    kind = "url"

    def __init__(self, name: str, urls: Iterable[str]):
        self.name = name
        self.urls = list(urls)
        self._seen: Dict[str, str] = {}      # url -> sha256(content) last observed

    def poll(self) -> Iterable[Observation]:
        from prism.runner import fetch            # the sha-verified single distribution path
        for url in self.urls:
            r = fetch._get({"url": url})                 # GET-only, scheme+host guarded
            if not r.get("ok"):
                continue                                 # blocked/failed -> no observation
            text = r["text"]
            h = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
            if self._seen.get(url) == h:
                continue                                 # unchanged -> not a new observation
            self._seen[url] = h
            yield Observation(
                id="url-" + hashlib.sha256(url.encode()).hexdigest()[:20],
                # Not "never truncated" — `fetch._get` caps the body at `_MAX_BYTES` and reports
                # `truncated`; that flag is carried into meta so a reader can tell. The
                # change-detection hash above is computed over the same truncated prefix, so a
                # change past the cap is still invisible to this source.
                content=f"{url}\n{text}",
                content_type=_ct_from_response(r.get("content_type", ""), url),
                # `prism.mass.Provenance` defines human_validated / observed / span_cited /
                # ontology_proposal / hypothesis / unknown / assertion — OBSERVED is the rung for
                # "an instrument / system of record", which is what a fetched URL is. DatasetSource
                # uses the same constant.
                provenance=_OBSERVED,
                meta={"source_url": url, "source": self.name, "via": "op.fetch.get",
                      "http_status": r.get("status"), "content_type_http": r.get("content_type"),
                      "truncated": bool(r.get("truncated"))},
            )


class DatasetSource:
    """Observe a HuggingFace dataset as a coalgebra — the world (a published corpus) unfolds
    into a stream of Observations. This is the reusable ingestion path for GENESIS Stages 1-5
    (§6, §9): every dataset enters through the same push/unfold machinery a folder or URL does.

    The acquisition rule (§10): pull the index, decide against the index, fetch only
    survivors. `predicate(row) -> bool` filters before any expensive per-row work; `limit` caps
    the stream. Streaming mode never materializes the whole dataset. (For parquet-backed sources
    a DuckDB predicate-pushdown path can be added; row-streaming covers Stages 1-2.)

    `to_record(row, i) -> dict | None` maps a dataset row to {content, content_type?, context?,
    lemmas?, id?, meta?}; return None to skip. `stamp` (set by the GENESIS ingest wrapper) is
    merged into every Observation's meta — it carries the ingest contract (collection_id,
    collections, cited_from, via, provenance) so the artifact lands fully homed and cited.
    """

    kind = "dataset"

    def __init__(self, name: str, hf_path: str, *, config: Optional[str] = None,
                 split: str = "train", streaming: bool = True,
                 to_record: Optional[Callable] = None, predicate: Optional[Callable] = None,
                 limit: Optional[int] = None, skip: int = 0, content_type: str = "text/plain",
                 id_prefix: Optional[str] = None, trust_remote_code: bool = False,
                 stamp: Optional[Dict] = None):
        self.name = name
        self.hf_path = hf_path
        self.config = config
        self.split = split
        self.streaming = streaming
        self.to_record = to_record or (lambda row, i: {"content": row.get("text") or ""})
        self.predicate = predicate
        self.limit = limit
        self.skip = skip                 # resume offset — the pump advances a stage incrementally
        self.content_type = content_type
        self.id_prefix = id_prefix or name
        self.trust_remote_code = trust_remote_code
        self.stamp = dict(stamp or {})
        self._emitted = 0

    def poll(self) -> Iterable[Observation]:
        from datasets import load_dataset
        kw = {"split": self.split, "streaming": self.streaming}
        if self.config:
            kw["name"] = self.config
        if self.trust_remote_code:
            kw["trust_remote_code"] = True
        ds = load_dataset(self.hf_path, **kw)
        if self.skip and hasattr(ds, "skip"):
            ds = ds.skip(self.skip)      # resumable increment (streaming IterableDataset.skip)
        for i, row in enumerate(ds):
            if self.limit is not None and self._emitted >= self.limit:
                break
            if self.predicate and not self.predicate(row):     # decide against the index first
                continue
            rec = self.to_record(row, i)
            if not rec:
                continue
            content = rec.get("content") or ""
            if not content.strip():
                continue
            oid = rec.get("id") or (self.id_prefix + "-"
                                    + hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()[:20])
            meta = {"source": self.name, "hf_path": self.hf_path, "config": self.config}
            meta.update(rec.get("meta") or {})
            if rec.get("lemmas"):
                meta["lemmas"] = rec["lemmas"]
            meta.update(self.stamp)                             # ingest contract wins
            yield Observation(
                id=oid,
                content=content,                               # full text — never truncated
                content_type=rec.get("content_type", self.content_type),
                context=rec.get("context", ""),
                provenance=self.stamp.get("provenance", _OBSERVED),
                meta=meta,
            )
            self._emitted += 1
