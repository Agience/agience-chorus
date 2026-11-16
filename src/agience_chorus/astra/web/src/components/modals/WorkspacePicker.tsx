// components/modals/WorkspacePicker.tsx
//
// Choose one workspace (BUG-075: "Add to workspace" from search asks where). The workspaces are
// listed by the labels the tabs use, so two with one name are told apart by the day each was made.
import { useMemo } from 'react';
import { Proportions } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { workspaceLabels } from '@/utils/workspaceLabels';

type Listed = { id: string; name?: string; created_time?: string };

type Props = {
  open: boolean;
  title: string;
  description?: string;
  workspaces: readonly Listed[];
  /** Listed first and marked, as where the choice usually goes. */
  currentId?: string | null;
  onPick: (workspaceId: string) => void;
  onClose: () => void;
};

export default function WorkspacePicker({ open, title, description, workspaces, currentId, onPick, onClose }: Props) {
  const labels = useMemo(() => workspaceLabels(workspaces), [workspaces]);
  const ordered = useMemo(
    () => [...workspaces].sort((a, b) => Number(b.id === currentId) - Number(a.id === currentId)),
    [workspaces, currentId],
  );
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent className="sm:max-w-[425px]" {...(description ? {} : { 'aria-describedby': undefined })}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>
        <ul className="max-h-80 overflow-auto space-y-1" aria-label="Workspaces">
          {ordered.map((ws) => (
            <li key={ws.id}>
              <button
                type="button"
                className="w-full flex items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/50"
                onClick={() => onPick(ws.id)}
              >
                <Proportions size={16} className="flex-shrink-0" aria-hidden="true" />
                <span className="truncate flex-1">{labels.get(ws.id) ?? ws.name}</span>
                {ws.id === currentId ? <span className="text-xs text-muted-foreground">open now</span> : null}
              </button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
