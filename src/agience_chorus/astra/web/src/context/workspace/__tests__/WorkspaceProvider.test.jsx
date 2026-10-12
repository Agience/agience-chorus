// src/context/workspace/__tests__/WorkspaceProvider.test.jsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { WorkspaceProvider } from '../WorkspaceProvider';
import { useWorkspace } from '../WorkspaceContext';
import { mockArtifact } from '../../../../tests/utils/helpers';

// Mock dependencies
vi.mock('../../../api/workspaces', () => ({
  listWorkspaceArtifacts: vi.fn(),
  addArtifactToWorkspace: vi.fn(),
  updateWorkspaceArtifact: vi.fn(),
  removeWorkspaceArtifact: vi.fn(),
  deleteWorkspaceArtifact: vi.fn(),
  orderWorkspaceArtifacts: vi.fn(),
  subscribeWorkspaceEvents: vi.fn(() => () => {}),
}));

vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'user-1', email: 'test@example.com' }
  })
}));

vi.mock('../../../api/agent', () => ({
  extractInformation: vi.fn(),
}));

const { useWorkspacesMock } = vi.hoisted(() => ({
  useWorkspacesMock: vi.fn().mockReturnValue({
    activeWorkspace: { id: 'ws-1', name: 'Test Workspace' }
  })
}));

vi.mock('../../workspaces/WorkspacesContext', () => ({
  useWorkspaces: (...args) => useWorkspacesMock(...args)
}));

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  }),
}));

import {
  listWorkspaceArtifacts,
  addArtifactToWorkspace,
  updateWorkspaceArtifact,
  removeWorkspaceArtifact,
  deleteWorkspaceArtifact,
} from '../../../api/workspaces';
import { toast } from 'sonner';

import { extractInformation } from '../../../api/agent';

// Test consumer component
function TestConsumer() {
  const workspace = useWorkspace();
  
  return (
    <div>
      <div data-testid="artifact-count">{workspace.artifacts.length}</div>
      <div data-testid="selected-count">{workspace.selectedArtifactIds.length}</div>
      <button onClick={() => workspace.addArtifact({ content: 'New artifact content' })}>
        Add Artifact
      </button>
      <button onClick={() => workspace.selectAllArtifacts()}>
        Select All
      </button>
      <button onClick={() => workspace.unselectAllArtifacts()}>
        Unselect All
      </button>
      <button onClick={() => workspace.extractInformationFromSelection()}>
        Extract Selection
      </button>
      {workspace.artifacts.map(artifact => (
        <div key={artifact.id} data-testid={`artifact-${artifact.id}`}>
          {artifact.title || artifact.description}
        </div>
      ))}
    </div>
  );
}

