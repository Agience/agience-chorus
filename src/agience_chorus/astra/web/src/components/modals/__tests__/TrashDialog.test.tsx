import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import TrashDialog from '../TrashDialog';

const listTrashMock = vi.fn();
const updateArtifactMock = vi.fn();
const deleteArtifactMock = vi.fn();
const refreshArtifactsMock = vi.fn();
const confirmMock = vi.fn();

vi.mock('@/api/artifacts', () => ({
  listTrash: (...args: unknown[]) => listTrashMock(...args),
  updateArtifact: (...args: unknown[]) => updateArtifactMock(...args),
  deleteArtifact: (...args: unknown[]) => deleteArtifactMock(...args),
}));

vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({ refreshArtifacts: refreshArtifactsMock }),
}));

vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-1' }),
}));

vi.mock('@/context/dialog/useConfirm', () => ({
  useConfirm: () => ({ confirm: confirmMock }),
}));

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const ITEM = {
  id: 'a-1',
  context: JSON.stringify({ title: 'Lantern notes' }),
  content: '',
  state: 'archived' as const,
  trashed_time: '2026-10-14T12:00:00+00:00',
  purge_after: '2026-11-13T12:00:00+00:00',
};

describe('TrashDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('reads nothing while closed', () => {
    render(<TrashDialog isOpen={false} onClose={vi.fn()} />);
    expect(listTrashMock).not.toHaveBeenCalled();
  });

  it('lists what is in Trash and when each goes for good', async () => {
    listTrashMock.mockResolvedValueOnce([ITEM]);
    render(<TrashDialog isOpen onClose={vi.fn()} />);
    expect(await screen.findByText('Lantern notes')).toBeInTheDocument();
    expect(screen.getByText(/gone for good on/)).toBeInTheDocument();
  });

  it('says so when Trash is empty', async () => {
    listTrashMock.mockResolvedValueOnce([]);
    render(<TrashDialog isOpen onClose={vi.fn()} />);
    expect(await screen.findByText('Trash is empty.')).toBeInTheDocument();
  });

  it('Restore makes it live again and refreshes the workspace', async () => {
    listTrashMock.mockResolvedValueOnce([ITEM]);
    updateArtifactMock.mockResolvedValueOnce({ ...ITEM, state: 'live' });
    const user = userEvent.setup();
    render(<TrashDialog isOpen onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Restore' }));

    await waitFor(() => expect(updateArtifactMock).toHaveBeenCalledWith('a-1', { state: 'live' }));
    await waitFor(() => expect(screen.queryByText('Lantern notes')).not.toBeInTheDocument());
    expect(refreshArtifactsMock).toHaveBeenCalledWith('ws-1');
  });

  it('Delete permanently asks first, then deletes for good', async () => {
    listTrashMock.mockResolvedValueOnce([ITEM]);
    confirmMock.mockResolvedValueOnce(true);
    deleteArtifactMock.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<TrashDialog isOpen onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Delete permanently' }));

    expect(confirmMock).toHaveBeenCalled();
    await waitFor(() => expect(deleteArtifactMock).toHaveBeenCalledWith('a-1'));
    await waitFor(() => expect(screen.queryByText('Lantern notes')).not.toBeInTheDocument());
  });

  it('a declined confirmation deletes nothing', async () => {
    listTrashMock.mockResolvedValueOnce([ITEM]);
    confirmMock.mockResolvedValueOnce(false);
    const user = userEvent.setup();
    render(<TrashDialog isOpen onClose={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Delete permanently' }));
    expect(deleteArtifactMock).not.toHaveBeenCalled();
    expect(screen.getByText('Lantern notes')).toBeInTheDocument();
  });
});
