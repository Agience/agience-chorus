import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import type { Artifact } from '@/context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';

// Every artifact's context menu offers Links…, which opens the one Links dialog for that
// artifact's own id; no host handles it, and any type gets it, whatever actions it declares.
vi.mock('../../ui/context-menu', () => ({
  ContextMenuItem: ({ children, onClick }: { children: React.ReactNode; onClick?: (e: React.MouseEvent) => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  ContextMenuSeparator: () => <hr />,
}));
vi.mock('@/context/share/useShare', () => ({ useShare: () => null }));
let linksCtx: { openLinks: ReturnType<typeof vi.fn> } | null = null;
vi.mock('@/context/links/useLinks', () => ({ useLinks: () => linksCtx }));

import { CardContextItems } from '../CardContextItems';

const plainType = { actions: [] } as unknown as ContentTypeDefinition;
const declaredType = { actions: [{ id: 'run', label: 'Run now', states: ['live'] }] } as unknown as ContentTypeDefinition;
const coll = (state = 'live') =>
  ({ id: 'coll-3', allowed_actions: ['read', 'update', 'share'], context: JSON.stringify({ title: 'Release requests' }), state }) as unknown as Artifact;

describe('CardContextItems — Links on any artifact', () => {
  beforeEach(() => { linksCtx = { openLinks: vi.fn() }; });

  it('opens Links for this artifact by its own id, not through the host', () => {
    const onAction = vi.fn();
    render(<CardContextItems artifact={coll()} contentType={plainType} onAction={onAction} />);
    fireEvent.click(screen.getByText('Links…'));
    expect(linksCtx!.openLinks).toHaveBeenCalledWith('coll-3');
    expect(onAction).not.toHaveBeenCalled();
  });

  it('is offered on a type that declares its own actions too', () => {
    render(<CardContextItems artifact={coll()} contentType={declaredType} onAction={vi.fn()} />);
    fireEvent.click(screen.getByText('Links…'));
    expect(linksCtx!.openLinks).toHaveBeenCalledWith('coll-3');
  });

  it('is not offered for an archived artifact, nor where no Links dialog is mounted', () => {
    const { unmount } = render(<CardContextItems artifact={coll('archived')} contentType={plainType} onAction={vi.fn()} />);
    expect(screen.queryByText('Links…')).toBeNull();
    unmount();
    linksCtx = null;
    render(<CardContextItems artifact={coll()} contentType={plainType} onAction={vi.fn()} />);
    expect(screen.queryByText('Links…')).toBeNull();
  });
});
