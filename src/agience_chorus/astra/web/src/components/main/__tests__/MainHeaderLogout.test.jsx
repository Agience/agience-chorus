// src/components/main/__tests__/MainHeaderLogout.test.jsx
//
// The header's Logout goes through the auth provider's `logout`, which as a service provider also
// ends the IdP's session. 2026-10-11: it removed the token and reloaded on its own, so Origin
// handed a new token to the reload and the person was signed straight back in. The browser journey
// `agience-cloud/e2e/journeys/journey_single_sign_on.py` found it; this pins the wiring.
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const logout = vi.fn();
vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => ({ user: { name: 'A', email: 'a@example.invalid' }, logout }),
}));
vi.mock('../../../hooks/useWorkspace', () => ({ useWorkspace: () => ({ createArtifact: vi.fn() }) }));
vi.mock('@/hooks/useWorkspaces', () => ({ useWorkspaces: () => ({ activeWorkspaceId: null }) }));
vi.mock('@/hooks/useUpgradePrompt', () => ({ useUpgradePrompt: () => {} }));
vi.mock('../../modals/SettingsModal', () => ({ default: () => null }));
vi.mock('../../modals/HelpDialog', () => ({ default: () => null }));
vi.mock('../../common/ShareDialog', () => ({ ShareDialog: () => null }));

import HeaderBar from '../MainHeader';

describe('MainHeader — Logout', () => {
  it('signs out through the auth provider', () => {
    render(<MemoryRouter><HeaderBar activeSource={null} /></MemoryRouter>);
    fireEvent.click(screen.getByTitle('User Menu'));
    fireEvent.click(screen.getByText('Logout'));
    expect(logout).toHaveBeenCalledTimes(1);
  });
});
