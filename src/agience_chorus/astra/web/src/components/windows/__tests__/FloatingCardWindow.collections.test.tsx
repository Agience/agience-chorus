// BUG-042 (2026-11-10): Manage Collections ticked nothing for an artifact held by a workspace, now
// that workspaces are offered there. It ticks every container the artifact is in.
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import FloatingCardWindow from '../FloatingCardWindow';

const pickerProps = vi.fn();
const patchArtifactLocally = vi.fn();
const api = vi.hoisted(() => ({
  changeMemberships: vi.fn(),
}));

vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({
    openedArtifacts: [], keepOpenedArtifact: () => {},
    isEditable: () => true, patchArtifactLocally,
    artifacts: [{
      id: 'backlog', root_id: 'backlog', state: 'live', content: '',
      context: JSON.stringify({ title: 'Backlog', content_type: 'text/plain' }),
      committed_collection_ids: ['col-1'], container_ids: ['ws-agency', 'col-1', 'col-hidden'],
      containers: [{ id: 'ws-agency', name: 'Agience' }, { id: 'col-1', name: 'Notes' }],
    }],
    displayedArtifacts: [], updateArtifact: vi.fn(),
  }),
}));
vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-agency', updateWorkspace: vi.fn(),
                          workspaces: [{ id: 'ws-agency', name: 'Agience' }] }),
}));
vi.mock('@/registry/content-types', () => ({
  getContentType: () => ({ id: 'text', defaultMode: 'floating', defaultState: 'view', states: ['view'],
                           viewer: async () => ({ default: () => <div /> }) }),
}));
vi.mock('@/registry/viewer-map', () => ({ defaultFactory: async () => ({ default: () => <div /> }) }));
vi.mock('@/components/ui/icon-button', () => ({
  IconButton: ({ children, active: _a, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) => (
    <button type="button" {...props}>{children}</button>),
}));
vi.mock('@/components/common/CollectionChip', () => ({ CollectionChip: ({ name }: { name: string }) => <div>chip:{name}</div> }));
vi.mock('@/components/modals/CollectionPicker', () => ({
  CollectionPicker: (props: { open: boolean; selectedCollectionIds?: string[]; onSelect: (ids: string[]) => void }) => {
    if (props.open) pickerProps(props.selectedCollectionIds);
    return props.open ? <button onClick={() => props.onSelect(['ws-agency'])}>pick</button> : null;
  },
}));
vi.mock('@/components/containers/ContainerCardViewer', () => ({ default: () => <div /> }));
vi.mock('@/hooks/useDebouncedSave', () => ({
  useDebouncedSave: () => ({ isSaving: false, lastSaved: null, resetTracking: () => {} }),
}));
vi.mock('@/api/collections', () => ({ addArtifactToCollection: vi.fn(), ...api,
                                       getCollection: vi.fn().mockResolvedValue({ name: 'x' }) }));

describe('Manage Collections', () => {
  it('ticks every container the artifact is in, workspaces included', async () => {
    render(<FloatingCardWindow artifactId="backlog" zIndex={10} onClose={() => {}} />);
    fireEvent.click(await screen.findByTitle('Collections'));
    fireEvent.click(await screen.findByText('Change'));
    await waitFor(() => expect(pickerProps).toHaveBeenCalled());
    expect(pickerProps.mock.calls[pickerProps.mock.calls.length - 1]?.[0]).toEqual(['ws-agency', 'col-1', 'col-hidden']);
  });

  it('shows the names Mantle gives, and none for a container its reader may not read', async () => {
    render(<FloatingCardWindow artifactId="backlog" zIndex={10} onClose={() => {}} />);
    fireEvent.click(await screen.findByTitle('Collections'));
    expect((await screen.findAllByText(/^chip:/)).map((n) => n.textContent)).toEqual(['chip:Agience', 'chip:Notes']);
  });

  it('sends the ticked containers and shows what Mantle answers holds it', async () => {
    const now = { id: 'backlog', root_id: 'backlog', committed_collection_ids: [], container_ids: ['ws-agency'],
                  containers: [{ id: 'ws-agency', name: 'Agience' }] };
    api.changeMemberships.mockResolvedValue({ items: [now], all: ['ws-agency'], some: [], archived: [], failed: [] });
    render(<FloatingCardWindow artifactId="backlog" zIndex={10} onClose={() => {}} />);
    fireEvent.click(await screen.findByTitle('Collections'));
    fireEvent.click(await screen.findByText('Change'));
    fireEvent.click(await screen.findByText('pick'));
    await waitFor(() => expect(patchArtifactLocally).toHaveBeenCalledWith({
      id: 'backlog', committed_collection_ids: [], container_ids: ['ws-agency'], containers: now.containers }));
    expect(api.changeMemberships).toHaveBeenCalledWith(['backlog'], { held: ['ws-agency'] });
  });
});
