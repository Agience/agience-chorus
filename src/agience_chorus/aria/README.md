# agience-server-aria

Status: **Reference** --- current server.py surface

Aria is the output and presentation persona. It formats artifacts for human consumption and serves viewer HTML as `ui://` resources.

## Current MCP Tools

Implemented paths:

| Tool | Description |
|---|---|
| `present_card` | Prepare an artifact for presentation-ready output |
| `attach_provenance` | Write source references into `context.semantic.sources` (`mode='sources_only'`) |

Declared placeholders:

| Tool | Description |
|---|---|
| `format_response` | Format content for human-facing delivery in markdown, HTML, or plain text |
| `render_visualization` | Create charts or diagrams from structured data |

Raises under the no-models rule (universal, including BYOK). These are refusals, not
work items — implementing one breaches a standing rule:

| Tool | Description |
|---|---|
| `adapt_tone` | Tone and register rewriting is model generation; this surface answers in the source's own words |
| `narrate` | Turning data into narrative prose is model generation; grounded operators return what the sources say |
| `extract_units` | Model-based extraction of decisions, constraints, actions, and claims |
| `run_chat_turn` | This platform runs no model-backed chat |
| `attach_provenance` with `mode='evidence'` | Model-extracted quotes; `mode='sources_only'` is the working path |

## UI Resources

Aria serves viewer HTML for generic view, chat, presentation, and visualization artifact types from `src/aria/ui/`.

## Configuration

`server.py` reads:

- `MANTLE_URI`
- `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `LOG_LEVEL`

Aria reads neither `AGIENCE_API_URI` nor `AGIENCE_API_KEY`. `AGIENCE_API_URI` is a deprecated
alias of `MANTLE_URI` in the prism config only.

## Running

```bash
pip install -r requirements.txt
python server.py
```

See `.well-known/mcp.json` for the transport and discovery metadata.
