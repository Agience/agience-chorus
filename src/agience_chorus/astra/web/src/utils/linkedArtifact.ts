/**
 * A link to one artifact (`/<id>`) that is not a workspace (FR-030: any artifact can be shared).
 *
 * The link opens the artifact in its own window. It is read first: a person who cannot read it
 * is told so, exactly as for a workspace, and whether it exists is not revealed. An invite's claim
 * page waits for the grant to reach Mantle (`waitForAccess`) before it navigates here, so one read
 * is the answer.
 */
import { getArtifact } from '../api/artifacts';
import type { Artifact } from '../context/workspace/workspace.types';

/** The artifact the link names, or null when this person cannot read it. */
export async function readLinkedArtifact(
  id: string,
  read: (id: string) => Promise<unknown> = getArtifact,
): Promise<Artifact | null> {
  try {
    return (await read(id)) as Artifact;
  } catch {
    return null;
  }
}

type Opener = (artifact: Artifact) => void;
let opener: Opener | null = null;
let pending: Artifact | null = null;

/** Ask the layout to open a linked artifact; held until a layout is listening. */
export function openLinkedArtifact(artifact: Artifact): void {
  if (opener) opener(artifact);
  else pending = artifact;
}

/** The layout listens here; an artifact asked for before it mounted is opened at once. */
export function onLinkedArtifact(fn: Opener): () => void {
  opener = fn;
  if (pending) {
    const a = pending;
    pending = null;
    fn(a);
  }
  return () => {
    if (opener === fn) opener = null;
  };
}
