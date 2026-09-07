/**
 * Shared workspace types used across the application, kept in their own
 * module so multiple components can import them without depending on
 * SidebarEnhanced.
 */

/** Describes the currently-active content source displayed in the workspace panel. */
export type ActiveSource =
  | { type: 'workspace'; id: string }
  | { type: 'collection'; id: string }
  | { type: 'mcp-server'; id: string }
  | null;
