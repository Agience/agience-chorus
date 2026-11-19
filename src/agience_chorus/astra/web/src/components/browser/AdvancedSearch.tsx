// components/browser/AdvancedSearch.tsx
import { useState, useRef, useEffect, useCallback, type RefObject } from 'react';
import { Search, X, Loader, SlidersHorizontal } from 'lucide-react';
import { 
  searchWorkspace, 
  searchCollection,
  searchGlobal,
  getWorkspaceSuggestions, 
  getCollectionSuggestions 
} from '../../api/search';
import type {
  SearchRequest,
  SearchResponse,
  SuggestionsRequest,
  SuggestionsResponse,
  TagSuggestion,
  TitleSuggestion,
} from '../../api/types/search';
import { CONTENT_TYPES } from '@/registry/content-types';
import { errorDetail } from '@/utils/errorDetail';
import { useShortcuts } from '@/context/shortcuts/useShortcuts';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';

interface AdvancedSearchProps {
  /** 'workspace', 'collection', or 'global' (searches both) */
  scope: 'workspace' | 'collection' | 'global';
  /** ID of workspace or collection to search (empty for global) */
  scopeId: string;
  /** Optional placeholder */
  placeholder?: string;
  /** Callback when search results change */
  onResults?: (results: SearchResponse) => void;
  /** Callback when search is cleared */
  onClear?: () => void;
  /** Enable/disable autocomplete suggestions */
  enableSuggestions?: boolean;
  /** Controlled sort mode (from header quick controls) */
  sortMode?: 'relevance' | 'recency';
  /** Trigger to clear the search input (increment to clear) */
  clearTrigger?: number;
  /** Increment to ask the open search again, for the query in the box. */
  refreshTrigger?: number;
  /** Compact mode for sidebar use - reduces padding and hides result count */
  compact?: boolean;
  /** For global scope, choose which sources to include. */
  globalSourceScope?: 'all' | 'collections' | 'workspaces';
}

