import type { ReactNode } from 'react';
import { FiX, FiTag, FiFolder, FiTrash2, FiArchive, FiLogOut, FiRotateCcw } from 'react-icons/fi';
import { MoreHorizontal } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import { withoutKey } from '@/display-state/lists';

interface MultiCardToolbarProps {
  selectedCount: number;
  onArchive: () => void;
  onAddTags: () => void;
  onMove: () => void;
  onDelete: () => void;
  onDrop: () => void;
  /** Remove's full wording ("Remove from Inbox"): the hover title, and the item's text in More on a phone. */
  dropTitle?: string;
  onClear: () => void;
  /** Selection includes at least one artifact the user may delete. */
  canDelete: boolean;
  /** Selection includes at least one artifact that is not archived. */
  hasLive: boolean;
  /** Selection includes at least one archived artifact; shows Restore. */
  hasArchived?: boolean;
  onRestore?: () => void;
}

interface Action {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  title?: string;
  /** The item's text in More, where a phone has no hover title to carry it. */
  menuLabel?: string;
  danger?: boolean;
  /** Stays in the bar on a phone; the others move into More. */
  primary?: boolean;
}

const BUTTON =
  'flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap h-11 sm:h-9 px-3 text-sm font-medium rounded-full transition-colors';

/**
 * The bar for a multi-selection: each action is an icon and a one-word verb, so the bar is one row
 * at any width. Below 640 px only the first actions stay in the bar and the rest open from More.
 * In the bar, a container's name goes in the hover title; in More it is the item's text, truncated,
 * with the full text in its title.
 */
export default function MultiCardToolbar({
  selectedCount,
  onArchive,
  onAddTags,
  onMove,
  onDelete,
  onDrop,
  dropTitle,
  onClear,
  canDelete,
  hasLive,
  hasArchived = false,
  onRestore,
}: MultiCardToolbarProps) {
  const actions: Action[] = [];
  if (hasLive) actions.push({ key: 'archive', label: 'Archive', icon: <FiArchive className="w-4 h-4" />, onSelect: onArchive, primary: true });
  if (hasArchived && onRestore) actions.push({ key: 'restore', label: 'Restore', icon: <FiRotateCcw className="w-4 h-4" />, onSelect: onRestore, primary: true });
  actions.push({ key: 'tag', label: 'Tag', icon: <FiTag className="w-4 h-4" />, onSelect: onAddTags, title: 'Add tags', primary: true });
  actions.push({ key: 'collect', label: 'Collect', icon: <FiFolder className="w-4 h-4" />, onSelect: onMove, title: 'Add to collections' });
  if (hasLive) actions.push({ key: 'remove', label: 'Remove', icon: <FiLogOut className="w-4 h-4" />, onSelect: onDrop, title: dropTitle, menuLabel: dropTitle });
  if (canDelete) actions.push({ key: 'delete', label: 'Delete', icon: <FiTrash2 className="w-4 h-4" />, onSelect: onDelete, danger: true });
  const overflow = withoutKey(actions, a => Boolean(a.primary), true);

  return (
    <div className="fixed bottom-4 sm:bottom-6 inset-x-2 flex justify-center z-50 pointer-events-none">
      <div
        role="toolbar"
        aria-label={`${selectedCount} selected`}
        className="pointer-events-auto flex max-w-full items-center gap-1 px-2 sm:px-4 py-1 bg-white rounded-full shadow-lg border border-gray-200"
      >
        <span className="flex-shrink-0 whitespace-nowrap text-sm font-medium text-gray-700 px-2">
          {selectedCount}<span className="hidden sm:inline"> selected</span>
        </span>

        <div className="hidden sm:block w-px h-6 bg-gray-200 mx-1" />

        {actions.map(a => (
          <button
            key={a.key}
            type="button"
            onClick={a.onSelect}
            title={a.title}
            className={`${BUTTON} ${a.primary ? '' : 'hidden sm:flex '}${
              a.danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            {a.icon}
            {a.label}
          </button>
        ))}

        {overflow.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="More actions"
                title="More actions"
                className={`${BUTTON} sm:hidden w-11 justify-center px-0 text-gray-700 hover:bg-gray-100`}
              >
                <MoreHorizontal className="w-4 h-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="top">
              {overflow.map(a => (
                <DropdownMenuItem
                  key={a.key}
                  onSelect={a.onSelect}
                  title={a.menuLabel ?? a.title}
                  className={`min-h-11 max-w-[16rem] gap-2 ${a.danger ? 'text-red-600' : ''}`}
                >
                  {a.icon}
                  <span className="truncate">{a.menuLabel ?? a.label}</span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <div className="hidden sm:block w-px h-6 bg-gray-200 mx-1" />

        <button
          type="button"
          onClick={onClear}
          aria-label="Clear selection"
          title="Clear selection"
          className="flex flex-shrink-0 h-11 w-11 sm:h-9 sm:w-9 items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-full transition-colors"
        >
          <FiX className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
