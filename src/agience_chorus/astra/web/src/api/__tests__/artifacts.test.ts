// src/api/__tests__/artifacts.test.ts
// Tests for api/artifacts.ts — unified artifact and grant API
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => ({
  get: vi.fn(),
  getList: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

import { get, getList, post, patch, del } from '../api';
import {
  createArtifact,
  getArtifact,
  updateArtifact,
  deleteArtifact,
  trashArtifact,
  listTrash,
  addItemToContainer,
  invokeArtifact,
  searchArtifacts,
  getGrant,
  updateGrant,
  deleteGrant,
  claimInvite,
  acceptGrant,
} from '../artifacts';

const mockGet = get as ReturnType<typeof vi.fn>;
const mockPost = post as ReturnType<typeof vi.fn>;
const mockPatch = patch as ReturnType<typeof vi.fn>;
const mockDel = del as ReturnType<typeof vi.fn>;
const mockGetList = getList as ReturnType<typeof vi.fn>;

describe('api/artifacts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // Artifact CRUD
  // ─────────────────────────────────────────────────────────────────────────────

  describe('createArtifact', () => {
    it('POSTs to /artifacts with container_id, context, and content', async () => {
      const artifact = { id: 'art-1', collection_id: 'ws-1', state: 'live' };
      mockPost.mockResolvedValueOnce(artifact);

      const result = await createArtifact('ws-1', '{"title":"Hello"}', 'body text');

      expect(mockPost).toHaveBeenCalledWith('/artifacts', {
        container_id: 'ws-1',
        context: '{"title":"Hello"}',
        content: 'body text',
      });
      expect(result).toEqual(artifact);
    });

    it('omits content when not provided', async () => {
      mockPost.mockResolvedValueOnce({ id: 'art-2' });

      await createArtifact('ws-1', '{}');

      const [, body] = mockPost.mock.calls[0];
      expect(body.content).toBeUndefined();
    });
  });

  describe('getArtifact', () => {
    it('GETs /artifacts/{id}', async () => {
      const artifact = { id: 'art-1', state: 'live' };
      mockGet.mockResolvedValueOnce(artifact);

      const result = await getArtifact('art-1');

      expect(mockGet).toHaveBeenCalledWith('/artifacts/art-1');
      expect(result).toEqual(artifact);
    });
  });

  describe('updateArtifact', () => {
    it('PATCHes /artifacts/{id} with the updates payload', async () => {
      const updated = { id: 'art-1', state: 'live' };
      mockPatch.mockResolvedValueOnce(updated);

      const result = await updateArtifact('art-1', { context: '{"title":"New"}' });

      expect(mockPatch).toHaveBeenCalledWith('/artifacts/art-1', {
        context: '{"title":"New"}',
      });
      expect(result).toEqual(updated);
    });
  });

  describe('deleteArtifact', () => {
    it('DELETEs /artifacts/{id}', async () => {
      mockDel.mockResolvedValueOnce(undefined);

      await deleteArtifact('art-1');

      expect(mockDel).toHaveBeenCalledWith('/artifacts/art-1');
    });
  });

  describe('Trash', () => {
    it('trashArtifact POSTs /artifacts/{id}/trash', async () => {
      mockPost.mockResolvedValueOnce({ id: 'art-1', state: 'archived' });
      await trashArtifact('art-1');
      expect(mockPost).toHaveBeenCalledWith('/artifacts/art-1/trash');
    });

    it('listTrash reads /artifacts/trash as a list', async () => {
      mockGetList.mockResolvedValueOnce([{ id: 'art-1', purge_after: '2026-11-13T00:00:00Z' }]);
      const items = await listTrash();
      expect(mockGetList).toHaveBeenCalledWith('/artifacts/trash');
      expect(items[0].purge_after).toBe('2026-11-13T00:00:00Z');
    });
  });

  describe('addItemToContainer', () => {
    it('POSTs to /artifacts — same shape as createArtifact', async () => {
      mockPost.mockResolvedValueOnce({ id: 'art-3' });

      await addItemToContainer('col-1', '{"title":"Imported"}', 'some content');

      expect(mockPost).toHaveBeenCalledWith('/artifacts', {
        container_id: 'col-1',
        context: '{"title":"Imported"}',
        content: 'some content',
      });
    });

    it('omits content when not provided', async () => {
      mockPost.mockResolvedValueOnce({ id: 'art-4' });

      await addItemToContainer('col-1', '{}');

      const [, body] = mockPost.mock.calls[0];
      expect(body.content).toBeUndefined();
    });
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // Invoke
  // ─────────────────────────────────────────────────────────────────────────────

  describe('invokeArtifact', () => {
    it('POSTs to /artifacts/{id}/op/invoke with all fields', async () => {
      const invokeResult = { status: 'completed', output: 'result text' };
      mockPost.mockResolvedValueOnce(invokeResult);

      const result = await invokeArtifact(
        'op-1',
        'run this',
        { strategy: 'fast' },
        'ws-1',
        ['art-a', 'art-b'],
      );

      expect(mockPost).toHaveBeenCalledWith('/artifacts/op-1/op/invoke', {
        input: 'run this',
        params: { strategy: 'fast' },
        workspace_id: 'ws-1',
        artifacts: ['art-a', 'art-b'],
      });
      expect(result).toEqual(invokeResult);
    });

    it('sends undefined fields when optional args are omitted', async () => {
      mockPost.mockResolvedValueOnce({ status: 'completed' });

      await invokeArtifact('op-2');

      const [, body] = mockPost.mock.calls[0];
      expect(body.input).toBeUndefined();
      expect(body.params).toBeUndefined();
      expect(body.workspace_id).toBeUndefined();
      expect(body.artifacts).toBeUndefined();
    });
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // Search
  // ─────────────────────────────────────────────────────────────────────────────

  describe('searchArtifacts', () => {
    it('POSTs to /artifacts/recall with query_text', async () => {
      const searchResult = { hits: [], total: 0 };
      mockPost.mockResolvedValueOnce(searchResult);

      const result = await searchArtifacts('machine learning');

      expect(mockPost).toHaveBeenCalledWith('/artifacts/recall', {
        query_text: 'machine learning',
        scope: undefined,
      });
      expect(result).toEqual(searchResult);
    });

    it('forwards scope, and does NOT send contentTypes', async () => {
      // `ArtifactRecallRequest` has no `content_types`; mantle's router names it among the fields
      // it stopped reading. Sending it claimed a filter that was never applied — a caller narrowing
      // by type got every type back, with no error to notice. Pinned so it cannot return.
      mockPost.mockResolvedValueOnce({ hits: [], total: 0 });

      await searchArtifacts('science', {
        scope: ['ws-1', 'col-1'],
        contentTypes: ['application/pdf'],
      });

      const [, body] = mockPost.mock.calls[0];
      expect(body.scope).toEqual(['ws-1', 'col-1']);
      expect(body.content_types).toBeUndefined();
      expect(body.source_types).toBeUndefined();
    });

    it('handles partial options (only scope provided)', async () => {
      mockPost.mockResolvedValueOnce({ hits: [], total: 0 });

      await searchArtifacts('art', { scope: ['ws-2'] });

      const [, body] = mockPost.mock.calls[0];
      expect(body.scope).toEqual(['ws-2']);
      expect(body.source_types).toBeUndefined();
      expect(body.content_types).toBeUndefined();
    });
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // Grant management
  // ─────────────────────────────────────────────────────────────────────────────

  // Review 15: every invite or grant is made through `collections.createGrant`, naming Origin's
  // preview the owner confirmed. No wrapper here makes one without it.
  describe('no legacy grant wrapper', () => {
    it('artifacts makes no grant, and collections resends no invite, without a preview', async () => {
      const artifacts = await import('../artifacts');
      const collections = await import('../collections');
      expect('createGrant' in artifacts).toBe(false);
      expect('resendInvite' in collections).toBe(false);
    });
  });

  describe('getGrant', () => {
    it('GETs /grants/{id}', async () => {
      const grant = { id: 'g-1', can_read: true };
      mockGet.mockResolvedValueOnce(grant);

      const result = await getGrant('g-1');

      expect(mockGet).toHaveBeenCalledWith('/grants/g-1');
      expect(result).toEqual(grant);
    });
  });

  describe('updateGrant and deleteGrant', () => {
    it('refuse a row Mantle listed, sending nothing anywhere (round 13)', async () => {
      const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
      vi.stubGlobal('fetch', fetchMock);
      const prior = { id: 'g-1', resource_id: 'col-1', grantee_type: 'user', grantee_id: 'u-1',
                      can_read: true } as never;
      await expect(updateGrant(prior, { can_update: true })).rejects.toThrow(/Origin/);
      await expect(deleteGrant(prior)).rejects.toThrow(/Origin/);
      expect(mockPatch).not.toHaveBeenCalled();
      expect(mockDel).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
      vi.unstubAllGlobals();
    });
  });

  describe('claimInvite', () => {
    it('claims at Origin, never through Mantle (review 12)', async () => {
      const sent: string[] = [];
      vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        sent.push(url);
        return new Response(JSON.stringify({ outcome: 'appended', resource_id: 'r-1' }),
                            { status: 200 });
      }));
      const result = await claimInvite('invite-token-abc');
      expect(mockPost).not.toHaveBeenCalled();
      expect(sent).toHaveLength(1);
      expect(sent[0]).toMatch(/\/auth\/me\/authority\/claim$/);
      expect(result.resource_id).toBe('r-1');
      vi.unstubAllGlobals();
    });
  });

  describe('acceptGrant', () => {
    it('POSTs to /grants/{id}/accept with an empty body', async () => {
      const grant = { id: 'g-6', accepted: true };
      mockPost.mockResolvedValueOnce(grant);

      const result = await acceptGrant('g-6');

      expect(mockPost).toHaveBeenCalledWith('/grants/g-6/accept', {});
      expect(result).toEqual(grant);
    });
  });
});