describe('WorkspaceProvider', () => {
  const mockArtifacts = [
    mockArtifact({ id: '1', title: 'Artifact 1', state: 'live' }),
    mockArtifact({ id: '2', title: 'Artifact 2', state: 'live' }),
    mockArtifact({ id: '3', title: 'Artifact 3', state: 'live' }),
  ];

  afterEach(() => {
    // Safety net: if a test enables fake timers and fails before cleanup,
    // subsequent tests that rely on RTL polling will hang.
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    listWorkspaceArtifacts.mockResolvedValue({ items: mockArtifacts });
    extractInformation.mockResolvedValue({
      workspace_id: 'ws-1',
      source_artifact_id: '1',
      created_artifact_ids: ['10', '11'],
      unit_count: 2,
    });
    useWorkspacesMock.mockReturnValue({
      activeWorkspace: { id: 'ws-1', name: 'Test Workspace' }
    });
  });

  describe('Extract Units Workflow', () => {
    it('uses selection to infer source + artifacts and calls extractInformation', async () => {
      const user = userEvent.setup();

      render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });

      await user.click(screen.getByText('Select All'));
      await user.click(screen.getByText('Extract Selection'));

      await waitFor(() => {
        expect(extractInformation).toHaveBeenCalledWith('ws-1', '1', ['2', '3']);
      });
    });
  });

  describe('Initial Load', () => {
    it('fetches and displays workspace artifacts on mount', async () => {
      render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });
      
      expect(listWorkspaceArtifacts).toHaveBeenCalledWith('ws-1');
      expect(screen.getByTestId('artifact-1')).toHaveTextContent('Artifact 1');
      expect(screen.getByTestId('artifact-2')).toHaveTextContent('Artifact 2');
      expect(screen.getByTestId('artifact-3')).toHaveTextContent('Artifact 3');
    });

    it('handles API errors gracefully', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      listWorkspaceArtifacts.mockRejectedValueOnce(new Error('Network error'));
      
      render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('0');
      });
      
      expect(consoleSpy).toHaveBeenCalledWith('Failed to load artifacts', expect.any(Error));
      
      consoleSpy.mockRestore();
    });

    it('clears artifacts when no active workspace', async () => {
      const { rerender } = render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });
      
      // Mock no active workspace
  useWorkspacesMock.mockReturnValueOnce({ activeWorkspace: null });
      
      rerender(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      // Artifacts should be cleared
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('0');
      });
    });
  });

  describe('Add Artifact', () => {
    it('adds new artifact via addArtifact()', async () => {
      const user = userEvent.setup();
      const newArtifact = mockArtifact({ id: '4', title: 'New Artifact', state: 'live' });
      addArtifactToWorkspace.mockResolvedValueOnce(newArtifact);
      
      render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });
      
      await user.click(screen.getByText('Add Artifact'));
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('4');
      });
      
      expect(addArtifactToWorkspace).toHaveBeenCalledWith('ws-1', {
        content: 'New artifact content',
        context: expect.any(String),
      });
      expect(screen.getByTestId('artifact-4')).toHaveTextContent('New Artifact');
    });

    it('handles add artifact errors', async () => {
      const user = userEvent.setup();
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      addArtifactToWorkspace.mockRejectedValueOnce(new Error('Failed to create'));
      
      render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });
      
      await user.click(screen.getByText('Add Artifact'));
      
      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith('Failed to create artifact', expect.any(Error));
      });
      
      // Artifact count should remain 3
      expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      
      consoleSpy.mockRestore();
    });
  });

  describe('Artifact Selection', () => {
    it('selects all artifacts via selectAllArtifacts()', async () => {
      const user = userEvent.setup();
      
      render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });
      
      await user.click(screen.getByText('Select All'));
      
      expect(screen.getByTestId('selected-count')).toHaveTextContent('3');
    });

    it('unselects all artifacts via unselectAllArtifacts()', async () => {
      const user = userEvent.setup();
      
      render(
        <WorkspaceProvider>
          <TestConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });
      
      // First select all
      await user.click(screen.getByText('Select All'));
      expect(screen.getByTestId('selected-count')).toHaveTextContent('3');
      
      // Then unselect all
      await user.click(screen.getByText('Unselect All'));
      expect(screen.getByTestId('selected-count')).toHaveTextContent('0');
    });
  });

  describe('Update Artifact', () => {
    it('updates artifact state optimistically', async () => {
      updateWorkspaceArtifact.mockResolvedValueOnce({ ...mockArtifacts[0], state: 'archived' });
      
      function UpdateConsumer() {
        const workspace = useWorkspace();
        
        return (
          <div>
            <div data-testid="artifact-1-state">
              {workspace.artifacts.find(c => c.id === '1')?.state}
            </div>
            <button onClick={() => workspace.updateArtifact({ id: '1', state: 'archived' })}>
              Update Artifact
            </button>
          </div>
        );
      }
      
      const user = userEvent.setup();
      
      render(
        <WorkspaceProvider>
          <UpdateConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-1-state')).toHaveTextContent('live');
      });
      
      await user.click(screen.getByText('Update Artifact'));
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-1-state')).toHaveTextContent('archived');
      });
      
      expect(updateWorkspaceArtifact).toHaveBeenCalledWith('ws-1', '1', { state: 'archived' });
      // Archived artifacts leave the listing, so archiving says so and offers Undo.
      expect(toast).toHaveBeenCalledWith(expect.stringContaining('Archived'),
        expect.objectContaining({ action: expect.objectContaining({ label: 'Undo' }) }));
    });

    // 2026-10-12, a tester: an archived card opened and edited, then vanished on save with the
    // PATCH answered 404. An archived artifact is read-only until restored.
    function ArchivedConsumer() {
      const workspace = useWorkspace();
      return (
        <div>
          <div data-testid="state">{workspace.artifacts.find(c => c.id === '1')?.state}</div>
          <button onClick={() => workspace.updateArtifact({ id: '1', content: 'edited' })}>Edit</button>
          <button onClick={() => workspace.updateArtifact({ id: '1', state: 'live' })}>Restore</button>
        </div>
      );
    }

    async function withArchived() {
      listWorkspaceArtifacts.mockResolvedValue({ items: [{ ...mockArtifacts[0], state: 'archived' }] });
      render(<WorkspaceProvider><ArchivedConsumer /></WorkspaceProvider>);
      await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('archived'));
    }

    it('refuses an edit to an archived artifact and sends nothing', async () => {
      await withArchived();
      await userEvent.setup().click(screen.getByText('Edit'));
      expect(updateWorkspaceArtifact).not.toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalledWith('This card is archived', expect.anything());
    });

    it('still restores an archived artifact', async () => {
      updateWorkspaceArtifact.mockResolvedValueOnce({ ...mockArtifacts[0], state: 'live' });
      await withArchived();
      await userEvent.setup().click(screen.getByText('Restore'));
      expect(updateWorkspaceArtifact).toHaveBeenCalledWith('ws-1', '1', { state: 'live' });
    });

    it('says when a save fails instead of failing silently', async () => {
      updateWorkspaceArtifact.mockRejectedValueOnce(new Error('Not found'));
      function SaveConsumer() {
        const workspace = useWorkspace();
        return <button onClick={() => workspace.updateArtifact({ id: '1', content: 'x' })}>Save</button>;
      }
      render(<WorkspaceProvider><SaveConsumer /></WorkspaceProvider>);
      await waitFor(() => expect(listWorkspaceArtifacts).toHaveBeenCalled());
      await userEvent.setup().click(screen.getByText('Save'));
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Could not save the card', expect.anything()));
    });
  });

  describe('Remove Artifact', () => {
    it('removes artifact from state after deletion', async () => {
      removeWorkspaceArtifact.mockResolvedValueOnce(undefined);
      
      function DeleteConsumer() {
        const workspace = useWorkspace();
        
        return (
          <div>
            <div data-testid="artifact-count">{workspace.artifacts.length}</div>
            <button onClick={() => workspace.removeArtifact('1')}>
              Delete Artifact
            </button>
          </div>
        );
      }
      
      const user = userEvent.setup();
      
      render(
        <WorkspaceProvider>
          <DeleteConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      });
      
      await user.click(screen.getByText('Delete Artifact'));
      
      await waitFor(() => {
        expect(screen.getByTestId('artifact-count')).toHaveTextContent('2');
      });
      
      expect(removeWorkspaceArtifact).toHaveBeenCalledWith('ws-1', '1');
    });
  });

  describe('Local-only patch', () => {
    it('patchArtifactLocally updates local state and sends nothing to the server', async () => {
      function LocalConsumer() {
        const workspace = useWorkspace();
        return (
          <div>
            <div data-testid="artifact-1-context">{workspace.artifacts.find(c => c.id === '1')?.context}</div>
            <button onClick={() => workspace.patchArtifactLocally({ id: '1', context: '{"upload":{"status":"uploading","progress":0.5}}' })}>
              Local Patch
            </button>
          </div>
        );
      }

      const user = userEvent.setup();
      render(
        <WorkspaceProvider>
          <LocalConsumer />
        </WorkspaceProvider>
      );
      await waitFor(() => expect(listWorkspaceArtifacts).toHaveBeenCalled());

      await user.click(screen.getByText('Local Patch'));

      await waitFor(() => expect(screen.getByTestId('artifact-1-context')).toHaveTextContent('"progress":0.5'));
      expect(updateWorkspaceArtifact).not.toHaveBeenCalled();
      expect(addArtifactToWorkspace).not.toHaveBeenCalled();
    });
  });

  describe('Delete vs remove', () => {
    function DeleteConsumer() {
      const workspace = useWorkspace();
      return (
        <div>
          <div data-testid="artifact-count">{workspace.artifacts.length}</div>
          <button onClick={() => workspace.deleteArtifact('1')}>Destroy</button>
        </div>
      );
    }

    it('deleteArtifact destroys through DELETE /artifacts/{id}, not the unlink', async () => {
      deleteWorkspaceArtifact.mockResolvedValueOnce(undefined);
      const user = userEvent.setup();
      render(
        <WorkspaceProvider>
          <DeleteConsumer />
        </WorkspaceProvider>
      );
      await waitFor(() => expect(screen.getByTestId('artifact-count')).toHaveTextContent('3'));

      await user.click(screen.getByText('Destroy'));

      await waitFor(() => expect(screen.getByTestId('artifact-count')).toHaveTextContent('2'));
      expect(deleteWorkspaceArtifact).toHaveBeenCalledWith('ws-1', '1');
      expect(removeWorkspaceArtifact).not.toHaveBeenCalled();
    });

    it('deleteArtifact keeps the card and toasts the server detail on refusal', async () => {
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      deleteWorkspaceArtifact.mockRejectedValueOnce({ response: { data: { detail: 'Forbidden' } } });
      const user = userEvent.setup();
      render(
        <WorkspaceProvider>
          <DeleteConsumer />
        </WorkspaceProvider>
      );
      await waitFor(() => expect(screen.getByTestId('artifact-count')).toHaveTextContent('3'));

      await user.click(screen.getByText('Destroy'));

      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Could not delete', { description: 'Forbidden' }));
      expect(screen.getByTestId('artifact-count')).toHaveTextContent('3');
      errSpy.mockRestore();
    });
  });

  describe('Create failure', () => {
    it('toasts the server detail when createArtifact fails', async () => {
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      addArtifactToWorkspace.mockRejectedValueOnce({ response: { data: { detail: 'Quota exceeded' } } });

      function CreateConsumer() {
        const workspace = useWorkspace();
        return <button onClick={() => workspace.createArtifact({ content: 'x' })}>Create</button>;
      }

      const user = userEvent.setup();
      render(
        <WorkspaceProvider>
          <CreateConsumer />
        </WorkspaceProvider>
      );
      await waitFor(() => expect(listWorkspaceArtifacts).toHaveBeenCalled());

      await user.click(screen.getByText('Create'));

      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Could not create card', { description: 'Quota exceeded' }));
      errSpy.mockRestore();
    });
  });

  describe('Displayed Artifacts', () => {
    it('provides displayedArtifacts state management', async () => {
      function DisplayConsumer() {
        const workspace = useWorkspace();
        
        return (
          <div>
            <div data-testid="displayed-count">
              {workspace.displayedArtifacts?.length ?? 0}
            </div>
            <button onClick={() => workspace.setDisplayedArtifacts?.([mockArtifacts[0]])}>
              Set Displayed
            </button>
          </div>
        );
      }
      
      const user = userEvent.setup();
      
      render(
        <WorkspaceProvider>
          <DisplayConsumer />
        </WorkspaceProvider>
      );
      
      await waitFor(() => {
        expect(screen.getByTestId('displayed-count')).toHaveTextContent('0');
      });
      
      await user.click(screen.getByText('Set Displayed'));
      
      expect(screen.getByTestId('displayed-count')).toHaveTextContent('1');
    });
  });
});
