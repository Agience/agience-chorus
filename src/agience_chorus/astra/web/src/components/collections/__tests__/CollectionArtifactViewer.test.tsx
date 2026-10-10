import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import CollectionArtifactViewer from '../CollectionArtifactViewer';
import type { Artifact } from '@/context/workspace/workspace.types';

const { listMock, removeFromCollectionMock, deleteArtifactMock, confirmMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  removeFromCollectionMock: vi.fn(),
  deleteArtifactMock: vi.fn(),
  confirmMock: vi.fn(),
}));

vi.mock('@/api/collections', () => ({
  addArtifactToCollection: vi.fn(),
  listCollectionArtifacts: (...args: unknown[]) => listMock(...args),
  removeArtifactFromCollection: (...args: unknown[]) => removeFromCollectionMock(...args),
  subscribeCollectionEvents: () => () => {},
}));

vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({ artifacts: [], deleteArtifact: deleteArtifactMock }),
}));

vi.mock('@/context/dialog/useConfirm', () => ({
  useConfirm: () => ({ confirm: confirmMock }),
}));

// The grid is replaced by two buttons that call the host's remove handler the way the real
// card does: plain for Remove, with 'delete' for the Delete menu item.
vi.mock('@/components/common/CardGrid', () => ({
  default: ({ artifacts, onRemove, deleteEnabled }: {
    artifacts: Artifact[];
    onRemove?: (a: Artifact, mode?: 'delete') => void;
    deleteEnabled?: boolean;
  }) => (
    <div data-delete-enabled={String(Boolean(deleteEnabled))} data-testid="grid">
      {artifacts.map((a) => (
        <div key={String(a.id)}>
          <span>{String(a.id)}</span>
          <button onClick={() => onRemove?.(a)}>remove {String(a.id)}</button>
          <button onClick={() => onRemove?.(a, 'delete')}>delete {String(a.id)}</button>
        </div>
      ))}
    </div>
  ),
}));

vi.mock('@/components/common/CardList', () => ({ default: () => null }));

const collection = { id: 'col-1', context: '{}', content: '', state: 'live' } as Artifact;
const member = { id: 'm1', root_id: 'm1', context: '{}', content: '', state: 'live' } as Artifact;

describe('CollectionArtifactViewer remove and delete', () => {
  beforeEach(() => {
    listMock.mockReset().mockResolvedValue([member]);
    removeFromCollectionMock.mockReset().mockResolvedValue(undefined);
    deleteArtifactMock.mockReset().mockResolvedValue(true);
    confirmMock.mockReset();
  });

  it('tells the grid it can delete', async () => {
    render(<CollectionArtifactViewer artifact={collection} />);
    expect(await screen.findByTestId('grid')).toHaveAttribute('data-delete-enabled', 'true');
  });

  it('Remove unlinks from the collection without asking', async () => {
    render(<CollectionArtifactViewer artifact={collection} />);
    fireEvent.click(await screen.findByText('remove m1'));

    await waitFor(() => expect(removeFromCollectionMock).toHaveBeenCalledWith('col-1', 'm1'));
    expect(confirmMock).not.toHaveBeenCalled();
    expect(deleteArtifactMock).not.toHaveBeenCalled();
  });

  it('Delete asks, then destroys the artifact rather than unlinking it', async () => {
    confirmMock.mockResolvedValue(true);
    render(<CollectionArtifactViewer artifact={collection} />);
    fireEvent.click(await screen.findByText('delete m1'));

    await waitFor(() => expect(deleteArtifactMock).toHaveBeenCalledWith('m1'));
    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(removeFromCollectionMock).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByText('remove m1')).toBeNull());
  });

  it('Delete does nothing when the confirmation is declined', async () => {
    confirmMock.mockResolvedValue(false);
    render(<CollectionArtifactViewer artifact={collection} />);
    fireEvent.click(await screen.findByText('delete m1'));

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(deleteArtifactMock).not.toHaveBeenCalled();
    expect(removeFromCollectionMock).not.toHaveBeenCalled();
    expect(screen.getByText('remove m1')).toBeInTheDocument();
  });
});
