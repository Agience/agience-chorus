// api/platform.ts
//
// Platform admin API. The surface is `/system/*` and it spans two services, so
// every call here names the one it wants:
//
//   • Users — Mantle (`onMantle`). Admin status is a grant on the authority
//     collection in Mantle's own store, gated by `require_platform_admin`.
//   • Settings — Origin (`onOrigin`). Origin does no authorization; "admin"
//     there is the bootstrap operator, gated by its own operator check.
//
// The split is why the target is explicit: both services answer `/system/*`,
// and the path says which surface, not which service.

import api, { onMantle, onOrigin } from './api';

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export interface PlatformUser {
  id: string;
  email: string;
  name: string;
  picture: string | null;
  is_platform_admin: boolean;
  created_time: string | null;
}

/** One page of person cards. `total` counts the whole People collection, so a
 *  caller can tell whether another page follows without asking for it. */
export interface PlatformUserPage {
  users: PlatformUser[];
  total: number;
  limit: number;
  offset: number;
}

/** The endpoint's own page size and ceiling — asking past the ceiling is a 422. */
export const USER_PAGE_SIZE = 100;
export const USER_PAGE_MAX = 1000;

export async function listUsers(
  offset = 0,
  limit: number = USER_PAGE_SIZE,
): Promise<PlatformUserPage> {
  const response = await api.get<PlatformUserPage>('/system/users', {
    ...onMantle,
    params: { limit: Math.min(limit, USER_PAGE_MAX), offset },
  });
  return response.data;
}

export async function grantPlatformAdmin(userId: string): Promise<void> {
  await api.post(`/system/users/${userId}/grant-admin`, undefined, onMantle);
}

export async function revokePlatformAdmin(userId: string): Promise<void> {
  await api.delete(`/system/users/${userId}/revoke-admin`, onMantle);
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export type PlatformSettings = {
  categories: Record<
    string,
    Array<{ key: string; value: string | null; is_secret: boolean }>
  >;
};

export async function getPlatformSettings(): Promise<PlatformSettings> {
  const response = await api.get<PlatformSettings>('/system/settings', onOrigin);
  return response.data;
}

export async function getPlatformSettingsByCategory(
  category: string,
): Promise<Array<{ key: string; value: string | null; is_secret: boolean }>> {
  const response = await api.get<
    Array<{ key: string; value: string | null; is_secret: boolean }>
  >(`/system/settings/${category}`, onOrigin);
  return response.data;
}

export async function updatePlatformSettings(
  settings: Array<{ key: string; value: string; is_secret?: boolean }>,
): Promise<{ updated: number; restart_required: boolean }> {
  const response = await api.patch<{ updated: number; restart_required: boolean }>(
    '/system/settings',
    { settings },
    onOrigin,
  );
  return response.data;
}
