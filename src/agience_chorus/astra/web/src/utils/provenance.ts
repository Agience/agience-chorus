import { splitList } from '@/display-state/lists';
export function formatProvenanceLabel(value?: string | null): string {
  if (!value) return 'Unknown';
  return splitList(value, '_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}
