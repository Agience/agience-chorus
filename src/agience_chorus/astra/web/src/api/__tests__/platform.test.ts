// src/api/__tests__/platform.test.ts
// Tests for api/platform.ts — the /system/* admin surface, which spans two
// services. Each call is pinned to its path AND its service: the two are
// independent facts here, and getting either wrong is a 404 or a 403.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { RecordedRequest } from './requestRecorder';
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

import {
  listUsers,
  grantPlatformAdmin,
  revokePlatformAdmin,
  getPlatformSettings,
  getPlatformSettingsByCategory,
  updatePlatformSettings,
  USER_PAGE_SIZE,
} from '../platform';

const MANTLE = 'https://api.example.com';
const ORIGIN = 'https://origin.example.com';

describe('api/platform', () => {
  let seen: RecordedRequest[] = [];
  let restore = () => {};
  let reply: unknown = {};

  beforeEach(() => {
    reply = {};
    ({ requests: seen, restore } = recordRequests(() => reply));
  });

  afterEach(() => restore());

  const call = () => seen[0];

  describe('users — Mantle', () => {
    it('GETs the first page of /system/users from Mantle', async () => {
      reply = { users: [{ id: 'u-1' }], total: 1, limit: USER_PAGE_SIZE, offset: 0 };

      const page = await listUsers();

      expect(call().method).toBe('get');
      expect(call().url).toBe('/system/users');
      expect(call().baseURL).toBe(MANTLE);
      expect(call().params).toEqual({ limit: USER_PAGE_SIZE, offset: 0 });
      expect(page).toEqual(reply);
    });

    // The envelope is the whole point: a caller that reads `.users` alone cannot
    // tell a complete list from the first hundred of ten thousand.
    it('returns total alongside the page so the caller can see what it is missing', async () => {
      reply = { users: [{ id: 'u-1' }], total: 4321, limit: USER_PAGE_SIZE, offset: 0 };

      const page = await listUsers();

      expect(page.total).toBe(4321);
      expect(page.users).toHaveLength(1);
    });

    it('asks for a later page by offset', async () => {
      await listUsers(200, 50);
      expect(call().params).toEqual({ limit: 50, offset: 200 });
    });

    it('clamps the page size to the ceiling the endpoint accepts', async () => {
      await listUsers(0, 99999);
      expect(call().params).toEqual({ limit: 1000, offset: 0 });
    });

    it('POSTs grant-admin to Mantle', async () => {
      await grantPlatformAdmin('u-7');
      expect(call().method).toBe('post');
      expect(call().url).toBe('/system/users/u-7/grant-admin');
      expect(call().baseURL).toBe(MANTLE);
    });

    it('DELETEs revoke-admin on Mantle', async () => {
      await revokePlatformAdmin('u-7');
      expect(call().method).toBe('delete');
      expect(call().url).toBe('/system/users/u-7/revoke-admin');
      expect(call().baseURL).toBe(MANTLE);
    });
  });

  describe('settings — Origin', () => {
    it('GETs /system/settings from Origin', async () => {
      reply = { categories: {} };
      await getPlatformSettings();
      expect(call().url).toBe('/system/settings');
      expect(call().baseURL).toBe(ORIGIN);
    });

    it('GETs one category from Origin', async () => {
      reply = [];
      await getPlatformSettingsByCategory('email');
      expect(call().url).toBe('/system/settings/email');
      expect(call().baseURL).toBe(ORIGIN);
    });

    it('PATCHes /system/settings on Origin', async () => {
      reply = { updated: 1, restart_required: false };
      await updatePlatformSettings([{ key: 'branding.title', value: 'Agience' }]);
      expect(call().method).toBe('patch');
      expect(call().url).toBe('/system/settings');
      expect(call().baseURL).toBe(ORIGIN);
      expect(call().data).toContain('branding.title');
    });
  });
});
