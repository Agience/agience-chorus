// src/components/browser/__tests__/archivedMembers.test.tsx
//
// An archived artifact stays findable: the container's view, which Crystal runs, offers the
// Archived chip with its members' count, and shows them when it is on.
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../../api/api', () => ({ get: vi.fn(), getList: vi.fn(() => Promise.resolve([])),
  post: vi.fn(() => Promise.resolve({})), postList: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() }));

import { post } from '../../../api/api';
import { runView } from '../../../api/collections';
import FilterChips from '../FilterChips';

const chips = (list: { key: string; label: string; count: number }[]) => (
  <FilterChips chips={list} kinds={[{ key: 'pdf', count: 2 }]} activeStates={new Set()}
    activeContentTypes={new Set()} hiddenContentTypes={new Set()} onStateToggle={() => {}}
    onContentTypeToggle={() => {}} onHiddenContentTypeToggle={() => {}} onClearAll={() => {}} />
);

describe('a container view', () => {
  it('is run by the view op with the person\'s choices', async () => {
    const choices = { apart: ['archived'], kinds: [], hidden_kinds: ['image'], sort: 'title' };
    await runView('ws 1', choices);
    expect(post).toHaveBeenCalledWith('/artifacts/ws%201/op/view', choices);
  });

  it('offers the chips and kinds it returns, with their counts', () => {
    render(chips([{ key: 'archived', label: 'Archived', count: 3 }, { key: 'closed', label: 'Closed', count: 1 }]));
    expect(screen.getByText(/Archived/).textContent).toContain('3');
    expect(screen.getByText(/Closed/).textContent).toContain('1');
    expect(screen.getAllByText(/PDFs/)[0].closest('button')?.textContent).toContain('2');
  });
});
