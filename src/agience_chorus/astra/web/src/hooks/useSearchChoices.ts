import { useEffect, useState } from 'react';
import { searchChoices } from '@/api/search';
import { splitList } from '@/display-state/lists';

/**
 * The ids the platform Search finds for `query` among `types`, in its order; null while the query
 * is empty. A failed search finds nothing.
 */
export function useSearchChoices(query: string, types: string[]): string[] | null {
  const [found, setFound] = useState<string[] | null>(null);
  const key = types.join('\n');
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setFound(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      searchChoices(q, splitList(key, '\n'))
        .then((ids) => live && setFound(ids))
        .catch(() => live && setFound([]));
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query, key]);
  return found;
}

/** `items` in the order the Search found them, or all of them when nothing was asked. */
export function inFoundOrder<T>(items: T[], found: string[] | null, idOf: (item: T) => string): T[] {
  if (found === null) return items;
  const byId = new Map(items.map((item) => [idOf(item), item]));
  const seen = new Set<T>();
  return found.flatMap((id) => {
    const item = byId.get(id);
    if (!item || seen.has(item)) return [];
    seen.add(item);
    return [item];
  });
}
