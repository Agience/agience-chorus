# Operator code lives in chorus and is distributed to hosts as a content-addressed source bundle
# (agience-observe/build_bundles.py); ember executes it via ember/runtime/runner.py, sha-verified
# before exec. There are no code mirrors — changes happen here.
"""Content resolution — a duck-typed seam, not a port of ember/content.py.

Ember's `content.resolve_text` (the tiered content store: FileContentCache, S3/CDN mirror with
sha256 verify-on-pull, Fernet content keys) is store machinery, not operator code, so it stays in
ember. The operator implementations only need "the full text of this artifact"; the hosting bundle
supplies it:

  • a bundle exposing `resolve_text(artifact) -> str` is used (the host's real content path);
  • otherwise the inline `content` field is the fallback — exact for capture/test stores and
    small inline artifacts (WordNet defs, operator specs).

A missing-content-key fault raised by the bundle's resolver propagates — a node-wide
configuration fault must not read as an empty artifact (same rule as ember's resolve_text).
"""
from __future__ import annotations


def resolve_text(bundle, artifact: dict) -> str:
    """The full text of an artifact via the bundle's own resolver, else inline `content`."""
    r = getattr(bundle, "resolve_text", None)
    if callable(r):
        return r(artifact)
    return artifact.get("content") or ""
