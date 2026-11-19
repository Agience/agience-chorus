import { describe, expect, it } from 'vitest';
import { inboxWorkspaceId } from '../inbox';
import type { Workspace } from '@/api/types/workspace';

const ws = (id: string, inbox?: boolean): Workspace =>
  ({ id, name: id, description: '', created_by: 'u-1', created_time: '', modified_time: '', inbox });

describe('inboxWorkspaceId', () => {
  it('is the workspace Mantle marks as the Inbox', () => {
    expect(inboxWorkspaceId([ws('shared'), ws('inbox', true), ws('later')])).toBe('inbox');
  });

  it('is none when Mantle marks none', () => {
    expect(inboxWorkspaceId([ws('shared'), ws('later')])).toBeNull();
  });
});
