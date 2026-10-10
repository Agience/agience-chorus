/**
 * The email-verification token is cleared from the address bar once the page has read it, and the
 * page still sends it for the steps that follow (the password prompt).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import VerifyEmail from '../VerifyEmail';

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));

vi.mock('../../api/api', () => ({
  post: (...args: unknown[]) => postMock(...args),
}));
vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ setAuthData: vi.fn() }),
}));
vi.mock('../../components/layout/AuthLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

describe('VerifyEmail token in the address bar', () => {
  beforeEach(() => {
    postMock.mockReset();
    window.history.replaceState(null, '', '/verify-email?token=secret-t1&ref=mail#top');
  });

  afterEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it('removes ?token= from the URL and keeps the other parts', async () => {
    postMock.mockResolvedValueOnce({ verified: true });
    render(
      <MemoryRouter initialEntries={['/verify-email?token=secret-t1&ref=mail']}>
        <VerifyEmail />
      </MemoryRouter>,
    );

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/auth/email/verify-confirm', { token: 'secret-t1' }));
    expect(window.location.href).not.toContain('secret-t1');
    expect(window.location.pathname).toBe('/verify-email');
    expect(window.location.search).toBe('?ref=mail');
    expect(window.location.hash).toBe('#top');
  });

  it('still sends the token with the password after the URL is cleared', async () => {
    postMock
      .mockResolvedValueOnce({ password_required: true })
      .mockResolvedValueOnce({ verified: true });
    render(
      <MemoryRouter initialEntries={['/verify-email?token=secret-t1&ref=mail']}>
        <VerifyEmail />
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'pw' } });
    expect(window.location.href).not.toContain('secret-t1');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm my email' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenLastCalledWith('/auth/email/verify-confirm', { token: 'secret-t1', password: 'pw' }),
    );
  });
});
