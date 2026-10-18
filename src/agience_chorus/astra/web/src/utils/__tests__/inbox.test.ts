import { describe, expect, it } from 'vitest';
import { inboxWorkspaceId } from '../inbox';
import type { Workspace } from '@/api/types/workspace';

const ws = (id: string, created_by: string, created_time: string): Workspace =>
  ({ id, name: id, description: '', created_by, created_time, modified_time: created_time });

describe('inboxWorkspaceId', () => {
  it('is the oldest workspace the person created, never their user id', () => {
    const list = [ws('later', 'u-1', '2026-10-01'), ws('inbox', 'u-1', '2026-08-01'), ws('shared', 'u-2', '2026-07-01')];
    expect(inboxWorkspaceId(list, 'u-1')).toBe('inbox');
  });

  it('is none when the person owns no workspace, or nobody is signed in', () => {
    expect(inboxWorkspaceId([ws('shared', 'u-2', '2026-07-01')], 'u-1')).toBeNull();
    expect(inboxWorkspaceId([ws('inbox', 'u-1', '2026-08-01')], null)).toBeNull();
  });
});
