/**
 * content-types.ts — Unified content type registry
 *
 * All definition data flows from the `types/` directory tree (presentation.json files)
 * via the `virtual:content-types` Vite plugin. Only wiring — icon resolution and
 * viewer lazy imports — lives here.
 *
 * To add or change a type: edit its `types/<top>/<sub>/presentation.json`.
 * No code change needed; the dev server hot-reloads automatically.
 */
import type { IconType } from 'react-icons';
import type { ComponentType } from 'react';
import { contentTypeDefinitions, CONTENT_TYPE_FALLBACK } from 'virtual:content-types';
import type {
  ResolvedContentType,
  ResolvedFrontendImplementation,
  RecordConfig,
  RecordFieldConfig,
} from 'virtual:content-types';
import type { Artifact } from '@/context/workspace/workspace.types';
import { resolveIcon } from './icon-map';
import { resolveViewer } from './viewer-map';

/**
 * View Modes & States
 *
 * Content types declare which modes and states they support.
 * Common modes: 'floating', 'preview', 'inline', 'tree', 'grid', 'list'
 */
export type ViewMode = string;
export type ViewState = string;

// Re-export the generic-record viewer schema types so viewers import from the registry.
export type { RecordConfig, RecordFieldConfig };

/**
 * A single action an artifact context menu or hover bar can offer.
 * Content types declare their actions in `presentation.json`; this
 * interface is the hydrated runtime form.
 */
export interface ContentTypeAction {
  /** Stable identifier used by action handlers (e.g. "open", "delete", "archive"). */
  id: string;

  /** Display label shown in the context menu item. */
  label: string;

  /** Icon name string (resolved via icon-map at runtime). Omit for no icon. */
  icon?: string;

  /**
   * Artifact states in which this action is available.
   * Omit (or empty array) to show in all states.
   */
  states?: string[];

  /**
   * If true, show this action as a hover quick-action button on the artifact tile
   * (in addition to the context menu).
   */
  showInHover?: boolean;

  /** Marks the action as destructive — styled in red. */
  destructive?: boolean;
}

export interface ContentTypeFrontendImplementation {
  id: string;
  planes: string[];
  delivery: string;
  trust: string;
  priority: number;
  viewerKey?: string;
  providerKey?: string;
  bridge?: string;
  entry?: Record<string, unknown>;
  capabilities: string[];
  requiresEntitlements: string[];
  hostConstraints: string[];
}

/**
 * Content Type Definition — the hydrated runtime form used by all components.
 * icon and viewer are fully resolved (no more string refs at runtime).
 */
export interface ContentTypeDefinition {
  /** Stable identifier — from presentation.json `id` or derived from MIME. */
  id: string;

  /** Content type for this definition (exact or wildcard like "text/*"). */
  content_type: string;

  /** Display name. */
  label: string;

  /** Resolved React-icons component. */
  icon: IconType;

  /** Color for the horizontal bar and icon (hex). */
  color: string;

  /** Tailwind badge CSS classes. Empty string = no badge shown. */
  badgeClassName: string;

  /** Extra tile CSS classes (e.g. ring for orders). */
  tileClassName: string;

  /** Supported view modes. */
  modes: ViewMode[];

  /** Supported view states. */
  states: ViewState[];

  /** Default mode when an artifact is opened. */
  defaultMode: ViewMode;

  /** Default state when an artifact is opened. */
  defaultState: ViewState;

  /** Default depth for tree mode (containers only). */
  defaultDepth?: number;

  /** Maximum depth for tree mode (containers only). */
  maxDepth?: number;

  /**
   * Semantic container variant used by generic viewers to select a sub-component,
   * e.g. "resources" | "tools" | "prompts".
   */
  containerVariant?: string;

  /** Whether this is a container that can show children. */
  isContainer: boolean;

  /**
   * Declarative schema for the generic `_record` viewer (view/edit/save).
   * Present when the type sets `ui.viewer: "record"` + a `ui.record` block;
   * the viewer renders from this instead of a hardcoded definition.
   */
  record?: RecordConfig;

  /** Lazy viewer/editor component. */
  viewer?: () => Promise<{
    default: ComponentType<{
      artifact: Artifact;
      mode?: ViewMode;
      state?: ViewState;
      onOpenCollection?: (collectionId: string) => void;
      onOpenArtifact?: (artifact: Artifact) => void;
    }>;
  }>;

  /** Action to take when artifact is opened (e.g. "palette"). Undefined = default window. */
  openAction?: string;

  /** `ui://` resource URI for MCP Apps iframe viewer. When set, McpAppHost is used instead of compiled-in viewer. */
  resourceUri?: string;

  /** Server ID that owns the `ui://` resource. */
  resourceServer?: string;

  /** Whether users may create new artifacts of this type. */
  creatable: boolean;

  /** File extensions associated with this type. */
  extensions: string[];

  /** Optional frontend implementation manifest entries for future plane-aware resolution. */
  implementations: ContentTypeFrontendImplementation[];

  /**
   * Context-menu and hover-button actions for artifacts of this type.
   * When empty/absent, the host falls back to state-based defaults.
   */
  actions?: ContentTypeAction[];
}

