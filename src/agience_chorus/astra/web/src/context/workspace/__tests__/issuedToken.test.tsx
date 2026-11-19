import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';

import { showIssued, takeIssued } from '../issuedToken';
import type { ConfirmOptions } from '@/context/dialog/types';

describe('issuedToken', () => {
  it('strips `issued` from the record and keeps the tokens it carried', () => {
    const { record, issued } = takeIssued({ id: 'k1', issued: { token_hash: 'agk_k1.s', empty: '' } });
    expect(record).toEqual({ id: 'k1' });
    expect(issued).toEqual({ token_hash: 'agk_k1.s' });
  });

  it('a record with no `issued`, or an empty one, carries no token', () => {
    expect(takeIssued({ id: 'k1' }).issued).toBeNull();
    expect(takeIssued({ id: 'k1', issued: {} })).toEqual({ record: { id: 'k1' }, issued: null });
  });

  it('shows each token once in the dialog', async () => {
    const confirm = vi.fn(async (_o: ConfirmOptions) => true);
    await showIssued({ confirm }, { token_hash: 'agk_k1.s' });
    expect(confirm).toHaveBeenCalledTimes(1);
    const shown = render(<>{confirm.mock.calls[0][0].customContent}</>);
    expect(shown.getByTestId('issued-token').textContent).toBe('agk_k1.s');
  });

  it('shows nothing when nothing was issued', async () => {
    const confirm = vi.fn(async (_o: ConfirmOptions) => true);
    await showIssued({ confirm }, null);
    expect(confirm).not.toHaveBeenCalled();
  });
});
