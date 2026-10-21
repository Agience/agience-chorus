/**
 * Tests for the McpAppHost iframe sandbox component.
 *
 * This is the security boundary between platform code and server-owned
 * `ui://` viewers: every tool call, link click, and artifact mutation that
 * originates inside the iframe passes through this component's JSON-RPC
 * handler. A regression here could silently widen the sandbox — so these
 * tests focus on the wire contract:
 *
 *   - iframe is rendered with sandbox="allow-scripts" only (not allow-same-origin)
 *   - CSP meta tag is injected into srcdoc before the caller-supplied HTML
 *   - postMessage events from a different window are ignored (origin isolation)
 *   - ui/initialize returns the protocol version + host context
 *   - tools/call with update_artifact / create_artifact routes to the right
 *     platform helper; update_artifact writes only the hosted artifact
 *   - create_api_key / delete_api_key run only after the host's confirmation
 *     dialog approves them, delete only for the key recorded on the hosted
 *     artifact, and a new key's secret is never posted into the iframe
 *   - tools/call with an unknown tool proxies through the MCP backend
 *   - ui/open-link routes agience:// links to host callbacks, http(s) URLs
 *     through window.open, and refuses every other scheme
 *   - unknown JSON-RPC methods respond with -32601 method-not-found
 *   - ui/notifications/size-changed resizes the iframe
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, cleanup } from '@testing-library/react';
import type { ReactElement } from 'react';

import McpAppHost from '../McpAppHost';
import type { Artifact } from '@/context/workspace/workspace.types';
import { ConfirmContext } from '@/context/dialog/ConfirmContext';
import type { ConfirmOptions } from '@/context/dialog/types';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const updateArtifactMock = vi.fn();
const createArtifactMock = vi.fn();

vi.mock('@/hooks/useWorkspace', () => ({
  useWorkspace: () => ({
    updateArtifact: updateArtifactMock,
    createArtifact: createArtifactMock,
  }),
}));

vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({
    activeWorkspaceId: 'ws-1',
  }),
}));

// Dynamic imports inside the component — stubbed so we never hit axios.
const getArtifactMock = vi.fn();
vi.mock('@/api/artifacts', () => ({
  getArtifact: (...args: unknown[]) => getArtifactMock(...args),
}));

const proxyToolCallMock = vi.fn();
const createAPIKeyMock = vi.fn();
const deleteAPIKeyMock = vi.fn();

vi.mock('@/api/mcp', () => ({
  proxyToolCall: (...args: unknown[]) => proxyToolCallMock(...args),
}));
vi.mock('@/api/apiKeys', () => ({
  createKeyOver: (...args: unknown[]) => createAPIKeyMock(...args),
  deleteAPIKey: (...args: unknown[]) => deleteAPIKeyMock(...args),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeArtifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: 'art-1',
    root_id: 'art-1',
    collection_id: 'ws-1',
    context: '{"content_type":"text/html"}',
    content: 'hello',
    state: 'live',
    ...overrides,
  } as Artifact;
}

/**
 * Grab the rendered iframe and install a postMessage spy on its contentWindow.
 * Returns a helper bundle for driving the JSON-RPC handler.
 */
function wireIframe(container: HTMLElement) {
  const iframe = container.querySelector('iframe') as HTMLIFrameElement;
  expect(iframe).not.toBeNull();

  // jsdom does not provide a live contentWindow inside an unloaded iframe —
  // the component's event handler reads `event.source` and compares it to
  // `iframe.contentWindow`. We stub both ends so the check passes and we can
  // capture outgoing messages.
  const posted: Array<{ message: unknown; targetOrigin: string }> = [];
  const fakeContentWindow = {
    postMessage: (message: unknown, targetOrigin: string) => {
      posted.push({ message, targetOrigin });
    },
  };
  Object.defineProperty(iframe, 'contentWindow', {
    configurable: true,
    value: fakeContentWindow,
  });

  function dispatchFromIframe(data: unknown) {
    const event = new MessageEvent('message', {
      data,
      source: fakeContentWindow as unknown as Window,
    });
    window.dispatchEvent(event);
  }

  function dispatchFromOtherOrigin(data: unknown) {
    const otherWindow = { postMessage: vi.fn() };
    const event = new MessageEvent('message', {
      data,
      source: otherWindow as unknown as Window,
    });
    window.dispatchEvent(event);
  }

  return { iframe, posted, dispatchFromIframe, dispatchFromOtherOrigin };
}

