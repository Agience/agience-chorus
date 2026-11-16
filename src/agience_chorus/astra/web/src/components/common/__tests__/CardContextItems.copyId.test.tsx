import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { Artifact } from '@/context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';

// BUG-075: every artifact's menu offers Copy ID, taken by the menu itself, never by a host: in a
// workspace, in search results, and on a type that declares its own actions.
vi.mock('../../ui/context-menu', () => ({
  ContextMenuItem: ({ children, onClick }: { children: React.ReactNode; onClick?: (e: React.MouseEvent) => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  ContextMenuSeparator: () => <hr />,
}));
vi.mock('@/context/share/useShare', () => ({ useShare: () => null }));
const toastSuccess = vi.fn();
vi.mock('sonner', () => ({ toast: { success: (...a: unknown[]) => toastSuccess(...a), error: vi.fn() } }));

import { CardContextItems } from '../CardContextItems';

const plainType = { actions: [] } as unknown as ContentTypeDefinition;
const declaredType = { actions: [{ id: 'run', label: 'Run now', states: ['live'] }] } as unknown as ContentTypeDefinition;
const note = (state = 'live') =>
  ({ id: 'note-9', context: JSON.stringify({ title: 'Meeting notes', content_type: 'text/markdown' }), state }) as unknown as Artifact;

describe('CardContextItems — Copy ID on any artifact', () => {
  let writeText: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    toastSuccess.mockClear();
  });

  it.each([
    ['in a workspace', plainType, false, 'live'],
    ['archived', plainType, false, 'archived'],
    ['in search results', plainType, true, 'live'],
    ['on a type with its own actions', declaredType, false, 'live'],
  ])('copies the artifact\'s own id %s, not through the host', async (_where, type, isSearchResult, state) => {
    const onAction = vi.fn();
    render(<CardContextItems artifact={note(state)} contentType={type} onAction={onAction}
      isSearchResult={isSearchResult} />);
    fireEvent.click(screen.getByText('Copy ID'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('note-9'));
    expect(onAction).not.toHaveBeenCalled();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('ID copied', { description: 'note-9' }));
  });
});
