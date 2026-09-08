// api/api.ts
import axios from 'axios';
import { getRuntimeConfig } from '../config/runtime';

// Base URLs. Origin owns identity; Mantle owns artifacts. A single axios
// instance is kept, and the request interceptor below rewrites baseURL to
// ORIGIN_URI for /auth/* calls — except /auth/authorizer/*, which stays on
// Mantle.
const MANTLE_URI = getRuntimeConfig().mantleUri || 'http://localhost:8081';
const ORIGIN_URI = getRuntimeConfig().originUri;
const CRYSTAL_URI = getRuntimeConfig().crystalUri;

const api = axios.create({
  baseURL: MANTLE_URI,
  timeout: 10000, // 10s — prevents indefinite hangs on server disconnect
  headers: {
    'Content-Type': 'application/json',
  },
});

// Name the service a call goes to, for surfaces where the path cannot. Origin
// and Mantle both serve `/system/*` — Origin the settings half, Mantle the
// users/issuers/seed half — so the prefix identifies the surface and not the
// service answering it. A call on such a surface passes one of these as its
// request config, and that is the only thing that decides where it lands: no
// rule below may match `/system`.
export const onOrigin = { baseURL: ORIGIN_URI };
export const onMantle = { baseURL: MANTLE_URI };

// Path-derived routing, valid only for prefixes ONE service owns end to end.
// Adding a prefix here that both services serve reintroduces the guess that
// `onOrigin` / `onMantle` exist to remove.
function isOriginAuthPath(url: string): boolean {
  // /auth/* — owned by Origin except `/auth/authorizer/*` which stays Mantle-side.
  if (url.startsWith('/auth/')) {
    if (url.startsWith('/auth/authorizer/')) return false;
    return true;
  }
  // /api-keys/* and /grants/* — sovereign authorization: Mantle owns grants + API
  // keys in its own store (see mantle/services/grant_store.py). These are served by
  // Mantle (the axios default baseURL), not Origin. Origin stays identity-only.
  // /server-credentials/* CRUD stays on Origin. The lone JWK PUT endpoint is
  // Mantle-side but isn't called from the browser, only from server-side startup.
  if (url.startsWith('/server-credentials') || url === '/server-credentials') return true;
  // /setup/* — Origin owns the setup wizard.
  if (url.startsWith('/setup') || url === '/setup') return true;
  return false;
}

function isCrystalOpPath(url: string): boolean {
  // Content-type operations dispatch through Crystal, the gateway
  // (`POST /artifacts/{id}/op/{name}`). Mantle does not mount the op surface,
  // so these calls go to Crystal (:8085); Crystal forwards the caller's token
  // and Mantle/personas enforce keyed access. Raw CRUD, search and events
  // stay on Mantle. `/create`, `/resolve/*`, `/embed` are Crystal-only too,
  // but facet does not call them.
  return /\/artifacts\/[^/]+\/op\//.test(url);
}

