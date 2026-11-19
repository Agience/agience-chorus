// Artifact visual helpers: icon, color, and state-badge helpers for artifacts.
// Icon and color lookups defer to the unified content type registry
// (registry/content-types.ts); the values here are the fallback used
// when a type isn't found there.
import { FiFile } from 'react-icons/fi';
import type { IconType } from 'react-icons';
import type { Artifact } from '@/context/workspace/workspace.types';
import { getContentType, getContentTypeById } from '@/registry/content-types';

// Artifact type detection from content_type
export function getArtifactType(artifact: Artifact): string {
  const contentType = getContentType(artifact);
  return contentType.id;
}

// Get icon for artifact type
export function getArtifactIcon(artifactType: string): IconType {
  // Prefer the unified registry.
  return getContentTypeById(artifactType)?.icon ?? FiFile;
}

// Get color for artifact type (horizontal bar)
export function getArtifactColor(artifactType: string): string {
  // Prefer the unified registry.
  return getContentTypeById(artifactType)?.color ?? '#9ca3af';
}

// Check if state badge should be shown. Only archived artifacts carry one.
export function shouldShowStateBadge(state: string | undefined): boolean {
  return state === 'archived';
}

// Get friendly label for state badge
export function getStateBadgeLabel(state: string | undefined): string {
  switch (state) {
    case 'archived': return 'Archived';
    default: return '';
  }
}
