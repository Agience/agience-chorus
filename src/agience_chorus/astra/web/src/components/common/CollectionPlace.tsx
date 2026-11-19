import { formatDay } from '@/utils/dates';
import type { CollectionResponse } from '@/api/types/collection';

/**
 * The line under a collection whose name another one the person can reach shares, from the marks
 * Crystal lays over the listing: the collection holding it, whose it is, and (with `withDate`) the
 * day it was made. A collection Crystal does not mark gets no line.
 */
export default function CollectionPlace({
  collection,
  withDate = true,
  className,
}: {
  collection: CollectionResponse;
  withDate?: boolean;
  className?: string;
}) {
  if (!collection.name_shared) return null;
  const parts: string[] = [];
  if (collection.place_in !== undefined) parts.push(`In ${collection.place_in}`);
  if (collection.place_yours !== undefined) parts.push(collection.place_yours ? 'Yours' : 'Shared with you');
  if (withDate && collection.created_time) parts.push(`made ${formatDay(collection.created_time)}`);
  if (!parts.length) return null;
  parts[0] = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
  return <span className={className} data-testid="collection-place">{parts.join(' · ')}</span>;
}
