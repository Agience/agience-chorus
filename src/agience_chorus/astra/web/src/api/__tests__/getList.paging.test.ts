// 2026-11-13, production: a Backlog of 102 listed exactly its first 100. `getList` now follows
// `has_more`, keeps each row once by id, and stops on a page that adds nothing new.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const pages: Array<{ offset: number; limit: number }> = [];
let rows: Array<{ id: string }> = [];
let repeatAtOffset: number | null = null;

vi.mock('axios', () => {
  const instance = {
    get: vi.fn(async (_url: string, config?: { params?: { offset?: number; limit?: number } }) => {
      const offset = Number(config?.params?.offset ?? 0);
      const limit = Number(config?.params?.limit ?? 100);
      pages.push({ offset, limit });
      // A server whose offset counts members, not readable rows: one row comes round again.
      const from = repeatAtOffset !== null && offset === repeatAtOffset ? offset - 1 : offset;
      const items = rows.slice(from, from + limit);
      return { data: { items, total: null, has_more: from + limit < rows.length } };
    }),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: { headers: { common: {} } },
  };
  return { default: { create: () => instance, ...instance }, create: () => instance };
});

import { getList, LIST_PAGE } from '../api';

beforeEach(() => {
  pages.length = 0;
  repeatAtOffset = null;
});

describe('getList pages through has_more', () => {
  it('returns every row of a list longer than one page, once each', async () => {
    rows = Array.from({ length: LIST_PAGE * 2 + 7 }, (_, i) => ({ id: `a${i}` }));
    const got = await getList<{ id: string }>('/artifacts/C/children');
    expect(got).toHaveLength(rows.length);
    expect(new Set(got.map((r) => r.id)).size).toBe(rows.length);
    expect(pages.map((p) => p.offset)).toEqual([0, LIST_PAGE, LIST_PAGE * 2]);
  });

  it('keeps a row the server serves twice only once', async () => {
    rows = Array.from({ length: LIST_PAGE + 3 }, (_, i) => ({ id: `b${i}` }));
    repeatAtOffset = LIST_PAGE;
    const got = await getList<{ id: string }>('/artifacts/C/children');
    expect(new Set(got.map((r) => r.id)).size).toBe(got.length);
  });

  it('asks for one page when the list fits', async () => {
    rows = Array.from({ length: 150 }, (_, i) => ({ id: `c${i}` }));
    const got = await getList<{ id: string }>('/artifacts/C/children');
    expect(got).toHaveLength(150);
    expect(pages).toEqual([{ offset: 0, limit: LIST_PAGE }]);
  });
});
