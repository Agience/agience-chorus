import { describe, expect, it, vi } from 'vitest';

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'me-1' } }) }));

import { AuthorityRefused } from '@/api/authority';
import { inviteRefusal } from '../ShareDialog';

// FR-004 (the Tester, 2026-11-13): a new account's invite was refused for its unverified address,
// and the share dialog said nothing. It now says why, and what to do.
describe('inviteRefusal', () => {
  it('tells an unverified sender to verify their address', () => {
    const err = new AuthorityRefused(403, 'verify your email address first: an invite names its sender by their verified address');
    const why = inviteRefusal(err);
    expect(why).toMatch(/^Verify your email address before sending invites/);
    expect(why).toMatch(/sign-up email/);
  });
  it('passes any other refusal through in Origin’s words', () => {
    expect(inviteRefusal(new AuthorityRefused(403, 'you hold neither Share nor Admin on this')))
      .toBe('you hold neither Share nor Admin on this');
    expect(inviteRefusal(new AuthorityRefused(503, 'Origin has no mail configured to send it')))
      .toBe('Origin has no mail configured to send it');
  });
  it('reads an axios-style error too', () => {
    expect(inviteRefusal({ response: { status: 409, data: { detail: 'new accounts are paused' } } }))
      .toBe('new accounts are paused');
  });
});
