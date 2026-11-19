import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  RELATIONSHIP_PATTERN,
  getArtifact,
  linkArtifact,
  listArtifactLinks,
  removeArtifactLinks,
  type ArtifactLink,
} from '@/api/artifacts';
import type { ArtifactResponse } from '@/api/types/artifact';
import { safeParseArtifactContext } from '@/utils/artifactContext';
import { errorDetailOf } from './shareText';
import { withKey } from '@/display-state/lists';

interface LinksDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The artifact whose named links are shown and edited. */
  artifactId: string;
}

function titleOf(a: Pick<ArtifactResponse, 'id' | 'context'>): string {
  const title = safeParseArtifactContext(a.context).title;
  return typeof title === 'string' && title.trim() ? title : String(a.id);
}

/**
 * The named links an artifact holds, and those pointing at it. A link names what the artifact at
 * its other end is to this one (`initialized_by`, `operator`): it is listed here, never as a member,
 * and grants nothing. The target is named by its id, which every artifact's menu copies.
 */
export function LinksDialog({ open, onOpenChange, artifactId }: LinksDialogProps) {
  const [title, setTitle] = useState<string>('');
  const [links, setLinks] = useState<ArtifactLink[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [relationship, setRelationship] = useState('');
  const [targetId, setTargetId] = useState('');
  const [target, setTarget] = useState<ArtifactResponse | null>(null);
  const [targetError, setTargetError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setLinks(await listArtifactLinks(artifactId, 'both'));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorDetailOf(err, 'The links could not be listed.'));
    }
  }, [artifactId]);

  useEffect(() => {
    if (!open) return;
    getArtifact(artifactId).then((a) => setTitle(titleOf(a))).catch(() => setTitle(artifactId));
    void reload();
  }, [open, artifactId, reload]);

  // The target is looked up as it is typed, so the person sees what they are about to link.
  useEffect(() => {
    const id = targetId.trim();
    setTarget(null);
    setTargetError(null);
    if (!id) return;
    let live = true;
    const t = setTimeout(() => {
      getArtifact(id)
        .then((a) => { if (live) setTarget(a); })
        .catch((err) => { if (live) setTargetError(errorDetailOf(err, 'No artifact you can read has that id.')); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [targetId]);

  const outgoing = useMemo(() => withKey(links, (l) => l.direction, 'out'), [links]);
  const incoming = useMemo(() => withKey(links, (l) => l.direction, 'in'), [links]);
  const nameValid = RELATIONSHIP_PATTERN.test(relationship.trim());
  const canAdd = nameValid && Boolean(target) && !busy;

  const add = async () => {
    if (!target) return;
    setBusy(true);
    setActionError(null);
    try {
      await linkArtifact(artifactId, String(target.root_id ?? target.id), relationship.trim());
      setRelationship('');
      setTargetId('');
      await reload();
    } catch (err) {
      setActionError(errorDetailOf(err, 'The link could not be made.'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (name: string) => {
    setBusy(true);
    setActionError(null);
    try {
      await removeArtifactLinks(artifactId, name);
      await reload();
    } catch (err) {
      setActionError(errorDetailOf(err, 'The link could not be removed.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100vw-2rem)] max-w-lg">
        <DialogHeader>
          <DialogTitle>Links: {title || artifactId}</DialogTitle>
          <DialogDescription>
            A link names what another artifact is to this one. It grants no access.
          </DialogDescription>
        </DialogHeader>

        {loadError && <p className="text-sm text-red-600" data-testid="links-load-error">{loadError}</p>}

        <section aria-label="Links from this artifact" className="space-y-2">
          <h3 className="text-sm font-medium">Links from this artifact</h3>
          {outgoing.length === 0 ? (
            <p className="text-sm text-gray-500">None.</p>
          ) : (
            <ul className="space-y-1">
              {outgoing.map((l) => (
                <li key={`${l.relationship}:${l.id}`} className="flex items-center gap-2 text-sm"
                    data-testid="link-out">
                  <code className="rounded bg-gray-100 px-1">{l.relationship}</code>
                  <span className="min-w-0 flex-1 truncate" title={String(l.root_id ?? l.id)}>{titleOf(l)}</span>
                  <Button variant="ghost" size="sm" disabled={busy}
                          aria-label={`Remove ${l.relationship}`}
                          onClick={() => void remove(l.relationship)}>
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {incoming.length > 0 && (
          <section aria-label="Links to this artifact" className="space-y-2">
            <h3 className="text-sm font-medium">Links to this artifact</h3>
            <ul className="space-y-1">
              {incoming.map((l) => (
                <li key={`${l.relationship}:${l.id}`} className="flex items-center gap-2 text-sm"
                    data-testid="link-in">
                  <span className="min-w-0 flex-1 truncate" title={String(l.root_id ?? l.id)}>{titleOf(l)}</span>
                  <code className="rounded bg-gray-100 px-1">{l.relationship}</code>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section aria-label="Add a link" className="space-y-2 border-t pt-3">
          <h3 className="text-sm font-medium">Add a link</h3>
          <label className="block text-sm">
            Name
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm"
              placeholder="initialized_by"
              value={relationship}
              onChange={(e) => setRelationship(e.target.value)}
            />
          </label>
          {relationship.trim() && !nameValid && (
            <p className="text-xs text-red-600" data-testid="link-name-invalid">
              Letters, digits and _ . : - only, up to 64 characters.
            </p>
          )}
          <label className="block text-sm">
            Artifact id
            <input
              className="mt-1 w-full rounded border px-2 py-1 font-mono text-sm"
              placeholder="Paste an id (Copy ID on any artifact)"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
            />
          </label>
          {target && <p className="text-xs text-gray-600" data-testid="link-target">Links to: {titleOf(target)}</p>}
          {targetError && <p className="text-xs text-red-600" data-testid="link-target-error">{targetError}</p>}
          {actionError && <p className="text-sm text-red-600" data-testid="link-action-error">{actionError}</p>}
          <div className="flex justify-end">
            <Button disabled={!canAdd} onClick={() => void add()}>Add link</Button>
          </div>
        </section>
      </DialogContent>
    </Dialog>
  );
}
