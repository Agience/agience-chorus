/**
 * `api/apiKeys` — the grant-key client.
 *
 * ⚠ WHAT THIS CAN AND CANNOT PROVE. The transport is mocked, so every assertion here is about the
 * request this module BUILDS, never about a server answering it. The previous version of this file
 * passed for months while every function called `/api-keys`, a path no service has ever served:
 * a mocked suite pins the URL its author intended.
 *
 * Reachability is a separate check with a live node behind it —
 * `agience-cloud/deploy/facet_contract_drift.py` diffs every call site here against what mantle,
 * origin and crystal publish, and probes anything missing before reporting it. Keep both: this one
 * fails fast on a shape mistake, that one fails on a path that does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from '../api';
import { createAPIKey, createKeyOver, deleteAPIKey, getAPIKey, listAPIKeys } from '../apiKeys';

const mockGet = api.get as ReturnType<typeof vi.fn>;
const mockPost = api.post as ReturnType<typeof vi.fn>;
const mockDelete = api.delete as ReturnType<typeof vi.fn>;

describe('api/apiKeys', () => {
  beforeEach(() => vi.clearAllMocks());

  it('creates a key on the grants surface, not the retired one', async () => {
    mockPost.mockResolvedValueOnce({
      data: { id: 'k1', name: 'ci', state: 'active', created_time: 't', key: 'agc_secret' },
    });

    const created = await createAPIKey({ name: 'ci', can_read: true });

    expect(mockPost).toHaveBeenCalledWith('/grants/keys', { name: 'ci', can_read: true });
    // The secret is returned once and never again — losing it here loses it entirely.
    expect(created.key).toBe('agc_secret');
  });

  it('sends capabilities as flags, because scopes have no counterpart', async () => {
    mockPost.mockResolvedValueOnce({ data: { id: 'k2', name: 'n', state: 'active', created_time: 't' } });

    await createAPIKey({ name: 'n', can_read: true, can_invoke: true, resource_id: 'a1' });

    expect(mockPost).toHaveBeenCalledWith('/grants/keys', {
      name: 'n', can_read: true, can_invoke: true, resource_id: 'a1',
    });
  });

  it('lists keys', async () => {
    mockGet.mockResolvedValueOnce({ data: [{ id: 'k1', name: 'ci', state: 'active', created_time: 't' }] });
    const keys = await listAPIKeys();
    expect(mockGet).toHaveBeenCalledWith('/grants/keys');
    expect(keys).toHaveLength(1);
  });

  it('reads one key by id', async () => {
    mockGet.mockResolvedValueOnce({ data: { id: 'k1', name: 'ci', state: 'active', created_time: 't' } });
    await getAPIKey('k1');
    expect(mockGet).toHaveBeenCalledWith('/grants/keys/k1');
  });

  it('encodes an id that would otherwise change the path', async () => {
    // An id is opaque; one carrying `/` or `#` silently addresses a different resource.
    mockGet.mockResolvedValueOnce({ data: { id: 'a/b', name: 'n', state: 'active', created_time: 't' } });
    await getAPIKey('a/b');
    expect(mockGet).toHaveBeenCalledWith('/grants/keys/a%2Fb');
  });

  it('revokes rather than deletes, and reports the resulting state', async () => {
    mockDelete.mockResolvedValueOnce({ data: { id: 'k1', state: 'revoked' } });
    const revoked = await deleteAPIKey('k1');
    expect(mockDelete).toHaveBeenCalledWith('/grants/keys/k1');
    expect(revoked.state).toBe('revoked');
  });
});

describe('api/apiKeys — createKeyOver (the Key card)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('one collection is a plain key on it, at the chosen access', async () => {
    mockPost.mockResolvedValueOnce({ data: { id: 'k1', key: 'agk_s' } });
    await createKeyOver('agent', 'editor', ['c-1']);
    expect(mockPost).toHaveBeenCalledTimes(1);
    expect(mockPost).toHaveBeenCalledWith('/grants/keys', { name: 'agent', role: 'editor', resource_id: 'c-1' });
  });

  it('several collections are a bundle with one member each', async () => {
    mockPost.mockResolvedValueOnce({ data: { id: 'k2', key: 'agk_s' } }).mockResolvedValue({ data: {} });
    await createKeyOver('agent', 'viewer', ['c-1', 'c-2']);
    expect(mockPost.mock.calls).toEqual([
      ['/grants/keys', { name: 'agent', role: 'viewer' }],
      ['/grants/keys/k2/members', { resource_id: 'c-1', role: 'viewer' }],
      ['/grants/keys/k2/members', { resource_id: 'c-2', role: 'viewer' }],
    ]);
  });

  it('a key that names nothing is refused before anything is created', async () => {
    // 2026-10-18: the Key card sent `scopes` and `resource_filters`, Mantle read neither, and the
    // key it made reached nothing.
    await expect(createKeyOver('agent', 'viewer', [' '])).rejects.toThrow('at least one collection');
    expect(mockPost).not.toHaveBeenCalled();
  });
});
