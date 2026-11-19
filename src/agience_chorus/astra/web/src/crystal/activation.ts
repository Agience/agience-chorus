// crystal/activation.ts
//
// The prism junction, browser side: the browser is the prism that grounds
// crystal.workbench. Crystal answers whether it activates (`POST /crystals/activate`):
// structure, then the claimed sha, then the reach of every requirement over what this
// prism advertises. A refusal is shown as Crystal gives it; nothing falls back.

import { post } from '@/api/api';
import { type Crystal, type Organon } from './crystalModel';
import { WORKBENCH, WORKBENCH_SHA256 } from './workbench';

/**
 * The browser prism's named capability set.
 *
 * Why each name is honestly advertised (capabilities the crystal exercises via its
 * conduits count as advertised — the facet is a conduit, and what flows through it is
 * what the far side can do):
 *
 *   ui.render     — the browser's native act: this app is the render runtime.
 *   net.get       — fetch/XHR; every conduit below rides on it.
 *   store.read    — the lattice read path, through the authenticated mantle API
 *                   (src/api/artifacts.ts et al.). The browser doesn't hold the store;
 *                   it conducts to it — that is exactly what a facet is (§12).
 *   store.write   — same conduit, write direction (op.remember's requirement).
 *   compute.local — js/wasm in-page compute (op.reason/op.respond's local half runs
 *                   where the signal is).
 *   storage       — localStorage/IndexedDB: the browser's own persistence.
 */
export function browserPrismCapabilities(): string[] {
  return ['ui.render', 'net.get', 'store.read', 'store.write', 'compute.local', 'storage'];
}

export type ActivationFailureKind =
  | 'invalid-structure' // Crystal found shape problems
  | 'integrity' // the structure does not hash to the pinned sha
  | 'capability-gap'; // the prism does not advertise everything the organons require

/** What Crystal answers for a crystal it does not refuse. */
interface Junction {
  crystal: Crystal;
  sha256: string;
  requires: string[];
  missing: string[];
  activates: boolean;
}

/** Typed refusal — thrown, never swallowed. The reason is the finding. */
export class ActivationError extends Error {
  readonly kind: ActivationFailureKind;
  readonly details: string[];

  constructor(kind: ActivationFailureKind, message: string, details: string[] = []) {
    super(message);
    this.name = 'ActivationError';
    this.kind = kind;
    this.details = details;
  }
}

/** The activated crystal descriptor — what a grounded workbench looks like. */
export interface ActivatedCrystal {
  crystal: Crystal;
  sha256: string;
  prismCapabilities: string[];
  /** Every organon, with its requirements — all bound, because activation is all-or-refuse. */
  boundOrganons: Organon[];
  requiredCapabilities: string[];
}

/** Crystal's refusal, read from the 422 it answers: `{detail: {kind, problems}}`. */
function refusal(e: unknown): ActivationError | null {
  const detail = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  if (detail?.status !== 422) return null;
  const d = detail.data?.detail as { kind?: string; problems?: unknown } | undefined;
  const kind = d?.kind === 'integrity' ? 'integrity' : 'invalid-structure';
  const problems = Array.isArray(d?.problems) ? d.problems.map(String) : [];
  return new ActivationError(kind, `Crystal refused crystal.workbench: ${problems.join('; ')}`, problems);
}

/** Ask Crystal whether crystal.workbench activates on this prism, and return the activated
 * descriptor, or throw the refusal Crystal gave. */
export async function activateWorkbench(
  prismCapabilities: string[] = browserPrismCapabilities(),
): Promise<ActivatedCrystal> {
  let j: Junction;
  try {
    j = await post<Junction>('/crystals/activate', {
      crystal: { ...WORKBENCH, sha256: WORKBENCH_SHA256 },
      capabilities: prismCapabilities,
    });
  } catch (e) {
    throw refusal(e) ?? e;
  }
  if (!j.activates) {
    throw new ActivationError(
      'capability-gap',
      `this prism does not advertise: ${j.missing.join(', ')}`,
      j.missing,
    );
  }
  return {
    crystal: j.crystal,
    sha256: j.sha256,
    prismCapabilities,
    boundOrganons: j.crystal.organons ?? [],
    requiredCapabilities: j.requires,
  };
}