async function nextTick() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

/** Render under a host confirmation dialog whose answers the test scripts. */
function renderWithConfirm(ui: ReactElement, answers: boolean[]) {
  const confirmMock = vi.fn(async (_options: ConfirmOptions) => answers.shift() ?? false);
  const utils = render(
    <ConfirmContext.Provider value={{ confirm: confirmMock }}>{ui}</ConfirmContext.Provider>,
  );
  return { ...utils, confirmMock };
}

function responseFor(posted: Array<{ message: unknown }>, id: number) {
  return posted.find((p) => (p.message as { id?: number }).id === id)?.message as
    | { result?: { content: Array<{ text: string }> }; error?: { code: number; message: string } }
    | undefined;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('McpAppHost', () => {
  beforeEach(() => {
    updateArtifactMock.mockReset();
    createArtifactMock.mockReset();
    proxyToolCallMock.mockReset();
    createAPIKeyMock.mockReset();
    deleteAPIKeyMock.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  describe('rendering and sandbox', () => {
    it('renders an iframe with sandbox="allow-scripts" only', () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="<p>hi</p>" />,
      );
      const iframe = container.querySelector('iframe')!;
      // Sandbox is scripts-only. Notably does not include allow-same-origin,
      // allow-top-navigation, allow-popups, or allow-forms — the security
      // boundary depends on this.
      expect(iframe.getAttribute('sandbox')).toBe('allow-scripts');
    });

    it('injects the CSP meta tag before the caller-supplied HTML inside srcdoc', () => {
      const html = '<p>viewer</p>';
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html={html} />,
      );
      const iframe = container.querySelector('iframe')!;
      const srcdoc = iframe.getAttribute('srcdoc') ?? '';
      // CSP meta tag wraps the payload.
      expect(srcdoc).toContain('<meta http-equiv="Content-Security-Policy"');
      expect(srcdoc.indexOf('<meta http-equiv="Content-Security-Policy"')).toBeLessThan(
        srcdoc.indexOf('<p>viewer</p>'),
      );
    });

    it('narrows the default CSP when caller provides csp domains', () => {
      const { container } = render(
        <McpAppHost
          artifact={makeArtifact()}
          html=""
          csp={{ connectDomains: ['https://allowed.example'] }}
        />,
      );
      const srcdoc =
        (container.querySelector('iframe') as HTMLIFrameElement).getAttribute('srcdoc') ?? '';
      expect(srcdoc).toContain('connect-src https://allowed.example');
      expect(srcdoc).not.toContain("connect-src 'none'");
    });
  });

  describe('origin isolation', () => {
    it('ignores postMessage events from a different window', () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromOtherOrigin } = wireIframe(container);
      dispatchFromOtherOrigin({ jsonrpc: '2.0', id: 1, method: 'ui/initialize' });
      // The handler must not respond to messages whose source is not the iframe's
      // contentWindow — this is the cross-origin guard.
      expect(posted).toHaveLength(0);
    });

    it('ignores non-JSON-RPC messages', () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);
      dispatchFromIframe({ hello: 'world' });
      dispatchFromIframe(null);
      dispatchFromIframe('string-payload');
      expect(posted).toHaveLength(0);
    });
  });

  describe('ui/initialize', () => {
    it('responds with protocol version and host context', async () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact({ id: 'art-99' })} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({ jsonrpc: '2.0', id: 1, method: 'ui/initialize' });
      await nextTick();

      // Two messages sent back: the response + a tool-result notification
      // with the artifact payload.
      expect(posted.length).toBeGreaterThanOrEqual(2);

      const initResponse = (posted[0].message as { result: Record<string, unknown> }).result;
      expect(initResponse.protocolVersion).toBe('2026-01-26');
      expect(initResponse.hostInfo).toMatchObject({ name: 'agience' });
      expect(initResponse.hostCapabilities).toHaveProperty('openLinks');
      expect(initResponse.hostCapabilities).toHaveProperty('serverTools');
      expect(initResponse.hostContext).toMatchObject({ platform: 'web' });
      expect(
        (initResponse.hostContext as { agience: { artifactId: string } }).agience.artifactId,
      ).toBe('art-99');
    });

    it('follows up ui/initialize with a tool-result notification carrying the artifact', async () => {
      const { container } = render(
        <McpAppHost
          artifact={makeArtifact({
            id: 'art-99',
            content: 'BODY',
            context: '{"content_type":"text/plain"}',
          })}
          html=""
        />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({ jsonrpc: '2.0', id: 1, method: 'ui/initialize' });
      await nextTick();

      const toolResult = posted.find(
        (p) =>
          (p.message as { method?: string }).method ===
          'ui/notifications/tool-result',
      );
      expect(toolResult).toBeDefined();
      const payload = JSON.parse(
        (toolResult!.message as { params: { content: Array<{ text: string }> } }).params.content[0]
          .text,
      );
      expect(payload.artifact_id).toBe('art-99');
      expect(payload.context).toEqual({ content_type: 'text/plain' });
      expect(payload.content).toBe('BODY');
    });
  });

  describe('tools/call platform tools', () => {
    it("a view's context save keeps what an operator wrote to the card while the view was open", async () => {
      // 2026-10-19, on staging: disarming a timer from its card wiped Lumen's record of its runs.
      updateArtifactMock.mockResolvedValue(undefined);
      const given = { title: 'Routine', key: { api_key_id: 'k1' } };
      getArtifactMock.mockResolvedValue({ id: 't1', context: JSON.stringify({ ...given, timer_state: { runs: 2 } }) });
      const { container } = render(
        <McpAppHost artifact={makeArtifact({ id: 't1', context: JSON.stringify(given) })} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);
      dispatchFromIframe({ jsonrpc: '2.0', id: 40, method: 'ui/initialize', params: {} });
      await waitFor(() => expect(responseFor(posted, 40)).toBeDefined());
      dispatchFromIframe({ jsonrpc: '2.0', id: 41, method: 'tools/call', params: { name: 'update_artifact',
        arguments: { id: 't1', patch: { context: JSON.stringify({ ...given, key: { api_key_id: 'k1', revoked_at: 'now' } }) } } } });
      await waitFor(() => expect(updateArtifactMock).toHaveBeenCalledTimes(1));
      expect(JSON.parse(updateArtifactMock.mock.calls[0][0].context)).toEqual({
        title: 'Routine', key: { api_key_id: 'k1', revoked_at: 'now' }, timer_state: { runs: 2 } });
    });

    it('routes update_artifact to useWorkspace.updateArtifact', async () => {
      updateArtifactMock.mockResolvedValue(undefined);
      const { container } = render(
        <McpAppHost artifact={makeArtifact({ id: 'art-1' })} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 7,
        method: 'tools/call',
        params: {
          name: 'update_artifact',
          arguments: { id: 'art-1', patch: { content: 'new' } },
        },
      });
      await waitFor(() => expect(updateArtifactMock).toHaveBeenCalledTimes(1));

      const call = updateArtifactMock.mock.calls[0][0];
      expect(call).toMatchObject({ id: 'art-1', content: 'new' });

      const response = posted.find(
        (p) => (p.message as { id?: number }).id === 7,
      );
      expect(response).toBeDefined();
      expect((response!.message as { result: unknown }).result).toEqual({
        content: [{ type: 'text', text: 'OK' }],
      });
    });

    it('update_artifact errors surface as JSON-RPC error responses', async () => {
      updateArtifactMock.mockRejectedValue(new Error('conflict'));
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 8,
        method: 'tools/call',
        params: { name: 'update_artifact', arguments: { patch: { x: 1 } } },
      });
      await waitFor(() => expect(updateArtifactMock).toHaveBeenCalled());

      const response = posted.find((p) => (p.message as { id?: number }).id === 8);
      expect(response).toBeDefined();
      const msg = response!.message as {
        error?: { code: number; message: string };
      };
      expect(msg.error).toBeDefined();
      expect(msg.error!.code).toBe(-32000);
      expect(msg.error!.message).toContain('Update failed');
    });

    it('routes create_artifact to useWorkspace.createArtifact and returns the new artifact', async () => {
      createArtifactMock.mockResolvedValue({ id: 'new-art' });
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 9,
        method: 'tools/call',
        params: {
          name: 'create_artifact',
          arguments: { content: 'x', content_type: 'text/plain' },
        },
      });
      await waitFor(() => expect(createArtifactMock).toHaveBeenCalled());

      const response = posted.find((p) => (p.message as { id?: number }).id === 9);
      const text = (
        response!.message as {
          result: { content: Array<{ text: string }> };
        }
      ).result.content[0].text;
      expect(JSON.parse(text)).toEqual({ id: 'new-art' });
    });

    it('update_artifact refuses an id other than the hosted artifact', async () => {
      updateArtifactMock.mockResolvedValue(undefined);
      const { container } = render(
        <McpAppHost artifact={makeArtifact({ id: 'art-1' })} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 14,
        method: 'tools/call',
        params: { name: 'update_artifact', arguments: { id: 'victim', patch: { content: 'x' } } },
      });
      await waitFor(() => expect(responseFor(posted, 14)).toBeDefined());

      expect(updateArtifactMock).not.toHaveBeenCalled();
      expect(responseFor(posted, 14)!.error!.code).toBe(-32000);
    });

    it('update_artifact keeps the hosted id when the patch carries its own id', async () => {
      updateArtifactMock.mockResolvedValue(undefined);
      const { container } = render(
        <McpAppHost artifact={makeArtifact({ id: 'art-1' })} html="" />,
      );
      const { dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 15,
        method: 'tools/call',
        params: { name: 'update_artifact', arguments: { patch: { id: 'victim', content: 'x' } } },
      });
      await waitFor(() => expect(updateArtifactMock).toHaveBeenCalledTimes(1));

      expect(updateArtifactMock.mock.calls[0][0]).toMatchObject({ id: 'art-1', content: 'x' });
    });
  });

  describe('tools/call credential tools', () => {
    const KEY_ARTIFACT_CONTEXT = JSON.stringify({ key: { api_key_id: 'k-own' } });

    it('create_api_key without a host confirmation dialog creates nothing', async () => {
      createAPIKeyMock.mockResolvedValue({ id: 'k-1', key: 'agc_secret' });
      const { container } = render(<McpAppHost artifact={makeArtifact()} html="" />);
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 10,
        method: 'tools/call',
        params: { name: 'create_api_key', arguments: { name: 'test' } },
      });
      await waitFor(() => expect(responseFor(posted, 10)).toBeDefined());

      expect(createAPIKeyMock).not.toHaveBeenCalled();
      expect(responseFor(posted, 10)!.error).toBeDefined();
    });

    it('create_api_key declined in the host dialog creates nothing', async () => {
      createAPIKeyMock.mockResolvedValue({ id: 'k-1', key: 'agc_secret' });
      const { container, confirmMock } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact()} html="" />,
        [false],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 16,
        method: 'tools/call',
        params: { name: 'create_api_key', arguments: { name: 'test' } },
      });
      await waitFor(() => expect(responseFor(posted, 16)).toBeDefined());

      expect(confirmMock).toHaveBeenCalledTimes(1);
      expect(createAPIKeyMock).not.toHaveBeenCalled();
      expect(responseFor(posted, 16)!.error).toBeDefined();
    });

    it('create_api_key approved shows the secret in the host and never posts it to the iframe', async () => {
      createAPIKeyMock.mockResolvedValue({ id: 'k-1', name: 'test', key: 'agc_secret' });
      const { container, confirmMock } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact()} html="" />,
        [true, true],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 17,
        method: 'tools/call',
        params: { name: 'create_api_key', arguments: { name: 'test', role: 'editor', resources: ['c-1'] } },
      });
      await waitFor(() => expect(responseFor(posted, 17)).toBeDefined());

      // The key reaches the collection the view named, at the access it chose.
      expect(createAPIKeyMock).toHaveBeenCalledWith('test', 'editor', ['c-1']);
      // The second host dialog carries the secret.
      const secretDialog = confirmMock.mock.calls[1][0];
      const shown = render(<>{secretDialog.customContent}</>);
      expect(shown.getByTestId('mcp-app-host-new-key').textContent).toBe('agc_secret');
      // Nothing that crossed into the iframe mentions it.
      expect(JSON.stringify(posted)).not.toContain('agc_secret');
      const record = JSON.parse(responseFor(posted, 17)!.result!.content[0].text);
      expect(record).toEqual({ id: 'k-1', name: 'test' });
    });

    it('delete_api_key refuses a key the hosted artifact does not record', async () => {
      deleteAPIKeyMock.mockResolvedValue(undefined);
      const { container, confirmMock } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ context: KEY_ARTIFACT_CONTEXT })} html="" />,
        [true],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 11,
        method: 'tools/call',
        params: { name: 'delete_api_key', arguments: { id: 'k-someone-else' } },
      });
      await waitFor(() => expect(responseFor(posted, 11)).toBeDefined());

      expect(confirmMock).not.toHaveBeenCalled();
      expect(deleteAPIKeyMock).not.toHaveBeenCalled();
      expect(responseFor(posted, 11)!.error).toBeDefined();
    });

    it('delete_api_key declined in the host dialog revokes nothing', async () => {
      deleteAPIKeyMock.mockResolvedValue(undefined);
      const { container } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ context: KEY_ARTIFACT_CONTEXT })} html="" />,
        [false],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 18,
        method: 'tools/call',
        params: { name: 'delete_api_key', arguments: { id: 'k-own' } },
      });
      await waitFor(() => expect(responseFor(posted, 18)).toBeDefined());

      expect(deleteAPIKeyMock).not.toHaveBeenCalled();
    });

    it('delete_api_key revokes the recorded key once the user approves', async () => {
      deleteAPIKeyMock.mockResolvedValue(undefined);
      const { container } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ context: KEY_ARTIFACT_CONTEXT })} html="" />,
        [true],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 19,
        method: 'tools/call',
        params: { name: 'delete_api_key', arguments: { id: 'k-own' } },
      });
      await waitFor(() => expect(deleteAPIKeyMock).toHaveBeenCalledWith('k-own'));
      await waitFor(() => expect(responseFor(posted, 19)!.result).toBeDefined());
    });
  });

  describe('timers', () => {
    const TIMER = JSON.stringify({ title: 'Digest', timer: { results_to: 'log-1' } });

    it('arm_timer issues a key over the workspace and its log, hands it to Lumen, and keeps it from the view', async () => {
      createAPIKeyMock.mockResolvedValue({ id: 'k9', key: 'agk_timer_secret' });
      proxyToolCallMock.mockResolvedValue({ content: [{ type: 'text', text: '{"armed": true}' }] });
      const { container } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ id: 't1', collection_id: 'ws-1', context: TIMER })} html="" />,
        [true],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);
      dispatchFromIframe({ jsonrpc: '2.0', id: 31, method: 'tools/call',
                           params: { name: 'arm_timer', arguments: { timer_id: 't1' } } });
      await waitFor(() => expect(responseFor(posted, 31)).toBeDefined());

      expect(createAPIKeyMock).toHaveBeenCalledWith('Timer: Digest', 'collaborator', ['ws-1', 'log-1']);
      expect(proxyToolCallMock).toHaveBeenCalledWith(
        'arm_timer', { timer_id: 't1', key: 'agk_timer_secret', key_id: 'k9' }, 'lumen');
      expect(JSON.stringify(posted)).not.toContain('agk_timer_secret');
      expect(JSON.parse(responseFor(posted, 31)!.result!.content[0].text)).toEqual(
        { key_id: 'k9', resources: ['ws-1', 'log-1'] });
    });

    it("arm_timer's key also reaches the Inbox a failed run is raised into, once", async () => {
      createAPIKeyMock.mockResolvedValue({ id: 'k9', key: 'agk_timer_secret' });
      proxyToolCallMock.mockResolvedValue({ content: [{ type: 'text', text: '{"armed": true}' }] });
      const ctx = JSON.stringify({ title: 'Digest', timer: { results_to: 'log-1', inbox_to: 'inbox-1' } });
      const { container } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ id: 't1', collection_id: 'ws-1', context: ctx })} html="" />,
        [true],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);
      dispatchFromIframe({ jsonrpc: '2.0', id: 35, method: 'tools/call',
                           params: { name: 'arm_timer', arguments: { timer_id: 't1' } } });
      await waitFor(() => expect(responseFor(posted, 35)).toBeDefined());
      expect(createAPIKeyMock).toHaveBeenCalledWith('Timer: Digest', 'collaborator', ['ws-1', 'log-1', 'inbox-1']);
    });

    it("arm_timer's key reaches the operators and links of the workflow it runs, as Lumen names them", async () => {
      createAPIKeyMock.mockResolvedValue({ id: 'k9', key: 'agk_timer_secret' });
      proxyToolCallMock.mockImplementation(async (name: string) => ({ content: [{ type: 'text', text:
        name === 'timer_reach' ? '{"resources": ["ws-1", "wf-1", "log-1", "op-rec", "accounts-1"]}' : '{"armed": true}' }] }));
      const { container } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ id: 't1', collection_id: 'ws-1', context: TIMER })} html="" />,
        [true],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);
      dispatchFromIframe({ jsonrpc: '2.0', id: 36, method: 'tools/call',
                           params: { name: 'arm_timer', arguments: { timer_id: 't1' } } });
      await waitFor(() => expect(responseFor(posted, 36)).toBeDefined());
      expect(proxyToolCallMock).toHaveBeenCalledWith('timer_reach', { timer_id: 't1' }, 'lumen');
      expect(createAPIKeyMock).toHaveBeenCalledWith('Timer: Digest', 'collaborator',
        ['ws-1', 'log-1', 'wf-1', 'op-rec', 'accounts-1']);
    });

    it('a timer Lumen will not arm leaves no key behind', async () => {
      createAPIKeyMock.mockResolvedValue({ id: 'k9', key: 'agk_timer_secret' });
      proxyToolCallMock.mockResolvedValue({ content: [{ type: 'text', text: '{"error": "no timers here"}' }] });
      deleteAPIKeyMock.mockResolvedValue(undefined);
      const { container } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ id: 't1', collection_id: 'ws-1', context: TIMER })} html="" />,
        [true],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);
      dispatchFromIframe({ jsonrpc: '2.0', id: 32, method: 'tools/call',
                           params: { name: 'arm_timer', arguments: { timer_id: 't1' } } });
      await waitFor(() => expect(responseFor(posted, 32)?.error).toBeDefined());
      expect(deleteAPIKeyMock).toHaveBeenCalledWith('k9');
    });

    it('disarm_timer revokes only the key the timer records', async () => {
      deleteAPIKeyMock.mockResolvedValue(undefined);
      proxyToolCallMock.mockResolvedValue({ content: [] });
      const ctx = JSON.stringify({ key: { api_key_id: 'k9' } });
      const { container } = renderWithConfirm(
        <McpAppHost artifact={makeArtifact({ id: 't1', context: ctx })} html="" />, [],
      );
      const { posted, dispatchFromIframe } = wireIframe(container);
      dispatchFromIframe({ jsonrpc: '2.0', id: 33, method: 'tools/call',
                           params: { name: 'disarm_timer', arguments: { id: 'k-other' } } });
      await waitFor(() => expect(responseFor(posted, 33)?.error).toBeDefined());
      expect(deleteAPIKeyMock).not.toHaveBeenCalled();
      dispatchFromIframe({ jsonrpc: '2.0', id: 34, method: 'tools/call',
                           params: { name: 'disarm_timer', arguments: { id: 'k9' } } });
      await waitFor(() => expect(responseFor(posted, 34)?.result).toBeDefined());
      expect(deleteAPIKeyMock).toHaveBeenCalledWith('k9');
      expect(proxyToolCallMock).toHaveBeenCalledWith('disarm_timer', { timer_id: 't1' }, 'lumen');
    });
  });

  describe('tools/call proxied tools', () => {

    it("a view's tools are called on the persona that served it", async () => {
      // 2026-10-18: every call went to the artifact's own `invoke`, which the Key type does not
      // declare, so the view's tools failed.
      proxyToolCallMock.mockResolvedValue({ content: [{ type: 'text', text: 'ok' }] });
      const { container } = render(
        <McpAppHost artifact={makeArtifact({ id: 'art-7' })} html="" resourceServer="seraph" />,
      );
      const { dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 13,
        method: 'tools/call',
        params: { name: 'list_api_keys', arguments: {} },
      });
      await waitFor(() => expect(proxyToolCallMock).toHaveBeenCalled());
      expect(proxyToolCallMock).toHaveBeenCalledWith('list_api_keys', {}, 'seraph', 'ws-1');
    });

    it('without a serving persona, unknown tools proxy through the artifact invoke endpoint', async () => {
      proxyToolCallMock.mockResolvedValue({
        content: [{ type: 'text', text: 'remote-result' }],
      });
      const { container } = render(
        <McpAppHost
          artifact={makeArtifact({ id: 'art-42' })}
          html=""
        />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 12,
        method: 'tools/call',
        params: {
          name: 'custom_tool',
          arguments: { foo: 'bar' },
        },
      });
      await waitFor(() => expect(proxyToolCallMock).toHaveBeenCalled());

      expect(proxyToolCallMock).toHaveBeenCalledWith(
        'custom_tool',
        { foo: 'bar' },
        'art-42',
        'ws-1',
      );
      const response = posted.find((p) => (p.message as { id?: number }).id === 12);
      expect(response).toBeDefined();
    });

    it('missing tool name returns -32602', async () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 13,
        method: 'tools/call',
        params: { arguments: {} },
      });
      await nextTick();

      const response = posted.find((p) => (p.message as { id?: number }).id === 13);
      expect(response).toBeDefined();
      expect((response!.message as { error: { code: number } }).error.code).toBe(-32602);
    });
  });

  describe('ui/open-link', () => {
    it('routes agience://collection/{id} to onOpenCollection', async () => {
      const onOpenCollection = vi.fn();
      const { container } = render(
        <McpAppHost
          artifact={makeArtifact()}
          html=""
          onOpenCollection={onOpenCollection}
        />,
      );
      const { dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 20,
        method: 'ui/open-link',
        params: { url: 'agience://collection/col-42' },
      });
      await nextTick();

      expect(onOpenCollection).toHaveBeenCalledWith('col-42');
    });

    it('routes external URLs through window.open with noopener noreferrer', async () => {
      const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null);
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 21,
        method: 'ui/open-link',
        params: { url: 'https://example.com/page' },
      });
      await nextTick();

      expect(windowOpen).toHaveBeenCalledWith(
        'https://example.com/page',
        '_blank',
        'noopener,noreferrer',
      );
    });

    it.each([
      'javascript:alert(document.domain)',
      'JaVaScRiPt:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'blob:https://example.com/0000',
      'file:///etc/passwd',
      '//example.com/scheme-relative',
    ])('refuses to open %s', async (url) => {
      const windowOpen = vi.spyOn(window, 'open').mockReturnValue(null);
      windowOpen.mockClear();
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({ jsonrpc: '2.0', id: 23, method: 'ui/open-link', params: { url } });
      await nextTick();

      expect(windowOpen).not.toHaveBeenCalled();
      expect(responseFor(posted, 23)!.error!.code).toBe(-32000);
      windowOpen.mockRestore();
    });

    it('missing url returns -32000 error', async () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 22,
        method: 'ui/open-link',
        params: {},
      });
      await nextTick();

      const response = posted.find((p) => (p.message as { id?: number }).id === 22);
      expect(response).toBeDefined();
      expect((response!.message as { error: { code: number } }).error.code).toBe(-32000);
    });
  });

  describe('miscellaneous RPC methods', () => {
    it('ping responds with empty result', async () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({ jsonrpc: '2.0', id: 30, method: 'ping' });
      await nextTick();

      const response = posted.find((p) => (p.message as { id?: number }).id === 30);
      expect(response).toBeDefined();
      expect((response!.message as { result: unknown }).result).toEqual({});
    });

    it('unknown method returns -32601', async () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        id: 31,
        method: 'nonexistent/method',
      });
      await nextTick();

      const response = posted.find((p) => (p.message as { id?: number }).id === 31);
      expect(response).toBeDefined();
      const msg = response!.message as { error: { code: number; message: string } };
      expect(msg.error.code).toBe(-32601);
      expect(msg.error.message).toContain('nonexistent/method');
    });

    it('ui/message / update-model-context / request-display-mode are acknowledged', async () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      for (const [idx, method] of [
        'ui/message',
        'ui/update-model-context',
        'ui/request-display-mode',
      ].entries()) {
        const id = 40 + idx;
        dispatchFromIframe({ jsonrpc: '2.0', id, method });
        await nextTick();
        const response = posted.find((p) => (p.message as { id?: number }).id === id);
        expect(response).toBeDefined();
        expect((response!.message as { result: unknown }).result).toEqual({});
      }
    });
  });

  describe('notifications', () => {
    it('size-changed resizes the iframe height', () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { iframe, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        method: 'ui/notifications/size-changed',
        params: { height: 640 },
      });

      expect(iframe.style.height).toBe('640px');
    });

    it('unknown notifications are silently ignored', () => {
      const { container } = render(
        <McpAppHost artifact={makeArtifact()} html="" />,
      );
      const { posted, dispatchFromIframe } = wireIframe(container);

      dispatchFromIframe({
        jsonrpc: '2.0',
        method: 'ui/notifications/nonexistent',
        params: {},
      });

      expect(posted).toHaveLength(0);
    });
  });
});
