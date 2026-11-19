// utils/artifact-permissions.ts
import type { Artifact } from '@/context/workspace/workspace.types';

/**
 * How a card's remove request should be carried out. `delete` destroys the artifact
 * (`DELETE /artifacts/{id}`); absent, the card is unlinked from the container it is shown in.
 */
export type CardRemoveMode = 'delete';

/**
 * Whether Mantle allows the caller this action on the artifact, as it answered in
 * `allowed_actions` with the artifact. An artifact without that answer offers nothing.
 */
export function allows(artifact: Pick<Artifact, 'allowed_actions'> | null | undefined,
  action: string): boolean {
  return Boolean(artifact?.allowed_actions?.includes(action));
}
