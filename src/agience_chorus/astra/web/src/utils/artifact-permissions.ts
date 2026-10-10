// utils/artifact-permissions.ts
import type { Artifact } from '@/context/workspace/workspace.types';

/**
 * How a card's remove request should be carried out. `delete` destroys the artifact
 * (`DELETE /artifacts/{id}`); absent, the card is unlinked from the container it is shown in.
 */
export type CardRemoveMode = 'delete';

/**
 * Whether to offer Delete for this artifact.
 *
 * The artifact carries no permissions field, so the offer is made from what it does carry:
 * the caller created it (`created_by`, which Mantle stamps with the creating user's id, the same
 * id the Inbox workspace is keyed on). The server's `delete` access check on
 * `DELETE /artifacts/{id}` is the gate; a refusal there surfaces as a toast.
 *
 * Never offered for the Inbox itself, whose id is the user id.
 */
export function canDeleteArtifact(artifact: Artifact, userId: string | null | undefined): boolean {
  if (userId && (artifact.id === userId || artifact.root_id === userId)) return false;
  return Boolean(userId) && artifact.created_by === userId;
}