function hydrateImplementation(
  raw: ResolvedFrontendImplementation,
): ContentTypeFrontendImplementation {
  return {
    id: raw.id,
    planes: raw.planes,
    delivery: raw.delivery,
    trust: raw.trust,
    priority: raw.priority,
    ...(raw.viewer_key ? { viewerKey: raw.viewer_key } : {}),
    ...(raw.provider_key ? { providerKey: raw.provider_key } : {}),
    ...(raw.bridge ? { bridge: raw.bridge } : {}),
    ...(raw.entry ? { entry: raw.entry } : {}),
    capabilities: raw.capabilities,
    requiresEntitlements: raw.requires_entitlements,
    hostConstraints: raw.host_constraints,
  };
}

// ──────────────────────────────────────────────────────────────────────────────
// Hydration — convert raw virtual-module data into runtime ContentTypeDefinition
// ──────────────────────────────────────────────────────────────────────────────

function hydrateDefinition(raw: ResolvedContentType): ContentTypeDefinition {
  const viewerFactory = resolveViewer(raw.viewer);
  return {
    id: raw.id,
    content_type: raw.content_type,
    label: raw.label,
    icon: resolveIcon(raw.icon),
    color: raw.color,
    badgeClassName: raw.badge_class,
    tileClassName: raw.tile_class,
    modes: raw.modes,
    states: raw.states,
    defaultMode: raw.default_mode,
    defaultState: raw.default_state,
    ...(raw.default_depth != null ? { defaultDepth: raw.default_depth } : {}),
    ...(raw.max_depth != null ? { maxDepth: raw.max_depth } : {}),
    ...(raw.container_variant ? { containerVariant: raw.container_variant } : {}),
    isContainer: raw.is_container,
    ...(raw.record ? { record: raw.record } : {}),
    ...(raw.open_action ? { openAction: raw.open_action } : {}),
    ...(raw.resource_uri ? { resourceUri: raw.resource_uri } : {}),
    ...(raw.resource_server ? { resourceServer: raw.resource_server } : {}),
    viewer: viewerFactory ?? undefined,
    creatable: raw.creatable,
    extensions: raw.extensions,
    implementations: raw.implementations.map(hydrateImplementation),
    // `actions` isn't part of the typed ResolvedContentType shape yet; read it
    // defensively in case a presentation.json already carries it.
    ...((raw as unknown as { actions?: ContentTypeAction[] }).actions?.length
      ? { actions: (raw as unknown as { actions?: ContentTypeAction[] }).actions }
      : {}),
  };
}

/**
 * Live content-type registry. The build-time `virtual:content-types` module seeds
 * it with the core primitives (`package/types`) as a synchronous bootstrap; at
 * runtime `setRuntimeContentTypes()` replaces it with the platform's fully-merged
 * feed (core + every server's types). The array reference is stable (mutated in
 * place) so existing synchronous consumers keep working.
 */
export const CONTENT_TYPES: ContentTypeDefinition[] = contentTypeDefinitions.map(hydrateDefinition);

/** Ultimate fallback used when no type matches an artifact's MIME. */
const FALLBACK_TYPE: ContentTypeDefinition = hydrateDefinition(CONTENT_TYPE_FALLBACK);

// ──────────────────────────────────────────────────────────────────────────────
// Runtime hydration (platform GET /types/all → registry)
// ──────────────────────────────────────────────────────────────────────────────

/** Derive a stable id from a MIME — must match the build plugin's contentTypeToId. */
function deriveTypeId(mime: string): string {
  if (mime === '*/*') return 'file';
  if (mime.endsWith('/*')) return mime.slice(0, -2);
  const m = mime.match(/^application\/vnd\.agience\.([\w-]+?)(?:\+\w+)?$/);
  if (m) return m[1];
  return mime.replace('/', '-').replace(/[^a-z0-9-]/gi, '-').toLowerCase();
}

/**
 * Map a platform-served type entry (`{content_type, definition}` with the nested
 * `ui` block) to the flat `ResolvedContentType` the registry hydrates. The viewer
 * pointer (`ui.resource_uri`/`ui.resource_server`) is read verbatim — declared by
 * the owning server, never inferred here.
 */
