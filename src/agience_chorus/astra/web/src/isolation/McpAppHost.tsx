/**
 * McpAppHost — MCP Apps-compliant iframe host component.
 *
 * Renders a `ui://` resource (HTML View) inside a sandboxed iframe and
 * implements the host side of the MCP Apps JSON-RPC protocol over postMessage.
 *
 * Spec: https://modelcontextprotocol.io/extensions/apps/overview (SEP-1865)
 */

import { forwardRef, useCallback, useContext, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { Artifact } from '@/context/workspace/workspace.types';
import { ConfirmContext } from '@/context/dialog/ConfirmContext';
import { useWorkspace } from '@/hooks/useWorkspace';
import { useWorkspaces } from '@/hooks/useWorkspaces';
import { useArtifactContent } from '@/hooks/useArtifactContent';
import { subscribeEvents } from '@/api/events';
import { proxyToolCall } from '@/api/mcp';
import { buildHostContext } from './hostContext';
import { buildCspMetaTag } from './csp';
import { isWebUrl } from './openLink';
import { getAgienceDragPayload } from '@/dnd/agienceDrag';
import { safeParseArtifactContext } from '@/utils/artifactContext';
import { getArtifact } from '@/api/artifacts';
import { mergeViewContext } from './mergeViewContext';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface McpAppHostProps {
  /** The artifact this view is rendering. */
  artifact: Artifact;
  /** The HTML content to render (fetched from a `ui://` resource). */
  html: string;
  /** The MCP server that owns this view (from presentation.json resource_server). */
  resourceServer?: string;
  /** Optional CSP metadata from the `_meta.ui.csp` resource field. */
  csp?: CspDomains;
  /** Callback when the view requests opening an artifact. */
  onOpenArtifact?: (artifact: Artifact) => void;
  /** Callback when the view requests opening a collection. */
  onOpenCollection?: (collectionId: string) => void;
  /** Callback when the view requests a picker modal. Host opens picker and posts result back. */
  onPickerRequest?: (params: PickerRequestParams) => void;
}

export interface PickerRequestParams {
  role: string;
  multi?: boolean;
  label?: string;
}

export interface CspDomains {
  connectDomains?: string[];
  resourceDomains?: string[];
  frameDomains?: string[];
  baseUriDomains?: string[];
}

interface JsonRpcRequest {
  jsonrpc: '2.0';
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcNotification {
  jsonrpc: '2.0';
  method: string;
  params?: Record<string, unknown>;
}

/**
 * The API key ids an artifact's context records as its own: `key.api_key_id` (the key artifact
 * view) and `api_key.id` (the MCP client view).
 */
function recordedKeyIds(artifact: Artifact): string[] {
  const ctx = safeParseArtifactContext(artifact.context) as Record<string, unknown>;
  const key = ctx.key as { api_key_id?: unknown } | undefined;
  const apiKey = ctx.api_key as { id?: unknown } | undefined;
  return [key?.api_key_id, apiKey?.id].filter((v): v is string => typeof v === 'string' && v !== '');
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface McpAppHostHandle {
  sendPickerResult: (result: { artifact_id?: string }) => void;
}

const McpAppHost = forwardRef<McpAppHostHandle, McpAppHostProps>(function McpAppHost({
  artifact,
  html,
  resourceServer,
  csp,
  onOpenArtifact,
  onOpenCollection,
  onPickerRequest,
}: McpAppHostProps, ref) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const dropWrapperRef = useRef<HTMLDivElement>(null);
  const [initialized, setInitialized] = useState(false);
  const { updateArtifact, createArtifact } = useWorkspace();
  const { activeWorkspaceId } = useWorkspaces();
  // Host-owned confirmation dialog. It renders in the host document, so the sandboxed view can
  // neither see nor click it. Absent (no DialogProvider above this host), credential tools refuse.
  const confirmDialog = useContext(ConfirmContext);
  const credentialRequestPending = useRef(false);
  // The context the view was given (at initialize), and after each save the one it wrote: the base
  // a save is merged against, so what an operator wrote meanwhile is kept (`mergeViewContext`).
  const viewContextBase = useRef<Record<string, unknown> | null>(null);
  const { content: resolvedContent } = useArtifactContent(artifact);

  // Assemble the HTML with CSP meta tag injected
  const srcdocHtml = buildCspMetaTag(csp) + html;

  // Expose sendPickerResult to parent via ref
  // (defined after sendNotification — hoisted within closure)
  useImperativeHandle(ref, () => ({
    sendPickerResult(result: { artifact_id?: string }) {
      iframeRef.current?.contentWindow?.postMessage(
        { jsonrpc: '2.0', method: 'ui/notifications/picker-result', params: result },
        '*',
      );
    },
  }));

  // ------ postMessage handler ------
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      const iframe = iframeRef.current;
      if (!iframe || event.source !== iframe.contentWindow) return;

      const data = event.data;
      if (!data || data.jsonrpc !== '2.0') return;

      // JSON-RPC request (has `id` — expects response)
      if (typeof data.id === 'number') {
        handleRequest(data as JsonRpcRequest);
      }
      // JSON-RPC notification (no `id`)
      else if (typeof data.method === 'string') {
        handleNotification(data as JsonRpcNotification);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [artifact, resolvedContent, updateArtifact, createArtifact, activeWorkspaceId, onOpenArtifact, onOpenCollection, confirmDialog],
  );

  function sendResponse(id: number, result: unknown) {
    iframeRef.current?.contentWindow?.postMessage(
      { jsonrpc: '2.0', id, result },
      '*',
    );
  }

  function sendError(id: number, code: number, message: string) {
    iframeRef.current?.contentWindow?.postMessage(
      { jsonrpc: '2.0', id, error: { code, message } },
      '*',
    );
  }

  function sendNotification(method: string, params: Record<string, unknown>) {
    iframeRef.current?.contentWindow?.postMessage(
      { jsonrpc: '2.0', method, params },
      '*',
    );
  }

  function handleRequest(req: JsonRpcRequest) {
    switch (req.method) {
      case 'ui/initialize': {
        const hostContext = buildHostContext({
          artifact,
          workspaceId: activeWorkspaceId ?? '',
        });
        sendResponse(req.id, {
          protocolVersion: '2026-01-26',
          hostInfo: { name: 'agience', version: '0.1.0' },
          hostCapabilities: {
            openLinks: {},
            serverTools: {},
            logging: {},
          },
          hostContext,
        });
        setInitialized(true);

        // After initialize, send the artifact data as tool-result
        viewContextBase.current = safeParseArtifactContext(artifact.context) as Record<string, unknown>;
        sendNotification('ui/notifications/tool-result', {
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                artifact_id: artifact.id,
                context: safeParseArtifactContext(artifact.context),
                content: resolvedContent,
              }),
            },
          ],
        });
        break;
      }

      case 'tools/call': {
        handleToolCall(req);
        break;
      }

      case 'ui/open-link': {
        const url = (req.params as { url?: string })?.url;
        if (url) {
          // Check if it's an internal artifact/collection link
          if (url.startsWith('agience://artifact/') && onOpenArtifact) {
            // agience://artifact/ links have no navigation handler here; respond OK
            // without navigating.
          } else if (url.startsWith('agience://collection/') && onOpenCollection) {
            const collectionId = url.replace('agience://collection/', '');
            onOpenCollection(collectionId);
          } else if (isWebUrl(url)) {
            window.open(url, '_blank', 'noopener,noreferrer');
          } else {
            // javascript:, data:, blob:, file: and every other scheme stay closed.
            sendError(req.id, -32000, 'Only http and https links can be opened');
            break;
          }
          sendResponse(req.id, {});
        } else {
          sendError(req.id, -32000, 'Invalid URL');
        }
        break;
      }

      case 'ui/message':
      case 'ui/update-model-context':
      case 'ui/request-display-mode':
        // Acknowledged only — no host-side handling for these methods.
        sendResponse(req.id, {});
        break;

      case 'ping':
        sendResponse(req.id, {});
        break;

      case 'ui/resource-teardown':
        sendResponse(req.id, {});
        break;

      default:
        sendError(req.id, -32601, `Method not found: ${req.method}`);
    }
  }

  async function handleToolCall(req: JsonRpcRequest) {
    const params = req.params as { name?: string; arguments?: Record<string, unknown> } | undefined;
    const toolName = params?.name;
    const toolArgs = params?.arguments ?? {};

    if (!toolName) {
      sendError(req.id, -32602, 'Missing tool name');
      return;
    }

    // Handle platform tools that the host provides directly
    switch (toolName) {
      case 'update_artifact': {
        // A view edits the artifact it is hosted for and no other. The id is the host's, and it is
        // applied after the patch so a patch carrying its own `id` cannot redirect the write.
        const requestedId = toolArgs.id;
        if (requestedId !== undefined && requestedId !== null && String(requestedId) !== String(artifact.id)) {
          sendError(req.id, -32000, 'update_artifact is limited to the hosted artifact');
          return;
        }
        try {
          let patch = toolArgs.patch as Record<string, unknown> | undefined;
          if (patch && patch.context !== undefined && viewContextBase.current) {
            const fromView = safeParseArtifactContext(patch.context as string) as Record<string, unknown>;
            const stored = await getArtifact(String(artifact.id))
              .then((a) => safeParseArtifactContext((a as { context?: unknown }).context as string) as Record<string, unknown>)
              .catch(() => null);
            if (stored) {
              const merged = mergeViewContext(viewContextBase.current, stored, fromView);
              patch = { ...patch, context: typeof patch.context === 'string' ? JSON.stringify(merged) : merged };
            }
            viewContextBase.current = fromView;
          }
          if (patch) {
            await updateArtifact({ ...patch, id: artifact.id } as Parameters<typeof updateArtifact>[0]);
          }
          sendResponse(req.id, { content: [{ type: 'text', text: 'OK' }] });
        } catch (e) {
          sendError(req.id, -32000, `Update failed: ${e}`);
        }
        return;
      }

      case 'create_artifact': {
        try {
          const newArtifact = await createArtifact((toolArgs as unknown) as Parameters<typeof createArtifact>[0]);
          sendResponse(req.id, {
            content: [{ type: 'text', text: JSON.stringify(newArtifact) }],
          });
        } catch (e) {
          sendError(req.id, -32000, `Create failed: ${e}`);
        }
        return;
      }

      // Credential tools. Each runs only after the user approves it in the host's own dialog, one
      // request at a time. A new key's secret is shown in that host dialog and is never posted
      // into the view: the view receives the key's record without `key`.
      case 'create_api_key': {
        if (!confirmDialog) {
          sendError(req.id, -32000, 'create_api_key needs the host confirmation dialog');
          return;
        }
        if (credentialRequestPending.current) {
          sendError(req.id, -32000, 'Another credential request is awaiting the user');
          return;
        }
        credentialRequestPending.current = true;
        try {
          const keyName = typeof toolArgs.name === 'string' && toolArgs.name ? toolArgs.name : 'API key';
          const approved = await confirmDialog.confirm({
            title: 'Create an API key?',
            description: `This artifact's view is asking to create the API key "${keyName}" with the settings below. Anyone holding the key can act with them.`,
            customContent: (
              <pre className="max-h-48 overflow-auto rounded bg-gray-50 p-2 text-xs">
                {JSON.stringify(toolArgs, null, 2)}
              </pre>
            ),
            confirmLabel: 'Create key',
            tone: 'warn',
          });
          if (!approved) {
            sendError(req.id, -32000, 'The user declined to create an API key');
            return;
          }
          // The view names the collections the key reaches and one access level; anything it
          // did not name, the key cannot reach. 2026-10-18: the view's `scopes` and
          // `resource_filters` were passed through as they were, Mantle read neither, and every
          // key made from a Key card was a bundle that reached nothing.
          const { createKeyOver } = await import('@/api/apiKeys');
          const resources = Array.isArray(toolArgs.resources)
            ? (toolArgs.resources as unknown[]).filter((r): r is string => typeof r === 'string')
            : [];
          const role = toolArgs.role === 'editor' ? 'editor' : 'viewer';
          const created = await createKeyOver(keyName, role, resources);
          const { key: secret, ...record } = created;
          if (secret) {
            await confirmDialog.confirm({
              title: 'Copy your new API key',
              description: 'It is shown once, here, and cannot be shown again.',
              customContent: (
                <code
                  data-testid="mcp-app-host-new-key"
                  className="block select-all break-all rounded bg-gray-50 p-2 text-xs"
                >
                  {secret}
                </code>
              ),
              confirmLabel: 'Done',
              cancelLabel: 'Close',
              tone: 'warn',
            });
          }
          sendResponse(req.id, {
            content: [{ type: 'text', text: JSON.stringify(record) }],
          });
        } catch (e) {
          sendError(req.id, -32000, `Create API key failed: ${e}`);
        } finally {
          credentialRequestPending.current = false;
        }
        return;
      }

      // Timers. Arming issues a key over the timer's workspace (and where it records runs), after
      // the user approves it here, and hands the key to Lumen directly; the view gets only its id.
      case 'arm_timer': {
        if (!confirmDialog) {
          sendError(req.id, -32000, 'arm_timer needs the host confirmation dialog');
          return;
        }
        if (credentialRequestPending.current) {
          sendError(req.id, -32000, 'Another credential request is awaiting the user');
          return;
        }
        const ctx = safeParseArtifactContext(artifact.context) as Record<string, unknown>;
        const timer = (ctx.timer ?? {}) as { results_to?: unknown; inbox_to?: unknown };
        const workspace = artifact.collection_id ?? '';
        if (!workspace) {
          sendError(req.id, -32000, 'This timer is in no workspace, so there is nothing for its key to reach');
          return;
        }
        // Where it records runs and where it raises a failed run as an Inbox item are reached too.
        const resources = [workspace];
        for (const place of [timer.results_to, timer.inbox_to]) {
          if (typeof place === 'string' && place && !resources.includes(place)) resources.push(place);
        }
        credentialRequestPending.current = true;
        try {
          const approved = await confirmDialog.confirm({
            title: 'Arm this timer?',
            description: 'It will run on its schedule, reading, writing and running operations in the '
              + 'places below on a key issued to it, until you disarm it. Disarming revokes the key.',
            customContent: (
              <pre className="max-h-48 overflow-auto rounded bg-gray-50 p-2 text-xs">
                {JSON.stringify({ reaches: resources, access: 'read, write and run' }, null, 2)}
              </pre>
            ),
            confirmLabel: 'Arm timer',
            tone: 'warn',
          });
          if (!approved) {
            sendError(req.id, -32000, 'The user declined to arm the timer');
            return;
          }
          const { createKeyOver, deleteAPIKey } = await import('@/api/apiKeys');
          const title = typeof ctx.title === 'string' && ctx.title ? ctx.title : 'Timer';
          const created = await createKeyOver(`Timer: ${title}`, 'collaborator', resources);
          const answer = await proxyToolCall('arm_timer',
            { timer_id: artifact.id, key: created.key, key_id: created.id }, 'lumen');
          const text = answer.content?.[0]?.text ?? '{}';
          const armed = JSON.parse(text) as { armed?: boolean; error?: string };
          if (!armed.armed) {
            await deleteAPIKey(created.id).catch(() => undefined);
            sendError(req.id, -32000, `Arming failed: ${armed.error ?? text}`);
            return;
          }
          sendResponse(req.id, {
            content: [{ type: 'text', text: JSON.stringify({ key_id: created.id, resources }) }],
          });
        } catch (e) {
          sendError(req.id, -32000, `Arming failed: ${e}`);
        } finally {
          credentialRequestPending.current = false;
        }
        return;
      }

      case 'disarm_timer': {
        const keyId = typeof toolArgs.id === 'string' ? toolArgs.id : '';
        if (!keyId || !recordedKeyIds(artifact).includes(keyId)) {
          sendError(req.id, -32000, 'disarm_timer is limited to the key recorded on the hosted timer');
          return;
        }
        try {
          const { deleteAPIKey } = await import('@/api/apiKeys');
          await deleteAPIKey(keyId);
          await proxyToolCall('disarm_timer', { timer_id: artifact.id }, 'lumen').catch(() => undefined);
          sendResponse(req.id, { content: [{ type: 'text', text: 'OK' }] });
        } catch (e) {
          sendError(req.id, -32000, `Disarming failed: ${e}`);
        }
        return;
      }

      case 'delete_api_key': {
        // Only the key recorded on the hosted artifact can be revoked from its view.
        const keyId = typeof toolArgs.id === 'string' ? toolArgs.id : '';
        if (!keyId || !recordedKeyIds(artifact).includes(keyId)) {
          sendError(req.id, -32000, 'delete_api_key is limited to the key recorded on the hosted artifact');
          return;
        }
        if (!confirmDialog) {
          sendError(req.id, -32000, 'delete_api_key needs the host confirmation dialog');
          return;
        }
        if (credentialRequestPending.current) {
          sendError(req.id, -32000, 'Another credential request is awaiting the user');
          return;
        }
        credentialRequestPending.current = true;
        try {
          const approved = await confirmDialog.confirm({
            title: 'Revoke this API key?',
            description: `This artifact's view is asking to revoke the API key ${keyId}. Anything using it stops working.`,
            confirmLabel: 'Revoke key',
            tone: 'danger',
          });
          if (!approved) {
            sendError(req.id, -32000, 'The user declined to revoke the API key');
            return;
          }
          const { deleteAPIKey } = await import('@/api/apiKeys');
          await deleteAPIKey(keyId);
          sendResponse(req.id, { content: [{ type: 'text', text: 'OK' }] });
        } catch (e) {
          sendError(req.id, -32000, `Delete API key failed: ${e}`);
        } finally {
          credentialRequestPending.current = false;
        }
        return;
      }

      default: {
        // A view calls the tools of the persona that served it (`resource_server`), as an MCP App
        // calls its own server. Without one, the call goes through the artifact's own `invoke`
        // operation, which its type declares. 2026-10-18: every call went to the artifact, and a
        // type that declares no `invoke` (Key, among others) failed every tool its view called.
        try {
          const result = await proxyToolCall(
            toolName,
            toolArgs,
            resourceServer || String(artifact.id ?? ''),
            activeWorkspaceId || undefined,
          );
          sendResponse(req.id, result);
        } catch (e) {
          sendError(req.id, -32000, `Tool call failed: ${e}`);
        }
      }
    }
  }

  function handleNotification(notif: JsonRpcNotification) {
    switch (notif.method) {
      case 'ui/notifications/initialized':
        // View confirms initialization complete
        break;

      case 'ui/notifications/size-changed': {
        const { height } = (notif.params ?? {}) as { height?: number };
        if (height && iframeRef.current) {
          iframeRef.current.style.height = `${height}px`;
        }
        break;
      }

      case 'ui/open-picker': {
        const params = notif.params as unknown as PickerRequestParams;
        if (onPickerRequest) {
          onPickerRequest(params);
        }
        break;
      }

      case 'notifications/message':
        // Logging from the view
        console.debug('[McpApp]', notif.params);
        break;

      default:
        break;
    }
  }

  // ------ Lifecycle ------
  useEffect(() => {
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [handleMessage]);

  // Send host context updates when theme/dimensions change
  useEffect(() => {
    if (!initialized) return;
    const hostContext = buildHostContext({
      artifact,
      workspaceId: activeWorkspaceId ?? '',
    });
    sendNotification('ui/notifications/host-context-changed', hostContext as Record<string, unknown>);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact, activeWorkspaceId]);

  // Relay chat streaming events from the events WebSocket to the iframe
  useEffect(() => {
    if (!initialized) return;

    const unsub = subscribeEvents(
      {
        container_id: activeWorkspaceId ?? undefined,
        artifact_id: artifact.id,
        event_names: ['artifact.chat.*'],
      },
      (evt) => {
        const payload = (evt.payload ?? {}) as Record<string, unknown>;
        if (evt.event === 'artifact.chat.delta') {
          sendNotification('ui/notifications/chat-delta', payload);
        } else if (evt.event === 'artifact.chat.status') {
          sendNotification('ui/notifications/chat-status', payload);
        }
      },
    );

    return unsub;
  }, [initialized, artifact.id, activeWorkspaceId]);

  // ------ Drag-drop bridge ------
  // The iframe runs under sandbox="allow-scripts" (no allow-same-origin),
  // so DataTransfer can't cross the frame boundary natively. We forward
  // drag events from the host wrapper div to the iframe via postMessage.
  function getIframeRelativeCoords(e: React.DragEvent): { x: number; y: number } {
    const iframe = iframeRef.current;
    if (!iframe) return { x: e.clientX, y: e.clientY };
    const rect = iframe.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function handleDragEnter(e: React.DragEvent) {
    e.preventDefault();
    const payload = getAgienceDragPayload(e.dataTransfer);
    if (!payload) return;
    const coords = getIframeRelativeCoords(e);
    sendNotification('ui/notifications/drag-enter', { payload, ...coords } as Record<string, unknown>);
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    const payload = getAgienceDragPayload(e.dataTransfer);
    if (!payload) return;
    const coords = getIframeRelativeCoords(e);
    sendNotification('ui/notifications/drag-over', { payload, ...coords } as Record<string, unknown>);
  }

  function handleDragLeave(e: React.DragEvent) {
    const coords = getIframeRelativeCoords(e);
    sendNotification('ui/notifications/drag-leave', { ...coords } as Record<string, unknown>);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    const payload = getAgienceDragPayload(e.dataTransfer);
    if (!payload) return;
    const coords = getIframeRelativeCoords(e);
    sendNotification('ui/notifications/drag-drop', { payload, ...coords } as Record<string, unknown>);
  }

  return (
    <div
      ref={dropWrapperRef}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{ width: '100%', height: '100%', position: 'relative' }}
    >
      <iframe
        ref={iframeRef}
        srcDoc={srcdocHtml}
        sandbox="allow-scripts"
        style={{ width: '100%', height: '100%', border: 'none', pointerEvents: 'auto' }}
        title="MCP App View"
      />
    </div>
  );
});

export default McpAppHost;
