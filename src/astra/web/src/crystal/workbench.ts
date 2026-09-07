// crystal/workbench.ts
//
// crystal.workbench is the founding crystal, mirrored 1:1 from
// agience-crystal/src/crystal/definitions/crystal_workbench.py.
//
// The web workbench: a React facet (the human conduit) + the tektons it engages + the
// organons it invokes. The Python file is the definition; this app (agience-facet) is
// the `web` facet's implementation (the render runtime); the browser prism (prism-js)
// grounds it.
//
// The definition is data: it validates, hashes, and refuses tampering like every
// crystal. Because canonicalJson byte-matches Python's
// json.dumps(sort_keys=True, separators=(",",":")), the sha computed here equals the
// sha computed by the Python host — one crystal, one content address, any environment.

import { type Crystal, crystalArtifact, type CrystalArtifact } from './crystalModel';

export const WORKBENCH: Crystal = {
  name: 'crystal.workbench',
  facets: [
    // The React web UI — the human conduit. Bound by the waveform (§12.1): the UI
    // carries the signal both ways; content types are born at the tektons it talks to.
    { name: 'web', direction: 'both', content_type: 'text/html' }, // discovery hint, never a gate (§12.1)
    // The artifact browser conduit — reads the lattice through mantle's API.
    { name: 'store', direction: 'in' },
    // The event feed — change events flowing out to the UI.
    { name: 'events', direction: 'out' },
  ],
  tektons: [
    { name: 'lumen', domain: 'wisdom' }, // reasoning/inference — the converse panel
    { name: 'sage', domain: 'knowledge' }, // retrieval/memory
    { name: 'astra', domain: 'input' }, // ingest/describe
    { name: 'aria', domain: 'output' }, // presentation
  ],
  organons: [
    { name: 'op.respond', requires: ['compute.local', 'store.read'] },
    { name: 'op.reason', requires: ['compute.local'] },
    { name: 'op.retrieve', requires: ['store.read'] },
    { name: 'op.describe', requires: ['store.read', 'compute.local'] },
    { name: 'op.remember', requires: ['store.write'] },
  ],
  lattice_seed: {
    collections: ['workbench.session'], // where a fresh workbench's state grows
  },
  created_by: 'connect@agience.ai',
};

/**
 * The content address of crystal.workbench, pinning cross-language equivalence with
 * the Python reference definition.
 *
 * Computed by the Python definition:
 *
 *   cd agience-crystal/src && python -c "import sys, json; sys.path.insert(0, '.'); \
 *     from crystal.definitions.crystal_workbench import workbench_artifact; \
 *     print(json.loads(workbench_artifact()['content'])['sha256'])"
 *   → b24fe272b857b6b775af3584894758157be0712683aa9c0a17baabfd90b0c976
 *
 * The TS test suite recomputes the sha from the WORKBENCH constant above via the TS
 * canonicalJson/crystalSha and asserts equality with this pin, proving the two
 * implementations produce the same bytes for the same structure. Python is the
 * reference implementation: when either definition changes, update both together and
 * re-derive the pin from Python.
 */
export const WORKBENCH_SHA256 = 'b24fe272b857b6b775af3584894758157be0712683aa9c0a17baabfd90b0c976';

/** The founding crystal as a store artifact — validated, sha-stamped, refusing tampering. */
export function workbenchArtifact(): Promise<CrystalArtifact> {
  return crystalArtifact(WORKBENCH);
}
