Implemented (live):

| Tool | Description |
|---|---|
| `synthesize` | Synthesize an evidence-backed answer: retrieve→reason→respond. Grounds the input in the corpus via the retrieval organon (mantle FTS under the caller' |
| `execute_transform` | Execute a Transform artifact. Reads the artifact's run block and dispatches based on run.type: 'mcp-tool' calls an MCP tool directly, 'transform-ref'  |
| `run_workflow` | Execute a multi-step workflow defined by a Transform artifact. Reads steps from the artifact's run block, evaluates conditions against a State Artifac |
| `chain_tasks` | Chain multiple MCP tool calls sequentially via the platform's artifact-invoke path. Each step is {server, tool, arguments}; the literal string "$prev" |
| `submit_feedback` | Submit evaluation feedback on an artifact. Records the judgment as an append-only feedback artifact (a confirmation event in the verification-mass loo |
| `install_package` | Install a package into a target workspace. Reads the package manifest, resolves MCP server dependencies (creating missing server artifacts), copies co |
| `export_package` | Populate a package manifest from workspace contents. Walks the named workspace (or subset by artifact_ids), generates stable package-scoped references |

Declared placeholders (registered, raise `NotImplementedError`):

| Tool | Description |
|---|---|
| `schedule_action` | Schedule a deferred action for future execution. Creates a task card that will be executed at the specified time or interval |
| `evaluate_output` | Evaluate the quality and accuracy of generated output. Scores content against criteria like relevance, completeness, coherence, and factual accuracy |
| `transcribe_artifact` | Raises. No-models rule: a hosted speech recognizer is a trained model |
| `invoke_llm` | Raises. No-models rule, universal and including BYOK. Grounded operators are the reasoning surface |
