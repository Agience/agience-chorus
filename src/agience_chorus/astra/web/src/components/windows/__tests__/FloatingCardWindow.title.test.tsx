// An artifact has one title, in its window header: a title stored from anywhere else shows there,
// and a long one wraps rather than being cut off.
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import FloatingCardWindow from '../FloatingCardWindow';

const store = vi.hoisted(() => ({ title: 'Plans' }));

vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({
    openedArtifacts: [], keepOpenedArtifact: () => {},
    isEditable: () => true, patchArtifactLocally: vi.fn(),
    artifacts: [{
      id: 'note', root_id: 'note', state: 'live', content: '',
      context: JSON.stringify({ title: store.title, content_type: 'text/markdown' }),
    }],
    displayedArtifacts: [], updateArtifact: vi.fn(),
  }),
}));
vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws', updateWorkspace: vi.fn(), workspaces: [] }),
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
vi.mock('@/components/containers/ContainerCardViewer', () => ({ default: () => <div /> }));
vi.mock('@/hooks/useDebouncedSave', () => ({
  useDebouncedSave: () => ({ isSaving: false, lastSaved: null, resetTracking: () => {} }),
}));
vi.mock('@/api/collections', () => ({ addArtifactToCollection: vi.fn(), changeMemberships: vi.fn(),
                                       getCollection: vi.fn().mockResolvedValue({ name: 'x' }) }));

const field = () => screen.getByLabelText('Artifact title') as HTMLTextAreaElement;

describe('the window title', () => {
  it('shows a title stored from elsewhere', () => {
    store.title = 'Plans';
    const { rerender } = render(<FloatingCardWindow artifactId="note" zIndex={1} onClose={() => {}} />);
    expect(field().value).toBe('Plans');
    store.title = 'Plans for spring';
    rerender(<FloatingCardWindow artifactId="note" zIndex={1} onClose={() => {}} />);
    expect(field().value).toBe('Plans for spring');
  });

  it('keeps what is being typed while the field has focus', () => {
    store.title = 'Plans';
    const { rerender } = render(<FloatingCardWindow artifactId="note" zIndex={1} onClose={() => {}} />);
    field().focus();
    fireEvent.change(field(), { target: { value: 'Plans for' } });
    store.title = 'Elsewhere';
    rerender(<FloatingCardWindow artifactId="note" zIndex={1} onClose={() => {}} />);
    expect(field().value).toBe('Plans for');
  });

  it('wraps a long title and keeps it on one line of text', () => {
    store.title = 'Plans';
    render(<FloatingCardWindow artifactId="note" zIndex={1} onClose={() => {}} />);
    expect(field().className).toContain('break-words');
    expect(field().className).not.toContain('truncate');
    fireEvent.change(field(), { target: { value: 'one\ntwo' } });
    expect(field().value).toBe('one two');
  });
});
