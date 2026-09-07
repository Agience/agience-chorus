"""seraph.agent — the docs-hygiene agent.

`DocsCleanupAgent` scans and dedupes Agience's own documentation over the Mantle API. That is a
task-specific governance chore, and seraph is the install/governance persona, so the chore lives
here rather than on a runner persona. The package is self-contained: every import is
intra-package, the transport is injected, and `httpx` is imported lazily. It is Apache-licensed
and imports no AGPL platform code.

`mantle_client.py` and `transport.py` provide `MantleClient` (an HTTP client using the caller's
delegation JWT) for `DocsCleanupAgent`'s use over the wire.
"""
from .cleanup import CleanupPlan, DocsCleanupAgent, OPERATOR, content_hash
from .mantle_client import MantleClient
from .transport import HttpResponse, HttpxTransport, Transport

__all__ = [
    "MantleClient", "DocsCleanupAgent", "CleanupPlan", "content_hash", "OPERATOR",
    "Transport", "HttpxTransport", "HttpResponse",
]
