// crystal/crystalModel.ts
//
// The crystal — the shareable unit of structure (Operator Architecture §12).
//
//     crystal = facets (signal conduits) + tektons (condensors) + organons (invoked by
//               condensation) ... grown on a lattice (the seed shard is inside the crystal).
//
// The shapes the web app displays. Crystal owns the contract: it checks a crystal's
// structure, its sha and its reach over a prism's capabilities (`POST /crystals/activate`);
// the web app sends the crystal and shows the answer.

/**
 * A facet is a signal conduit, bidirectional. A human view is a facet whose far side is
 * a human; a webhook is one whose far side is a machine. `direction` declares the
 * conduit's allowed flow; "both" is the general case. `content_type` is a discovery
 * hint, never a gate (§12.1).
 */
export interface Facet {
  name: string;
  direction: 'in' | 'out' | 'both';
  /** Discovery hint, never a gate (§12.1). */
  content_type?: string;
}

export interface Tekton {
  name: string;
  domain?: string;
}

export interface Organon {
  name: string;
  /** Named capabilities this organon needs the prism to advertise. */
  requires?: string[];
}

export interface LatticeSeed {
  artifacts?: unknown[];
  collections?: string[];
}

export interface Crystal {
  name: string;
  facets: Facet[];
  tektons: Tekton[];
  organons?: Organon[];
  lattice_seed?: LatticeSeed;
  created_by: string;
  sha256?: string;
}
