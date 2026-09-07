# Agience Chorus

[![License](https://img.shields.io/badge/license-AGPL--3.0--only%20OR%20commercial-blue)](LICENSE)
[![CI](https://github.com/Agience/agience-chorus/actions/workflows/ci.yml/badge.svg)](https://github.com/Agience/agience-chorus/actions/workflows/ci.yml)
[![Sponsor](https://img.shields.io/badge/Sponsor-Agience-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/Agience)

**Operators, by domain. Chorus members are tektons (personas) — the choir of tektons.**

Chorus is the **tekton standard library**: tektons are condensors whose tools are **organons**,
invoked by condensation (OPERATOR-ARCHITECTURE §12).

Chorus is the one home of the platform's operators — patterns for transformation — grouped by domain
into tektons. A tekton is a chorus member, the craftsman holding the operators of one domain:
**aria** = output, **astra** = input, **iris** = networking, **lumen** = wisdom & inference,
**ophan** = economics, **sage** = knowledge, **seraph** = security & defense. **The hands**
(actuation) is an open gap with no tekton yet (GENESIS-NEXT §B1.7).

Everything else reaches Chorus **over the wire** (HTTP/MCP) and never links it. It ships as a set of
independently-deployable tekton services, fronted by the Crystal gateway/dispatcher in its own repo,
so an operator deploys only the tektons they need.

Tektons never import one another. Each constructs its own `AgienceServerAuth` and signs with its own
identity.

**Tektons run model-free.** There is no LLM completion dispatch anywhere in chorus. The fail-loud
stubs are `invoke_llm` and `transcribe_artifact` in `src/lumen/server.py` and
`resolve_llm_credentials` in `src/seraph/server.py`, each raising `NotImplementedError` with the
no-models rule named in its `@mcp.tool` description.

## Layout

| Path | Purpose |
|---|---|
| `src/<tekton>/` | One deployable tekton service: `server.py`, `manifest.py`, its own `pyproject.toml` / `requirements.txt`, `tests/`, and `ui/`. |
| `src/<tekton>/ui/<top>/<sub>/type.json` | The content types that tekton owns. It pushes them to the Crystal gateway's `/register` at host startup; the store never sees them. |
| `src/_chorus_identity.py`, `src/_persona.py`, `src/_host_seams.py` | Shared identity, artifact and host-seam helpers the tektons load at runtime. |
| `src/server.py` | The unified MCP tekton host, mounting every tekton on one process. |
| `src/reach_host.py`, `src/reach_wiring.py`, `src/reading_junction.py`, `src/corpus_fts.py`, `src/corpus_stats.py`, `src/live_service.py`, `src/personas.py` | The reach, corpus and live-service surfaces shared across tektons. |
| `manifest.json` | Tekton discovery: `name`, `title`, `path`, `client_id`, `role` for each member. |
| `requirements.txt` | What the unified host needs — `src/server.py` on `:8082`. |
| `bundles/`, `bundle_spec.json` | The operator payloads, built from the sources the spec names. The runtime reads the PAYLOAD, so an edit to a tekton that was not rebuilt is inert. |

Crystal — the dispatcher/gateway that fronts the tektons — lives in its own repo,
[`agience-crystal`](https://github.com/Agience/agience-crystal).

## Running it

Chorus is **not on PyPI**, and `pyproject.toml` says why: no directory under `src/` carries an
`__init__.py`, so a build would produce a wheel with no modules in it. Run it from a checkout:

    pip install ../agience-prism/py'[trust,vector,wire]' ../agience-crystal'[service,ontology]'                 ../agience-mantle ../agience-ember
    pip install -r requirements.txt
    python src/server.py            # every tekton on one process, :8082

The operator payloads in `bundles/` are read by the runtime rather than the source files, so after
changing a tekton rebuild them — `python ../agience-observe/build_bundles.py` — or the change is
inert. `src/tests/test_bundles_match_source.py` fails when they drift.

## License

**Dual-licensed: AGPL-3.0-only *or* commercial.** See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE);
commercial and white-label terms in [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md). Contributing:
[`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CLA.md`](CLA.md).