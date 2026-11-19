/**
 * On-screen lists: what the viewer has selected, opened, dragged, docked or typed. These helpers
 * work on any list of keys or items and know nothing of artifacts, types or people. What a list
 * shows comes from Mantle and Crystal; these only keep the screen's own lists in step with what
 * the viewer does.
 */

type Absent = null | undefined | false | '';

/** The entries that are there: no null, undefined, false or empty string. */
export function present<T>(items: readonly (T | Absent)[]): T[] {
  const out: T[] = [];
  for (const item of items) if (item !== null && item !== undefined && item !== false && item !== '') out.push(item as T);
  return out;
}

/** A list of keys from a payload: each entry as trimmed text, empties dropped. Not a list gives []. */
export function keyList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const item of raw) {
    const key = String(item ?? '').trim();
    if (key) out.push(key);
  }
  return out;
}

/** Typed text split on `separator`, each part trimmed, empties dropped. */
export function splitList(text: string, separator: string | RegExp = ','): string[] {
  return keyList(text.split(separator));
}

/** The text entries of a payload list, as given; anything else is dropped. */
export function textEntries(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const item of raw) if (typeof item === 'string' && item !== '') out.push(item);
  return out;
}

/** The list without `item`. */
export function without<T>(items: readonly T[], item: T): T[] {
  const out: T[] = [];
  for (const each of items) if (each !== item) out.push(each);
  return out;
}

/** The list without the entries whose key is `key`. */
export function withoutKey<T>(items: readonly T[], keyOf: (item: T) => unknown, key: unknown): T[] {
  const out: T[] = [];
  const wanted = String(key);
  for (const each of items) if (String(keyOf(each)) !== wanted) out.push(each);
  return out;
}

/** Only the entries whose key is `key`. */
export function withKey<T>(items: readonly T[], keyOf: (item: T) => unknown, key: unknown): T[] {
  const out: T[] = [];
  const wanted = String(key);
  for (const each of items) if (String(keyOf(each)) === wanted) out.push(each);
  return out;
}

/** `item` added when absent, taken out when present. */
export function toggle<T>(items: readonly T[], item: T): T[] {
  return items.includes(item) ? without(items, item) : [...items, item];
}

/** `item` moved (or added) to the end: the window or tab the viewer last touched. */
export function toEnd<T>(items: readonly T[], item: T): T[] {
  return [...without(items, item), item];
}

/** Each entry once, in first-seen order. */
export function unique<T>(items: Iterable<T>): T[] {
  return Array.from(keySet(items));
}

/** The entries also in `keep`, in list order. */
export function onlyIn<T>(items: readonly T[], keep: Iterable<T>): T[] {
  const set = keySet(keep);
  const out: T[] = [];
  for (const each of items) if (set.has(each)) out.push(each);
  return out;
}

/** The entries not in `drop`, in list order. */
export function notIn<T>(items: readonly T[], drop: Iterable<T>): T[] {
  const set = keySet(drop);
  const out: T[] = [];
  for (const each of items) if (!set.has(each)) out.push(each);
  return out;
}

/** The entries of `items` whose key is in `keys`, in list order. */
export function keyedIn<T>(items: readonly T[], keyOf: (item: T) => unknown, keys: Iterable<string>): T[] {
  const set = keySet(keys);
  const out: T[] = [];
  for (const each of items) if (set.has(String(keyOf(each)))) out.push(each);
  return out;
}

/** The entries of `items` whose key is not in `keys`, in list order. */
export function keyedNotIn<T>(items: readonly T[], keyOf: (item: T) => unknown, keys: Iterable<unknown>): T[] {
  const set = keySet([...keys].map(String));
  const out: T[] = [];
  for (const each of items) if (!set.has(String(keyOf(each)))) out.push(each);
  return out;
}

/** `keys` looked up in `byKey`, in key order; keys with nothing there are dropped. */
export function lookUp<K, V>(keys: readonly K[], byKey: ReadonlyMap<K, V>): V[] {
  const out: V[] = [];
  for (const key of keys) {
    const value = byKey.get(key);
    if (value !== undefined) out.push(value);
  }
  return out;
}

/** A set of the given keys; none gives an empty set. */
export function keySet<T>(items: Iterable<T> = []): Set<T> {
  return new Set(items);
}

/** A new set with `key` added when absent, taken out when present. */
export function toggleInSet<T>(set: ReadonlySet<T>, key: T): Set<T> {
  const next = keySet(set);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

/** A new set with `key` added. */
export function addToSet<T>(set: ReadonlySet<T>, key: T): Set<T> {
  return keySet(set).add(key);
}

/** A new set with `key` taken out. */
export function removeFromSet<T>(set: ReadonlySet<T>, key: T): Set<T> {
  const next = keySet(set);
  next.delete(key);
  return next;
}

/** Whether the two hold the same keys, in any order. */
export function sameKeys<T>(a: Iterable<T>, b: Iterable<T>): boolean {
  const left = keySet(a);
  const right = keySet(b);
  if (left.size !== right.size) return false;
  for (const key of left) if (!right.has(key)) return false;
  return true;
}

/** The keys of `group` moved, in `current`'s order, to stand before index `at` of what remains. */
export function moveGroup<T>(current: readonly T[], group: Iterable<T>, at: number): T[] {
  const moving = keySet(group);
  const remaining = notIn(current, moving);
  const moved = onlyIn(current, moving);
  const index = Math.max(0, Math.min(at, remaining.length));
  return [...remaining.slice(0, index), ...moved, ...remaining.slice(index)];
}

/** A new array in on-screen order: by each key in turn, text by locale and numbers ascending. */
export function sortedBy<T>(items: Iterable<T>, ...keys: Array<(item: T) => string | number>): T[] {
  return Array.from(items).sort((a, b) => {
    for (const key of keys) {
      const left = key(a);
      const right = key(b);
      const order = typeof left === 'number' && typeof right === 'number'
        ? left - right
        : String(left).localeCompare(String(right));
      if (order !== 0) return order;
    }
    return 0;
  });
}

/** The times at or after `start`: the viewer's own recent actions. */
export function since(times: readonly number[], start: number): number[] {
  const out: number[] = [];
  for (const time of times) if (time >= start) out.push(time);
  return out;
}
