import { describe, expect, it } from 'vitest';
import { refusedWriteDetail } from '../errorDetail';

const failed = (status: number, detail = 'Not found') => ({ response: { status, data: { detail } } });

// 2026-10-29, a tester with Viewer access was told "not found" saving a card in a workspace they had open.
describe('a refused change to something on screen', () => {
  it.each([403, 404])('is said as read-only access (%s)', (status) => {
    expect(refusedWriteDetail(failed(status), 'x')).toBe('You can view this but not change it.');
  });

  it("keeps the server's reason for any other failure", () => {
    expect(refusedWriteDetail(failed(409, 'Version conflict'), 'x')).toBe('Version conflict');
  });
});
