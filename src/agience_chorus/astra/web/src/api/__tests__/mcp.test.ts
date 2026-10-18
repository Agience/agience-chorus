// src/api/__tests__/mcp.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    getList: vi.fn(),
    post: vi.fn(),
  },
  // `getList` is a NAMED export, not a member of the default — `mcp.ts` does
  // `import api, { getList } from './api'`. Mocking it under `default` leaves the
  // named import undefined, which fails the whole MODULE rather than one test.
  getList: vi.fn(),
}));

import api, { getList } from '../api';
import { listWorkspaceMCPServers, readMCPResource, readUiResource, proxyToolCall } from '../mcp';

const mockList = getList as unknown as ReturnType<typeof vi.fn>;
const mockPost = api.post as ReturnType<typeof vi.fn>;

const SERVER_ARTIFACT = '123e4567-e89b-42d3-a456-426614174001';

describe('api/mcp — listWorkspaceMCPServers', () => {
  beforeEach(() => vi.clearAllMocks());

  it('lists the personas from Crystal and the mcp-server artifacts the user can see', async () => {
    mockList.mockImplementation(async (url: string) => (url === '/personas'
      ? [{ server: 'seraph', name: 'seraph', tools: [{ name: 'create_api_key' }], resources: [], status: 'ok' }]
      : [{
        id: SERVER_ARTIFACT,
        name: 'Nexus',
        content_type: 'application/vnd.agience.mcp-server+json',
        context: JSON.stringify({ mcp_server: { name: 'Nexus' } }),
      }]));

    const result = await listWorkspaceMCPServers('ws-123');

    expect(mockList).toHaveBeenCalledWith('/personas');
    expect(mockList).toHaveBeenCalledWith('/artifacts/visible', {
      params: { content_type: 'application/vnd.agience.mcp-server+json' },
    });
    expect(result.map((s) => s.server)).toEqual(['seraph', SERVER_ARTIFACT]);
    expect(result[0].tools[0].name).toBe('create_api_key');
    expect(result[1].name).toBe('Nexus');
  });

  it('keeps the personas when the artifact listing fails', async () => {
    mockList.mockImplementation(async (url: string) => {
      if (url === '/personas') return [{ server: 'lumen', name: 'lumen', tools: [], resources: [], status: 'ok' }];
      throw new Error('mantle down');
    });
    const result = await listWorkspaceMCPServers('ws-1');
    expect(result.map((s) => s.server)).toEqual(['lumen']);
  });

  it('propagates an error when both sources fail', async () => {
    mockList.mockRejectedValue(new Error('Unauthorized'));
    await expect(listWorkspaceMCPServers('ws-1')).rejects.toThrow('Unauthorized');
  });
});

describe('api/mcp — readMCPResource', () => {
  beforeEach(() => vi.clearAllMocks());

  it('reads a persona view by name through Crystal, with no artifact lookup', async () => {
    // 2026-10-18: the name was resolved to an mcp-server artifact first; personas have none, so
    // every `vnd.agience.*` viewer said its server was not running.
    mockPost.mockResolvedValueOnce({ data: { uri: 'ui://seraph/vnd.agience.key.html', name: 'k', text: '<html/>' } });

    const { html } = await readUiResource('seraph', 'ui://seraph/vnd.agience.key.html', 'ws-1');

    expect(mockPost).toHaveBeenCalledWith('/personas/seraph/resources/read',
      { uri: 'ui://seraph/vnd.agience.key.html' });
    expect(mockList).not.toHaveBeenCalled();
    expect(html).toBe('<html/>');
  });

  it("reads an mcp-server artifact's resource through Crystal, by its UUID", async () => {
    // The card's own `resources_read` op pointed at a removed Mantle importer; Crystal reaches a
    // person's server through Iris.
    mockPost.mockResolvedValueOnce({
      data: { uri: 'external://doc', name: 'External Doc', mimeType: 'text/plain', text: 'content' },
    });

    await readMCPResource(SERVER_ARTIFACT, 'external://doc', 'ws-1');

    expect(mockPost).toHaveBeenCalledWith(`/personas/${SERVER_ARTIFACT}/resources/read`,
      { uri: 'external://doc' });
  });

  it('propagates read errors', async () => {
    mockPost.mockRejectedValueOnce(new Error('Resource not found'));
    await expect(readMCPResource('seraph', 'ui://seraph/missing', 'ws-1')).rejects.toThrow('Resource not found');
  });

  it('refuses an empty server', async () => {
    await expect(readMCPResource(' ', 'ui://x/y')).rejects.toThrow('Missing MCP server');
    expect(mockPost).not.toHaveBeenCalled();
  });
});

describe('api/mcp — proxyToolCall', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls a persona tool by name through Crystal', async () => {
    mockPost.mockResolvedValueOnce({ data: { content: [{ type: 'text', text: 'ok' }] } });

    const result = await proxyToolCall('synthesize', { input: 'hi' }, 'lumen');

    expect(mockPost).toHaveBeenCalledWith('/personas/lumen/tools/call',
      { name: 'synthesize', arguments: { input: 'hi' } }, { timeout: 0 });
    expect(result.content[0]?.text).toBe('ok');
  });

  it("calls an artifact's invoke operation by UUID", async () => {
    mockPost.mockResolvedValueOnce({ data: { content: [] } });

    await proxyToolCall('billing.get_portal', { invoice_id: 'inv-1' }, SERVER_ARTIFACT, 'ws-1');

    expect(mockPost).toHaveBeenCalledWith(
      `/artifacts/${SERVER_ARTIFACT}/op/invoke`,
      { name: 'billing.get_portal', arguments: { invoice_id: 'inv-1' }, workspace_id: 'ws-1' },
      { timeout: 0 },
    );
  });
});
