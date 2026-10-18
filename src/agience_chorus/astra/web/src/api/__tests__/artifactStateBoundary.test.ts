import { afterEach, describe, expect, it, vi } from 'vitest';

import { recordRequests } from './requestRecorder';

vi.mock('../../config/runtime', () => ({
  getRuntimeConfig: () => ({
    mantleUri: 'https://api.example.com',
    originUri: 'https://origin.example.com',
    crystalUri: 'https://crystal.example.com',
    clientId: '',
    title: 'Agience',
    favicon: '/favicon.png',
  }),
}));

import api from '../api';

// Artifact-shaped rows (they carry `context`), so only the endpoint decides.
const legacyRows = () => ({
  items: [
    { id: 'a', context: '{}', state: 'draft' },
    { id: 'b', context: '{}', state: 'committed' },
  ],
});

type Rows = { items: { state: string }[] };

describe('legacy artifact states at the API boundary', () => {
  let restore: () => void = () => {};
  afterEach(() => restore());

  it.each([
    ['/artifacts/ws-1/children'],
    ['/artifacts/visible?content_type=x'],
    ['/artifacts/art-1'],
    ['/artifacts/batch'],
    ['/artifacts/recall'],
  ])('normalises %s to live', async (url) => {
    ({ restore } = recordRequests(legacyRows));
    const res = await api.get<Rows>(url);
    expect(res.data.items.map((i) => i.state)).toEqual(['live', 'live']);
  });

  it('normalises the artifact in an upload-initiate response', async () => {
    ({ restore } = recordRequests(() => ({
      upload_id: 'up-1',
      artifact: { id: 'art-9', context: '{}', state: 'draft' },
    })));
    const res = await api.post<{ artifact: { state: string } }>('/artifacts/ws-1/upload-initiate', {});
    expect(res.data.artifact.state).toBe('live');
  });

  it('normalises the artifact returned by upload-status', async () => {
    ({ restore } = recordRequests(() => ({ id: 'art-9', context: '{}', state: 'committed' })));
    const res = await api.patch<{ state: string }>('/artifacts/art-9/upload-status', { status: 'complete' });
    expect(res.data.state).toBe('live');
  });

  it('leaves an /op/invoke payload untouched, even when it looks like an artifact', async () => {
    ({ restore } = recordRequests(legacyRows));
    const res = await api.post<Rows>('/artifacts/srv-1/op/invoke', { name: 'tool' });
    expect(res.data.items.map((i) => i.state)).toEqual(['draft', 'committed']);
  });

  it.each([
    ['/personas/seraph/resources/read'],
    ['/artifacts/art-1/content-url'],
    ['/grants'],
  ])('leaves %s untouched', async (url) => {
    ({ restore } = recordRequests(legacyRows));
    const res = await api.get<Rows>(url);
    expect(res.data.items.map((i) => i.state)).toEqual(['draft', 'committed']);
  });
});
