import { useState, useEffect, useMemo } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { FolderOpen, Search } from 'lucide-react';
import { listCollections, listVisibleOfType } from '../../api/collections';
import toast from 'react-hot-toast';

interface BindingPickerProps {
  open: boolean;
  onClose: () => void;
  /** Called when the user picks an artifact, with the name it was shown by. */
  onSelect: (artifactId: string, title?: string) => void;
  /** Role label shown in the dialog title. */
  label?: string;
  /** The content types the choice may be; collections when absent. */
  contentTypes?: string[];
}

interface Choice { id: string; name: string }

// A listed artifact's name: a collection's `name`, otherwise the title in its context.
function nameOf(a: Record<string, unknown>): string {
  if (typeof a.name === 'string' && a.name) return a.name;
  let ctx = a.context as unknown;
  if (typeof ctx === 'string') { try { ctx = JSON.parse(ctx); } catch { ctx = {}; } }
  const title = ctx && typeof ctx === 'object' ? (ctx as Record<string, unknown>).title : undefined;
  return typeof title === 'string' && title ? title : String(a.id ?? '');
}

export function BindingPicker({ open, onClose, onSelect, label, contentTypes }: BindingPickerProps) {
  const [collections, setCollections] = useState<Choice[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  const types = (contentTypes ?? []).join(' ');
  useEffect(() => {
    if (open) {
      loadCollections();
      setSearchQuery('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, types]);

  const loadCollections = async () => {
    try {
      setLoading(true);
      const lists = contentTypes && contentTypes.length
        ? await Promise.all(contentTypes.map((ct) => listVisibleOfType(ct)))
        : [await listCollections()];
      const seen = new Set<string>();
      const data: Choice[] = [];
      for (const a of lists.flat() as unknown as Record<string, unknown>[]) {
        const id = String(a.id ?? '');
        if (!id || seen.has(id)) continue;
        seen.add(id);
        data.push({ id, name: nameOf(a) });
      }
      setCollections(data);
    } catch (error) {
      console.error('Failed to load collections:', error);
      toast.error('Failed to load collections');
    } finally {
      setLoading(false);
    }
  };

  const filtered = useMemo(
    () =>
      collections.filter((c) =>
        (c.name ?? '').toLowerCase().includes(searchQuery.toLowerCase()),
      ),
    [collections, searchQuery],
  );

  const handleSelect = (c: Choice) => {
    onSelect(c.id, c.name);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{label ? `Select: ${label}` : 'Select Artifact'}</DialogTitle>
        </DialogHeader>

        <div className="relative mb-3">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm outline-none focus:ring-1 focus:ring-ring"
            autoFocus
          />
        </div>

        <div className="max-h-64 overflow-y-auto space-y-1">
          {loading ? (
            <p className="py-4 text-center text-sm text-muted-foreground">Loading…</p>
          ) : filtered.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No results</p>
          ) : (
            filtered.map((c) => (
              <button
                key={c.id}
                onClick={() => handleSelect(c)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent text-left"
              >
                <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="truncate">{c.name || c.id}</span>
              </button>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
