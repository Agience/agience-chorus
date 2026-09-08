// crystal/crystalModel.ts
//
// The crystal — the shareable unit of structure (Operator Architecture §12).
//
//     crystal = facets (signal conduits) + tektons (condensors) + organons (invoked by
//               condensation) ... grown on a lattice (the seed shard is inside the crystal).
//
// This is the TypeScript mirror of the Python contract at
// agience-crystal/src/crystal/crystal_model.py — the same semantics, byte-for-byte the
// same canonical JSON, the same sha. A crystal validated and hashed here is the same
// artifact a Python host validates and hashes: the sha is a stable cross-environment ref.
//
// Dependency-free on purpose (WebCrypto + TextEncoder only): the browser prism must be
// able to validate and hash a crystal before deciding to ground it — same rule as
// bundle_manifest and the Python module's stdlib-only rule.

export const CRYSTAL_CONTENT_TYPE = 'application/vnd.agience.crystal+json';

/**
 * A facet is a signal conduit, bidirectional. A human view is a facet whose far side is
 * a human; a webhook is one whose far side is a machine. `direction` declares the
 * conduit's allowed flow; "both" is the general case.
 *
 * The binding is the waveform (§12.1): a facet's contract is the signal itself, in its
 * ordered waveform, never a declared schema. `content_type` on a facet is a discovery
 * hint, never a gate; the content type is born at the tekton (condensation is "signal to
 * content type").
 */
export const FACET_DIRECTIONS = ['in', 'out', 'both'] as const;
export type FacetDirection = (typeof FACET_DIRECTIONS)[number];

export interface Facet {
  name: string;
  direction: FacetDirection;
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

export interface CrystalArtifact {
  id: string;
  name: string;
  content_type: string;
  context: string;
  content: string;
}

const REQUIRED = ['name', 'facets', 'tektons', 'created_by'] as const;

// ---------------------------------------------------------------------------
// Canonical JSON — byte-parity with CPython's json.dumps
// ---------------------------------------------------------------------------

/** Python truthiness for the validate() port: '', [], {}, 0, false, null, undefined. */
function pyFalsy(v: unknown): boolean {
  if (v == null || v === '' || v === 0 || v === false) return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === 'object') return Object.keys(v as object).length === 0;
  return false;
}

/**
 * String literal exactly as CPython's json encoder emits it (ensure_ascii=True):
 * short escapes for \" \\ \b \t \n \f \r; every other char outside printable ASCII
 * (0x20–0x7E) as lowercase \uXXXX, surrogate halves escaped individually — which is
 * exactly what a per-UTF-16-code-unit loop produces.
 */
function pyString(s: string): string {
  // RFC 8785 (JCS): raw UTF-8, no `\uXXXX` escaping of non-ASCII. `JSON.stringify` of a string is
  // exactly that — it escapes only what must be escaped (quote, backslash, control chars, and lone
  // surrogates) and passes everything else through. Matches prism-py, prism-c and prism-js, all of
  // which canonicalize to RFC 8785 / JCS.
  return JSON.stringify(s);
}

function pyNumber(n: number): string {
  if (!Number.isFinite(n)) {
    // Python emits Infinity/NaN (invalid JSON); refusing is the honest divergence.
    throw new Error('canonicalJson: non-finite number cannot be canonicalized');
  }
  // Integers byte-match Python exactly. Float seam (flagged, not silently divergent):
  // JS shortest-round-trip repr matches CPython repr for most doubles, but exponent
  // formatting differs at the extremes (JS "1e+16" thresholds differ from Python's).
  // No crystal in the codebase carries floats; if one ever does, derive the exact
  // repr rule from CPython float_repr_style rather than capping/rounding here.
  return JSON.stringify(n);
}

/**
 * Key ordering: UTF-16 code units, per RFC 8785 §3.2.3 — which is exactly what a plain
 * `Array.prototype.sort()` on strings already does in JavaScript.
 *
 * Compares code units rather than code points because JCS sorts by code units, and the two differ
 * for astral-plane characters: a surrogate pair begins at 0xD800, which sorts below U+FFFD, so
 * `{"😀":1,"�":2}` would order differently under a code-point comparison. prism-py implements the
 * same code-unit rule (`crystal_model._jcs`), so all three SDKs agree.
 */
