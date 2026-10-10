import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { WorkspacesProvider } from '../WorkspacesProvider';
import { useWorkspaces } from '../WorkspacesContext';

const { listWorkspacesMock, createWorkspaceMock, toastErrorMock } = vi.hoisted(() => ({
  listWorkspacesMock: vi.fn(),
  createWorkspaceMock: vi.fn(),
  toastErrorMock: vi.fn(),
}));

vi.mock('../../../api/workspaces', () => ({
  listWorkspaces: (...args: unknown[]) => listWorkspacesMock(...args),
  createWorkspace: (...args: unknown[]) => createWorkspaceMock(...args),
  updateWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
}));

vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: true, loading: false, user: { id: 'user-1' } }),
}));

vi.mock('../../../hooks/usePreferences', () => ({
  usePreferences: () => ({ preferences: {}, isLoading: false, updatePreferences: vi.fn() }),
}));

vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => toastErrorMock(...args), success: vi.fn() },
}));

const serverRefusal = (detail: string) => Object.assign(new Error('Request failed with status code 403'), {
  response: { status: 403, data: { detail } },
});

const rejected = vi.fn();

function CreateButton() {
  const { createWorkspace } = useWorkspaces();
  return <button onClick={() => { createWorkspace('W', '').catch(rejected); }}>create</button>;
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <WorkspacesProvider>
        <CreateButton />
      </WorkspacesProvider>
    </MemoryRouter>,
  );
}

describe('WorkspacesProvider failures', () => {
  beforeEach(() => {
    listWorkspacesMock.mockReset();
    createWorkspaceMock.mockReset();
    toastErrorMock.mockReset();
    rejected.mockReset();
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('toasts the server detail when the workspace list fails to load', async () => {
    listWorkspacesMock.mockRejectedValueOnce(serverRefusal('Not allowed'));
    renderProvider();
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith(
      'Could not load workspaces', { description: 'Not allowed' },
    ));
  });

  it('toasts the server detail and rethrows when create fails', async () => {
    listWorkspacesMock.mockResolvedValueOnce([]);
    createWorkspaceMock.mockRejectedValueOnce(serverRefusal('Workspace limit reached'));
    renderProvider();

    fireEvent.click(screen.getByText('create'));

    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith(
      'Could not create workspace', { description: 'Workspace limit reached' },
    ));
    await waitFor(() => expect(rejected).toHaveBeenCalledTimes(1));
  });

  it('falls back to the error message when the server gave no detail', async () => {
    listWorkspacesMock.mockRejectedValueOnce(new Error('Network Error'));
    renderProvider();
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith(
      'Could not load workspaces', { description: 'Network Error' },
    ));
  });
});
