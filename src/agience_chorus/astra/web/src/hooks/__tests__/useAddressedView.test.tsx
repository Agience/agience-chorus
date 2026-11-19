// A view held in the address: opening it adds a history entry, so Back closes it.
import { describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { useAddressedFlag, useAddressedValue } from '../useAddressedView';

function Probe() {
  const [help, setHelp] = useAddressedFlag('open', 'help');
  const [layout, setLayout] = useAddressedValue<'grid' | 'list'>('layout', 'grid');
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <div>
      <span data-testid="where">{location.pathname + location.search}</span>
      <span data-testid="help">{help ? 'open' : 'closed'}</span>
      <span data-testid="layout">{layout}</span>
      <button onClick={() => setHelp(true)}>open help</button>
      <button onClick={() => setHelp(false)}>close help</button>
      <button onClick={() => setLayout('list')}>list</button>
      <button onClick={() => navigate(-1)}>back</button>
    </div>
  );
}

const at = (url: string) => render(
  <MemoryRouter initialEntries={['/ws-1', url]} initialIndex={1}>
    <Routes><Route path="/:id" element={<Probe />} /></Routes>
  </MemoryRouter>,
);

describe('useAddressedView', () => {
  it('gives an open view its own address, and Back closes it', () => {
    at('/ws-1');
    fireEvent.click(screen.getByText('open help'));
    expect(screen.getByTestId('where').textContent).toBe('/ws-1?open=help');
    expect(screen.getByTestId('help').textContent).toBe('open');
    act(() => { fireEvent.click(screen.getByText('back')); });
    expect(screen.getByTestId('help').textContent).toBe('closed');
    expect(screen.getByTestId('where').textContent).toBe('/ws-1');
  });

  it('closing a view it opened steps back over its own entry', () => {
    at('/ws-1');
    fireEvent.click(screen.getByText('open help'));
    fireEvent.click(screen.getByText('close help'));
    expect(screen.getByTestId('where').textContent).toBe('/ws-1');
    // Back again leaves for the entry before the workspace, not to Help.
    fireEvent.click(screen.getByText('back'));
    expect(screen.getByTestId('where').textContent).toBe('/ws-1');
  });

  it('opens from a linked address and closes in place', () => {
    at('/ws-1?open=help&layout=list');
    expect(screen.getByTestId('help').textContent).toBe('open');
    expect(screen.getByTestId('layout').textContent).toBe('list');
    fireEvent.click(screen.getByText('close help'));
    expect(screen.getByTestId('where').textContent).toBe('/ws-1?layout=list');
  });

  it('keeps the other views in the address', () => {
    at('/ws-1');
    fireEvent.click(screen.getByText('list'));
    fireEvent.click(screen.getByText('open help'));
    expect(screen.getByTestId('where').textContent).toBe('/ws-1?layout=list&open=help');
  });
});
