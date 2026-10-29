// src/api/__tests__/agent.test.js
// Tests for api/agent.ts — extractUnits, extractInformation.
// These helpers dispatch through POST /artifacts/{server}/invoke, which is
// the MCP server artifact's invoke operation. The invoke operation reads
// body.name as the tool to call on that server.
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => ({
  post: vi.fn(),
}));

import { post } from '../api';
import { extractUnits, extractInformation } from '../agent';

describe('api/agent', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  describe('extractUnits', () => {
    it('dispatches to aria.extract_units with workspace + source ids', async () => {
      post.mockResolvedValueOnce({
        workspace_id: 'ws-1',
        source_artifact_id: 'art-1',
        created_artifact_ids: ['art-2', 'art-3'],
        unit_count: 2,
      });

      const result = await extractUnits('ws-1', 'art-1');

      expect(post).toHaveBeenCalledWith('/artifacts/aria/op/invoke', {
        name: 'extract_units',
        workspace_id: 'ws-1',
        arguments: {
          workspace_id: 'ws-1',
          source_artifact_id: 'art-1',
          artifact_artifact_ids: [],
        },
      });
      expect(result.created_artifact_ids).toEqual(['art-2', 'art-3']);
      expect(result.unit_count).toBe(2);
    });

    it('passes through optional artifact_artifact_ids when provided', async () => {
      post.mockResolvedValueOnce({
        workspace_id: 'ws-1',
        source_artifact_id: 'art-1',
        created_artifact_ids: ['art-4'],
      });

      await extractUnits('ws-1', 'art-1', ['ctx-a', 'ctx-b']);

      const [, payload] = post.mock.calls[0];
      expect(payload.arguments.artifact_artifact_ids).toEqual(['ctx-a', 'ctx-b']);
    });

    it('propagates backend errors', async () => {
      post.mockRejectedValueOnce(new Error('extraction failed'));
      await expect(extractUnits('ws-1', 'art-1')).rejects.toThrow('extraction failed');
    });
  });

  describe('extractInformation (alias for extractUnits)', () => {
    it('is the same function reference as extractUnits', () => {
      expect(extractInformation).toBe(extractUnits);
    });

    it('forwards all arguments identically to extractUnits', async () => {
      post.mockResolvedValueOnce({
        workspace_id: 'ws-2',
        source_artifact_id: 'art-9',
        created_artifact_ids: ['art-10'],
      });

      await extractInformation('ws-2', 'art-9', ['extra-ctx']);

      const [url, payload] = post.mock.calls[0];
      expect(url).toBe('/artifacts/aria/op/invoke');
      expect(payload.name).toBe('extract_units');
      expect(payload.workspace_id).toBe('ws-2');
      expect(payload.arguments.source_artifact_id).toBe('art-9');
      expect(payload.arguments.artifact_artifact_ids).toEqual(['extra-ctx']);
    });
  });
});
