import { describe, expect, it, vi } from 'vitest';

vi.mock('virtual:content-types', () => ({
  contentTypeDefinitions: [
    {
      id: 'text',
      content_type: 'text/plain',
      is_wildcard: false,
      wildcard_prefix: null,
      extensions: ['.txt'],
      description: 'Plain text',
      label: 'Text',
      icon: 'file-text',
      color: '#111111',
      badge_class: 'badge-text',
      tile_class: '',
      modes: ['floating'],
      states: ['view'],
      default_mode: 'floating',
      default_state: 'view',
      is_container: false,
      creatable: true,
      viewer: 'text-plain',
      default_depth: null,
      max_depth: null,
      frontend_version: null,
      implementations: [],
    },
    {
      id: 'pdf',
      content_type: 'application/pdf',
      is_wildcard: false,
      wildcard_prefix: null,
      extensions: ['.pdf'],
      description: 'PDF',
      label: 'PDF',
      icon: 'file-text',
      color: '#dc2626',
      badge_class: 'badge-pdf',
      tile_class: '',
      modes: ['floating'],
      states: ['view'],
      default_mode: 'floating',
      default_state: 'view',
      is_container: false,
      creatable: false,
      viewer: 'application-pdf',
      default_depth: null,
      max_depth: null,
      frontend_version: null,
      implementations: [],
    },
    {
      id: 'image',
      content_type: 'image/*',
      is_wildcard: true,
      wildcard_prefix: 'image/',
      extensions: ['.png'],
      description: 'Image',
      label: 'Image',
      icon: 'image',
      color: '#ec4899',
      badge_class: 'badge-image',
      tile_class: '',
      modes: ['floating'],
      states: ['view'],
      default_mode: 'floating',
      default_state: 'view',
      is_container: false,
      creatable: false,
      viewer: 'image',
      default_depth: null,
      max_depth: null,
      frontend_version: null,
      implementations: [],
    },
    {
      id: 'authority',
      content_type: 'application/vnd.agience.authority+json',
      is_wildcard: false,
      wildcard_prefix: null,
      extensions: [],
      description: 'Authority',
      label: 'Authority',
      icon: 'shield',
      color: '#92400e',
      badge_class: 'badge-authority',
      tile_class: '',
      modes: ['floating'],
      states: ['view'],
      default_mode: 'floating',
      default_state: 'view',
      is_container: false,
      creatable: true,
      viewer: 'authority',
      default_depth: null,
      max_depth: null,
      frontend_version: null,
      implementations: [],
    },
    {
      id: 'chat',
      content_type: 'application/vnd.agience.chat+json',
      is_wildcard: false,
      wildcard_prefix: null,
      extensions: [],
      description: 'Chat',
      label: 'Chat',
      icon: 'message-circle',
      color: '#0ea5e9',
      badge_class: 'badge-chat',
      tile_class: '',
      modes: ['floating'],
      states: ['active'],
      default_mode: 'floating',
      default_state: 'active',
      is_container: false,
      creatable: true,
      viewer: null,
      default_depth: null,
      max_depth: null,
      frontend_version: null,
      implementations: [],
    },
    {
      id: 'transform',
      content_type: 'application/vnd.agience.transform+json',
      is_wildcard: false,
      wildcard_prefix: null,
      extensions: [],
      description: 'Transform',
      label: 'Transform',
      icon: 'zap',
      color: '#8b5cf6',
      badge_class: 'badge-order',
      tile_class: '',
      modes: ['floating'],
      states: ['edit'],
      default_mode: 'floating',
      default_state: 'edit',
      is_container: false,
      creatable: true,
      viewer: 'application-vnd-agience-transform',
      default_depth: null,
      max_depth: null,
      frontend_version: null,
      implementations: [],
    },
    {
      id: 'view',
      content_type: 'application/vnd.agience.view+json',
      is_wildcard: false,
      wildcard_prefix: null,
      extensions: [],
      description: 'View',
      label: 'View',
      icon: 'eye',
      color: '#0f766e',
      badge_class: 'badge-view',
      tile_class: '',
      modes: ['floating'],
      states: ['view'],
      default_mode: 'floating',
      default_state: 'view',
      is_container: false,
      creatable: true,
      viewer: 'application-vnd-agience-view',
      default_depth: null,
      max_depth: null,
      frontend_version: null,
      implementations: [],
    },
  ],
  CONTENT_TYPE_FALLBACK: {
    id: 'artifact',
    content_type: '*/*',
    is_wildcard: true,
    wildcard_prefix: null,
    extensions: [],
    description: 'An artifact: content plus its context',
    label: 'Artifact',
    icon: 'package',
    color: '#9ca3af',
    badge_class: '',
    tile_class: '',
    modes: ['floating'],
    states: ['view'],
    default_mode: 'floating',
    default_state: 'view',
    is_container: false,
    creatable: false,
    viewer: null,
    default_depth: null,
    max_depth: null,
    frontend_version: null,
    implementations: [],
  },
}));

