"""Chorus host entrypoint — a thin shim over ``crystal.host``.

Chorus members are tektons (personas): aria, astra, iris, lumen, ophan, sage, seraph. Chorus is
the tekton standard library — condensors whose tools are organons, invoked by condensation
(OPERATOR-ARCHITECTURE §12).

The host/gateway process lives in crystal (GENESIS-NEXT §B1.10): crystal handles routing (mount /
gateway / relay / discovery / registration-orchestration), chorus handles operators, by domain (the
tekton modules). This file preserves the deployment contract — the Docker image runs
``python server.py`` on :8082, and ``uvicorn server:app`` still resolves — while delegating all
host behavior to :mod:`crystal.host`.

Tekton discovery is chorus-specific (layout detection, the Lumen premium swap, service-identity
boot) and lives in :mod:`personas`; the discovered providers are injected into the generic host,
so crystal imports no tekton by name.

Config: MCP_HOST (default 0.0.0.0), MCP_PORT (default 8082), LOG_LEVEL (default INFO).
"""

from __future__ import annotations

from crystal import host as _host
from personas import load_personas

# Build the app at import time so `uvicorn server:app` works and the persona modules
# (and chorus service identity) are loaded before serving.
app = _host.build_app(load_personas())


if __name__ == "__main__":
    _host.run(app=app)
