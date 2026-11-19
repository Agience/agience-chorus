import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import AdvancedSearch from '../AdvancedSearch';

const { searchGlobalMock } = vi.hoisted(() => ({ searchGlobalMock: vi.fn() }));

vi.mock('../../../api/search', () => ({
  searchGlobal: (...a: unknown[]) => searchGlobalMock(...a),
  searchWorkspace: vi.fn(),
  searchCollection: vi.fn(),
  getWorkspaceSuggestions: vi.fn(() => Promise.resolve({ tags: [], titles: [] })),
  getCollectionSuggestions: vi.fn(() => Promise.resolve({ tags: [], titles: [] })),
}));

vi.mock('@/context/shortcuts/useShortcuts', () => ({
  useShortcuts: () => ({ registerShortcut: () => () => {} }),
}));

const empty = { hits: [], total: 0, query_text: '', from: 0, size: 20 };

describe('AdvancedSearch refresh', () => {
  it('asks the open search again, and shows what Mantle answers', async () => {
    vi.useFakeTimers();
    searchGlobalMock.mockResolvedValue(empty);
    const onResults = vi.fn();
    const { rerender } = render(
      <AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact onResults={onResults} refreshTrigger={0} />);
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'budget' } });
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(searchGlobalMock).toHaveBeenCalledTimes(1);

    const answer = { ...empty, hits: [{ id: 'a2' }], total: 1, query_text: 'budget' };
    searchGlobalMock.mockResolvedValue(answer);
    rerender(
      <AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact onResults={onResults} refreshTrigger={1} />);
    await act(async () => {});
    expect(searchGlobalMock).toHaveBeenCalledTimes(2);
    expect(searchGlobalMock.mock.calls[1][0]).toMatchObject(searchGlobalMock.mock.calls[0][0]);
    expect(onResults).toHaveBeenLastCalledWith(expect.objectContaining({ hits: [{ id: 'a2' }] }));
    vi.useRealTimers();
  });

  it('asks nothing when the box is empty', async () => {
    searchGlobalMock.mockClear();
    const { rerender } = render(
      <AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact refreshTrigger={0} />);
    rerender(<AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact refreshTrigger={1} />);
    await act(async () => {});
    expect(searchGlobalMock).not.toHaveBeenCalled();
  });
});
