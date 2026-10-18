// api/mcp.ts
import api, { getList } from './api';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// A server is named one of two ways. A persona (seraph, lumen, ...) by its name: Crystal holds the
// only name -> endpoint map, so its view and tools are reached through `/personas/{name}/...`. A
// server a person added is a `vnd.agience.mcp-server+json` artifact, named by its UUID, and is
// reached through that artifact's operations.
//
// 2026-10-18: every name was resolved to an artifact first. Personas have none, the lookup threw,
// and every `vnd.agience.*` viewer said its server was not running.
function personaPath(server: string, rest: string): string {
  return `/personas/${encodeURIComponent(server.trim())}/${rest}`;
}

function isArtifactRef(server: string): boolean {
  return UUID_PATTERN.test(server.trim());
}

export interface MCPServerTransport {
  type: 'stdio' | 'http';
  command?: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  well_known?: string;
}

export interface MCPTool {
  name: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  icon?: string; // Tool-specific icon from _meta.icon
}

export interface MCPResource {
  id: string;
  kind: string;
  uri?: string;
  title?: string;
  text?: string;
  content_type?: string;
  contentType?: string; // API returns content_type but frontend uses camelCase
  props?: Record<string, unknown>;
  icon?: string; // Resource-specific icon from _meta.icon
}

export interface MCPResourceContents {
  uri: string;
  name: string;
  title?: string;
  mimeType?: string;
  contentType?: string;
  text?: string;
  blob?: string;
}

export interface MCPPrompt {
  name: string;
  description?: string;
  arguments?: Array<{
    name: string;
    description?: string;
    required?: boolean;
  }>;
  icon?: string; // Prompt-specific icon from _meta.icon
}

export interface MCPServerInfo {
  server: string;
  name?: string;
  tools: MCPTool[];
  resources: MCPResource[];
  prompts?: MCPPrompt[];
  status: string;
  message?: string;
  icon?: string; // Icon from serverInfo._meta.icon (URL, data URI, emoji, or "agience")
}

/**
 * Lightweight config record derived from MCPServerInfo (no separate endpoint).
 * Used as display metadata alongside the live MCPServerInfo.
 */
export interface MCPServerConfig {
  id: string;
  label: string;
  icon?: string;
}

const _MCP_SERVER_CONTENT_TYPE = 'application/vnd.agience.mcp-server+json';

/**
 * Map an artifact record (from GET /artifacts/visible) to the MCPServerInfo
 * shape. Tools, resources, and prompts are materialized separately as child
 * artifacts (vnd.agience.tool+json etc.), so this mapping leaves them empty.
 */
function _artifactToServerInfo(artifact: Record<string, unknown>): MCPServerInfo {
  const id = String(artifact.id ?? '');
  let serverName: string | undefined;
  try {
    const ctx = typeof artifact.context === 'string'
      ? JSON.parse(artifact.context || '{}')
      : (artifact.context ?? {});
    const mcpServer = (ctx as Record<string, unknown>).mcp_server;
    if (mcpServer && typeof mcpServer === 'object') {
      serverName = String((mcpServer as Record<string, unknown>).name ?? '') || undefined;
    }
  } catch {
    // ignore malformed context
  }
  return {
    server: id,
    name: serverName || String(artifact.name ?? artifact.description ?? id),
    tools: [],
    resources: [],
    prompts: [],
    status: 'ok',
  };
}

/**
 * Every MCP server the current user can reach: the personas (from Crystal, with their tools and
 * resources) and the mcp-server artifacts visible to the user. A source that fails is left out;
 * the other still answers.
 */
export async function listAllMCPServers(): Promise<MCPServerInfo[]> {
  const [personas, artifacts] = await Promise.allSettled([
    getList<MCPServerInfo>('/personas'),
    getList<Record<string, unknown>>('/artifacts/visible', {
      params: { content_type: _MCP_SERVER_CONTENT_TYPE },
    }),
  ]);
  if (personas.status === 'rejected' && artifacts.status === 'rejected') {
    throw personas.reason;
  }
  return [
    ...(personas.status === 'fulfilled' ? personas.value : []),
    ...(artifacts.status === 'fulfilled' ? artifacts.value.map(_artifactToServerInfo) : []),
  ];
}

/**
 * MCP servers available to the current user. The workspace is accepted for interface
 * compatibility; access is decided by the token on each source, not by the workspace.
 */
export async function listWorkspaceMCPServers(_workspaceId: string): Promise<MCPServerInfo[]> {
  return listAllMCPServers();
}

/**
 * Read a resource's contents from an MCP server: a persona by name, or an mcp-server artifact by
 * UUID. ``workspaceId`` travels with an artifact's op for its own context.
 */
export async function readMCPResource(
  server: string,
  uri: string,
  workspaceId?: string,
): Promise<MCPResourceContents> {
  if (!server.trim()) throw new Error('Missing MCP server');
  const response = isArtifactRef(server)
    ? await api.post<MCPResourceContents>(
      `/artifacts/${encodeURIComponent(server.trim())}/op/resources_read`,
      { uri, workspace_id: workspaceId },
    )
    : await api.post<MCPResourceContents>(personaPath(server, 'resources/read'), { uri });
  return response.data;
}

/**
 * Read a `ui://` resource for rendering in a McpAppHost iframe.
 *
 * Returns the HTML content string for the view.
 */
export async function readUiResource(
  server: string,
  uri: string,
  workspaceId?: string,
): Promise<{ html: string; csp?: Record<string, string[]> }> {
  const result = await readMCPResource(server, uri, workspaceId);
  return {
    html: result.text ?? (result.blob ? atob(result.blob) : ''),
  };
}

/**
 * Call a tool on an MCP server, for an MCP App view or a settings frame.
 *
 * A persona (by name) is called through Crystal's `/personas/{name}/tools/call`; a view calls the
 * tools of the persona that served it. An mcp-server artifact (by UUID) goes through its
 * `invoke` operation (`POST /artifacts/{id}/op/invoke`), whose type definition reads the tool name
 * from `body.name`. No timeout: a call can run an unbounded LLM and tool chain, with deltas
 * streamed over WebSocket.
 */
export async function proxyToolCall(
  toolName: string,
  args: Record<string, unknown>,
  server: string,
  workspaceId?: string,
): Promise<{ content: Array<{ type: string; text?: string }> }> {
  if (!server.trim()) throw new Error('Missing MCP server');
  const response = isArtifactRef(server)
    ? await api.post(
      `/artifacts/${encodeURIComponent(server.trim())}/op/invoke`,
      { name: toolName, arguments: args, workspace_id: workspaceId },
      { timeout: 0 },
    )
    : await api.post(personaPath(server, 'tools/call'), { name: toolName, arguments: args }, { timeout: 0 });
  return response.data as { content: Array<{ type: string; text?: string }> };
}

