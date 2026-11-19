/**
 * CardContextItems
 *
 * Type-driven context menu content for any artifact. Used inside all artifact shells
 * (CardGridItem, CardListItem, CardTreeItem) and the FloatingCardWindow header.
 *
 * Action resolution priority:
 *   1. contentType.actions[] — explicit actions declared in presentation.json
 *   2. State-based defaults — used for any content type with no declared actions
 *
 * Hosts (Browser, WorkspacePanel, …) supply handlers via the `onAction` callback.
 * The action `id` string is passed to `onAction`; hosts map it to the correct
 * async operation (dangerConfirm + service call).
 */
import React, { useContext } from 'react';
import {
  FiTrash2 as TrashIcon,
  FiArrowDownRight as RemoveIcon,
  FiArchive as ArchiveIcon,
  FiShare2 as ShareIcon,
  FiRefreshCcw as RestoreIcon,
  FiEye as OpenIcon,
  FiPlus as AddIcon,
  FiFolder as CollectionIcon,
  FiExternalLink as TabIcon,
  FiCopy as CopyIcon,
  FiLink as LinkIcon,
} from 'react-icons/fi';
import { copyId } from '@/utils/copyId';
import {
  ContextMenuItem,
  ContextMenuSeparator,
} from '../ui/context-menu';
import type { Artifact } from '../../context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';
import { useLockedActions } from '@/context/view/useLockedActions';
import { allows } from '@/utils/artifact-permissions';
import { useCurrentUserId } from '@/hooks/useCurrentUserId';
import { WorkspacesContext } from '@/context/workspaces/WorkspacesContext';
import { safeParseArtifactContext } from '@/utils/artifactContext';
import { WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';

import { useShare } from '@/context/share/useShare';
import { useLinks } from '@/context/links/useLinks';

// ─── Public API ───────────────────────────────────────────────────────────────

/** Well-known action IDs understood by all artifact hosts. */
export type CardActionId =
  | 'open'
  | 'open-tab'
  | 'delete'
  | 'remove'
  | 'archive'
  | 'restore'
  | 'add-to-workspace'
  | 'assign-collections'
  | 'share'
  | 'links'
  | 'copy-id';

export interface CardContextItemsProps {
  artifact: Artifact;
  contentType: ContentTypeDefinition;
  /** Called when the user activates a menu item. */
  onAction: (actionId: CardActionId | string, artifact: Artifact) => void;
  /** Whether the artifact is being shown as a search result (affects available actions). */
  isSearchResult?: boolean;
  /** Optional override for the default remove label in host-specific contexts. */
  removeLabel?: string;
  /**
   * The host destroys the artifact when it receives the `delete` action. Without it, Delete is
   * never offered: a host whose remove handler only drops the card from its own list would turn a
   * "Delete" into something else.
   */
  deleteEnabled?: boolean;
}

// ─── Default state-based actions (fallback) ───────────────────────────────────

interface DefaultAction {
  id: CardActionId;
  label: string;
  icon: React.ElementType;
  /** Artifact states where this action is available. Empty = all. */
  states: string[];
  /** Offered only when this also holds. */
  when?: (artifact: Artifact, userId: string | null, deleteEnabled: boolean, canOpenTab: boolean) => boolean;
  destructive?: boolean;
  separator?: 'before';
}

const DEFAULT_ACTIONS: DefaultAction[] = [
  // No separate Edit: Open puts the card in an editable window. 2026-10-23, a tester: Edit here only
  // selected the card, for an inline editor that is gone, so it did nothing visible.
  { id: 'open',    label: 'Open',            icon: OpenIcon,      states: [] },
  // A workspace shown as a card (in another workspace, or a card window) opens as a main tab, where
  // it can be shared. 2026-10-23, a tester found no way to share a workspace made as a card.
  { id: 'open-tab', label: 'Open as tab',    icon: TabIcon,       states: ['live'],
    when: (artifact, _userId, _deleteEnabled, canOpenTab) => canOpenTab && isWorkspaceCard(artifact) },
  { id: 'assign-collections', label: 'Assign to collections…', icon: CollectionIcon, states: [] },
  // FR-030: any artifact is shared from here, by its own id. Taken in this component, not by hosts.
  { id: 'share',   label: 'Share…',          icon: ShareIcon,     states: ['live'] },
  // Any artifact's named links are made and removed here. Taken in this component, not by hosts.
  { id: 'links',   label: 'Links…',          icon: LinkIcon,      states: ['live'] },
  // Every artifact's id can be copied, to name it to someone or to a tool (BUG-075). Taken here.
  { id: 'copy-id', label: 'Copy ID',         icon: CopyIcon,      states: [] },
  { id: 'archive', label: 'Archive',         icon: ArchiveIcon,   states: ['live'], separator: 'before' },
  { id: 'restore', label: 'Restore',         icon: RestoreIcon,   states: ['archived'] },
  { id: 'remove',  label: 'Remove from workspace', icon: RemoveIcon, states: ['live'] },
  { id: 'delete',  label: 'Delete',          icon: TrashIcon,     states: [], destructive: true,
    when: (artifact, _userId, deleteEnabled) => deleteEnabled && allows(artifact, 'delete') },
];

// The action Mantle must allow the caller on the artifact (its `allowed_actions`) before a menu
// action is offered: sharing it needs Share, and changing its links or its state needs Update.
const NEEDS: Partial<Record<string, string>> = {
  share: 'share', links: 'update', archive: 'update', restore: 'update',
};
const permitted = (artifact: Artifact, id: string) => !NEEDS[id] || allows(artifact, NEEDS[id]!);

const SEARCH_RESULT_ACTIONS: DefaultAction[] = [
  { id: 'open',            label: 'Open',                 icon: OpenIcon,     states: [] },
  { id: 'add-to-workspace', label: 'Add to workspace',   icon: AddIcon,      states: [] },
  { id: 'assign-collections', label: 'Assign to collections…', icon: CollectionIcon, states: [] },
  { id: 'copy-id',         label: 'Copy ID',              icon: CopyIcon,     states: [] },
  // 2026-10-29, a tester: an archived result could be restored only by opening it.
  { id: 'restore',         label: 'Restore',              icon: RestoreIcon,  states: ['archived'], separator: 'before' },
];

function isWorkspaceCard(artifact: Artifact): boolean {
  const declared = (artifact as { content_type?: string }).content_type
    ?? safeParseArtifactContext(artifact.context).content_type;
  return declared === WORKSPACE_CONTENT_TYPE;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function CardContextItems({
  artifact,
  contentType,
  onAction,
  isSearchResult = false,
  removeLabel,
  deleteEnabled = false,
}: CardContextItemsProps) {
  const state = artifact.state;
  const userId = useCurrentUserId();
  // Opening a tab is the workspaces' own act, not a host's, so it is taken here when offered.
  const tabs = useContext(WorkspacesContext);
  const canOpenTab = Boolean(tabs?.workspaces.some((w) => w.id === String(artifact.id)));
  const share = useShare();
  const links = useLinks();
  const locked = useLockedActions(artifact);
  const act = (actionId: CardActionId | string) => {
    if (actionId === 'open-tab' && tabs) tabs.openWorkspaceTab(String(artifact.id));
    else if (actionId === 'share' && share) share.openShare(String(artifact.id));
    else if (actionId === 'links' && links) links.openLinks(String(artifact.id));
    else if (actionId === 'copy-id') void copyId(String(artifact.id));
    else onAction(actionId, artifact);
  };

  // A content type's declared actions take precedence when present; otherwise the
  // state-based defaults below apply.
  const typeActions = contentType.actions;

  if (typeActions && typeActions.length > 0) {
    // ── Type-driven path ─────────────────────────────────────────────────────
    const applicable = typeActions.filter((a) => {
      // A declared Delete is gated the same way as the default one.
      if (a.id === 'delete' && !(deleteEnabled && allows(artifact, 'delete'))) return false;
      if (!permitted(artifact, a.id)) return false;
      if (locked.includes(a.id)) return false;
      return !a.states || a.states.length === 0 || a.states.includes(state);
    });

    return (
      <>
        {applicable.map((action) => (
          <ContextMenuItem
            key={action.id}
            onClick={(e) => {
              e.stopPropagation();
              onAction(action.id, artifact);
            }}
            className={action.destructive ? 'text-red-600 focus:text-red-600' : undefined}
          >
            <span className="mr-2 h-4 w-4 inline-flex items-center justify-center opacity-70">
              {/* The icon is a string ID from presentation.json; this path renders no icon,
                  leaving the choice of an icon-map lookup to hosts that want one. */}
            </span>
            {action.label}
          </ContextMenuItem>
        ))}
        {!applicable.some((a) => a.id === 'copy-id') && (
          <ContextMenuItem key="copy-id" onClick={(e) => { e.stopPropagation(); act('copy-id'); }}>
            <CopyIcon className="mr-2 h-4 w-4" />
            Copy ID
          </ContextMenuItem>
        )}
        {/* Share is every artifact's, whatever its type declares (FR-030). */}
        {share && state === 'live' && permitted(artifact, 'share') && !applicable.some((a) => a.id === 'share') && (
          <ContextMenuItem key="share" onClick={(e) => { e.stopPropagation(); act('share'); }}>
            <ShareIcon className="mr-2 h-4 w-4" />
            Share…
          </ContextMenuItem>
        )}
        {links && state === 'live' && permitted(artifact, 'links') && !applicable.some((a) => a.id === 'links') && (
          <ContextMenuItem key="links" onClick={(e) => { e.stopPropagation(); act('links'); }}>
            <LinkIcon className="mr-2 h-4 w-4" />
            Links…
          </ContextMenuItem>
        )}
      </>
    );
  }

  // ── State-based fallback ───────────────────────────────────────────────────
  const pool = isSearchResult ? SEARCH_RESULT_ACTIONS : DEFAULT_ACTIONS;

  const applicable = pool.filter((a) => {
    if (a.id === 'share' && !share) return false;
    if (a.id === 'links' && !links) return false;
    if (a.when && !a.when(artifact, userId, deleteEnabled, canOpenTab)) return false;
    if (!permitted(artifact, a.id)) return false;
    if (locked.includes(a.id)) return false;
    return !a.states || a.states.length === 0 || a.states.includes(state);
  });

  const items: React.ReactNode[] = [];
  applicable.forEach((action) => {
    if (action.separator === 'before' && items.length > 0) {
      items.push(<ContextMenuSeparator key={`sep-${action.id}`} />);
    }
    const Icon = action.icon;
    items.push(
      <ContextMenuItem
        key={action.id}
        onClick={(e) => {
          e.stopPropagation();
          act(action.id);
        }}
        className={action.destructive ? 'text-red-600 focus:text-red-600' : undefined}
      >
        <Icon className="mr-2 h-4 w-4" />
        {action.id === 'remove' && removeLabel ? removeLabel : action.label}
      </ContextMenuItem>,
    );
  });

  return <>{items}</>;
}

export default CardContextItems;
