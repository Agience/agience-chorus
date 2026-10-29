import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'u1', email: 'u@example.invalid', name: 'U' }, startLinkProvider: vi.fn(), unlinkProvider: vi.fn() }),
}));
vi.mock('../../../api/api', () => ({ get: vi.fn().mockResolvedValue({}) }));
vi.mock('../../settings/McpSettingsFrame', () => ({ default: () => null }));

import SettingsModal from '../SettingsModal';

// 2026-10-29, measured on staging: Settings was rendered inside the header, its own stacking context
// (z-20), so an open artifact window (z-40 layer) covered it. It renders into <body>.
describe('Settings', () => {
  it('renders into the document body, outside whatever holds it', () => {
    const { container } = render(<div className="z-20"><SettingsModal isOpen onClose={() => {}} /></div>);
    const overlay = screen.getByText('Settings').closest('.fixed');
    expect(overlay).not.toBeNull();
    expect(container.contains(overlay)).toBe(false);
    expect(overlay?.parentElement).toBe(document.body);
  });
});
