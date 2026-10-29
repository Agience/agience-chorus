import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getAccessLogMock = vi.fn();
const listVersionsMock = vi.fn();
const getVersionMock = vi.fn();
const restoreVersionMock = vi.fn();
vi.mock('@/api/history', () => ({
  getAccessLog: (...args: unknown[]) => getAccessLogMock(...args),
  listVersions: (...args: unknown[]) => listVersionsMock(...args),
  getVersion: (...args: unknown[]) => getVersionMock(...args),
  restoreVersion: (...args: unknown[]) => restoreVersionMock(...args),
}));
const patchArtifactLocallyMock = vi.fn();
let editable = true;
vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({ isEditable: () => editable, patchArtifactLocally: patchArtifactLocallyMock }),
}));
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const listGrantsMock = vi.fn();
vi.mock('@/api/collections', () => ({
  listGrants: (...args: unknown[]) => listGrantsMock(...args),
}));
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'me-1' } }),
}));

import { HistoryPanel } from '../HistoryPanel';

const CARD = { id: 'card-1', context: '{}', content: '' } as never;

function renderAccess(artifact: never) {
  render(<HistoryPanel artifact={artifact} />);
  fireEvent.click(screen.getByRole('tab', { name: 'Access' }));
}

describe('HistoryPanel — who reached a card, and how', () => {
  // A braced body: a hook that RETURNS a function has it run as teardown, and `mockReset` returns
  // the mock — which then called the rejecting fetch after the test and failed it.
  beforeEach(() => {
    getAccessLogMock.mockReset();
    listGrantsMock.mockReset();
    listGrantsMock.mockResolvedValue([]);
    listVersionsMock.mockReset();
    listVersionsMock.mockResolvedValue({ artifact_id: 'card-1', items: [], total: 0, has_more: false });
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
    renderAccess({ ...(CARD as object), container_ids: ['record-1'] } as never);
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
    renderAccess(CARD);
    await waitFor(() => expect(screen.getByTestId('history-panel')).toBeTruthy());
    expect(getAccessLogMock).toHaveBeenCalledWith('card-1');
    expect(screen.getAllByText('You').length).toBe(1);
    expect(screen.getByText('Key key-abcd')).toBeTruthy();
    expect(screen.getByText('You, through agience-server-lumen')).toBeTruthy();
    expect(screen.getByText('Someone else (other-99)')).toBeTruthy();
    expect(screen.getByText('denied').className).toContain('text-red-600');
  });

  it('tells someone who does not administer the card that only its administrators see this', async () => {
    getAccessLogMock.mockRejectedValue({ response: { status: 404 } });
    renderAccess(CARD);
    await waitFor(() => expect(screen.getByTestId('history-forbidden')).toBeTruthy());
  });

  it('says when the history could not be loaded', async () => {
    getAccessLogMock.mockRejectedValue({ response: { status: 500 } });
    renderAccess(CARD);
    await waitFor(() => expect(screen.getByText('The history could not be loaded.')).toBeTruthy());
  });
});

// 2026-10-23, a tester: History showed who reached a card, and no way to an earlier version.
describe('HistoryPanel — earlier versions', () => {
  const versions = [
    { id: 'card-1', parent_id: 'card-1@b', current: true, title: 'Three', modified_time: '2026-10-27T10:02:00Z', modified_by: 'me-1' },
    { id: 'card-1@b', parent_id: 'card-1@a', current: false, title: 'Two', modified_time: '2026-10-27T10:01:00Z', modified_by: 'me-1' },
    { id: 'card-1@a', parent_id: null, current: false, title: 'One', modified_time: '2026-10-27T10:00:00Z', modified_by: 'me-1' },
  ];

  beforeEach(() => {
    editable = true;
    listGrantsMock.mockResolvedValue([]);
    getAccessLogMock.mockResolvedValue({ artifact_id: 'card-1', items: [], total: null, has_more: false });
    listVersionsMock.mockReset();
    listVersionsMock.mockResolvedValue({ artifact_id: 'card-1', items: versions, total: 3, has_more: false });
    getVersionMock.mockReset();
    getVersionMock.mockResolvedValue({ id: 'card-1@a', context: JSON.stringify({ title: 'One' }), content: 'first body' });
    restoreVersionMock.mockReset();
    restoreVersionMock.mockResolvedValue({ id: 'card-1', context: JSON.stringify({ title: 'One' }), content: 'first body' });
    patchArtifactLocallyMock.mockReset();
  });

  it('opens on Versions, shows an earlier one and restores it', async () => {
    render(<HistoryPanel artifact={CARD} />);
    await waitFor(() => expect(screen.getByTestId('versions-panel')).toBeTruthy());
    expect(screen.getByText('Current')).toBeTruthy();
    fireEvent.click(screen.getByText('One'));
    await waitFor(() => expect(screen.getByText('first body')).toBeTruthy());
    expect(getVersionMock).toHaveBeenCalledWith('card-1', 'card-1@a');
    fireEvent.click(screen.getByText('Restore this version'));
    await waitFor(() => expect(restoreVersionMock).toHaveBeenCalledWith('card-1', 'card-1@a'));
    await waitFor(() => expect(patchArtifactLocallyMock).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'card-1', content: 'first body' })));
  });

  it('offers no restore to someone who cannot change the card', async () => {
    editable = false;
    render(<HistoryPanel artifact={CARD} />);
    await waitFor(() => expect(screen.getByTestId('versions-panel')).toBeTruthy());
    fireEvent.click(screen.getByText('One'));
    await waitFor(() => expect(screen.getByText('first body')).toBeTruthy());
    expect(screen.queryByText('Restore this version')).toBeNull();
  });

  it('says there are no earlier versions yet', async () => {
    listVersionsMock.mockResolvedValue({ artifact_id: 'card-1', items: [versions[0]], total: 1, has_more: false });
    render(<HistoryPanel artifact={CARD} />);
    await waitFor(() => expect(screen.getByText(/No earlier versions yet/)).toBeTruthy());
  });
});
