// components/browser/EmptyState.tsx
import { Inbox, Plus, FolderPlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EMPTY_STATE } from '@/constants/strings';

interface EmptyStateProps {
  type: 'no-artifacts' | 'no-search-results' | 'no-source';
  searchQuery?: string;
  onClearSearch?: () => void;
  /** Shown as "Clear filters" in the no-search-results state when filters hide every card. */
  onClearFilters?: () => void;
  /** Shown as "Create a workspace" in the no-artifacts and no-source states. */
  onCreateWorkspace?: () => void;
  /** Shown as "New card" in the no-artifacts and no-source states. */
  onCreateCard?: () => void;
  /** The empty workspace is the user's Inbox. */
  isInbox?: boolean;
}

function CreateActions({ onCreateWorkspace, onCreateCard }: Pick<EmptyStateProps, 'onCreateWorkspace' | 'onCreateCard'>) {
  if (!onCreateWorkspace && !onCreateCard) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
      {onCreateCard && (
        <Button size="sm" onClick={onCreateCard}>
          <Plus />
          {EMPTY_STATE.NEW_CARD}
        </Button>
      )}
      {onCreateWorkspace && (
        <Button size="sm" variant="outline" onClick={onCreateWorkspace}>
          <FolderPlus />
          {EMPTY_STATE.CREATE_WORKSPACE}
        </Button>
      )}
    </div>
  );
}

export default function EmptyState({
  type,
  searchQuery,
  onClearSearch,
  onClearFilters,
  onCreateWorkspace,
  onCreateCard,
  isInbox = false,
}: EmptyStateProps) {

  if (type === 'no-source') {
    return (
      <div className="flex h-full items-center justify-center px-6 py-12">
        <div className="w-full max-w-2xl rounded-2xl border border-dashed border-slate-300 bg-white px-8 py-12 text-center shadow-sm">
          <Inbox className="mx-auto mb-4 h-16 w-16 text-slate-300" />
          <p className="text-lg font-semibold text-slate-900">{EMPTY_STATE.NO_SOURCE_TITLE}</p>
          <p className="mx-auto mt-2 max-w-xl text-sm text-slate-600">
            {EMPTY_STATE.NO_SOURCE_BODY}
          </p>
          <CreateActions onCreateWorkspace={onCreateWorkspace} onCreateCard={onCreateCard} />
        </div>
      </div>
    );
  }

  if (type === 'no-search-results') {
    return (
      <div className="flex flex-col items-center justify-center h-full px-4 text-center gap-2 text-gray-500">
        <p className="font-medium">{EMPTY_STATE.NO_SEARCH_RESULTS_TITLE}</p>
        <p className="text-xs">
          {searchQuery ? EMPTY_STATE.NO_SEARCH_RESULTS_BODY(searchQuery) : EMPTY_STATE.NO_FILTER_RESULTS_BODY}
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {onClearSearch && (
            <Button size="sm" variant="outline" onClick={onClearSearch}>
              {EMPTY_STATE.CLEAR_SEARCH}
            </Button>
          )}
          {onClearFilters && (
            <Button size="sm" variant="outline" onClick={onClearFilters}>
              {EMPTY_STATE.CLEAR_FILTERS}
            </Button>
          )}
        </div>
      </div>
    );
  }

  // no-artifacts
  const body = isInbox
    ? EMPTY_STATE.NO_ARTIFACTS_INBOX_BODY
    : onCreateCard
      ? EMPTY_STATE.NO_ARTIFACTS_BODY
      : null;
  return (
    <div className="flex flex-col items-center justify-center h-full px-4 text-center gap-2 text-gray-500">
      <p className="font-medium">{EMPTY_STATE.NO_ARTIFACTS_TITLE}</p>
      {body && <p className="text-xs">{body}</p>}
      <CreateActions onCreateWorkspace={onCreateWorkspace} onCreateCard={onCreateCard} />
    </div>
  );
}
