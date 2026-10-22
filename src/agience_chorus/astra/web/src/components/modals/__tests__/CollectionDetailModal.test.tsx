import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import CollectionDetailModal from '../CollectionDetailModal';

const listCollectionsMock = vi.fn();
const listGrantsMock = vi.fn();

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'user-1' },
  }),
}));

vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-1' }),
}));

vi.mock('@/api/collections', () => ({
  listCollections: (...args: unknown[]) => listCollectionsMock(...args),
  listGrants: (...args: unknown[]) => listGrantsMock(...args),
  createCollection: vi.fn(),
  updateCollection: vi.fn(),
  deleteCollection: vi.fn(),
  createGrant: vi.fn(),
  updateGrant: vi.fn(),
  deleteGrant: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

describe('CollectionDetailModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    listCollectionsMock.mockResolvedValue([
      {
        id: 'col-1',
        name: 'Main Collection',
        description: 'Primary collection',
        created_by: 'user-1',
        created_time: '2026-03-21T00:00:00Z',
        modified_time: '2026-03-21T00:00:00Z',
      },
    ]);
    listGrantsMock.mockResolvedValue([]);
  });

  // 2026-10-22 (John): commits are not part of the model; each change is a new version of its root.
  it("shows the collection's sharing and no commit history", async () => {
    render(<CollectionDetailModal open onClose={vi.fn()} />);
    await waitFor(() => expect(listGrantsMock).toHaveBeenCalledWith('col-1'));
    expect(screen.queryByText('Commit History')).toBeNull();
  });
});
