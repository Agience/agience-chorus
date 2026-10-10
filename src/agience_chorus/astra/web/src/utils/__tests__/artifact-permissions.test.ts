import { describe, expect, it } from 'vitest';

import { canDeleteArtifact } from '../artifact-permissions';
import type { Artifact } from '@/context/workspace/workspace.types';

const card = (over: Partial<Artifact>): Artifact => ({ context: '{}', content: '', state: 'live', ...over });

describe('canDeleteArtifact', () => {
  it('allows a card the user created', () => {
    expect(canDeleteArtifact(card({ id: 'a', created_by: 'u1' }), 'u1')).toBe(true);
  });

  it('refuses a card someone else created, or with no user', () => {
    expect(canDeleteArtifact(card({ id: 'a', created_by: 'u2' }), 'u1')).toBe(false);
    expect(canDeleteArtifact(card({ id: 'a', created_by: 'u1' }), null)).toBe(false);
    expect(canDeleteArtifact(card({ id: 'a' }), 'u1')).toBe(false);
  });

  it('refuses a card someone else created whatever its legacy state', () => {
    const legacy = { id: 'a', created_by: 'u2', state: 'draft' } as unknown as Partial<Artifact>;
    expect(canDeleteArtifact(card(legacy), 'u1')).toBe(false);
  });

  it('never offers the Inbox itself', () => {
    expect(canDeleteArtifact(card({ id: 'u1', created_by: 'u1' }), 'u1')).toBe(false);
    expect(canDeleteArtifact(card({ id: 'x', root_id: 'u1', created_by: 'u1' }), 'u1')).toBe(false);
  });
});
