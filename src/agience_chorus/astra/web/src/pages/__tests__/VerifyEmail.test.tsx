import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import VerifyEmail from '../VerifyEmail';

const { postMock, setAuthDataMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
  setAuthDataMock: vi.fn(),
}));

vi.mock('../../api/api', () => ({
  post: (...args: unknown[]) => postMock(...args),
}));

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ setAuthData: setAuthDataMock }),
}));

vi.mock('../../components/layout/AuthLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <VerifyEmail />
    </MemoryRouter>,
  );
}

describe('VerifyEmail', () => {
  beforeEach(() => {
    postMock.mockReset();
    setAuthDataMock.mockReset();
  });

  it('says "Email verified — sign in" when the server verifies without a token', async () => {
    postMock.mockResolvedValueOnce({ verified: true });
    renderAt('/verify-email?token=t1');

    expect(await screen.findByText('Email verified — sign in to continue.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login');
    expect(setAuthDataMock).not.toHaveBeenCalled();
  });

  it('treats already_verified as a friendly sign-in prompt, not an error', async () => {
    postMock.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'This email is already verified — sign in.', error: 'already_verified' } },
    });
    renderAt('/verify-email?token=t1');

    expect(await screen.findByText('This email is already verified — sign in.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText('Send a new link')).toBeNull();
  });

  it('asks for the password when the account has one, and confirms with it', async () => {
    postMock
      .mockResolvedValueOnce({ password_required: true })
      .mockRejectedValueOnce({
        response: { status: 401, data: { detail: "That password doesn't match this account." } },
      })
      .mockResolvedValueOnce({ verified: true });
    renderAt('/verify-email?token=t1');

    const field = await screen.findByLabelText('Password');
    fireEvent.change(field, { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm my email' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("doesn't match");
    expect(screen.getByLabelText('Password')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'right' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm my email' }));
    expect(await screen.findByText('Email verified — sign in to continue.')).toBeInTheDocument();
    expect(postMock).toHaveBeenLastCalledWith('/auth/email/verify-confirm', { token: 't1', password: 'right' });
  });

  it('lets the mailbox holder disown an account they did not create', async () => {
    postMock
      .mockResolvedValueOnce({ password_required: true })
      .mockResolvedValueOnce({ verified: true, password_cleared: true });
    renderAt('/verify-email?token=t1');

    fireEvent.click(await screen.findByRole('button', { name: "I didn't create this account" }));
    expect(postMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Remove the password and confirm this email as mine' }));
    expect(await screen.findByText(/Email confirmed as yours/)).toBeInTheDocument();
    expect(postMock).toHaveBeenLastCalledWith('/auth/email/verify-confirm', { token: 't1', disown: true });
    expect(setAuthDataMock).not.toHaveBeenCalled();
  });

  it('still shows an error with a resend option for an invalid link', async () => {
    postMock.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'This verification link is no longer valid. Request a new one.' } },
    });
    renderAt('/verify-email?token=t1');

    expect(await screen.findByRole('alert')).toHaveTextContent('no longer valid');
    expect(screen.getByText('Send a new link')).toBeInTheDocument();
  });
});
