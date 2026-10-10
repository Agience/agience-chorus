import { clsx } from 'clsx';

export interface CollectionChipProps {
  /** Collection ID */
  id: string;
  /** Collection name to display */
  name?: string;
  /** Collection membership status */
  status: 'member' | 'add' | 'remove' | 'targeted';
  /** Additional CSS classes */
  className?: string;
}

/**
 * CollectionChip component displays collection membership status with visual distinction:
 * - Solid (filled): member (the artifact is in this collection)
 * - Ghost (outline): targeted/add (the artifact will be added to this collection)
 * - Remove: targeted for removal (the artifact will be removed from this collection)
 */
export function CollectionChip({ id, name, status, className }: CollectionChipProps) {
  const displayName = name || id;

  // Solid style for collections the artifact is in
  if (status === 'member') {
    return (
      <span
        className={clsx(
          'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
          'bg-emerald-100 text-emerald-800 border border-emerald-300',
          className
        )}
        title={`In ${displayName}`}
      >
        {displayName}
      </span>
    );
  }

  // Ghost/outline style for targeted (pending) collections
  if (status === 'add' || status === 'targeted') {
    return (
      <span
        className={clsx(
          'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
          'bg-transparent text-purple-700 border border-purple-400 border-dashed',
          className
        )}
        title={`Will be added to ${displayName}`}
      >
        {displayName}
      </span>
    );
  }

  // Remove style for collections being removed
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
        'bg-rose-50 text-rose-700 border border-rose-300 line-through',
        className
      )}
      title={`Will be removed from ${displayName}`}
    >
      {displayName}
    </span>
  );
}
