# agience-server-iris

Status: **Reference** --- current server.py surface

The rename from `nexus` is incomplete: `pyproject.toml` (package name and entry point) and
`.well-known/mcp.json` (name and the `ghcr.io/agience/agience-server-nexus:latest` image) still
carry the old name, while `server.py` says `iris`. Completing the rename requires moving a
published image.

Iris is the networking and transport tekton. It handles delivery channels and the scaffolding for endpoint and tunnel routing.

## Current MCP Tools

Rows are derived from the `@mcp.tool` registrations in `server.py` rather than maintained by hand,
so the table below tracks the live registrations rather than drifting from them.

Implemented (live):

| Tool | Description |
|---|---|
| `send_email` | Send an email via an Authorizer artifact (Gmail API) |
| `notify_inbound` | Notify the operator about an inbound lead/artifact (contact form, newsletter subscribe, webhook, etc.) |
| `send_templated_email` | Send a templated transactional email driven by a triggering artifact (autoresponder, welcome, receipt, usage warning, etc.) |
| `send_message` | Send a message via a registered channel adapter (Telegram, Slack, email). The message is routed through the platform's channel infrastructure |
| `get_messages` | Poll a channel adapter for new messages since a given cursor. Returns message list sorted by time |
| `list_channels` | List registered channel adapters for the current user. Returns available channels and their connection status |
| `fetch_url` | Fetch content from a URL and return it inline |
| `ask_human` | Ask a question to the human operator |

Declared placeholders (registered, raise `NotImplementedError`):

| Tool | Description |
|---|---|
| `health_check` | Check the health and availability of a service endpoint. Returns status, latency, and any error details |
| `list_connections` | List registered service connections and their current status |
| `register_endpoint` | Register a service endpoint for routing. Registered endpoints can be targeted by route_request and proxy_tool |
| `route_request` | Route an HTTP request to a registered endpoint. Acts as a platform-aware proxy with auth injection |
| `proxy_tool` | Proxy an MCP tool call through a registered endpoint. Forwards the tool invocation to a remote MCP server and returns the result |

> `create_webhook` is not a registered tool. Inbound keys are live in Mantle (`check_inbound_nonce`,
> wired into `POST /artifacts`); no mantle route mints an inbound key for a card, so a wrapper here
> would have nothing to call. See `server.py` for the current registrations.

`tunnel` is not a registered tool. The word remains in `server.py:134`, inside the
`FastMCP(instructions=...)` string, which describes "manage secure tunnels between hosts and
the platform" to every client that reads the server instructions. `proxy_tool`'s own description
mentions no tunnel.

## Security Notes

Iris runs in the container holding `chorus.private.pem`, the RS256 key every persona
signs with. Nothing exposed by Iris may execute caller-supplied code in that container.

Iris has no `exec_shell` tool for this reason, and runs no sandbox. Remote execution, if
added, belongs in a workload that does not hold the signing key, behind an explicit
operator entitlement.

## Configuration

`AGIENCE_API_URI` and `AGIENCE_API_KEY` are read nowhere in `server.py`. No `NEXUS_`-prefixed
variable exists anywhere in iris — a grep across `*.py`, `*.toml` and `*.json` returns zero. The
settings are `IRIS_`-prefixed in code. The rename from `nexus` is incomplete — `pyproject.toml` and
`.well-known/mcp.json` still say `agience-server-nexus` — but it never reached the environment
variables, which are `IRIS_` throughout.

- `MANTLE_URI` — **required**; Base URI of the Mantle backend (defaults to `http://localhost:8081`)
- `IRIS_AUTHORIZER_ARTIFACT_ID`, `IRIS_AUTHORIZER_WORKSPACE_ID` — the authorizer artifact + workspace
- `IRIS_NOTIFY_EMAIL` — operator address for inbound notifications
- `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `LOG_LEVEL`

Measured from `server.py`; `.well-known/mcp.json` is generated from the same source.

## Running

```bash
pip install -r requirements.txt
MANTLE_URI=http://localhost:8081 python server.py
```
