// crystal/__tests__/activation.test.ts
//
// The web app asks Crystal whether crystal.workbench activates on the browser prism and
// shows what Crystal answers: the activated crystal, or Crystal's refusal.
import { describe, expect, it, vi } from 'vitest';

const post = vi.fn();
vi.mock('@/api/api', () => ({ post: (...a: unknown[]) => post(...a) }));

import { WORKBENCH, WORKBENCH_SHA256 } from '../workbench';
import { ActivationError, activateWorkbench, browserPrismCapabilities } from '../activation';

const answer = (missing: string[] = []) => ({
  crystal: { ...WORKBENCH, sha256: WORKBENCH_SHA256 },
  sha256: WORKBENCH_SHA256,
  requires: ['compute.local', 'store.read', 'store.write'],
  missing,
  activates: missing.length === 0,
});

const refused = (kind: string, problems: string[]) =>
  Object.assign(new Error('422'), { response: { status: 422, data: { detail: { kind, problems } } } });

async function failure(p: Promise<unknown>): Promise<unknown> {
  try {
    await p;
    return null;
  } catch (e) {
    return e;
  }
}

describe('crystal/activation — Crystal answers the junction', () => {
  it('sends the workbench with its pinned sha and the prism capabilities', async () => {
    post.mockResolvedValue(answer());
    await activateWorkbench();
    expect(post).toHaveBeenCalledWith('/crystals/activate', {
      crystal: { ...WORKBENCH, sha256: WORKBENCH_SHA256 },
      capabilities: browserPrismCapabilities(),
    });
  });

  it('shows the activated crystal as Crystal gives it', async () => {
    post.mockResolvedValue(answer());
    const activated = await activateWorkbench();
    expect(activated.sha256).toBe(WORKBENCH_SHA256);
    expect(activated.crystal.name).toBe('crystal.workbench');
    expect(activated.boundOrganons.map((o) => o.name)).toEqual([
      'op.respond', 'op.reason', 'op.retrieve', 'op.describe', 'op.remember',
    ]);
    expect(activated.requiredCapabilities).toEqual(['compute.local', 'store.read', 'store.write']);
  });

  it('shows a crystal Crystal refuses for a missing required field', async () => {
    post.mockImplementation(async () => { throw refused('invalid-structure', ['missing required field: created_by']); });
    const err = await failure(activateWorkbench());
    expect(err).toBeInstanceOf(ActivationError);
    expect((err as ActivationError).kind).toBe('invalid-structure');
    expect((err as ActivationError).details).toEqual(['missing required field: created_by']);
    expect((err as ActivationError).message).toContain('missing required field: created_by');
  });

  it('shows an integrity refusal as integrity', async () => {
    post.mockImplementation(async () => { throw refused('integrity', ['claimed sha256=a but the structure hashes to b']); });
    expect(((await failure(activateWorkbench())) as ActivationError).kind).toBe('integrity');
  });

  it('shows a capability gap with the requirements out of reach', async () => {
    post.mockResolvedValue(answer(['store.write']));
    const err = await failure(activateWorkbench(['ui.render', 'store.read', 'compute.local']));
    expect((err as ActivationError).kind).toBe('capability-gap');
    expect((err as ActivationError).details).toEqual(['store.write']);
  });

  it('passes any other failure through unchanged', async () => {
    const down = new Error('Network Error');
    post.mockImplementation(async () => { throw down; });
    expect(await failure(activateWorkbench())).toBe(down);
  });
});
