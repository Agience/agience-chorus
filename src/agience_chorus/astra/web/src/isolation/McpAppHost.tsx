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
import { CHAT_CONTENT_TYPE, OPERATOR_CONTENT_TYPE } from '@/utils/content-type';
import { getArtifact } from '@/api/artifacts';
import { mergeViewContext } from './mergeViewContext';

/** The document every view runs in: `public/view-host.html`, with its own CSP at the edge. */
export const VIEW_HOST = `${import.meta.env.BASE_URL}view-host.html`;

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
  /** The content types the choice may be (an argument's `x-content-types`); collections when absent. */
  content_types?: string[];
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

/** The job grant a timer's context records as the one it runs on (`job_grant.grant_id`). */
function recordedJobGrant(artifact: Artifact): string {
  const ctx = safeParseArtifactContext(artifact.context) as Record<string, unknown>;
  const grant = ctx.job_grant as { grant_id?: unknown } | undefined;
  return typeof grant?.grant_id === 'string' ? grant.grant_id : '';
}

/** An error as a person reads it: a refusal's own detail, never a transport's class name. */
function readableError(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (e instanceof Error && e.message) return e.message;
  return String(e);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface PickerResult {
  artifact_id?: string;
  /** The `role` of the request it answers, so a view with several pickers knows which one. */
  role?: string;
  title?: string;
}

export interface McpAppHostHandle {
  sendPickerResult: (result: PickerResult) => void;
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

  // The view's document is `view-host.html`, loaded from this origin into the sandboxed frame:
  // a srcdoc frame would inherit the app page's CSP (`script-src 'self'`), which refuses every
  // view's inline scripts (BUG-007, 2026-11-10: timers could not be armed, Inbox items not
  // approved). The host page runs under its own path-scoped CSP; it says it is ready, and is sent
  // the view's HTML, CSP meta tag first, to become.
  useEffect(() => {
    function onReady(event: MessageEvent) {
      const frame = iframeRef.current?.contentWindow;
      if (!frame || event.source !== frame) return;
      if (event.data?.type !== 'agience/view-host/ready') return;
      // The frame's origin is opaque (no allow-same-origin), so it cannot be named as a target.
      frame.postMessage({ type: 'agience/view-host/render', html: srcdocHtml }, '*');
    }
    window.addEventListener('message', onReady);
    return () => window.removeEventListener('message', onReady);
  }, [srcdocHtml]);

  // Expose sendPickerResult to parent via ref
  // (defined after sendNotification — hoisted within closure)
  useImperativeHandle(ref, () => ({
    sendPickerResult(result: PickerResult) {
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

      // Timers run on a job grant the person approves at Origin (John, 2026-11-10, BUG-024 and
      // BUG-035): over what the timer reaches and nothing else, never its workspace. The host shows
      // that list, opens Origin's page on the person's click, and hands Lumen the grant's id; no
      // key is issued and none passes through here. Once armed, the grant's own delegation opens
      // the person's key for the items it lists, and for nothing else.
      case 'arm_timer': {
        if (!confirmDialog) {
          sendError(req.id, -32000, 'arm_timer needs the host confirmation dialog');
          return;
        }
        if (credentialRequestPending.current) {
          sendError(req.id, -32000, 'Another approval is awaiting the user');
          return;
        }
        const ctx = safeParseArtifactContext(artifact.context) as Record<string, unknown>;
        const title = typeof ctx.title === 'string' && ctx.title ? ctx.title : 'Timer';
        credentialRequestPending.current = true;
        try {
          // Before arming, nothing opens the person's key for Lumen (John, 2026-11-10): Lumen names
          // what it needs to read, and the host reads it here, in the person's own session.
          // Only the timer's own chain is read (the timer, its target, the transforms its steps
          // name), each found here from what was read before, and only the field Lumen parses
          // (`timer`, `run`): a need for anything else reads nothing and arms nothing.
          const timerKey = String(artifact.id ?? '');
          const contexts: Record<string, Record<string, unknown>> = {};
          const chain = (): Set<string> => {
            const ids = new Set<string>([timerKey]);
            const spec = (contexts[timerKey]?.timer ?? {}) as { target?: { artifact_id?: unknown } };
            const target = spec.target?.artifact_id;
            if (typeof target === 'string' && target) {
              ids.add(target);
              const steps = ((contexts[target]?.run ?? {}) as { steps?: unknown }).steps;
              for (const step of Array.isArray(steps) ? steps : []) {
                const s = (step ?? {}) as { transform_id?: unknown; operator_id?: unknown };
                if (typeof s.transform_id === 'string' && s.transform_id && !s.operator_id) ids.add(s.transform_id);
              }
            }
            return ids;
          };
          let reach: { resources?: unknown; error?: unknown; need?: unknown } = {};
          for (let round = 0; round < 4; round++) {
            const answer = await proxyToolCall('timer_reach', { timer_id: artifact.id, contexts }, 'lumen');
            reach = JSON.parse(answer.content?.[0]?.text ?? '{}') as typeof reach;
            const need = Array.isArray(reach.need)
              ? reach.need.filter((n): n is string => typeof n === 'string' && n !== '' && !(n in contexts))
              : [];
            if (need.length === 0) break;
            const allowed = chain();
            const outside = need.find((id) => !allowed.has(id));
            if (outside) {
              reach = { error: `Lumen asked to read ${outside}, which this timer does not run; nothing was granted` };
              break;
            }
            for (const id of need) {
              const doc = id === timerKey ? artifact : await getArtifact(id);
              const ctxOf = safeParseArtifactContext(doc.context) as Record<string, unknown>;
              // A run block where the runner finds it: on the card, or under `transform` or `order`.
              const nested = (k: string) => ((ctxOf[k] ?? {}) as { run?: unknown }).run;
              contexts[id] = id === timerKey ? { timer: ctxOf.timer }
                : { run: ctxOf.run ?? nested('transform') ?? nested('order') };
            }
          }
          const resources = Array.isArray(reach.resources)
            ? reach.resources.filter((r): r is string => typeof r === 'string' && r !== '')
            : [];
          const timerId = String(artifact.id ?? '');
          if (!timerId || !resources.includes(timerId)) {
            sendError(req.id, -32000, `Arming failed: ${typeof reach.error === 'string' ? reach.error
              : 'Lumen could not say what this timer reaches'}`);
            return;
          }
          const approved = await confirmDialog.confirm({
            title: 'Arm this timer?',
            description: 'It will run on its schedule as you, reading, writing and running operations in '
              + 'these items and what they contain, and nowhere else, until you disarm it. You approve it '
              + 'at Origin, in the window that opens next.',
            customContent: (
              <pre className="max-h-48 overflow-auto rounded bg-gray-50 p-2 text-xs">
                {JSON.stringify({ reaches: resources, access: 'read, write and run' }, null, 2)}
              </pre>
            ),
            confirmLabel: 'Continue at Origin',
            tone: 'warn',
          });
          if (!approved) {
            sendError(req.id, -32000, 'You did not arm the timer');
            return;
          }
          const { approveTimerAtOrigin } = await import('@/api/jobGrants');
          const grantId = await approveTimerAtOrigin(timerId, resources, title);
          const armedAnswer = await proxyToolCall('arm_timer', { timer_id: timerId, job_grant: grantId }, 'lumen');
          const text = armedAnswer.content?.[0]?.text ?? '{}';
          const armed = JSON.parse(text) as { armed?: boolean; error?: string };
          if (!armed.armed) {
            sendError(req.id, -32000, `Arming failed: ${armed.error ?? 'Lumen did not arm it'}. The job grant `
              + 'you approved can be stopped from Origin\'s Passkeys page.');
            return;
          }
          sendResponse(req.id, {
            content: [{ type: 'text', text: JSON.stringify({ job_grant: grantId, resources }) }],
          });
        } catch (e) {
          sendError(req.id, -32000, `Arming failed: ${readableError(e)}`);
        } finally {
          credentialRequestPending.current = false;
        }
        return;
      }

      case 'disarm_timer': {
        const grantId = recordedJobGrant(artifact);
        if (!grantId) {
          sendError(req.id, -32000, 'This timer records no job grant to stop');
          return;
        }
        if (!confirmDialog) {
          sendError(req.id, -32000, 'disarm_timer needs the host confirmation dialog');
          return;
        }
        try {
          // It stops here at once; the grant is then stopped at Origin, where it was made.
          await proxyToolCall('disarm_timer', { timer_id: artifact.id }, 'lumen');
          const stop = await confirmDialog.confirm({
            title: 'Timer disarmed',
            description: 'It no longer runs. Stop the job grant it ran on at Origin too, so nothing can '
              + 'run on it again before it expires.',
            confirmLabel: 'Stop it at Origin',
            cancelLabel: 'Later',
            tone: 'warn',
          });
          let revoked = false;
          if (stop) {
            const ctx = safeParseArtifactContext(artifact.context) as Record<string, unknown>;
            const { revokeAtOrigin } = await import('@/api/jobGrants');
            await revokeAtOrigin(grantId, typeof ctx.title === 'string' ? ctx.title : 'Timer');
            revoked = true;
          }
          sendResponse(req.id, { content: [{ type: 'text', text: JSON.stringify({ disarmed: true, revoked }) }] });
        } catch (e) {
          sendError(req.id, -32000, `Disarming failed: ${readableError(e)}`);
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

      // A Chat's question, answered from the person's own notes (BUG-036, 2026-11-10): Sage's
      // grounded `ask` (retrieval under the person's grants, cited extracts or a stated refusal) on
      // the delegation the app holds for Sage. No model answers; no other view may ask.
      case 'ask_notes': {
        if (artifact.content_type !== CHAT_CONTENT_TYPE) {
          sendError(req.id, -32000, 'ask_notes answers a Chat only');
          return;
        }
        const question = typeof toolArgs.question === 'string' ? toolArgs.question.trim() : '';
        if (!question || question.length > 2000) {
          sendError(req.id, -32602, 'Ask a question of at most 2000 characters');
          return;
        }
        try {
          const workspaceId = activeWorkspaceId || artifact.collection_id || undefined;
          const result = await proxyToolCall('ask', { question, ...(workspaceId ? { workspace_id: workspaceId } : {}) },
                                             'sage', workspaceId);
          sendResponse(req.id, result);
        } catch (e) {
          sendError(req.id, -32000, `Asking failed: ${readableError(e)}`);
        }
        return;
      }

      // What a workflow's steps are, by name (BUG-045, 2026-11-10): an operator's title, description
      // and input form are sealed under its owner's key, so the persona listing them showed each as
      // "Operator". Read here, in the person's session, for operators only, and only those fields.
      case 'describe_operators': {
        const ids = Array.isArray(toolArgs.ids)
          ? [...new Set(toolArgs.ids.filter((i): i is string => typeof i === 'string' && i !== ''))]
          : [];
        if (ids.length === 0 || ids.length > 100) {
          sendError(req.id, -32602, 'describe_operators takes 1 to 100 operator ids');
          return;
        }
        const out: Record<string, { title: string; description: string; input_schema: unknown }> = {};
        await Promise.all(ids.map(async (id) => {
          try {
            const doc = await getArtifact(id);
            if (doc.content_type !== OPERATOR_CONTENT_TYPE) return;
            const c = safeParseArtifactContext(doc.context) as Record<string, unknown>;
            out[id] = {
              title: typeof c.title === 'string' ? c.title : '',
              description: typeof c.description === 'string' ? c.description.slice(0, 300) : '',
              input_schema: c.input_schema && typeof c.input_schema === 'object' ? c.input_schema : {},
            };
          } catch { /* one the person cannot read is left out */ }
        }));
        sendResponse(req.id, { content: [{ type: 'text', text: JSON.stringify({ operators: out }) }] });
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
          sendError(req.id, -32000, `Tool call failed: ${readableError(e)}`);
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
        // A new view is a new document: the frame reloads the host, which asks for it again.
        key={srcdocHtml}
        ref={iframeRef}
        src={VIEW_HOST}
        sandbox="allow-scripts"
        style={{ width: '100%', height: '100%', border: 'none', pointerEvents: 'auto' }}
        title="MCP App View"
      />
    </div>
  );
});

export default McpAppHost;
