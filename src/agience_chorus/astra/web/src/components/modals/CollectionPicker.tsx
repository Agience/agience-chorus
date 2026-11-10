// components/modals/CollectionPicker.tsx
import { useState, useEffect, useMemo } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { FolderOpen, Plus, Search, Check, Minus } from 'lucide-react';
import { listCollections, createCollection } from '../../api/collections';
import { CollectionResponse } from '../../api/types';
import { WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';
import { useWorkspaces } from '../../hooks/useWorkspaces';
import toast from 'react-hot-toast';

interface CollectionPickerProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Callback when dialog closes */
  onClose: () => void;
  /** Called with the collections checked, and the mixed ones the person cleared (bulk only). */
  onSelect: (collectionIds: string[], clearedPartialIds: string[]) => void;
  /** Pre-selected collection IDs */
  selectedCollectionIds?: string[];
  /** Collections only some of a bulk selection belong to. They show a dash and are left alone
   *  unless changed: a click cycles some -> all -> none -> some. */
  partialCollectionIds?: string[];
  /** Allow multiple selection */
  multiple?: boolean;
  /** Dialog title */
  title?: string;
}

/**
 * CollectionPicker - Modal for selecting collections
 * 
 * Features:
 * - Search/filter collections by name
 * - Multi-select support
 * - Create new collection inline
 * - Shows collection count and created date
 * 
 * @example
 * ```tsx
 * <CollectionPicker
 *   open={isOpen}
 *   onClose={() => setIsOpen(false)}
 *   onSelect={(ids) => moveArtifactsToCollections(ids)}
 *   multiple={true}
 * />
 * ```
 */
