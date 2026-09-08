// crystal/__tests__/activation.test.ts
//
// crystal.workbench grounds on the browser prism — and the sha computed by the TS
// implementation equals the sha computed by the Python reference (cross-language
// equivalence, pinned).
import { describe, it, expect } from 'vitest';

import { crystalSha, requiredCapabilities, validate } from '../crystalModel';
import { WORKBENCH, WORKBENCH_SHA256, workbenchArtifact } from '../workbench';
import {
  ActivationError,
  activateWorkbench,
  browserPrismCapabilities,
} from '../activation';

describe('crystal/workbench — the founding crystal', () => {
  it('validates clean (same assertion the Python module makes at import time)', () => {
    expect(validate(WORKBENCH as unknown as Record<string, unknown>)).toEqual([]);
  });

  it('hashes to the sha the Python definition computes — cross-language equivalence', async () => {
    // Pin derived from the reference implementation (see workbench.ts for the command):
    //   python -c "...crystal_workbench.workbench_artifact()..." →
    //   b24fe272b857b6b775af3584894758157be0712683aa9c0a17baabfd90b0c976
    expect(await crystalSha(WORKBENCH as unknown as Record<string, unknown>)).toBe(WORKBENCH_SHA256);
  });

  it('requires exactly what the organons name', () => {
    expect(requiredCapabilities(WORKBENCH)).toEqual(['compute.local', 'store.read', 'store.write']);
  });

  it('artifact wire shape byte-matches the Python builder (content + context hashes pinned)', async () => {
    // Pins generated from the reference implementation:
    //   art = crystal_workbench.workbench_artifact()
    //   sha256(art['content'].encode()) → 98bc4d9e99e961f9f19095712ef5efb12514d21bf8615f6be78db9d3badc27ed
    //   sha256(art['context'].encode()) → 1a152c9ec38f500425daf8243d257d153f58347864493f1a5beaf762974fb136
    const art = await workbenchArtifact();
    const hex = async (s: string) =>
      Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))))
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('');
    expect(await hex(art.content)).toBe('98bc4d9e99e961f9f19095712ef5efb12514d21bf8615f6be78db9d3badc27ed');
    expect(await hex(art.context)).toBe('1a152c9ec38f500425daf8243d257d153f58347864493f1a5beaf762974fb136');
  });

  it('artifact carries the crystal content type and a verifiable body', async () => {
    const art = await workbenchArtifact();
    expect(art.id).toBe('crystal.workbench');
    expect(art.content_type).toBe('application/vnd.agience.crystal+json');
    const ctx = JSON.parse(art.context);
    expect(ctx.sha256).toBe(WORKBENCH_SHA256);
    expect(ctx.facets).toEqual(['web', 'store', 'events']);
    expect(ctx.tektons).toEqual(['lumen', 'sage', 'astra', 'aria']);
    expect(ctx.organons).toEqual(['op.respond', 'op.reason', 'op.retrieve', 'op.describe', 'op.remember']);
  });
});

describe('crystal/activation — the browser prism junction', () => {
  it('the browser prism advertises the named capability set', () => {
    expect(browserPrismCapabilities()).toEqual([
      'ui.render',
      'net.get',
      'store.read',
      'store.write',
      'compute.local',
      'storage',
    ]);
  });

  it('activates on the browser prism: validate → verify sha → subset check', async () => {
    const activated = await activateWorkbench();
    expect(activated.sha256).toBe(WORKBENCH_SHA256);
    expect(activated.crystal.name).toBe('crystal.workbench');
    expect(activated.boundOrganons.map((o) => o.name)).toEqual([
      'op.respond',
      'op.reason',
      'op.retrieve',
      'op.describe',
      'op.remember',
    ]);
    expect(activated.requiredCapabilities).toEqual(['compute.local', 'store.read', 'store.write']);
  });

  it('refuses on a capability gap — no silent fallback, the reason is the finding', async () => {
    // A prism that cannot write to the store cannot bind op.remember.
    const err = await activateWorkbench(['ui.render', 'net.get', 'store.read', 'compute.local']).then(
      () => null,
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ActivationError);
    expect((err as ActivationError).kind).toBe('capability-gap');
    expect((err as ActivationError).details).toEqual(['store.write']);
    expect((err as ActivationError).message).toContain('store.write');
  });
});
