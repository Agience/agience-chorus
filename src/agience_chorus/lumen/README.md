# agience-server-lumen

Status: **Reference** --- current server.py surface

Lumen is the wisdom & inference tekton (a tekton is a chorus member — the operators of one domain): reasoning, learning, curriculum, consolidation, illumination. It exposes seven live tools — synthesis, a workflow runner, a transform dispatcher, package
export/install, task chaining and feedback capture — alongside four declared placeholders.

## Current MCP Tools

Rows are derived from the `@mcp.tool` registrations in `server.py`, not maintained by hand. Seven
tools are live: `chain_tasks` dispatches real cross-server tool calls under the caller's
delegation, `submit_feedback` writes an append-only feedback artifact, and `execute_transform`
raises only for `run.type` of `llm` or `webhook`, fully executing `mcp-tool`, `transform-ref`,
`order-ref` and `workflow`.

Implemented (live):

| Tool | Description |
|---|---|
| `synthesize` | Synthesize an evidence-backed answer: retrieve→reason→respond |
| `execute_transform` | Execute a Transform artifact |
| `run_workflow` | Execute a multi-step workflow defined by a Transform artifact |
| `chain_tasks` | Chain multiple MCP tool calls sequentially via the platform's artifact-invoke path |
| `submit_feedback` | Submit evaluation feedback on an artifact |
| `install_package` | Install a package into a target workspace |
| `export_package` | Populate a package manifest from workspace contents |

Declared placeholders (registered, raise `NotImplementedError`):

| Tool | Description |
|---|---|
| `schedule_action` | Schedule a deferred action for future execution. Creates a task card that will be executed at the specified time or interval |
| `evaluate_output` | Evaluate the quality and accuracy of generated output. Scores content against criteria like relevance, completeness, coherence, and factual accuracy |
| `transcribe_artifact` | Raises. No-models rule: a hosted speech recognizer is a trained model |
| `invoke_llm` | Raises. No-models rule, universal and including BYOK. Grounded operators are the reasoning surface |

## Configuration

`AGIENCE_API_URI` and `AGIENCE_API_KEY` are read nowhere in `server.py` — a grep for both returns
zero. `.well-known/mcp.json` is generated from the same source as the table above.

- `MANTLE_URI` — **required**; Base URI of the Mantle backend (defaults to `http://localhost:8081`)
- `ORIGIN_URI` — **required**; Base URI of the Origin identity authority
- `LUMEN_GROUNDING_CHARS`, `LUMEN_GROUNDING_PER_DOC_CHARS` — grounding budgets in characters
- `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `LOG_LEVEL`

## Running

```bash
pip install -r requirements.txt
MANTLE_URI=http://localhost:8081 ORIGIN_URI=http://localhost:8080 python server.py
```


> The tool table for this persona also lives at [`_lumen_tables.md`](_lumen_tables.md). Its
> contents restate the source strings above and can drift from them; this file's table is
> generated from `server.py` directly.
