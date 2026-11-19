import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import WorkspaceDetailModal from '../WorkspaceDetailModal';

describe('WorkspaceDetailModal, creating (BUG-001: a new workspace is named first)', () => {
  it('offers the name it is given, and creates with the name typed', () => {
    const onSave = vi.fn();
    render(
      <WorkspaceDetailModal open mode="create" initial={{ name: 'Untitled workspace 2', description: '' }}
        onSave={onSave} onClose={() => {}} />,
    );
    expect(screen.getByRole('heading', { name: 'New workspace' })).toBeDefined();
    const name = screen.getByLabelText('Name') as HTMLInputElement;
    expect(name.value).toBe('Untitled workspace 2');
    fireEvent.change(name, { target: { value: 'Pilot notes' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(onSave).toHaveBeenCalledWith('Pilot notes', '');
  });

  it('creates a workspace with a blank name, left for Mantle to number', () => {
    const onSave = vi.fn();
    render(
      <WorkspaceDetailModal open mode="create" initial={{ name: '', description: '' }}
        onSave={onSave} onClose={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '   ' } });
    const create = screen.getByRole('button', { name: 'Create' }) as HTMLButtonElement;
    expect(create.disabled).toBe(false);
    fireEvent.click(create);
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});
