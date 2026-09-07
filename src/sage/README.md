# agience-server-sage

Status: **Reference** --- current server.py surface

Sage is the research and retrieval persona. It exposes lexical search, artifact lookup, and collection browsing over the platform's own index.

## Current MCP Tools

Implemented paths:

| Tool | Description |
|---|---|
| `search` | Lexical BM25 search across workspaces and collections |
| `corpus_search` | Rank this node's corpus by what the question is about; returns only artifacts the caller may read |
| `get_artifact` | Fetch a single artifact by ID |
| `browse_collections` | List committed collections visible to the caller |
| `web_retrieve` | Fetch a URL, extract text, persist it as a text/markdown artifact |
| `research` | Search, deepen each hit, assemble a budgeted evidence digest with citations |
| `cite_sources` | Produce a provenance receipt: id, title, content type, length, sha256 per cited card |
| `ask` | Ground a question in the corpus; returns an evidence extract with citations, or a computed refusal |
| `extract_information` | Extract schema fields from card content by JSON key or `field: value` line; ungrounded fields are returned as `missing` |

Raises:

| Tool | Description |
|---|---|
| `search_azure` | No-models rule; use `search` |
| `index_to_azure` | No-models rule; the platform index is the retrieval surface |
| `generate_meeting_insights` | Awaits a grounded summarization operator; the model leg is barred by the no-models rule. Use `ask` or `research` against the transcript card |

## UI Resources

Sage currently serves `ui://Sage/vnd.agience.research.html` for the research artifact viewer.

## Azure Integration

`search_azure` and `index_to_azure` are declared and raise under the no-models rule. Retrieval runs on the platform's own index.

## Configuration

`AGIENCE_API_URI` and `AGIENCE_API_KEY` are read nowhere in `server.py`; `.well-known/mcp.json` is
generated from the same source and carries the same set.

- `MANTLE_URI` — **required**; Base URI of the Mantle backend (defaults to `http://localhost:8081`)
- `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `LOG_LEVEL`

## Running

```bash
pip install -r requirements.txt
MANTLE_URI=http://localhost:8081 python server.py
```
