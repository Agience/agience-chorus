/**
 * Preview options that keep @uiw/react-md-editor's live preview from rendering artifact content
 * as live HTML.
 *
 * @uiw/react-markdown-preview always inserts `rehype-raw`, which turns raw HTML in the markdown
 * (`<iframe srcdoc>`, `<img onerror>`, `<script>`) into real elements, and its default
 * `urlTransform` passes every URL through unchanged, `javascript:` included. These options drop
 * `rehype-raw` from the rehype plugin list, so raw HTML renders as text, and allow only relative
 * URLs and http, https and mailto links.
 */

import rehypeRaw from 'rehype-raw';
import type { MDEditorProps } from '@uiw/react-md-editor';

const SAFE_PROTOCOL = /^(https?|mailto)$/i;

/**
 * A URL as written when it is relative or uses a safe protocol; otherwise the empty string.
 * The scheme test is the one react-markdown's own `defaultUrlTransform` makes: a colon before any
 * `/`, `?` or `#` names a protocol, and anything that is not on the list is dropped.
 */
export function safeMarkdownUrl(url: string): string {
  const colon = url.indexOf(':');
  const questionMark = url.indexOf('?');
  const numberSign = url.indexOf('#');
  const slash = url.indexOf('/');
  if (
    colon === -1 ||
    (slash !== -1 && colon > slash) ||
    (questionMark !== -1 && colon > questionMark) ||
    (numberSign !== -1 && colon > numberSign) ||
    SAFE_PROTOCOL.test(url.slice(0, colon))
  ) {
    return url;
  }
  return '';
}

export const SAFE_MARKDOWN_PREVIEW_OPTIONS: NonNullable<MDEditorProps['previewOptions']> = {
  pluginsFilter: (type, plugins) =>
    type === 'rehype'
      ? plugins.filter((plugin) => (Array.isArray(plugin) ? plugin[0] : plugin) !== rehypeRaw)
      : plugins,
  urlTransform: safeMarkdownUrl,
};