function compareCodeUnits(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * json.dumps work-alike. `itemSep`/`kvSep` mirror Python's `separators`; `sortKeys`
 * mirrors `sort_keys` (insertion order otherwise — JS string-keyed property order is
 * insertion order, same as a Python dict).
 */
function pyDumps(v: unknown, itemSep: string, kvSep: string, sortKeys: boolean): string {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return pyNumber(v);
  if (typeof v === 'string') return pyString(v);
  if (Array.isArray(v)) {
    return '[' + v.map((x) => pyDumps(x === undefined ? null : x, itemSep, kvSep, sortKeys)).join(itemSep) + ']';
  }
  if (typeof v === 'object') {
    const rec = v as Record<string, unknown>;
    // undefined-valued properties do not exist in a Python dict — skip them.
    let keys = Object.keys(rec).filter((k) => rec[k] !== undefined);
    if (sortKeys) keys = keys.sort(compareCodeUnits);
    return (
      '{' + keys.map((k) => pyString(k) + kvSep + pyDumps(rec[k], itemSep, kvSep, sortKeys)).join(itemSep) + '}'
    );
  }
  // Python side uses default=str for anything non-serializable.
  return pyString(String(v));
}

/**
 * Sorted-keys, no-whitespace JSON — the same logical crystal always hashes the same on
 * any host. Must byte-match Python's
 * `json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")`
 * (output is pure ASCII by construction, so the string is the byte sequence).
 */
export function canonicalJson(obj: unknown): string {
  return pyDumps(obj, ',', ':', true);
}

/** json.dumps(obj, sort_keys=True) with Python's default separators (", ", ": ") — used
 * for the artifact `content` field so the wire shape byte-matches the Python builder. */
export function pythonJson(obj: unknown, sortKeys = true): string {
  return pyDumps(obj, ', ', ': ', sortKeys);
}

// ---------------------------------------------------------------------------
// The contract: sha, validate, capabilities, activation, verify
// ---------------------------------------------------------------------------

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** Content-address the structure: everything except the sha field itself. */
export async function crystalSha(crystal: Record<string, unknown>): Promise<string> {
  const body: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(crystal)) {
    if (k !== 'sha256') body[k] = v;
  }
  return sha256Hex(canonicalJson(body));
}

/**
 * Schema check — problems list ([] = valid). Loud on shape errors: an invalid crystal
 * must refuse to ground, never half-load. Semantics ported 1:1 from the Python
 * validate() (including its truthiness: an empty facets list is both "missing" and
 * "sealed").
 *
 *   name         : the crystal id
 *   facets       : [{name, direction, content_type?}] — the conduits (≥1: a crystal
 *                  with no facet is sealed glass — nothing can enter or leave)
 *   tektons      : [{name, domain}] — the condensors (≥1: nothing condenses without one)
 *   organons     : [{name, requires?}] — the invoked instruments (op.*). May be empty:
 *                  a pure-conduit crystal routes without transforming.
 *   lattice_seed : optional seed shard. State grows from here; it never ships back.
 *   created_by   : resolvable creator (provenance gates grounding — the Higgs rule)
 */
