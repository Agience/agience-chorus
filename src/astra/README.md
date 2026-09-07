# agience-server-astra

Status: **Reference** --- current server.py surface

Astra is the ingestion persona. It brings external content into Agience, derives artifact text when needed, and owns the live-streaming ingestion path.

## Current MCP Tools

Rows are derived from the `@mcp.tool` registrations in `server.py`, not maintained by hand.
`connect_source`'s own docstring records the connector types it accepts.

Implemented (live):

| Tool | Description |
|---|---|
| `ingest_file` | Ingest a file URL or raw text into a workspace as a card |
| `document_text_extract` | Extract text from a PDF artifact and create a derived text artifact |
| `process_uploaded_content` | Process uploaded text content � extract text and create derived artifacts for search and agent use |
| `apply_metadata` | Merge caller-supplied metadata into an artifact's context.metadata field, then re-index so the fields become searchable |
| `ingest_pipeline` | Run the document ingestion pipeline on a PDF artifact: deduplication check → text extraction |
| `deduplicate` | Check for duplicate content by SHA-256 hash |
| `connect_source` | Register an external connector (Drive folder, inbox, Slack channel) |
| `sync_source` | Pull latest content from a registered connector into the workspace |
| `ingest_text` | Extract text from an uploaded artifact, optionally chunk it, and create derived workspace artifacts (ingest.parsed_text and ingest.chunk) that are… |
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

## Configuration

`server.py` reads `MANTLE_URI` for the Mantle backend. It does not read `AGIENCE_API_URI`,
`AGIENCE_API_KEY`, or `SRS_HTTP_API`. `.well-known/mcp.json` is generated from the same source as
this table.

| Variable | Required | Default | Description |
|---|---|---|---|
| `MANTLE_URI` | **Yes** | `http://localhost:8081` | Base URI of the Mantle backend |
| `SEARCH_CHUNK_SIZE` | — | `1000` | Chunk size for text extraction |
| `SEARCH_CHUNK_OVERLAP` | — | `200` | Chunk overlap for text extraction |
| `STREAM_INGEST_URL` | — | `rtmp://localhost:1936/live` | Public RTMP ingest URL shown to OBS clients |
| `MCP_TRANSPORT` | — | `streamable-http` | MCP transport mode |
| `MCP_HOST` | — | `0.0.0.0` | Bind host |
| `MCP_PORT` | — | `8087` | HTTP port for MCP server |
| `LOG_LEVEL` | — | `INFO` | Logging level |

## Running

```bash
pip install -r requirements.txt
MANTLE_URI=http://localhost:8081 python server.py
```

For stream-side components, see `stream/README.md`.

> [`_astra_tables.md`](_astra_tables.md) also documents this persona's tool table; its contents are
> maintained independently of `server.py` and can drift from the tables above.
