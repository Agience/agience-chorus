/**
 * Centralized, product-level UI copy.
 *
 * Goals:
 * - Keep internal identifiers stable (e.g., API/entities still use "artifact").
 * - Keep the product noun, Artifact, in one place.
 * - The help glossary is `product/help/glossary.ts`.
 */

export type ProductNoun = {
  singular: string;
  plural: string;
};

export const PRODUCT_NOUN: ProductNoun = {
  singular: 'Artifact',
  plural: 'Artifacts',
} as const;

export function noun(count: number): string {
  return count === 1 ? PRODUCT_NOUN.singular : PRODUCT_NOUN.plural;
}

export function indefinite(nounSingular: string): string {
  // Minimal heuristic; good enough for UI copy.
  const first = (nounSingular || '').trim().charAt(0).toLowerCase();
  const article = ['a', 'e', 'i', 'o', 'u'].includes(first) ? 'an' : 'a';
  return `${article} ${nounSingular}`;
}
