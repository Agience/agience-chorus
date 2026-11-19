import { afterEach, describe, expect, it } from 'vitest';
import { Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Markdown } from 'tiptap-markdown';
import { PlainMarkdownText, relaxBrackets } from './plainText';

let editor: Editor | null = null;
afterEach(() => { editor?.destroy(); editor = null; });

function roundTrip(md: string): string {
  editor = new Editor({
    extensions: [StarterKit.configure({ text: false }), PlainMarkdownText, Markdown.configure({ html: false })],
    content: md,
  });
  return (editor.storage as unknown as { markdown: { getMarkdown: () => string } }).markdown.getMarkdown();
}

describe('Markdown bodies are stored as typed', () => {
  it('keeps < and > as themselves', () => {
    expect(roundTrip('a < b and c > d')).toBe('a < b and c > d');
  });

  it('keeps brackets that cannot form a link', () => {
    expect(roundTrip('see [draft] and [x')).toBe('see [draft] and [x');
  });

  it('keeps the escape where bare brackets would make a link', () => {
    expect(roundTrip('\\[a\\](b)')).toBe('\\[a\\](b)');
  });

  it('keeps links and emphasis as Markdown', () => {
    expect(roundTrip('a [site](https://example.com) and **bold** and \\*star')).toBe(
      'a [site](https://example.com) and **bold** and \\*star',
    );
  });

  it('keeps a spaced * and a mid-line # as typed', () => {
    expect(roundTrip('2 * 3 = 6, see # 4 and a ** b')).toBe('2 * 3 = 6, see # 4 and a ** b');
  });

  it('keeps the escape where * could open emphasis or start a list', () => {
    expect(roundTrip('\\* item and \\*word\\*')).toBe('\\* item and \\*word\\*');
  });

  it('relaxes only bracket escapes', () => {
    expect(relaxBrackets('\\[x\\] \\*', '[x] *')).toBe('[x] \\*');
  });
});
