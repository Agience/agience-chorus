/**
 * McpSettingsFrame's `ui/open-link` opens http(s) URLs and refuses every other scheme, so a
 * server-owned settings page cannot have the host open a `javascript:` or `data:` URL.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';

import McpSettingsFrame from '../McpSettingsFrame';

vi.mock('@/api/mcp', () => ({
  readUiResource: vi.fn(async () => ({ html: '<p>settings</p>' })),
  proxyToolCall: vi.fn(),
}));
vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-1' }),
}));
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { id: 'u-1' } }),
}));

async function mountFrame() {
  const { container } = render(<McpSettingsFrame server="ophan" resourceUri="ui://ophan/s.html" />);
  await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());
  const iframe = container.querySelector('iframe') as HTMLIFrameElement;
  const posted: unknown[] = [];
  const fakeContentWindow = { postMessage: (message: unknown) => posted.push(message) };
  Object.defineProperty(iframe, 'contentWindow', { configurable: true, value: fakeContentWindow });
  function send(data: unknown) {
    window.dispatchEvent(
      new MessageEvent('message', { data, source: fakeContentWindow as unknown as Window }),
    );
  }
  return { posted, send };
}

describe('McpSettingsFrame ui/open-link', () => {
  let windowOpen: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    windowOpen = vi.spyOn(window, 'open').mockReturnValue(null);
    windowOpen.mockClear();
  });

  it('opens an https URL in a new tab', async () => {
    const { posted, send } = await mountFrame();
    send({ jsonrpc: '2.0', id: 1, method: 'ui/open-link', params: { href: 'https://example.com/billing' } });
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(windowOpen).toHaveBeenCalledWith('https://example.com/billing', '_blank', 'noopener,noreferrer');
  });

  it.each([
    'javascript:alert(document.domain)',
    'data:text/html,<script>alert(1)</script>',
    'file:///etc/passwd',
  ])('refuses to open %s', async (href) => {
    const { posted, send } = await mountFrame();
    send({ jsonrpc: '2.0', id: 2, method: 'ui/open-link', params: { href } });
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(windowOpen).not.toHaveBeenCalled();
    expect((posted[0] as { error?: { code: number } }).error?.code).toBe(-32000);
  });
});
