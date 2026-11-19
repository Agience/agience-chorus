/**
 * A short fingerprint of a value as the screen holds it, the same whatever order its keys were
 * written in: an editor compares it with the saved copy's to show unsaved changes. Not
 * cryptographic.
 */
export function fingerprint(value: unknown): string {
  const input = JSON.stringify(withKeysInOrder(value));
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

function withKeysInOrder(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withKeysInOrder);
  if (!value || typeof value !== 'object') return value;
  const obj = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(obj).sort()) out[k] = withKeysInOrder(obj[k]);
  return out;
}