// Route each call to its owning plane: Origin (auth/identity), Crystal (op
// dispatch), else Mantle (the axios instance default). A call that named its
// service through `onOrigin` / `onMantle` arrives with that baseURL already
// merged in and matches no rule here, so it keeps it.
api.interceptors.request.use(config => {
  const url = config.url || '';
  if (isOriginAuthPath(url)) {
    config.baseURL = ORIGIN_URI;
  } else if (isCrystalOpPath(url)) {
    config.baseURL = CRYSTAL_URI;
  }
  const token = localStorage.getItem('access_token');
  if (token && config.headers) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401, clear token and redirect to login
api.interceptors.response.use(
  response => response,
  error => {
    const originalRequest = error.config;
    if (error.response?.status === 401 && !originalRequest._retry) {
      // Don't intercept 401s from auth endpoints — let the Login page handle them.
      const url = originalRequest?.url || '';
      const isAuthEndpoint =
        url.startsWith('/auth/password/') ||
        url.startsWith('/auth/otp/') ||
        url.startsWith('/auth/passkey/');
      if (!isAuthEndpoint) {
        originalRequest._retry = true;
        localStorage.removeItem('access_token');
        window.location.href = '/login';
      }
    }
    // On 402 (Payment Required), dispatch upgrade prompt event
    if (error.response?.status === 402) {
      const reason = error.response.headers?.['x-upgrade-reason'] || 'limit_reached';
      const detail = error.response.data?.detail;
      window.dispatchEvent(
        new CustomEvent('agience:upgrade-prompt', {
          detail: {
            reason,
            code: typeof detail === 'object' ? detail?.code : undefined,
            limit: typeof detail === 'object' ? detail?.limit : undefined,
            used: typeof detail === 'object' ? detail?.used : undefined,
          },
        }),
      );
    }
    return Promise.reject(error);
  }
);

// Typed helpers using simple config type
export async function get<T>(
  url: string,
  config?: Record<string, unknown>
): Promise<T> {
  const res = await api.get<T>(url, config);
  return res.data;
}

/**
 * A LIST endpoint's rows.
 *
 * `/artifacts/visible`, `/children`, `/batch`, `/commits` and `/access-log` return
 * `{ items, total, has_more }` since 2026-08-25 (P-6/P-7). The bare array is still accepted so a
 * browser pointed at an older node keeps working, and so does a mixed fleet mid-rollout.
 *
 * NOTE: this takes ONE page. `has_more` says whether there are others; nothing here follows them
 * yet. A list that silently stopped at a page boundary reads as "you have none of those", which is
 * the exact failure the envelope was introduced to make visible.
 */
export async function getList<T>(
  url: string,
  config?: Record<string, unknown>
): Promise<T[]> {
  const body = await get<T[] | { items?: T[] }>(url, config);
  if (Array.isArray(body)) return body;
  return body?.items ?? [];
}

/**
 * A LIST endpoint reached by POST — `/artifacts/batch` is the only one today.
 *
 * ⛔ WHY THIS EXISTS. `getList` unwraps the `{ items, total, has_more }` envelope, but it is a GET
 * helper, and the two batch callers used a raw `post<{ artifacts: ... }>` and read `res.artifacts`.
 * That key was retired when `/artifacts/batch` moved to the one page shape, so the read returned
 * `undefined` and `?? []` turned it into an empty list: **global search across collections and
 * workspaces silently found nothing, with no error anywhere.**
 *
 * The bare array is still accepted for the same reason `getList` accepts it — an older node, or a
 * mixed fleet mid-rollout.
 */
export async function postList<T, B = unknown>(
  url: string,
  body?: B,
  config?: Record<string, unknown>
): Promise<T[]> {
  const res = await post<T[] | { items?: T[] }, B>(url, body, config);
  if (Array.isArray(res)) return res;
  return res?.items ?? [];
}

export async function post<T, B = unknown>(
  url: string,
  body?: B,
  config?: Record<string, unknown>
): Promise<T> {
  const res = await api.post<T>(url, body, config);
  return res.data;
}

export async function put<T, B = unknown>(
  url: string,
  body?: B,
  config?: Record<string, unknown>
): Promise<T> {
  const res = await api.put<T>(url, body, config);
  return res.data;
}

export async function patch<T, B = unknown>(
  url: string,
  body?: B,
  config?: Record<string, unknown>
): Promise<T> {
  const res = await api.patch<T>(url, body, config);
  return res.data;
}

export async function del<T>(
  url: string,
  config?: Record<string, unknown>
): Promise<T> {
  const res = await api.delete<T>(url, config);
  return res.data;
}

// x-www-form-urlencoded helper. Honors the same Origin / Mantle split as the
// axios interceptor above — /auth/* goes to ORIGIN_URI (with the same carve-outs).
export async function postForm<T>(
  url: string,
  body: URLSearchParams
): Promise<T> {
  const baseUri = isOriginAuthPath(url) ? ORIGIN_URI : MANTLE_URI;
  const res = await fetch(`${baseUri}${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(err.detail ?? 'Request failed');
  }

  return res.json() as Promise<T>;
}

export default api;
