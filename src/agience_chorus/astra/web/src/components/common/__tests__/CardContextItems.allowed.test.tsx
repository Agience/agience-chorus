import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { Artifact } from '@/context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';

// The menu offers what Mantle allows the caller on the artifact (`allowed_actions`): Share needs
// Share; Links, Archive and Restore need Update.
vi.mock('../../ui/context-menu', () => ({
  ContextMenuItem: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
  ContextMenuSeparator: () => <hr />,
}));
vi.mock('@/context/share/useShare', () => ({ useShare: () => ({ openShare: vi.fn() }) }));
vi.mock('@/context/links/useLinks', () => ({ useLinks: () => ({ openLinks: vi.fn() }) }));

import { CardContextItems } from '../CardContextItems';

const plainType = { actions: [] } as unknown as ContentTypeDefinition;
const declaredType = { actions: [{ id: 'run', label: 'Run now', states: ['live'] }] } as unknown as ContentTypeDefinition;
const item = (allowed: string[], state = 'live') =>
  ({ id: 'n1', allowed_actions: allowed, context: '{}', content: '', state }) as unknown as Artifact;

describe('CardContextItems — offers only what Mantle allows', () => {
  it('a reader is offered no Share, Links or Archive', () => {
    render(<CardContextItems artifact={item(['read'])} contentType={plainType} onAction={vi.fn()} />);
    expect(screen.getByText('Open')).toBeInTheDocument();
    for (const label of ['Share…', 'Links…', 'Archive']) expect(screen.queryByText(label)).toBeNull();
  });

  it('an editor who may not share gets Links and Archive, not Share', () => {
    render(<CardContextItems artifact={item(['read', 'update'])} contentType={plainType} onAction={vi.fn()} />);
    expect(screen.getByText('Links…')).toBeInTheDocument();
    expect(screen.getByText('Archive')).toBeInTheDocument();
    expect(screen.queryByText('Share…')).toBeNull();
  });

  it('a reader of an archived artifact is not offered Restore', () => {
    render(<CardContextItems artifact={item(['read'], 'archived')} contentType={plainType} onAction={vi.fn()} />);
    expect(screen.queryByText('Restore')).toBeNull();
  });

  it('a type with its own actions still gates Share on Share', () => {
    render(<CardContextItems artifact={item(['read'])} contentType={declaredType} onAction={vi.fn()} />);
    expect(screen.getByText('Run now')).toBeInTheDocument();
    expect(screen.queryByText('Share…')).toBeNull();
  });
});
