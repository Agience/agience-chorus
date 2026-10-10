import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';

import CreateAccountForm from '../CreateAccountForm';

// Origin's registration refuses an account without an email address, so the form must not submit
// one: the sign-up that looked complete would come back as a 400.

function Harness({ onSubmit, requireEmail }: { onSubmit: () => void; requireEmail?: boolean }) {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('someone');
  const [password, setPassword] = useState('a-long-enough-password');
  return (
    <CreateAccountForm
      email={email}
      onEmailChange={setEmail}
      requireEmail={requireEmail}
      name={name}
      onNameChange={setName}
      password={password}
      onPasswordChange={setPassword}
      onSubmit={onSubmit}
    />
  );
}

const submitButton = () => screen.getByRole('button', { name: 'Create account' });
const emailInput = () => screen.getByLabelText(/^Email/) as HTMLInputElement;

describe('CreateAccountForm email', () => {
  it('is labelled and marked as required', () => {
    render(<Harness onSubmit={vi.fn()} />);
    expect(screen.queryByText('(optional)')).toBeNull();
    expect(emailInput().required).toBe(true);
  });

  it('keeps the submit disabled until an address is entered', () => {
    render(<Harness onSubmit={vi.fn()} />);
    expect((submitButton() as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(emailInput(), { target: { value: 'not-an-address' } });
    expect((submitButton() as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(emailInput(), { target: { value: 'someone@example.com' } });
    expect((submitButton() as HTMLButtonElement).disabled).toBe(false);
  });

  it('does not submit without an address, even when the form is submitted directly', () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    fireEvent.submit(submitButton().closest('form')!);
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(emailInput(), { target: { value: 'someone@example.com' } });
    fireEvent.submit(submitButton().closest('form')!);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('stays optional where the caller opts out', () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} requireEmail={false} />);
    expect(screen.getByText('(optional)')).toBeTruthy();
    expect(emailInput().required).toBe(false);
    expect((submitButton() as HTMLButtonElement).disabled).toBe(false);
    fireEvent.submit(submitButton().closest('form')!);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
