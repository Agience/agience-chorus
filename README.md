# Agience Chorus

[![License](https://img.shields.io/badge/license-AGPL--3.0--only-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Protocol](https://img.shields.io/badge/protocol-MCP-6E56CF)](src/personas.py)
[![Sponsor](https://img.shields.io/badge/Sponsor-Agience-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/Agience)

**Operators, by domain.** Chorus is the tekton standard library: seven MCP services, each holding
the operators of one domain, served from one host or deployed one at a time.

A **tekton** is a chorus member — a condensor whose tools are organons, invoked by condensation.
Each declares a module-level `PERSONA` in its own `server.py`, and
[`src/personas.py`](src/personas.py) discovers them and hands the roster to the host:

| tekton | domain | mount |
|---|---|---|
| **aria** | Presentation & Interface | `/aria/mcp` |
| **astra** | Ingestion & Indexing | `/astra/mcp` |
| **sage** | Research & Retrieval | `/sage/mcp` |
| **iris** | Routing & Communication | `/iris/mcp` |
| **ophan** | Economic Operations | `/ophan/mcp` |
| **seraph** | Security & Governance | `/seraph/mcp` |
| **lumen** | Wisdom & Inference | `/lumen/mcp` |

Tektons are reached over the wire — HTTP and MCP — and are independently deployable, so an operator
runs only the ones they need. Each constructs its own server auth and signs with its own identity,
and no tekton imports another.

## Running it

```bash
pip install -r requirements.txt
python src/server.py            # every tekton on one process, :8082
```

`MCP_HOST` (default `0.0.0.0`), `MCP_PORT` (default `8082`) and `LOG_LEVEL` (default `INFO`)
configure the host. `uvicorn server:app` resolves too — the app is built at import time.

Chorus is run from a checkout rather than installed from an index: no directory under `src/` carries
an `__init__.py`, because the seven tektons deploy as services and their operators travel as
sha-verified bundles. [`pyproject.toml`](pyproject.toml) records that decision in full.

## The bundles

[`bundles/`](bundles/) holds the operator payloads, one JSON per group, built from the sources named
in [`src/seraph/bundle_spec.json`](src/seraph/bundle_spec.json). Each carries a `sha256` that the mesh publishes.

**The runtime reads the payload, not the source file.** An edit to a tekton that is not rebuilt has
no effect, and the published sha then disagrees with the tree.
`src/tests/test_bundles_match_source.py` fails when they drift.

## Layout

| path | what it is |
|---|---|
| `src/<tekton>/server.py` | one deployable tekton service, with its own `manifest.py`, `tests/` and `ui/` |
| `src/<tekton>/ui/<top>/<sub>/type.json` | the content types that tekton owns; it registers them with the gateway at host startup |
| [`src/server.py`](src/server.py) | the unified host, mounting every tekton on one process |
| [`src/_chorus_identity.py`](src/_chorus_identity.py) · [`src/_persona.py`](src/_persona.py) · [`src/_host_seams.py`](src/_host_seams.py) | the identity, artifact and host-seam helpers tektons load at runtime |
| [`src/reach_host.py`](src/reach_host.py) · [`src/reach_wiring.py`](src/reach_wiring.py) · [`src/reading_junction.py`](src/reading_junction.py) | the reach surfaces shared across tektons |
| [`src/personas.py`](src/personas.py) | tekton discovery and host binding: layout detection, module loading, service-identity boot, and the roster the host consumes |
| [`src/corpus_fts.py`](src/corpus_fts.py) · [`src/corpus_stats.py`](src/corpus_stats.py) · [`src/live_service.py`](src/live_service.py) | the corpus and live-service surfaces shared across tektons |
| [`requirements.txt`](requirements.txt) | what the unified host needs |

## Model-free

Tektons dispatch no LLM completion. Three call sites raise `NotImplementedError` and name the rule
in the `@mcp.tool` description a caller reads: `invoke_llm` and `transcribe_artifact` in
[`src/lumen/server.py`](src/lumen/server.py), and `resolve_llm_credentials` in
[`src/seraph/server.py`](src/seraph/server.py).

Security issues: email **connect@agience.ai** rather than opening a public issue.

Dual-licensed — see [`LICENSE`](LICENSE), [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md),
[`NOTICE`](NOTICE) and [`CLA.md`](CLA.md).