import { getContentType, setRuntimeContentTypes } from '../content-types';
import { resolveViewer } from '../viewer-map';
import type { Artifact } from '@/context/workspace/workspace.types';

function makeArtifact(contentType?: string, context: Record<string, unknown> | string = {}): Artifact {
  return {
    id: 'artifact-1',
    content_type: contentType,
    context: typeof context === 'string' ? context : JSON.stringify(context),
    content: 'body',
    state: 'live',
  };
}

describe('content type registry', () => {
  it('resolves from artifact.content_type', () => {
    expect(getContentType(makeArtifact('application/vnd.agience.chat+json')).id).toBe('chat');
  });

  it('resolves text/plain from artifact.content_type', () => {
    expect(getContentType(makeArtifact('text/plain')).id).toBe('text');
  });

  it('hydrates packaged viewers for exact content type matches', () => {
    expect(getContentType(makeArtifact('application/vnd.agience.authority+json')).viewer).toBe(
      resolveViewer('authority')
    );
    expect(getContentType(makeArtifact('text/plain')).viewer).toBe(resolveViewer('text-plain'));
    expect(getContentType(makeArtifact('application/pdf')).viewer).toBe(resolveViewer('application-pdf'));
    expect(getContentType(makeArtifact('application/vnd.agience.transform+json')).viewer).toBe(
      resolveViewer('application-vnd-agience-transform')
    );
    expect(getContentType(makeArtifact('application/vnd.agience.view+json')).viewer).toBe(
      resolveViewer('application-vnd-agience-view')
    );
  });

  it('resolves category wildcards to packaged viewers', () => {
    const imageType = getContentType(makeArtifact('image/png'));
    expect(imageType.id).toBe('image');
    expect(imageType.viewer).toBe(resolveViewer('image'));
  });

  it('an artifact with no content type is an Artifact', () => {
    expect(getContentType(makeArtifact(undefined, '{not-json')).id).toBe('artifact');
  });
});

describe('everything inherits from Artifact (*/*)', () => {
  // The platform's catalogue as Crystal serves it: the root, File, and the containers.
  const entry = (content_type: string, label: string, extra: Record<string, unknown> = {}) => ({
    content_type, definition: { content_type, ui: { label, ...extra } },
  });

  function loadCatalogue() {
    setRuntimeContentTypes([
      entry('*/*', 'Artifact'),
      entry('application/*', 'File'),
      entry('application/vnd.agience.collection+json', 'Collection', { is_container: true }),
      entry('application/vnd.agience.workspace+json', 'Workspace', { is_container: true }),
      entry('text/*', 'Text'),
    ]);
  }

  it('a workspace and a collection resolve to their own types', () => {
    loadCatalogue();
    expect(getContentType(makeArtifact('application/vnd.agience.workspace+json')).label).toBe('Workspace');
    expect(getContentType(makeArtifact('application/vnd.agience.collection+json')).label).toBe('Collection');
  });

  // 2026-10-17, staging: a website lead (`application/vnd.agience.lead+json`, a type no persona
  // declares) showed as a File.
  it('an Agience or +json type nothing declares is an Artifact, never a File', () => {
    loadCatalogue();
    expect(getContentType(makeArtifact('application/vnd.agience.lead+json')).label).toBe('Artifact');
    expect(getContentType(makeArtifact('application/ld+json')).label).toBe('Artifact');
  });

  it('a file format nothing declares is a File, and an unknown category is an Artifact', () => {
    loadCatalogue();
    expect(getContentType(makeArtifact('application/zip')).label).toBe('File');
    expect(getContentType(makeArtifact('text/x-anything')).label).toBe('Text');
    expect(getContentType(makeArtifact('model/gltf+binary')).label).toBe('Artifact');
  });
});