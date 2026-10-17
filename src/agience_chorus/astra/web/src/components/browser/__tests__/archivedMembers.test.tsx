// src/components/browser/__tests__/archivedMembers.test.tsx
//
// 2026-10-13, a tester: an archived artifact disappeared from its workspace and its collection
// after a refresh, with no way in the app to find it again. Default listings read past archived
// members; the Archived chip counts them from the server and loads them from `?state=archived`.
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../../api/api', () => ({ get: vi.fn(), getList: vi.fn(() => Promise.resolve([])),
  post: vi.fn(), postList: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() }));

import { getList } from '../../../api/api';
import { listArchivedChildren } from '../../../api/collections';
import FilterChips from '../FilterChips';

const chips = (archivedCount?: number) => (
  <FilterChips artifacts={[]} activeStates={new Set()} activeContentTypes={new Set()}
    hiddenContentTypes={new Set()} onStateToggle={() => {}} onContentTypeToggle={() => {}}
    onHiddenContentTypeToggle={() => {}} onClearAll={() => {}} archivedCount={archivedCount} />
);

describe('archived members', () => {
  it('are listed from the container with state=archived', async () => {
    await listArchivedChildren('ws 1');
    expect(getList).toHaveBeenCalledWith('/artifacts/ws%201/children?state=archived');
  });

  it('are counted on the Archived chip from the server, not from what is loaded', () => {
    render(chips(3));
    expect(screen.getByText(/Archived/).textContent).toContain('3');
  });
});
