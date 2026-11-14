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

vi.mock('../jobGrants', () => ({ askOrigin: vi.fn() }));

import api from '../api';
import { askOrigin } from '../jobGrants';
import { createAPIKey, createKeyOver, deleteAPIKey, getAPIKey, listAPIKeys } from '../apiKeys';

const mockGet = api.get as ReturnType<typeof vi.fn>;
const mockPost = api.post as ReturnType<typeof vi.fn>;
const mockDelete = api.delete as ReturnType<typeof vi.fn>;
const mockAsk = askOrigin as ReturnType<typeof vi.fn>;

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

  it("revokes at Origin's own key page, and reports the resulting state", async () => {
    mockAsk.mockResolvedValueOnce(true);
    const revoked = await deleteAPIKey('k1');
    expect(mockAsk).toHaveBeenCalledWith({ revoke: 'k1' }, expect.any(Function), '/key');
    expect(mockDelete).not.toHaveBeenCalled();
    expect(revoked).toEqual({ id: 'k1', state: 'revoked' });
  });
});

describe('api/apiKeys — createKeyOver (the Key card)', () => {
  beforeEach(() => vi.clearAllMocks());

  const NOW = Date.parse('2026-11-14T00:00:00.000Z');

  it("a key is minted at Origin's own page, at the chosen access and term, and no token comes back", async () => {
    mockAsk.mockResolvedValueOnce('k1');
    const made = await createKeyOver('agent', 'editor', ['c-1'], '2026-12-14T00:00:00.000Z', NOW);
    // FR-019: the key carries the term the view asked for (30 days here).
    expect(mockAsk).toHaveBeenCalledWith(
      { name: 'agent', members: 'c-1:create+read+update+delete+evict', days: '30' },
      expect.any(Function), '/key');
    expect(made.id).toBe('k1');
    expect(made.key).toBeUndefined();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('several collections are one key with one member each, and the term is at most 90 days', async () => {
    mockAsk.mockResolvedValueOnce('k2');
    await createKeyOver('agent', 'viewer', ['c-1', 'c-2'], '2027-11-14T00:00:00.000Z', NOW);
    expect(mockAsk).toHaveBeenCalledWith({ name: 'agent', members: 'c-1:read,c-2:read', days: '90' },
                                         expect.any(Function), '/key');
  });

  it('a key that names nothing is refused before anything is created', async () => {
    // 2026-10-18: the Key card sent `scopes` and `resource_filters`, Mantle read neither, and the
    // key it made reached nothing.
    await expect(createKeyOver('agent', 'viewer', [' '])).rejects.toThrow('at least one collection');
    expect(mockPost).not.toHaveBeenCalled();
  });
});