export function validate(crystal: Record<string, unknown>): string[] {
  const p: string[] = [];
  for (const k of REQUIRED) {
    if (pyFalsy(crystal[k])) p.push(`missing required field: ${k}`);
  }
  const rawFacets = crystal.facets;
  const facets: unknown[] = pyFalsy(rawFacets) ? [] : (rawFacets as unknown[]);
  const isObj = (x: unknown): x is Record<string, unknown> =>
    typeof x === 'object' && x !== null && !Array.isArray(x);
  if (!Array.isArray(facets) || (facets.length > 0 && !facets.every(isObj))) {
    p.push('facets must be a list of objects');
  } else {
    for (const f of facets as Record<string, unknown>[]) {
      if (pyFalsy(f.name)) p.push('every facet needs a name');
      if (!(FACET_DIRECTIONS as readonly unknown[]).includes(f.direction)) {
        p.push(`facet ${JSON.stringify(f.name)}: direction must be one of ${FACET_DIRECTIONS.join('|')}`);
      }
    }
    if (Array.isArray(rawFacets) && facets.length === 0) {
      p.push('a crystal needs at least one facet (a sealed crystal conducts nothing)');
    }
  }
  const rawTektons = crystal.tektons;
  const tektons: unknown[] = pyFalsy(rawTektons) ? [] : (rawTektons as unknown[]);
  if (!Array.isArray(tektons) || !tektons.every((t) => isObj(t) && !pyFalsy(t.name)) || tektons.length === 0) {
    p.push('tektons must be a non-empty list of named objects (nothing condenses without one)');
  }
  const organons = crystal.organons;
  if (organons !== undefined && organons !== null) {
    if (!Array.isArray(organons) || !organons.every((o) => isObj(o) && !pyFalsy(o.name))) {
      p.push('organons must be a list of named objects');
    }
  }
  const seed = crystal.lattice_seed;
  if (seed !== undefined && seed !== null && !isObj(seed)) {
    p.push('lattice_seed must be an object {artifacts?, collections?}');
  }
  return p;
}

/** The union of every organon's named capability requirements — what a prism must
 * advertise for this crystal to fully activate. Sorted for determinism. */
export function requiredCapabilities(crystal: { organons?: Organon[] | null }): string[] {
  const caps = new Set<string>();
  for (const o of crystal.organons ?? []) {
    for (const c of o.requires ?? []) caps.add(c);
  }
  return Array.from(caps).sort();
}

/** The bidirectional prism junction, as one subset check: every capability any organon
 * requires must be named in the prism's advertised set. Grounding-in and actuating-out
 * are the same gate. */
export function activatesOn(
  crystal: { organons?: Organon[] | null },
  prismCapabilities: string[] | null | undefined,
): boolean {
  const advertised = new Set(prismCapabilities ?? []);
  return requiredCapabilities(crystal).every((c) => advertised.has(c));
}

/** Assemble the store artifact: the crystal (structure) is the content, the sha is
 * stamped, the manifest summary rides in context. Byte-parity with the Python builder
 * (context in insertion order + default separators; content sort_keys + default
 * separators). */
export async function crystalArtifact(crystal: Crystal): Promise<CrystalArtifact> {
  const problems = validate(crystal as unknown as Record<string, unknown>);
  if (problems.length > 0) {
    throw new Error('invalid crystal: ' + problems.join('; '));
  }
  const body: Crystal = { ...crystal };
  body.sha256 = await crystalSha(body as unknown as Record<string, unknown>);
  return {
    id: body.name,
    name: body.name,
    content_type: CRYSTAL_CONTENT_TYPE,
    context: pythonJson(
      {
        sha256: body.sha256,
        facets: (body.facets ?? []).map((f) => f.name),
        tektons: (body.tektons ?? []).map((t) => t.name),
        organons: (body.organons ?? []).map((o) => o.name),
        requires: requiredCapabilities(body),
        created_by: body.created_by,
      },
      false, // Python builds context with json.dumps(...) — insertion order, no sort
    ),
    content: pythonJson(body, true),
  };
}

/** Re-hash a crystal artifact's content and refuse on mismatch — the integrity gate,
 * same refuse-before-grounding rule as the bundle runner. Returns the parsed crystal on
 * success; throws on tamper. */
export async function verify(artifact: { content: string }): Promise<Crystal> {
  const body = JSON.parse(artifact.content) as Crystal;
  const claimed = body.sha256;
  const actual = await crystalSha(body as unknown as Record<string, unknown>);
  if (claimed !== actual) {
    throw new Error(
      `crystal integrity failure: claimed sha256=${claimed} but structure hashes to ${actual} ` +
        '— refusing to ground unverified structure',
    );
  }
  return body;
}
