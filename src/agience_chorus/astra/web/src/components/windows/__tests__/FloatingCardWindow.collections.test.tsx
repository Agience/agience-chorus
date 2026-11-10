// BUG-042 (2026-11-10): Manage Collections ticked nothing for an artifact held by a workspace, now
// that workspaces are offered there. It ticks every container the artifact is in.
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import FloatingCardWindow from '../FloatingCardWindow';

const pickerProps = vi.fn();

vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({
    openedArtifacts: [], keepOpenedArtifact: () => {},
    isEditable: () => true,
    artifacts: [{
      id: 'backlog', root_id: 'backlog', state: 'live', content: '',
      context: JSON.stringify({ title: 'Backlog', content_type: 'text/plain' }),
      committed_collection_ids: ['col-1'], container_ids: ['ws-agency', 'col-1'],
    }],
    displayedArtifacts: [], updateArtifact: vi.fn(),
  }),
}));
vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-agency', updateWorkspace: vi.fn(),
                          workspaces: [{ id: 'ws-agency', name: 'Agience' }] }),
}));
vi.mock('@/hooks/useCollections', () => ({ useCollections: () => ({ collections: [{ id: 'col-1', name: 'Notes' }] }) }));
vi.mock('@/registry/content-types', () => ({
  getContentType: () => ({ id: 'text', defaultMode: 'floating', defaultState: 'view', states: ['view'],
                           viewer: async () => ({ default: () => <div /> }) }),
}));
vi.mock('@/registry/viewer-map', () => ({ defaultFactory: async () => ({ default: () => <div /> }) }));
vi.mock('@/components/ui/icon-button', () => ({
  IconButton: ({ children, active: _a, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) => (
    <button type="button" {...props}>{children}</button>),
}));
vi.mock('@/components/common/CollectionChip', () => ({ CollectionChip: () => <div /> }));
vi.mock('@/components/modals/CollectionPicker', () => ({
  CollectionPicker: (props: { open: boolean; selectedCollectionIds?: string[] }) => {
    if (props.open) pickerProps(props.selectedCollectionIds);
    return null;
  },
}));
vi.mock('@/components/containers/ContainerCardViewer', () => ({ default: () => <div /> }));
vi.mock('@/hooks/useDebouncedSave', () => ({
  useDebouncedSave: () => ({ isSaving: false, lastSaved: null, resetTracking: () => {} }),
}));
vi.mock('@/api/collections', () => ({ addArtifactToCollection: vi.fn(), setArtifactCollections: vi.fn(),
                                       getCollection: vi.fn().mockResolvedValue({ name: 'x' }) }));

describe('Manage Collections', () => {
  it('ticks every container the artifact is in, workspaces included', async () => {
    render(<FloatingCardWindow artifactId="backlog" zIndex={10} onClose={() => {}} />);
    fireEvent.click(await screen.findByTitle('Collections'));
    fireEvent.click(await screen.findByText('Change'));
    await waitFor(() => expect(pickerProps).toHaveBeenCalled());
    expect(pickerProps.mock.calls[pickerProps.mock.calls.length - 1]?.[0]).toEqual(['ws-agency', 'col-1']);
  });
});
