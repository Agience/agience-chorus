import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import KeyValueEditor, { type JSONObject } from '../KeyValueEditor';

vi.mock('../../../hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspace: null }),
}));

const STORE_OWNED = [
  'minted_by', 'minted', 'placement', 'addressing', 'screen', 'enriched', 'caller',
  'provenance', 'provenance_history', 'provenance_evidence', 'content_key',
  'content_cas_ref', 'content_sha256', 'upload', 'processing', 'storage',
];

function contextWithEveryStoreOwnedKey(): JSONObject {
  const ctx: JSONObject = { title: 'Note', my_field: 'mine' };
  for (const key of STORE_OWNED) ctx[key] = { owned_by: 'store', key };
  return ctx;
}

// Custom rows render their key in an <input placeholder="key">.
function customRowKeys(): string[] {
  return screen.queryAllByPlaceholderText('key').map((el) => (el as HTMLInputElement).value);
}

describe('KeyValueEditor with store-owned keys', () => {
  it('offers none of them as editable rows, and keeps an ordinary custom key editable', () => {
    render(<KeyValueEditor value={contextWithEveryStoreOwnedKey()} onChange={vi.fn()} />);

    expect(customRowKeys()).toEqual(['my_field']);
  });

  it('shows them in the read-only section', () => {
    render(<KeyValueEditor value={contextWithEveryStoreOwnedKey()} onChange={vi.fn()} />);

    expect(screen.getByText('System Metadata (Read-only)')).toBeInTheDocument();
    for (const key of STORE_OWNED) {
      expect(screen.getByText(key)).toBeInTheDocument();
    }
  });

  it('passes them through unchanged when an ordinary field is edited', () => {
    const onChange = vi.fn();
    const value = contextWithEveryStoreOwnedKey();
    render(<KeyValueEditor value={value} onChange={onChange} />);

    fireEvent.change(screen.getByDisplayValue('mine'), { target: { value: 'edited' } });

    const next = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as JSONObject;
    expect(next.my_field).toBe('edited');
    for (const key of STORE_OWNED) expect(next[key]).toEqual(value[key]);
  });

  it('a custom row cannot set a store-owned key', () => {
    const onChange = vi.fn();
    render(<KeyValueEditor value={{ title: 'Note', my_field: 'mine' }} onChange={onChange} />);

    fireEvent.change(screen.getByDisplayValue('my_field'), { target: { value: 'caller' } });

    const next = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as JSONObject;
    expect('caller' in next).toBe(false);
  });
});
