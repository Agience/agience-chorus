import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getAccessLogMock = vi.fn();
const getCommitsMock = vi.fn();
vi.mock('@/api/history', () => ({
  getAccessLog: (...args: unknown[]) => getAccessLogMock(...args),
  getCommits: (...args: unknown[]) => getCommitsMock(...args),
}));
const listGrantsMock = vi.fn();
vi.mock('@/api/collections', () => ({
  listGrants: (...args: unknown[]) => listGrantsMock(...args),
}));
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'me-1' } }),
}));

import { HistoryPanel } from '../HistoryPanel';

const CARD = { id: 'card-1', context: '{}', content: '' } as never;
const NO_COMMITS = { items: [], total: 0, has_more: false };

describe('HistoryPanel — who reached a card, and how', () => {
  // A braced body: a hook that RETURNS a function has it run as teardown, and `mockReset` returns
  // the mock — which then called the rejecting fetch after the test and failed it.
  beforeEach(() => {
    getAccessLogMock.mockReset();
    getCommitsMock.mockReset();
    getCommitsMock.mockResolvedValue(NO_COMMITS);
    listGrantsMock.mockReset();
    listGrantsMock.mockResolvedValue([]);
  });

  it('names a reader by the name the owner gave the grant that reaches them, on the card or its record', async () => {
    getAccessLogMock.mockResolvedValue({
      artifact_id: 'card-1', total: null, has_more: false,
      items: [
        { principal_id: 'nurse-123456', action: 'read', result: 'denied', ts: '2026-10-22T09:00:00+00:00', ctx: { via: 'user' } },
        { principal_id: 'doc-7654321', action: 'read', result: 'allowed', ts: '2026-10-22T09:01:00+00:00', ctx: { via: 'user' } },
        { principal_id: 'gone-0000000', action: 'read', result: 'allowed', ts: '2026-10-22T09:02:00+00:00', ctx: { via: 'user' } },
      ],
    });
    listGrantsMock.mockImplementation(async (id: string) => (id === 'record-1'
      ? [{ grantee_id: 'doc-7654321', name: 'Dr. Patel', state: 'active' },
         { grantee_id: 'gone-0000000', name: 'Locum, ended', state: 'revoked' }]
      : [{ grantee_id: 'nurse-123456', name: 'Nurse: care plan', state: 'active' }]));
    render(<HistoryPanel artifact={{ ...(CARD as object), container_ids: ['record-1'] } as never} />);
    await waitFor(() => expect(screen.getByText('Dr. Patel (doc-7654)')).toBeTruthy());
    expect(screen.getByText('Nurse: care plan (nurse-12)')).toBeTruthy();
    expect(screen.getByText('Someone else (gone-000)')).toBeTruthy();
    expect(listGrantsMock).toHaveBeenCalledWith('card-1');
    expect(listGrantsMock).toHaveBeenCalledWith('record-1');
  });

  it("names the owner, a key and an acting persona, and marks a denial", async () => {
    getAccessLogMock.mockResolvedValue({
      artifact_id: 'card-1', total: null, has_more: false,
      items: [
        { principal_id: 'me-1', action: 'read', result: 'allowed', ts: '2026-10-19T09:00:00+00:00',
          ctx: { via: 'user' } },
        { principal_id: 'key-abcdef123', action: 'create', result: 'allowed', ts: '2026-10-19T09:01:00+00:00',
          ctx: { via: 'grant_key', grant_key_id: 'key-abcdef123' } },
        { principal_id: 'me-1', action: 'invoke', result: 'allowed', ts: '2026-10-19T09:02:00+00:00',
          ctx: { via: 'delegation', actor: 'agience-server-lumen' } },
        { principal_id: 'other-99999', action: 'update', result: 'denied', ts: '2026-10-19T09:03:00+00:00',
          ctx: { via: 'user' } },
      ],
    });
    render(<HistoryPanel artifact={CARD} />);
    await waitFor(() => expect(screen.getByTestId('history-panel')).toBeTruthy());
    expect(getAccessLogMock).toHaveBeenCalledWith('card-1');
    expect(screen.getAllByText('You').length).toBe(1);
    expect(screen.getByText('Key key-abcd')).toBeTruthy();
    expect(screen.getByText('You, through agience-server-lumen')).toBeTruthy();
    expect(screen.getByText('Someone else (other-99)')).toBeTruthy();
    expect(screen.getByText('denied').className).toContain('text-red-600');
    expect(screen.queryByTestId('history-changes')).toBeNull();
  });

  it('shows what changed in what the card holds, to someone who may read it but not its access log', async () => {
    getAccessLogMock.mockRejectedValue({ response: { status: 404 } });
    getCommitsMock.mockResolvedValue({
      total: 1, has_more: false,
      items: [{ id: 'c1', author_id: 'me-1', created_time: '2026-10-19T09:00:00+00:00',
                message: 'filed the run', adds: ['a', 'b'], removes: ['z'] }],
    });
    render(<HistoryPanel artifact={CARD} />);
    await waitFor(() => expect(screen.getByTestId('history-changes')).toBeTruthy());
    expect(screen.getByText('added 2 cards, removed 1 card — filed the run')).toBeTruthy();
    expect(screen.getByTestId('history-forbidden')).toBeTruthy();
  });

  it('tells someone who does not administer the card that only its administrators see this', async () => {
    getAccessLogMock.mockRejectedValue({ response: { status: 404 } });
    render(<HistoryPanel artifact={CARD} />);
    await waitFor(() => expect(screen.getByTestId('history-forbidden')).toBeTruthy());
  });

  it('says when the history could not be loaded', async () => {
    getAccessLogMock.mockRejectedValue({ response: { status: 500 } });
    render(<HistoryPanel artifact={CARD} />);
    await waitFor(() => expect(screen.getByText('The history could not be loaded.')).toBeTruthy());
  });
});
