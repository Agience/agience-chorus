// The narrow top bar: logo, a Search/Workspace switch, Share, Help and one More menu.
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => ({ user: { name: 'A', email: 'a@example.invalid' }, logout: vi.fn() }),
}));
vi.mock('../../../hooks/useWorkspace', () => ({ useWorkspace: () => ({ createArtifact: vi.fn() }) }));
vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-1', workspaces: [{ id: 'ws-1', name: 'Pilot' }] }),
}));
vi.mock('@/hooks/useUpgradePrompt', () => ({ useUpgradePrompt: () => {} }));
vi.mock('../../modals/SettingsModal', () => ({ default: () => null }));
vi.mock('../../modals/HelpDialog', () => ({ default: () => null }));
vi.mock('../../common/ShareDialog', () => ({ ShareDialog: () => null }));

import HeaderBar from '../MainHeader';

describe('MainHeader — narrow', () => {
  it('keeps Share and Help in the bar and switches panels', () => {
    const onChange = vi.fn();
    render(
      <MemoryRouter>
        <HeaderBar activeSource={null} narrowPanel="right" onNarrowPanelChange={onChange} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('button', { name: 'Open help' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Share workspace' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Workspace' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Search' }).getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(onChange).toHaveBeenCalledWith('left');
    // The folded icons are not in the bar itself.
    expect(screen.queryByTitle('User Menu')).toBeNull();
    expect(screen.queryByTitle('Trash')).toBeNull();
  });

  it('wide layout has no panel switch', () => {
    render(<MemoryRouter><HeaderBar activeSource={null} /></MemoryRouter>);
    expect(screen.queryByRole('group', { name: 'Panel' })).toBeNull();
  });
});
