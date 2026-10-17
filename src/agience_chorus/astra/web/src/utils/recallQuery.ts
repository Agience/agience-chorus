// utils/recallQuery.ts
//
// The search panel's choices, written into the recall query. Mantle's recall takes its filters
// inside `query_text`, as `field:value` (`artifacts_router.recall_artifacts`): `tag:` and `type:`
// match case-insensitively, `a,b` is any-of, `field:="Exact"` is taken whole, and `="a phrase"`
// matches the words exactly. A query of nothing but filters is refused: a filter narrows a
// recall and does not make one. 2026-10-13, a tester found every panel control ignored, because
// none of them reached the query.

/** The panel's type choices, each the content types it stands for. Recall matches a content
 * type exactly, so a broad choice lists its members. */
export const TYPE_GROUPS: Record<string, { label: string; types: string[] }> = {
  text: { label: 'Text', types: ['text/plain', 'text/markdown', 'text/html'] },
  markdown: { label: 'Markdown', types: ['text/markdown'] },
  plain: { label: 'Plain text', types: ['text/plain'] },
  image: { label: 'Image', types: ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml'] },
  video: { label: 'Video', types: ['video/mp4', 'video/webm', 'video/quicktime'] },
  audio: { label: 'Audio', types: ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/mp4'] },
  pdf: { label: 'PDF', types: ['application/pdf'] },
  office: {
    label: 'Office',
    types: [
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      'application/msword', 'application/vnd.ms-excel', 'application/vnd.ms-powerpoint',
    ],
  },
};

export type RecallChoices = {
  text: string;
  /** "Exact words": the text matches as a phrase. */
  exact?: boolean;
  tag?: string;
  /** The tag matches whole and case-sensitively instead of case-insensitively. */
  tagExact?: boolean;
  /** A key of `TYPE_GROUPS`, or empty for every type. */
  typeGroup?: string;
};

/** `{ query }` to send, or `{ error }` when the choices cannot make a recall. */
export function composeRecallQuery(c: RecallChoices): { query: string } | { error: string } {
  const text = c.text.trim();
  const parts: string[] = [];
  if (text) parts.push(c.exact ? `="${text.replace(/"/g, '')}"` : text);
  const tag = (c.tag ?? '').trim();
  if (tag) parts.push(c.tagExact ? `tag:="${tag.replace(/"/g, '')}"` : `tag:${tag.replace(/\s+/g, '')}`);
  const group = c.typeGroup ? TYPE_GROUPS[c.typeGroup] : undefined;
  if (group) parts.push(`type:${group.types.join(',')}`);
  if (!text) {
    return { error: parts.length ? 'Filters narrow a search: add a word to search for.' : '' };
  }
  return { query: parts.join(' ') };
}