export function CollectionPicker({
  open,
  onClose,
  onSelect,
  selectedCollectionIds = [],
  partialCollectionIds = [],
  multiple = false,
  title = 'Select Collection',
}: CollectionPickerProps) {
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set(selectedCollectionIds));
  // Mixed collections the person set to "none": removed from the selection's members on confirm.
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const partial = useMemo(() => new Set(partialCollectionIds), [partialCollectionIds]);
  const [isCreating, setIsCreating] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState('');
  const { activeWorkspaceId } = useWorkspaces();
  const [workspaceIds, setWorkspaceIds] = useState<Set<string>>(new Set());

  // Load collections when dialog opens
  useEffect(() => {
    if (open) {
      loadCollections();
      setSelected(new Set(selectedCollectionIds));
      setCleared(new Set());
      setSearchQuery('');
      setIsCreating(false);
      setNewCollectionName('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]); // Only re-run when modal opens/closes, not when selectedCollectionIds changes

  const loadCollections = async () => {
    try {
      setLoading(true);
      // The picker exists to assign artifacts into a collection, so list only
      // collections the caller can add to ('create'). Read-only platform
      // collections are excluded server-side — they are not assignable.
      // Workspaces hold artifacts as collections do, so they are offered too, after the
      // collections and marked as workspaces (BUG-014, 2026-11-10: a workspace could not be chosen).
      const [data, workspaces] = await Promise.all([
        listCollections('create'),
        listCollections('create', WORKSPACE_CONTENT_TYPE).catch(() => [] as CollectionResponse[]),
      ]);
      setWorkspaceIds(new Set(workspaces.map(w => String(w.id))));
      setCollections([...data, ...workspaces.filter(w => !data.some(c => c.id === w.id))]);
    } catch (error) {
      console.error('Failed to load collections:', error);
      toast.error('Failed to load collections');
    } finally {
      setLoading(false);
    }
  };

  // Filter collections by search query
  const filteredCollections = useMemo(() => {
    if (!searchQuery) return collections;
    const query = searchQuery.toLowerCase();
    return collections.filter(c => 
      (c.name || '').toLowerCase().includes(query) || 
      c.description?.toLowerCase().includes(query)
    );
  }, [collections, searchQuery]);

  // Toggle selection
  const toggleSelection = (collectionId: string) => {
    if (!multiple) {
      // Single select: clear others and select this one
      setSelected(new Set([collectionId]));
    } else {
      // Multi-select: toggle; a mixed collection cycles some -> all -> none -> some.
      if (partial.has(collectionId)) {
        const nextSelected = new Set(selected);
        const nextCleared = new Set(cleared);
        if (nextSelected.has(collectionId)) {
          nextSelected.delete(collectionId);
          nextCleared.add(collectionId);
        } else if (nextCleared.has(collectionId)) {
          nextCleared.delete(collectionId);
        } else {
          nextSelected.add(collectionId);
        }
        setSelected(nextSelected);
        setCleared(nextCleared);
        return;
      }
      const newSelected = new Set(selected);
      if (newSelected.has(collectionId)) {
        newSelected.delete(collectionId);
      } else {
        newSelected.add(collectionId);
      }
      setSelected(newSelected);
    }
  };

  // Create new collection
  const handleCreateCollection = async () => {
    if (!newCollectionName.trim()) {
      toast.error('Collection name is required');
      return;
    }

    try {
      const newCollection = await createCollection({
        name: newCollectionName.trim(),
        description: '',
      }, activeWorkspaceId || undefined);
      
      toast.success(`Created collection "${newCollection.name}"`);
      
      // Add to list and select it
      setCollections([...collections, newCollection]);
      setSelected(new Set([newCollection.id]));
      setIsCreating(false);
      setNewCollectionName('');
    } catch (error) {
      console.error('Failed to create collection:', error);
      toast.error('Failed to create collection');
    }
  };

  // Confirm selection
  const handleConfirm = () => {
    onSelect(Array.from(selected), Array.from(cleared));
    onClose();
  };

  // Format date
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {/* Search Bar */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search collections..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Collections List */}
        <div className="flex-1 overflow-y-auto border border-gray-200 rounded-lg">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <div className="text-sm text-gray-500">Loading collections...</div>
            </div>
          ) : filteredCollections.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-center px-4">
              <FolderOpen className="w-12 h-12 text-gray-300 mb-2" />
              <p className="text-sm text-gray-500">
                {searchQuery ? 'No collections match your search' : 'No collections yet'}
              </p>
              <button
                onClick={() => setIsCreating(true)}
                className="mt-2 text-sm text-blue-600 hover:text-blue-700"
              >
                Create your first collection
              </button>
            </div>
          ) : (
            <div className="divide-y divide-gray-200">
              {filteredCollections.map((collection) => {
                const isSelected = selected.has(collection.id);
                const isSome = !isSelected && partial.has(collection.id) && !cleared.has(collection.id);
                return (
                  <button
                    key={collection.id}
                    data-membership={isSelected ? 'all' : isSome ? 'some' : 'none'}
                    title={isSome ? 'Some of the selected artifacts are in this collection' : undefined}
                    onClick={() => toggleSelection(collection.id)}
                    className={`w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors ${
                      isSelected ? 'bg-blue-50' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="flex-shrink-0 mt-1">
                          {isSelected ? (
                            <div className="w-5 h-5 bg-blue-600 rounded flex items-center justify-center">
                              <Check className="w-3 h-3 text-white" />
                            </div>
                          ) : isSome ? (
                            <div className="w-5 h-5 border-2 border-blue-600 rounded flex items-center justify-center">
                              <Minus className="w-3 h-3 text-blue-600" />
                            </div>
                          ) : (
                            <div className="w-5 h-5 border-2 border-gray-300 rounded" />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <FolderOpen className="w-4 h-4 text-gray-400 flex-shrink-0" />
                            <h3 className="font-medium text-gray-900 truncate">
                              {collection.name || (workspaceIds.has(String(collection.id)) ? 'Untitled workspace' : 'Untitled collection')}
                            </h3>
                            {workspaceIds.has(String(collection.id)) && (
                              <span className="flex-shrink-0 rounded bg-purple-50 px-1.5 text-xs text-purple-700">Workspace</span>
                            )}
                          </div>
                          {collection.description && (
                            <p className="text-sm text-gray-500 mt-1 line-clamp-2">
                              {collection.description}
                            </p>
                          )}
                          <p className="text-xs text-gray-400 mt-1">
                            Created {formatDate(collection.created_time)}
                          </p>
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Create New Collection Section */}
        {isCreating ? (
          <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
            <h4 className="text-sm font-medium text-gray-900 mb-2">Create New Collection</h4>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Collection name"
                value={newCollectionName}
                onChange={(e) => setNewCollectionName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateCollection();
                  if (e.key === 'Escape') setIsCreating(false);
                }}
                autoFocus
                className="flex-1 px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                onClick={handleCreateCollection}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
              >
                Create
              </button>
              <button
                onClick={() => setIsCreating(false)}
                className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setIsCreating(true)}
            className="w-full px-4 py-2 border border-dashed border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50 hover:border-gray-400 transition-colors flex items-center justify-center gap-2"
          >
            <Plus className="w-4 h-4" />
            Create New Collection
          </button>
        )}

        {/* Footer */}
        <DialogFooter>
          <div className="flex items-center justify-between w-full">
            <div className="text-sm text-gray-500">
              {selected.size > 0 && (
                <span>{selected.size} selected</span>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={!multiple && selected.size === 0}
                className={`px-4 py-2 rounded transition-colors ${
                  !multiple && selected.size === 0
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                }`}
              >
                {multiple ? `Select ${selected.size > 0 ? `(${selected.size})` : ''}` : 'Select'}
              </button>
            </div>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
