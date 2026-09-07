"""DocsCleanupAgent — Ember dogfooding Agience to clean up Agience's docs.

The agent model, made real: **identity** (its bearer token / principal), **compute host** (Ember,
local), **information** (the docs corpus it can read), and a **task** (de-duplicate, organize). It
reads the corpus from Mantle and writes results back.

This agent connects to no model — no LLM. It has no `consolidate` method: merging overlapping docs
by generating new prose is not something this file does, with no replacement and no stub.
Model-free consolidation lives elsewhere — `genesis.consolidate_nearvdup` / `consolidate_colimit` /
`consolidate_crosswalk` (shingled-Jaccard + colimit, deterministic) and `docs_ops`. What remains
here — `scan` and `dedupe` — never needed generation.

Two invariants, both load-bearing:

* **Immutable.** Nothing is destroyed. Exact duplicates are *archived* (superseded, not deleted);
  a consolidation is a *new* artifact linked to its sources — the originals remain, provenance
  intact. (Ember enforces the same inertia the platform does.)
* **Operator provenance.** Every artifact the agent writes records its **operator** — which
  transform/tool made it (``ember:docs-cleanup``) — plus a ``derived_from`` edge to the sources.
  That completes the content/context/operator triple, so the corpus can always answer "how was
  this made". Dropping the operator on write would forfeit that.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List

from .mantle_client import MantleClient

OPERATOR = "ember:docs-cleanup"


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class CleanupPlan:
    total: int = 0
    duplicate_groups: List[List[str]] = field(default_factory=list)  # each: artifact ids, same content

    @property
    def duplicates(self) -> int:
        return sum(len(g) - 1 for g in self.duplicate_groups)


class DocsCleanupAgent:
    def __init__(self, mantle: MantleClient, collection_id: str, *,
                 operator: str = OPERATOR) -> None:
        # `operator` is keyword-only on purpose: a caller passing it positionally could silently
        # bind the wrong parameter instead of raising, and a loud TypeError is the outcome that
        # actually helps here.
        self.mantle = mantle
        self.collection_id = collection_id
        self.operator = operator

    # -- observe -----------------------------------------------------------
    def scan(self) -> CleanupPlan:
        """Read the docs and find exact-duplicate groups (content-identical) — the safest cleanup,
        since content-identical rows carry no ambiguity about which one is canonical."""
        docs = self.mantle.children(self.collection_id, content_type="text/markdown")
        by_hash: dict[str, List[str]] = {}
        for d in docs:
            by_hash.setdefault(content_hash(d.get("content", "")), []).append(d.get("id"))
        groups = [ids for ids in by_hash.values() if len(ids) > 1]
        return CleanupPlan(total=len(docs), duplicate_groups=groups)

    # -- act: dedupe (no reasoning needed) --------------------------------
    def dedupe(self, plan: CleanupPlan, *, dry_run: bool = True) -> dict:
        """Archive all-but-one of each exact-duplicate group. Immutable: archive (soft), keep one
        canonical. Idempotent and safe to preview (dry_run)."""
        archived: List[str] = []
        for group in plan.duplicate_groups:
            _keep, *drop = group   # keep the first, archive the rest
            for aid in drop:
                if dry_run or self.mantle.archive_artifact(aid):
                    archived.append(aid)
        return {"groups": len(plan.duplicate_groups), "archived": len(archived),
                "archived_ids": archived, "dry_run": dry_run}

    # -- consolidate: not implemented here -------------------------------
    # There is no `consolidate(artifact_ids, title=..., dry_run=...)` method, and none is stubbed:
    # merging docs by generating new prose needs a model, and this agent connects to none. Callers
    # get AttributeError — loud and correct — rather than an empty or concatenated placeholder "merge".
    # For model-free consolidation use `genesis.consolidate_*` or `docs_ops`.


__all__ = ["DocsCleanupAgent", "CleanupPlan", "content_hash", "OPERATOR"]
