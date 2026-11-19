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
// The definition is data. Crystal checks it like every crystal: its structure, and that
// it hashes to the pinned sha below, before it activates.

import { type Crystal } from './crystalModel';

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
 * The content address of crystal.workbench, as the Python reference definition computes it:
 *
 *   python -c "from agience_chorus.aria.crystal_workbench import workbench_artifact;  *     import json; print(json.loads(workbench_artifact()['content'])['sha256'])"
 *
 * The web app sends it as the crystal's claimed sha; Crystal refuses the crystal when the
 * structure above does not hash to it. When either definition changes, change both and
 * re-derive the pin from Python.
 */
export const WORKBENCH_SHA256 = 'b24fe272b857b6b775af3584894758157be0712683aa9c0a17baabfd90b0c976';
