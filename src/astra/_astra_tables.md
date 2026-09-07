Implemented (live):

| Tool | Description |
|---|---|
| `ingest_file` | Ingest a file URL or raw text into a workspace as a card |
| `document_text_extract` | Extract text from a PDF artifact and create a derived text artifact. Returns structured JSON with text_artifact_id, extraction method, page count, and |
| `process_uploaded_content` | Process uploaded text content � extract text and create derived artifacts for search and agent use |
| `apply_metadata` | Merge caller-supplied metadata into an artifact's context.metadata field, then re-index so the fields become searchable. Deterministic merge; no model |
| `ingest_pipeline` | Run the document ingestion pipeline on a PDF artifact: deduplication check → text extraction |
| `deduplicate` | Check for duplicate content by SHA-256 hash. Stamps content_hash on the artifact context and searches the workspace for prior ingestions of the same f |
| `connect_source` | Register an external connector (Drive folder, inbox, Slack channel) |
| `sync_source` | Pull latest content from a registered connector into the workspace |
| `ingest_text` | Extract text from an uploaded artifact, optionally chunk it, and create derived workspace artifacts (ingest.parsed_text and ingest.chunk) that are aut |
| `transcribe` | Finalize a completed stream session card into a transcript card |
| `rotate_stream_key` | Generate or rotate the RTMP stream key for a stream source artifact |

Declared placeholders (registered, raise `NotImplementedError`):

| Tool | Description |
|---|---|
| `validate_input` | Validate incoming data against a schema or content rules |
| `normalize_artifact` | Normalize card content � standardize fields, clean formatting, resolve encodings |
| `classify_content` | Raises. No-models rule: this platform runs no trained classifier |
| `index_artifact` | Force re-index of a card into the search layer |
| `collect_telemetry` | Collect and record system activity telemetry as workspace cards |