export default function AdvancedSearch({
  scope,
  scopeId,
  placeholder = 'Search artifacts…',
  onResults,
  onClear,
  enableSuggestions = true,
  sortMode: controlledSortMode,
  clearTrigger,
  refreshTrigger,
  compact = false,
  globalSourceScope = 'all',
}: AdvancedSearchProps) {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestionsResponse>({});
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  // The panel's choices, sent with the text; Mantle writes them into the query it runs.
  const [tagFilter, setTagFilter] = useState('');
  const [tagExact, setTagExact] = useState(false);
  const [typeChoice, setTypeChoice] = useState('');
  const [exactWords, setExactWords] = useState(false);
  const [searchArchived, setSearchArchived] = useState(false);
  const [notice, setNotice] = useState('');
  // Why Apply did not search, said inside the panel, which stays open. 2026-10-23, a tester applied
  // a tag with no search text and saw nothing: the notice under the box was hidden by the row below.
  const [panelNotice, setPanelNotice] = useState('');
  useEffect(() => { setPanelNotice(''); }, [query, tagFilter, typeChoice]);
  // What was sent and what the server applied, shown under the box when the panel shaped the query.
  const [sentQuery, setSentQuery] = useState('');
  const [appliedFilters, setAppliedFilters] = useState<string[]>([]);
  // Clear filters re-runs the search once the cleared choices are in state.
  const [clearPending, setClearPending] = useState(false);
  const { registerShortcut } = useShortcuts();
  
  const sortMode = controlledSortMode ?? 'relevance';
  
  const inputRef = useRef<HTMLInputElement>(null);
  // The input row anchors both popovers, which render in the top layer so no panel clips them.
  const anchorRef = useRef<HTMLDivElement>(null);
  const keepAnchor = (e: { target: EventTarget | null; preventDefault: () => void }) => {
    if (e.target instanceof Node && anchorRef.current?.contains(e.target)) e.preventDefault();
  };
  const searchDebounceRef = useRef<NodeJS.Timeout | null>(null);
  const suggestDebounceRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  // Execute search. Resolves to Mantle's refusal, or '' when it searched.
  const executeSearch = useCallback(async (
    searchQuery: string
  ): Promise<string> => {
    const types = typeChoice ? [typeChoice] : undefined;
    setNotice('');
    setSentQuery('');
    setAppliedFilters([]);
    if (!searchQuery.trim() && !tagFilter.trim() && !types?.length) {
      setResults(null);
      if (onResults) onResults({ hits: [], total: 0, query_text: '', from: 0, size: 20 });
      if (onClear) onClear();
      return '';
    }
    
    // Cancel previous request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    
    setIsSearching(true);
    
    try {
      const request: SearchRequest = {
        query_text: searchQuery,
        exact: exactWords,
        tag: tagFilter.trim() || undefined,
        tag_exact: tagExact,
        types,
        from_: 0,
        size: 100, // Load more results for Browser display
        sort: sortMode,
        state: searchArchived ? 'archived' : 'live',
      };
      
      if (scope === 'global') {
        // Global search: searches all accessible artifacts
        const response = await searchGlobal(request);
        if (controller.signal.aborted) return '';
        setResults(response);
        setSentQuery(response.query_text);
        setAppliedFilters(response.applied_filters ?? []);
        if (onResults) onResults(response);
      } else {
        // Scoped search
        request.collection_id = scopeId;
        
        const response = scope === 'workspace'
          ? await searchWorkspace(request)
          : await searchCollection(request);
        if (controller.signal.aborted) return '';
        
        setResults(response);
        setSentQuery(response.query_text);
        setAppliedFilters(response.applied_filters ?? []);
        if (onResults) onResults(response);
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return ''; // Silently ignore cancelled requests
      }
      const refusal = errorDetail(error, 'Search failed.');
      setNotice(refusal);
      setResults({ hits: [], total: 0, query_text: '', from: 0, size: 0 });
      if (onResults) onResults({ hits: [], total: 0, query_text: '', from: 0, size: 20 });
      return refusal;
    } finally {
      if (!controller.signal.aborted) setIsSearching(false);
    }
    return '';
  }, [scope, scopeId, sortMode, onResults, onClear, exactWords, tagFilter, tagExact, typeChoice, searchArchived]);
  
  // Fetch suggestions
  const fetchSuggestions = useCallback(async (suggestQuery: string) => {
    if (!suggestQuery.trim() || !enableSuggestions) {
      setSuggestions({});
      return;
    }
    
    try {
      const request: SuggestionsRequest = {
        query_text: suggestQuery,
        limit: 8,
        types: ['tags', 'titles'],
      };
      
      if (scope !== 'global') {
        request.collection_id = scopeId;
      }
      
      const response = scope === 'workspace'
        ? await getWorkspaceSuggestions(request)
        : await getCollectionSuggestions(request);
      
      setSuggestions(response);
      setShowSuggestions(true);
    } catch (error) {
      console.error('Suggestions failed:', error);
      setSuggestions({});
    }
  }, [scope, scopeId, enableSuggestions]);
  
  // Handle query change with debouncing
  const handleQueryChange = (value: string) => {
    setQuery(value);
    
    // Clear previous timers
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (suggestDebounceRef.current) clearTimeout(suggestDebounceRef.current);
    
    // Debounce search (300ms)
    searchDebounceRef.current = setTimeout(() => {
      executeSearch(value);
    }, 300);
    
    // Debounce suggestions (200ms - faster for autocomplete feel)
    suggestDebounceRef.current = setTimeout(() => {
      fetchSuggestions(value);
    }, 200);
  };
  
  // Clearing the box ends the search: no timer or request still in flight, and no line under the box
  // that names the search it ended.
  const resetSearch = useCallback(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (suggestDebounceRef.current) clearTimeout(suggestDebounceRef.current);
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setQuery('');
    setResults(null);
    setShowSuggestions(false);
    setSuggestions({});
    setSentQuery('');
    setAppliedFilters([]);
    setNotice('');
    setIsSearching(false);
  }, []);

  // Clear search
  const handleClear = useCallback(() => {
    resetSearch();
    if (onResults) onResults({ hits: [], total: 0, query_text: '', from: 0, size: 0 });
    if (onClear) onClear();
  }, [onResults, onClear, resetSearch]);

  // Handle external clear trigger (when source changes)
  useEffect(() => {
    if (clearTrigger !== undefined && clearTrigger > 0) {
      resetSearch();
      if (inputRef.current) {
        inputRef.current.value = '';
      }
    }
  }, [clearTrigger, resetSearch]);
  
  // Ask the open search again; nothing to ask when the box is empty.
  const latestSearchRef = useRef({ query, executeSearch });
  latestSearchRef.current = { query, executeSearch };
  useEffect(() => {
    if (!refreshTrigger) return;
    const { query: open, executeSearch: ask } = latestSearchRef.current;
    if (open.trim()) ask(open);
  }, [refreshTrigger]);

  // Pagination beyond the initial results page is handled by the Browser component.
  
  // Handle suggestion click
  const handleSuggestionClick = (value: string) => {
    setQuery(value);
    setShowSuggestions(false);
    executeSearch(value);
    inputRef.current?.focus();
  };
  
  // Results render in the Browser component's artifact grid, not in a dropdown here.
  
  // Keyboard shortcuts
  useEffect(() => {
    const unregister = registerShortcut({
      id: 'search:focus-global',
      label: 'Focus global search',
      group: 'Navigation',
      groupTitle: 'Navigation',
      groupOrder: 1,
      combos: ['/'],
      handler: (event) => {
        const target = event.target as HTMLElement | null;
        if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
          return;
        }
        event.preventDefault();
        inputRef.current?.focus();
      },
      options: {
        description: 'Jump to the global search field',
      },
    });

    return unregister;
  }, [registerShortcut]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && document.activeElement === inputRef.current) {
        if (query) {
          handleClear();
        } else {
          inputRef.current?.blur();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [query, handleClear]);
  
  useEffect(() => {
    if (!clearPending) return;
    setClearPending(false);
    if (query.trim()) executeSearch(query);
  }, [clearPending, query, executeSearch]);

  // Re-search when the sort or the source scope changes
  useEffect(() => {
    if (query.trim()) {
      executeSearch(query);
    }
    // Only re-run when they change (not query or executeSearch, to avoid loops)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortMode, globalSourceScope]);
  
  const hasSuggestions = (suggestions.tags?.length ?? 0) > 0 || (suggestions.titles?.length ?? 0) > 0;
  
  return (
    <div className="relative w-full max-w-none">
      <div className="flex flex-col gap-2">
        {/* Search Input */}
        <div ref={anchorRef} className="relative">
          <Search className={`absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 ${compact ? 'h-5 w-5' : 'h-5 w-5'}`} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            onFocus={() => {
              if (hasSuggestions) setShowSuggestions(true);
            }}
            placeholder={placeholder}
            className={`w-full ${compact ? 'pl-11 pr-16 py-2.5' : 'pl-11 pr-28 py-2.5'} text-sm border border-border rounded-lg bg-white/95 shadow-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-all`}
          />
          
          {/* Right side: controls + clear */}
          <div className={`absolute right-2 top-1/2 -translate-y-1/2 flex items-center ${compact ? 'gap-1' : 'gap-1'}`}>
            {/* Result count - hidden in compact mode */}
            {results && !compact && (
              <span className="text-xs text-gray-500 px-2">
                {results.hits.length} {results.hits.length === 1 ? 'result' : 'results'}
              </span>
            )}
            
            {/* Loading spinner - hidden in compact mode */}
            {isSearching && !compact && (
              <Loader className="h-4 w-4 text-purple-500 animate-spin" />
            )}
            
            {/* Clear button (only when there's a query) — placed before filters so it's immediately accessible */}
            {query && (
              <button
                onClick={handleClear}
                className="p-1 hover:bg-gray-100 rounded transition-colors"
                title="Clear (Esc)"
              >
                <X className="h-4 w-4 text-gray-500" />
              </button>
            )}

            {/* Advanced filters toggle - always visible so users can open filters before typing */}
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className={`p-1 rounded transition-colors ${
                showAdvanced ? 'bg-purple-100 text-purple-600' : 'hover:bg-gray-100 text-gray-500'
              }`}
              title="Advanced search filters"
            >
              <SlidersHorizontal className="h-4 w-4" />
            </button>
          </div>
        </div>
        
        {notice && (
          <div role="status" className="mt-1 px-1 text-xs text-amber-700">{notice}</div>
        )}
        {/* When the panel shaped the query: what was sent, and what the server applied. */}
        {query.trim() && sentQuery && sentQuery !== query.trim() && (
          <div className="mt-1 px-1 text-xs text-gray-500 flex flex-wrap items-center gap-1" data-testid="sent-query">
            <span>Searching</span>
            <code className="rounded bg-gray-100 px-1 text-gray-700">{sentQuery}</code>
            {appliedFilters.map((f) => (
              <span key={f} className="rounded-full bg-purple-50 px-2 py-0.5 text-purple-700">{f}</span>
            ))}
          </div>
        )}

        {/* Advanced Search Panel - Drops down from search bar */}
        <Popover open={showAdvanced} onOpenChange={setShowAdvanced}>
          <PopoverAnchor virtualRef={anchorRef as RefObject<HTMLDivElement>} />
          <PopoverContent
            align="start"
            onOpenAutoFocus={(e) => e.preventDefault()}
            onInteractOutside={keepAnchor}
            className="w-[var(--radix-popover-trigger-width)] bg-white border border-gray-200 rounded-lg shadow-xl p-5"
          >
            {/* One column in the sidebar (compact), whose width it shares: two there put the tag
                field over the match options. */}
            <div className={compact ? 'grid grid-cols-1 gap-4' : 'grid grid-cols-2 gap-6'}>
              {/* Left Column */}
              <div className="space-y-4">
                {/* Tags Filter */}
                <div>
                  <label className="text-xs font-medium text-gray-700 mb-2 block">Has tag</label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="Enter tag..."
                      aria-label="Has tag"
                      value={tagFilter}
                      onChange={(e) => setTagFilter(e.target.value)}
                      className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-purple-500"
                    />
                    <select
                      aria-label="Tag match"
                      value={tagExact ? 'exact' : 'is'}
                      onChange={(e) => setTagExact(e.target.value === 'exact')}
                      className="w-32 shrink-0 px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-purple-500"
                    >
                      {/* `tag:v` matches the whole tag in any case, a comma meaning any of;
                          `tag:="v"` matches it with case and commas kept. Neither matches part of a tag. */}
                      <option value="is" title="The whole tag, in any case. Separate tags with commas to match any of them.">is (any case)</option>
                      <option value="exact" title="The whole tag, exactly as typed, including case and commas.">is exactly</option>
                    </select>
                  </div>
                </div>
                
                {/* MIME Type Filter */}
                <div>
                  <label className="text-xs font-medium text-gray-700 mb-2 block">Type</label>
                  <select
                    aria-label="Type"
                    value={typeChoice}
                    onChange={(e) => setTypeChoice(e.target.value)}
                    className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-purple-500"
                  >
                    <option value="">All types</option>
                    {CONTENT_TYPES.map((t) => (
                      <option key={t.id} value={t.content_type}>{t.label}</option>
                    ))}
                  </select>
                </div>

                {/* Live or archived: archived artifacts are in their own index segment. */}
                <div>
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={searchArchived}
                      onChange={(e) => setSearchArchived(e.target.checked)}
                      className="text-purple-600"
                    />
                    Search archived artifacts instead
                  </label>
                </div>

              </div>
              
              {/* Right Column */}
              <div className="space-y-4">

                {/* Match style (user-friendly) */}
                <div>
                  <label className="text-xs font-medium text-gray-700 mb-2 block">How should we match results?</label>
                  <div className="space-y-2">
                    <label className="flex items-start gap-2 cursor-pointer">
                      <input type="radio" name="searchType" value="smart" checked={!exactWords} onChange={() => setExactWords(false)} className="text-purple-600 mt-1" />
                      <div>
                        <div className="text-sm">Full text (recommended)</div>
                        <div className="text-xs text-gray-500">Matches the words you typed, ranked by relevance.</div>
                      </div>
                    </label>
                    <label className="flex items-start gap-2 cursor-pointer">
                      <input type="radio" name="searchType" value="exact" checked={exactWords} onChange={() => setExactWords(true)} className="text-purple-600 mt-1" />
                      <div>
                        <div className="text-sm">Exact words</div>
                        <div className="text-xs text-gray-500">Only shows results that contain the exact words you typed.</div>
                      </div>
                    </label>
                  </div>
                </div>
              </div>
            </div>
            
            {panelNotice && (
              <div role="status" className="mt-4 text-xs text-amber-700">{panelNotice}</div>
            )}

            {/* Bottom Actions */}
            <div className="flex items-center justify-between mt-6 pt-4 border-t border-gray-200">
              <button
                onClick={() => {
                  setTagFilter(''); setTagExact(false); setTypeChoice('');
                  setExactWords(false); setSearchArchived(false); setNotice('');
                  setClearPending(true);
                }}
                className="text-sm text-gray-600 hover:text-gray-700"
              >
                Clear filters
              </button>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowAdvanced(false)}
                  className="px-4 py-2 text-sm text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={async () => {
                    setPanelNotice('');
                    const refusal = await executeSearch(query);
                    if (refusal) setPanelNotice(refusal);
                    else setShowAdvanced(false);
                  }}
                  className="px-4 py-2 text-sm text-white bg-purple-600 rounded hover:bg-purple-700"
                >
                  Apply filters
                </button>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      {/* Suggestions */}
      <Popover open={showSuggestions && hasSuggestions} onOpenChange={(open) => { if (!open) setShowSuggestions(false); }}>
        <PopoverAnchor virtualRef={anchorRef as RefObject<HTMLDivElement>} />
        <PopoverContent
          align="start"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onInteractOutside={keepAnchor}
          className="w-[var(--radix-popover-trigger-width)] bg-white border border-gray-200 rounded-lg shadow-lg p-0 max-h-64 overflow-auto"
        >
          {/* Tags */}
          {suggestions.tags && suggestions.tags.length > 0 && (
            <div className="py-2">
              <div className="px-3 py-1 text-xs font-medium text-gray-500 uppercase">
                Tags
              </div>
              {suggestions.tags.map((tag: TagSuggestion) => (
                <button
                  key={tag.value}
                  onClick={() => handleSuggestionClick(`tag:=${tag.value}`)}
                  className="w-full px-3 py-1.5 text-sm text-left hover:bg-gray-50 flex items-center justify-between group"
                >
                  <span className="text-gray-700">{tag.value}</span>
                  <span className="text-xs text-gray-400 group-hover:text-gray-500">
                    {tag.count}
                  </span>
                </button>
              ))}
            </div>
          )}
          
          {/* Titles */}
          {suggestions.titles && suggestions.titles.length > 0 && (
            <div className="py-2 border-t border-gray-100">
              <div className="px-3 py-1 text-xs font-medium text-gray-500 uppercase">
                Titles
              </div>
              {suggestions.titles.map((title: TitleSuggestion) => (
                <button
                  key={title.id}
                  onClick={() => handleSuggestionClick(title.title)}
                  className="w-full px-3 py-1.5 text-sm text-left hover:bg-gray-50 text-gray-700 truncate"
                >
                  {title.title}
                </button>
              ))}
            </div>
          )}
        </PopoverContent>
      </Popover>

      {/* Results are displayed in the Browser component's artifact grid */}
    </div>
  );
}
