# agience-server-lumen

Status: **Reference** --- current server.py surface

Lumen is the wisdom & inference tekton (a tekton is a chorus member — the operators of one domain): reasoning, learning, curriculum, consolidation, illumination. It exposes ten live tools — synthesis, a workflow runner, a transform dispatcher, timers, package
export/install, task chaining and feedback capture — alongside one declared placeholder.

## Current MCP Tools

Rows are derived from the `@mcp.tool` registrations in `server.py`, not maintained by hand. Ten
tools are live: `chain_tasks` dispatches real cross-server tool calls under the caller's
delegation, `submit_feedback` writes an append-only feedback artifact, and `execute_transform`
raises only for `run.type` of `llm` or `webhook`, fully executing `mcp-tool`, `transform-ref`,
`order-ref` and `workflow`.

Implemented (live):

| Tool | Description |
|---|---|
| `synthesize` | The evidence for a question: the artifacts that bear on it, retrieved on sage under the caller's grants, as numbered extracts with their ids; cited or refused |
| `execute_transform` | Execute a Transform artifact |
| `run_workflow` | Execute a multi-step workflow defined by a Transform artifact |
| `chain_tasks` | Chain multiple MCP tool calls sequentially, each through Crystal to a persona by name or a person's MCP server by id |
| `schedule_action` | Create a Timer card that will run an artifact's operation on a schedule; it runs once its owner arms it from the card |
| `arm_timer` | Arm a Timer: keep the key it acts on, sealed, and fire it on its schedule |
| `timer_reach` | What a Timer's key must reach to run what it runs: for a workflow, each operator a step invokes and each artifact a step links |
| `disarm_timer` | Disarm a Timer: forget its key; it does not fire again |
| `reconcile` | Reconcile several accounts of one event: what all agree on, where they differ (with the accounts and evidence behind each version), what only one states; each difference raised for a person to settle |
| `workflow_catalog` | What a workflow card's builder offers: the operators the caller may invoke (the platform's, their own, ones shared with them), the workflow's steps with what each links, and the caller's Inbox |
| `prepare_runs` | Prepare a workflow's Runs collection, where each run is recorded as a Run card |
| `add_workflow_step` | Add a step to a workflow card: an operator the caller may invoke, its artifacts kept as typed links from the workflow |
| `invoke_connection` | Invoke an LLM connection card: send a conversation to the model it names, with the key it points at, on the caller's grant to that key |
| `raise_item` | Raise an Inbox item: something that needs a person, with why, what it came from, and optionally an action approving it runs |
| `set_item_state` | Move an Inbox item to triaged, resolved, or back to new, recorded in its history |
| `approve_item` | Approve an Inbox item: run its action on the approver's credential, record the result, and resolve it |
| `submit_feedback` | Submit evaluation feedback on an artifact |
| `install_package` | Install a package into a target workspace |
| `export_package` | Populate a package manifest from workspace contents |

Declared placeholders (registered, raise `NotImplementedError`):

| Tool | Description |
|---|---|
| `evaluate_output` | Evaluate the quality and accuracy of generated output. Scores content against criteria like relevance, completeness, coherence, and factual accuracy |

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
