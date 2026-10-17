import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import CollectionArtifactViewer from '../CollectionArtifactViewer';
import type { Artifact } from '@/context/workspace/workspace.types';

const { listMock, removeFromCollectionMock, deleteArtifactMock, confirmMock, patchMock, store } = vi.hoisted(() => ({
  listMock: vi.fn(),
  removeFromCollectionMock: vi.fn(),
  deleteArtifactMock: vi.fn(),
  confirmMock: vi.fn(),
  patchMock: vi.fn(),
  store: { artifacts: [] as unknown[] },
}));

vi.mock('@/api/collections', () => ({
  addArtifactToCollection: vi.fn(),
  listCollectionArtifacts: (...args: unknown[]) => listMock(...args),
  removeArtifactFromCollection: (...args: unknown[]) => removeFromCollectionMock(...args),
  subscribeCollectionEvents: () => () => {},
}));

vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({ artifacts: store.artifacts, deleteArtifact: deleteArtifactMock, patchArtifactLocally: patchMock }),
}));

vi.mock('@/context/dialog/useConfirm', () => ({
  useConfirm: () => ({ confirm: confirmMock }),
}));

vi.mock('@/api/workspaces', () => ({ addArtifactToWorkspace: vi.fn() }));
vi.mock('@/components/browser/CardTypePickerDialog', () => ({ default: () => null }));

// The grid is replaced by two buttons that call the host's remove handler the way the real
// card does: plain for Remove, with 'delete' for the Delete menu item.
vi.mock('@/components/common/CardGrid', () => ({
  default: ({ artifacts, onRemove, deleteEnabled, activeSource }: {
    artifacts: Artifact[];
    onRemove?: (a: Artifact, mode?: 'delete') => void;
    deleteEnabled?: boolean;
    activeSource?: { noun?: string };
  }) => (
    <div data-delete-enabled={String(Boolean(deleteEnabled))} data-noun={activeSource?.noun} data-testid="grid">
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
    patchMock.mockReset();
    store.artifacts = [];
  });

  // 2026-10-13, a tester: Remove answered 200 `removed: true` and the card stayed. The view adds
  // every workspace-store card that lists this container, and the store's copy still listed it.
  it('Remove also drops the membership from the workspace store, so the card does not come back', async () => {
    store.artifacts = [{ ...member, committed_collection_ids: ['col-1', 'other'] }];
    render(<CollectionArtifactViewer artifact={collection} />);
    fireEvent.click(await screen.findByText('remove m1'));
    await waitFor(() => expect(patchMock).toHaveBeenCalledWith({ id: 'm1', committed_collection_ids: ['other'] }));
  });

  // 2026-10-13, a tester: a collection kept showing an archived artifact a workspace had dropped.
  it('does not show an archived card the workspace store still holds', async () => {
    listMock.mockResolvedValue([]);
    store.artifacts = [{ id: 'a1', root_id: 'a1', context: '{}', content: '', state: 'archived', committed_collection_ids: ['col-1'] }];
    render(<CollectionArtifactViewer artifact={collection} />);
    await screen.findByTestId('grid');
    expect(screen.queryByText('a1')).toBeNull();
  });

  it('calls a workspace a workspace', async () => {
    const workspace = { ...collection, context: '{"content_type":"application/vnd.agience.workspace+json"}' } as Artifact;
    render(<CollectionArtifactViewer artifact={workspace} />);
    expect(await screen.findByTestId('grid')).toHaveAttribute('data-noun', 'workspace');
    expect(screen.getByTitle('New card in this workspace')).toBeTruthy();
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
