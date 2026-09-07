// crystal/activation.ts
//
// The prism junction, browser side: the browser (via prism-js conventions) is the prism
// that grounds crystal.workbench; this module is the activation gate. No silent
// fallback anywhere — a crystal that fails validation, integrity, or the capability
// subset check refuses to activate, and the refusal reason is the finding.

import {
  activatesOn,
  type Crystal,
  type Organon,
  requiredCapabilities,
  validate,
  verify,
} from './crystalModel';
import { WORKBENCH, WORKBENCH_SHA256, workbenchArtifact } from './workbench';

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
  | 'invalid-structure' // validate() found shape problems
  | 'integrity' // sha mismatch (tamper, or drift from the pinned Python sha)
  | 'capability-gap'; // the prism does not advertise everything the organons require

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

/**
 * validate → verify sha → activatesOn — then and only then return the activated
 * descriptor. Order matters: structure before integrity before capability, so the
 * refusal names the first gate that failed.
 */
export async function activateWorkbench(
  prismCapabilities: string[] = browserPrismCapabilities(),
): Promise<ActivatedCrystal> {
  // 1. Structure: an invalid crystal must refuse to ground, never half-load.
  const problems = validate(WORKBENCH as unknown as Record<string, unknown>);
  if (problems.length > 0) {
    throw new ActivationError('invalid-structure', 'crystal.workbench failed validation', problems);
  }

  // 2. Integrity: build the artifact, re-hash it, refuse on mismatch...
  const artifact = await workbenchArtifact();
  let crystal: Crystal;
  try {
    crystal = await verify(artifact);
  } catch (e) {
    throw new ActivationError('integrity', e instanceof Error ? e.message : String(e));
  }
  // ...and hold the definition to its pinned cross-language content address: if the TS
  // constant drifts from the Python reference definition, that is tampering-by-drift.
  if (crystal.sha256 !== WORKBENCH_SHA256) {
    throw new ActivationError(
      'integrity',
      `crystal.workbench hashes to ${crystal.sha256} but the pinned reference sha is ` +
        `${WORKBENCH_SHA256} — the definition drifted from the Python reference; refusing to ground`,
    );
  }

  // 3. The prism junction: one subset check, both directions (§12).
  if (!activatesOn(crystal, prismCapabilities)) {
    const required = requiredCapabilities(crystal);
    const advertised = new Set(prismCapabilities);
    const missing = required.filter((c) => !advertised.has(c));
    throw new ActivationError(
      'capability-gap',
      `this prism does not advertise: ${missing.join(', ')}`,
      missing,
    );
  }

  return {
    crystal,
    sha256: crystal.sha256 as string,
    prismCapabilities,
    boundOrganons: crystal.organons ?? [],
    requiredCapabilities: requiredCapabilities(crystal),
  };
}
