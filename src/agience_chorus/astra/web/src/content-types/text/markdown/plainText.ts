import { Node } from '@tiptap/react';

/** The serializer's slice of tiptap-markdown's state that this node writes through. */
interface SerializerState {
  out: string;
  text: (text: string, escape?: boolean) => void;
}

/**
 * Text that could read as a link or a reference once its brackets are bare: `[a](b)`,
 * `[a][b]`, `[a]: b`, `[^a]`, or an autolink-looking `<…>` is not at stake (raw HTML is off).
 */
const LINK_SHAPED = /\]\s*[([:]|\[\^/;

/**
 * A run of `*` or `_` with whitespace on both sides is neither left- nor right-flanking, so it
 * can neither open nor close emphasis: `a * b` is stored without a backslash.
 */
const SPACED_DELIMITERS = /(?<=\s)((?:\\[*_])+)(?=\s)/g;

/** Escapes back to the typed character wherever the bare character cannot change the meaning. */
export function relaxBrackets(written: string, source: string): string {
  const spaced = written.replace(SPACED_DELIMITERS, (run) => run.replace(/\\/g, ''));
  if (LINK_SHAPED.test(source)) return spaced;
  return spaced.replace(/\\([[\]])/g, '$1');
}

/**
 * The text node, serialized as the author typed it. The editor reads Markdown with raw HTML
 * off, so `<` and `>` are stored as themselves rather than as `&lt;` and `&gt;`; brackets are
 * escaped only where bare ones would turn the text into a link. Emphasis and code markers are
 * still escaped, so a typed `*` stays a `*`.
 */
export const PlainMarkdownText = Node.create({
  name: 'text',
  group: 'inline',

  addStorage() {
    return {
      markdown: {
        serialize(state: SerializerState, node: { text?: string }) {
          const text = node.text ?? '';
          const start = state.out.length;
          state.text(text);
          state.out = state.out.slice(0, start) + relaxBrackets(state.out.slice(start), text);
        },
        parse: {},
      },
    };
  },
});