function serverEntryToResolved(entry: {
  content_type: string;
  definition: Record<string, unknown>;
}): ResolvedContentType {
  const ct = entry.content_type;
  const def = (entry.definition ?? {}) as Record<string, unknown>;
  const ui = (def.ui ?? {}) as Record<string, unknown>;
  const typeBlock = (def.type ?? {}) as Record<string, unknown>;
  const isWildcard = ct.endsWith('/*');
  const str = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined);
  const arr = (v: unknown): string[] | undefined => (Array.isArray(v) ? (v as string[]) : undefined);
  return {
    id: str(ui.id) ?? deriveTypeId(ct),
    content_type: ct,
    is_wildcard: isWildcard,
    wildcard_prefix: isWildcard ? ct.slice(0, -2) : null,
    extensions: arr(typeBlock.extensions) ?? [],
    description: str(typeBlock.description) ?? str(ui.description) ?? '',
    label: str(ui.label) ?? ct,
    icon: str(ui.icon) ?? 'file',
    color: str(ui.color) ?? '#9ca3af',
    badge_class: str(ui.badge_class) ?? '',
    tile_class: str(ui.tile_class) ?? '',
    modes: arr(ui.modes) ?? ['floating'],
    states: arr(ui.states) ?? ['view'],
    default_mode: str(ui.default_mode) ?? 'floating',
    default_state: str(ui.default_state) ?? 'view',
    is_container: Boolean(ui.is_container),
    creatable: Boolean(ui.creatable),
    open_action: str(ui.open_action) ?? null,
    resource_uri: str(ui.resource_uri) ?? null,
    resource_server: str(ui.resource_server) ?? null,
    container_variant: str(ui.container_variant) ?? null,
    record: (ui.record as RecordConfig | null | undefined) ?? null,
    viewer: str(ui.viewer) ?? null,
    provider: str(ui.provider) ?? null,
    default_depth: typeof ui.default_depth === 'number' ? (ui.default_depth as number) : null,
    max_depth: typeof ui.max_depth === 'number' ? (ui.max_depth as number) : null,
    frontend_version: null,
    implementations: [],
  };
}

/**
 * Replace the registry with the platform's runtime feed (called once, before the
 * artifact UI renders — see ContentTypesProvider). The feed is authoritative: it
 * already merges core + server types, so it supersedes the build-time bootstrap.
 */
export function setRuntimeContentTypes(
  entries: Array<{ content_type: string; definition: Record<string, unknown> }>,
): void {
  const resolved = entries
    .map(serverEntryToResolved)
    // exact MIME types before wildcards (matching priority), then by name
    .sort((a, b) => (a.is_wildcard === b.is_wildcard
      ? a.content_type.localeCompare(b.content_type)
      : a.is_wildcard ? 1 : -1))
    .map(hydrateDefinition);
  CONTENT_TYPES.splice(0, CONTENT_TYPES.length, ...resolved);
}

// ──────────────────────────────────────────────────────────────────────────────
// MIME resolution
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Resolve the best ContentTypeDefinition for a given MIME string.
 *
 * Priority:
 *   1. Exact match (e.g. "text/markdown")
 *   2. Category wildcard (e.g. "text/*" for any "text/...")
 *   3. Application wildcard ("application/*") as catch-all binary file
 *   4. Global fallback
 */
function findForContentType(contentType: string): ContentTypeDefinition {
  const normalized = contentType.split(';')[0]?.trim().toLowerCase() ?? '';
  if (!normalized) return FALLBACK_TYPE;

  // 1. Exact match
  const exact = CONTENT_TYPES.find((t) => t.content_type === normalized);
  if (exact) return exact;

  // 2. Category wildcard
  const category = normalized.split('/')[0];
  const wildcard = CONTENT_TYPES.find((t) => t.content_type === `${category}/*`);
  if (wildcard) return wildcard;

  // 3. application/* as last-resort for non-matched binary formats
  if (category !== 'application') {
    const appFallback = CONTENT_TYPES.find((t) => t.content_type === 'application/*');
    if (appFallback) return appFallback;
  }

  return FALLBACK_TYPE;
}

// ──────────────────────────────────────────────────────────────────────────────
// Public API — the stable surface every consumer relies on
// ──────────────────────────────────────────────────────────────────────────────

/** Returns the ContentTypeDefinition for a given artifact using canonical top-level content_type. */
export function getContentType(artifact: Artifact): ContentTypeDefinition {
  if (artifact.content_type) return findForContentType(artifact.content_type);
  return FALLBACK_TYPE;
}

/** Returns the ContentTypeDefinition whose id or MIME matches the given value. */
export function getContentTypeById(id: string): ContentTypeDefinition | undefined {
  return CONTENT_TYPES.find((t) => t.id === id || t.content_type === id);
}

/** All container types (isContainer === true). */
export function getContainerTypes(): ContentTypeDefinition[] {
  return CONTENT_TYPES.filter((t) => t.isContainer);
}

/** All types that users can create (creatable === true). */
export function getCreatableTypes(): ContentTypeDefinition[] {
  return CONTENT_TYPES.filter((t) => t.creatable);
}

// ──────────────────────────────────────────────────────────────────────────────
// Implementation resolution
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Resolve the best frontend implementation for a content type on a given
 * UX plane.
 *
 * Resolution order (per content-type-registry-v2.md):
 *   1. Gather candidate implementations from the content type.
 *   2. Filter by requested plane.
 *   3. Sort by priority (higher wins).
 *   4. Return the first compatible candidate, or null.
 *
 * When no implementation matches the requested plane, the caller falls
 * back to the default bundled viewer path.
 */
export function resolveImplementation(
  contentType: ContentTypeDefinition,
  plane: string,
): ContentTypeFrontendImplementation | null {
  const candidates = contentType.implementations
    .filter((impl) => impl.planes.length === 0 || impl.planes.includes(plane))
    .sort((a, b) => b.priority - a.priority);

  return candidates[0] ?? null;
}
