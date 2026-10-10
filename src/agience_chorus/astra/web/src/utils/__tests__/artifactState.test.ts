import { describe, expect, it } from 'vitest';

import { normalizeArtifactState, normalizeArtifactStates } from '../artifactState';

describe('normalizeArtifactState', () => {
  it('maps legacy committed and draft to live, and keeps archived', () => {
    expect(normalizeArtifactState('committed')).toBe('live');
    expect(normalizeArtifactState('draft')).toBe('live');
    expect(normalizeArtifactState('live')).toBe('live');
    expect(normalizeArtifactState(undefined)).toBe('live');
    expect(normalizeArtifactState('archived')).toBe('archived');
  });
});

describe('normalizeArtifactStates', () => {
  it('rewrites legacy states on artifact-shaped objects anywhere in a payload', () => {
    const payload = {
      items: [
        { id: 'a', context: '{}', state: 'committed' },
        { id: 'b', root_id: 'b', state: 'draft' },
        { id: 'c', content_type: 'text/plain', state: 'archived' },
      ],
      event: { artifact: { id: 'd', collection_id: 'ws', state: 'draft' } },
    };

    normalizeArtifactStates(payload);

    expect(payload.items.map((i) => i.state)).toEqual(['live', 'live', 'archived']);
    expect(payload.event.artifact.state).toBe('live');
  });

  it('leaves non-artifact records alone', () => {
    const grant = { id: 'g', state: 'draft', grantee_type: 'invite' };
    const status = { state: 'committed' };
    normalizeArtifactStates([grant, status]);
    expect(grant.state).toBe('draft');
    expect(status.state).toBe('committed');
  });

  it('passes through primitives and null', () => {
    expect(normalizeArtifactStates(null)).toBeNull();
    expect(normalizeArtifactStates('x')).toBe('x');
  });
});
