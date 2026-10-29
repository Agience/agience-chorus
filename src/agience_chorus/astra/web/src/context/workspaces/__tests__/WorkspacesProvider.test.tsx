import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { WorkspacesProvider } from '../WorkspacesProvider';
import { useWorkspaces } from '../WorkspacesContext';

const { listWorkspacesMock, createWorkspaceMock, toastErrorMock, prefs } = vi.hoisted(() => ({
  listWorkspacesMock: vi.fn(),
  createWorkspaceMock: vi.fn(),
  toastErrorMock: vi.fn(),
  prefs: { current: {} as Record<string, unknown>, update: (() => {}) as (p: Record<string, unknown>) => void },
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
  usePreferences: () => ({ preferences: prefs.current, isLoading: false, updatePreferences: prefs.update }),
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

describe('WorkspacesProvider deep links', () => {
  beforeEach(() => {
    listWorkspacesMock.mockReset();
    toastErrorMock.mockReset();
    prefs.current = {};
    prefs.update = () => {};
    localStorage.clear();
  });

  function ActiveId() {
    const { activeWorkspaceId } = useWorkspaces();
    return <div data-testid="active">{activeWorkspaceId ?? ''}</div>;
  }

  function renderAt(url: string) {
    return render(
      <MemoryRouter initialEntries={[url]}>
        <WorkspacesProvider>
          <ActiveId />
        </WorkspacesProvider>
      </MemoryRouter>,
    );
  }

  // 2026-10-13, a tester opened a shared workspace link before being invited and saw their own
  // Inbox with no word that the link had not worked.
  it('says so when the link names a workspace this account cannot reach', async () => {
    listWorkspacesMock.mockResolvedValue([{ id: 'inbox-1', name: 'Inbox' }]);
    renderAt('/?workspace=shared-ws');
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith(
      "You can't open this workspace", expect.objectContaining({ description: expect.stringContaining('invitation') }),
    ));
    expect(screen.getByTestId('active')).toHaveTextContent('inbox-1');
  });

  it('opens the linked workspace when this account holds it', async () => {
    listWorkspacesMock.mockResolvedValueOnce([{ id: 'inbox-1', name: 'Inbox' }, { id: 'shared-ws', name: 'S' }]);
    renderAt('/?workspace=shared-ws');
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('shared-ws'));
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  // 2026-10-23, a tester claimed a Viewer invite; the claim page navigated to the workspace with
  // the list loaded before the claim, and the app said it had not been shared with them.
  it('reads the list again before refusing a link the loaded list does not hold', async () => {
    listWorkspacesMock
      .mockResolvedValueOnce([{ id: 'inbox-1', name: 'Inbox' }])
      .mockResolvedValueOnce([{ id: 'inbox-1', name: 'Inbox' }, { id: 'shared-ws', name: 'S' }]);
    renderAt('/?workspace=shared-ws');
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('shared-ws'));
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('docks a linked workspace that is not yet a tab, and keeps it selected', async () => {
    const updates: Record<string, unknown>[] = [];
    prefs.current = { browser: { dockedWorkspaceCardIds: ['inbox-1'] } };
    prefs.update = (p) => { updates.push(p); };
    listWorkspacesMock.mockResolvedValue([{ id: 'inbox-1', name: 'Inbox' }, { id: 'shared-ws', name: 'S' }]);
    renderAt('/?workspace=shared-ws');
    await waitFor(() => expect(updates).toContainEqual(
      { browser: { dockedWorkspaceCardIds: ['inbox-1', 'shared-ws'] } }));
    expect(screen.getByTestId('active')).toHaveTextContent('shared-ws');
  });
});

describe('WorkspacesProvider selection on load', () => {
  beforeEach(() => {
    listWorkspacesMock.mockReset();
    prefs.current = {};
    prefs.update = () => {};
    localStorage.clear();
  });

  function ActiveId() {
    const { activeWorkspaceId, setActiveWorkspaceId } = useWorkspaces();
    return <button data-testid="active" onClick={() => setActiveWorkspaceId('qa-ws')}>{activeWorkspaceId ?? ''}</button>;
  }

  const list = [
    // The id that sorts first is not the Inbox: the order `/artifacts/visible` returns.
    { id: '73459b53-qa', name: 'QA', created_by: 'user-1', created_time: '2026-10-13T00:00:00Z' },
    { id: 'f7d56caf-inbox', name: 'Inbox', created_by: 'user-1', created_time: '2026-10-01T00:00:00Z' },
    { id: 'qa-ws', name: 'Other', created_by: 'user-1', created_time: '2026-10-14T00:00:00Z' },
  ];

  function renderRoot() {
    return render(
      <MemoryRouter initialEntries={['/']}>
        <WorkspacesProvider>
          <ActiveId />
        </WorkspacesProvider>
      </MemoryRouter>,
    );
  }

  // 2026-10-23, a tester: with the Inbox selected, a reload selected the workspace sorting first.
  it('selects the Inbox, not the first workspace by id', async () => {
    listWorkspacesMock.mockResolvedValue(list);
    renderRoot();
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('f7d56caf-inbox'));
  });

  it('reopens the tab last selected', async () => {
    listWorkspacesMock.mockResolvedValue(list);
    const first = renderRoot();
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('f7d56caf-inbox'));
    fireEvent.click(screen.getByTestId('active'));
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('qa-ws'));
    first.unmount();
    renderRoot();
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('qa-ws'));
  });
});

// 2026-10-29, a tester: a workspace made as a card could not be opened as a tab or found with Ctrl+K
// until a refresh, and a rename kept the old name there.
describe('WorkspacesProvider follows changes saved elsewhere', () => {
  beforeEach(() => { listWorkspacesMock.mockReset(); listWorkspacesMock.mockResolvedValue([{ id: 'ws-1', created_by: 'user-1' }]); });

  it.each([
    ['a new workspace', { id: 'ws-new', content_type: 'application/vnd.agience.workspace+json' }],
    ['a listed workspace renamed', { id: 'ws-1', context: '{"title":"Renamed"}' }],
  ])('reads the list again for %s', async (_name, change) => {
    const { announceArtifactChange } = await import('../../../constants/strings');
    renderProvider();
    await waitFor(() => expect(listWorkspacesMock).toHaveBeenCalledTimes(1));
    announceArtifactChange(change);
    await waitFor(() => expect(listWorkspacesMock).toHaveBeenCalledTimes(2));
  });

  it('does not for an ordinary card', async () => {
    const { announceArtifactChange } = await import('../../../constants/strings');
    renderProvider();
    await waitFor(() => expect(listWorkspacesMock).toHaveBeenCalledTimes(1));
    announceArtifactChange({ id: 'note-1', context: '{"content_type":"text/plain"}' });
    await new Promise((r) => setTimeout(r, 50));
    expect(listWorkspacesMock).toHaveBeenCalledTimes(1);
  });
});
