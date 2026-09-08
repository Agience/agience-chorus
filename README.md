# Agience Chorus

[![License](https://img.shields.io/badge/license-AGPL--3.0--only-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Protocol](https://img.shields.io/badge/protocol-MCP-6E56CF)](src/agience_chorus/personas.py)
[![Sponsor](https://img.shields.io/badge/Sponsor-Agience-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/Agience)

**Operators, by domain.** Chorus is the tekton standard library: seven MCP services, each holding
the operators of one domain, served from one host or deployed one at a time.

A **tekton** is a chorus member — a condensor whose tools are organons, invoked by condensation.
Each declares a module-level `PERSONA` in its own `server.py`, and
[`src/agience_chorus/personas.py`](src/agience_chorus/personas.py) discovers them and hands the roster to the host:

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
pip install agience-chorus                  # every tekton
pip install "agience-chorus[iris,seraph]"   # only what those two need
python -m agience_chorus.server             # every tekton on one process, :8082
```

`MCP_HOST` (default `0.0.0.0`), `MCP_PORT` (default `8082`) and `LOG_LEVEL` (default `INFO`)
configure the host. `uvicorn agience_chorus.server:app` resolves too — the app is built at import
time. `CHORUS_CRYSTALS=aria,seraph` boots a node holding a subset.

The import name is `agience_chorus`, and the tektons are subpackages of it —
`agience_chorus.aria`, `.astra`, `.iris`, `.lumen`, `.ophan`, `.sage`, `.seraph`.

**The extras select dependencies, not modules.** `agience-chorus[ophan]` installs all seven tektons
and adds Stripe; Python has no mechanism for an extra to exclude code. What it saves is real, all
the same: a node running only `iris` and `seraph` otherwise installs Stripe, HuggingFace `datasets`,
pypdf, sympy and numpy to run none of them. Whether an operator may *discharge* is still the
capability gate's answer, not the installer's.

For a checkout, `pip install -e ".[all,dev]"` — which is what [`requirements.txt`](requirements.txt)
resolves to.

## The bundles

[`src/agience_chorus/bundles/`](src/agience_chorus/bundles/) holds the operator payloads, one JSON
per group, built from the sources named in
[`src/agience_chorus/seraph/bundle_spec.json`](src/agience_chorus/seraph/bundle_spec.json). Each
carries a `sha256` that the mesh publishes.

They live inside the package so the wheel carries them: the runtime executes the payload, so an
installed chorus without them could not discharge an operator at all.

**The runtime reads the payload, not the source file.** An edit to a tekton that is not rebuilt has
no effect, and the published sha then disagrees with the tree.
[`src/tests/test_bundles_match_source.py`](src/tests/test_bundles_match_source.py) fails when they drift.

## Layout

| path | what it is |
|---|---|
| `src/agience_chorus/<tekton>/server.py` | one deployable tekton service, with its own `manifest.py`, `tests/` and `ui/` |
| `src/agience_chorus/<tekton>/ui/<top>/<sub>/type.json` | the content types that tekton owns; it registers them with the gateway at host startup |
| [`src/agience_chorus/server.py`](src/agience_chorus/server.py) | the unified host, mounting every tekton on one process |
| `src/agience_chorus/`​`_chorus_identity.py` · `_persona.py` · `_host_seams.py` | the identity, artifact and host-seam helpers tektons load at runtime |
| `src/agience_chorus/`​`reach_host.py` · `reach_wiring.py` · `reading_junction.py` | the reach surfaces shared across tektons |
| [`src/agience_chorus/personas.py`](src/agience_chorus/personas.py) | tekton discovery and host binding: module loading, service-identity boot, and the roster the host consumes |
| `src/agience_chorus/`​`corpus_fts.py` · `corpus_stats.py` · `live_service.py` | the corpus and live-service surfaces shared across tektons |
| [`src/conftest.py`](src/conftest.py) · [`src/tests/`](src/tests/) | the test process's environment, and the cross-tekton suite — outside the package, so neither ships |
| [`pyproject.toml`](pyproject.toml) | the distribution: dependencies, per-tekton extras, and what goes in the wheel |

## Model-free

Tektons dispatch no LLM completion. Three call sites raise `NotImplementedError` and name the rule
in the `@mcp.tool` description a caller reads: `invoke_llm` and `transcribe_artifact` in
[`src/agience_chorus/lumen/server.py`](src/agience_chorus/lumen/server.py), and `resolve_llm_credentials` in
[`src/agience_chorus/seraph/server.py`](src/agience_chorus/seraph/server.py).

Security issues: email **connect@agience.ai** rather than opening a public issue.

Dual-licensed — see [`LICENSE`](LICENSE), [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md),
[`NOTICE`](NOTICE) and [`CLA.md`](CLA.md).
