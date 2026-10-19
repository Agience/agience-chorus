// api/feedArtifact.ts — a change-feed descriptor, completed through the authorized read.
//
// The feed says WHAT changed and never carries content: since 2026-10-19 that includes the title,
// which is part of an artifact's content (declared by the root type) and sealed at rest. A card
// shown from the descriptor alone would lose its title, and a merge over a card already on screen
// would wipe it. So each created or updated descriptor is completed with `GET /artifacts/{id}`,
// which restores the title for a reader allowed to read it; if that read fails, the descriptor
// stands, with the card's existing title kept by the caller's merge.

import { getArtifact } from './artifacts';
import type { ArtifactResponse } from './types';

export async function completeFromFeed(descriptor: ArtifactResponse): Promise<ArtifactResponse> {
  const id = descriptor?.id;
  if (!id) return descriptor;
  try {
    const full = await getArtifact(String(id));
    return { ...descriptor, ...full } as ArtifactResponse;
  } catch {
    return withoutContext(descriptor);
  }
}

/** The descriptor without its context, so a merge over a card on screen keeps that card's title. */
function withoutContext(descriptor: ArtifactResponse): ArtifactResponse {
  const { context: _context, ...rest } = descriptor as ArtifactResponse & { context?: unknown };
  return rest as ArtifactResponse;
}
