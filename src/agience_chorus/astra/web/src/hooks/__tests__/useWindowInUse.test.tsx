import { act, render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useWindowInUse } from '../useWindowInUse';

function Probe() {
  return <span data-testid="probe">{useWindowInUse() ? 'window' : 'grid'}</span>;
}

function press(el: Element) {
  act(() => {
    el.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 2 }));   // jsdom has no PointerEvent
  });
}

describe('useWindowInUse (BUG-019)', () => {
  it('holds while the last press was inside a floating window, and ends on a press elsewhere or its close', async () => {
    const { getByTestId } = render(<Probe />);
    const grid = document.createElement('div');
    const win = document.createElement('div');
    win.setAttribute('data-floating-window', '');
    const card = document.createElement('button');
    win.appendChild(card);
    document.body.append(grid, win);
    expect(getByTestId('probe').textContent).toBe('grid');
    press(card);                                 // a right-click on a card in the window
    expect(getByTestId('probe').textContent).toBe('window');
    press(grid);
    expect(getByTestId('probe').textContent).toBe('grid');
    press(card);
    await act(async () => { win.remove(); await Promise.resolve(); });
    expect(getByTestId('probe').textContent).toBe('grid');
    grid.remove();
  });
});
