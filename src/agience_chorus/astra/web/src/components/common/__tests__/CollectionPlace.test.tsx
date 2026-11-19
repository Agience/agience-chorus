import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import CollectionPlace from '../CollectionPlace';
import type { CollectionResponse } from '@/api/types/collection';

const base: CollectionResponse = {
  id: 'a', name: 'Notes', description: '', created_by: 'u1',
  created_time: '2026-11-03T10:00:00Z', modified_time: '2026-11-03T10:00:00Z',
};

describe('CollectionPlace', () => {
  it('shows nothing for a collection Mantle does not mark', () => {
    const { container } = render(<CollectionPlace collection={base} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the holder, whose and the day from the marks', () => {
    render(<CollectionPlace collection={{ ...base, name_shared: true, place_in: 'Clients', place_yours: true }} />);
    expect(screen.getByTestId('collection-place')).toHaveTextContent('In Clients · Yours · made 3 Nov 2026');
  });

  it('says shared with you and leaves the day out when asked', () => {
    render(<CollectionPlace collection={{ ...base, name_shared: true, place_yours: false }} withDate={false} />);
    expect(screen.getByTestId('collection-place')).toHaveTextContent(/^Shared with you$/);
  });
});
