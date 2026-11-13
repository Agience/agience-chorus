import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderScalarEditorForTest as editor } from '../viewer';

// G6 (the Tester, 2026-11-13): a Backlog item's state is set in its window, limited to the type's
// own values, so an item can be closed through the app.
const STATES = ['open', 'working', 'in_cut', 'validated', 'shipped', 'closed'];

describe('the record viewer’s select editor', () => {
  it('offers exactly the type’s values and reports the one chosen', () => {
    const onChange = vi.fn();
    render(editor({ id: 'state', value: 'open', onChange,
                    descriptor: { path: 'state', editor: 'select', options: STATES } }));
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(STATES);
    expect(select.value).toBe('open');
    fireEvent.change(select, { target: { value: 'closed' } });
    expect(onChange).toHaveBeenCalledWith('closed');
  });

  it('shows a stored value the list does not hold, without offering anything new to type', () => {
    render(editor({ id: 'state', value: 'legacy', onChange: vi.fn(),
                    descriptor: { path: 'state', editor: 'select', options: STATES } }));
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('legacy');
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['legacy', ...STATES]);
    expect(screen.queryByRole('textbox')).toBeNull();
  });
});
