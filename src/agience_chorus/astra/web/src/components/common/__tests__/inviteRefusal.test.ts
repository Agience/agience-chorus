import { describe, expect, it, vi } from 'vitest';

vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'me-1' } }) }));

import { AuthorityRefused } from '@/api/authority';
import { inviteRefusal } from '../shareText';

// FR-004: the share dialog shows why an invite was refused, in Origin's words. BUG-071: an
// unverified account cannot sign in, so the dialog has no message of its own for one; Origin's 403
// still refuses it, and its words pass through.
describe('inviteRefusal', () => {
  it('passes the unverified-sender 403 through in Origin\u2019s words', () => {
    const detail = 'verify your email address first: an invite names its sender by their verified address';
    expect(inviteRefusal(new AuthorityRefused(403, detail))).toBe(detail);
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
