/**
 * The markdown editor's live preview renders artifact content. Raw HTML in that content must not
 * become live elements, and link/image URLs are limited to relative, http(s) and mailto.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';

import { MarkdownEditor } from '../MarkdownEditor';
import { safeMarkdownUrl } from '../safeMarkdownPreview';

const HOSTILE_MARKDOWN = [
  '# Title',
  '',
  '<iframe srcdoc="<script>parent.pwned=1</script>"></iframe>',
  '',
  '<script>window.pwned = 1</script>',
  '',
  '<img src="x" onerror="window.pwned = 1">',
  '',
  '[click](javascript:alert(document.domain))',
  '',
  '[ok](https://example.com/page)',
].join('\n');

describe('markdown editor preview', () => {
  it('does not turn raw HTML into live elements', async () => {
    const { container } = render(
      <MarkdownEditor content={HOSTILE_MARKDOWN} onChange={vi.fn()} autoFocus={false} />,
    );
    const preview = await waitFor(() => {
      const el = container.querySelector('.wmde-markdown');
      expect(el?.querySelector('h1')).not.toBeNull();
      return el as HTMLElement;
    });

    expect(preview.querySelector('iframe')).toBeNull();
    expect(preview.querySelector('script')).toBeNull();
    expect(preview.querySelector('img[onerror]')).toBeNull();
    expect(preview.querySelector('[srcdoc]')).toBeNull();
  });

  it('drops javascript: links and keeps https links', async () => {
    const { container } = render(
      <MarkdownEditor content={HOSTILE_MARKDOWN} onChange={vi.fn()} autoFocus={false} />,
    );
    const preview = await waitFor(() => {
      const el = container.querySelector('.wmde-markdown');
      expect(el?.querySelector('h1')).not.toBeNull();
      return el as HTMLElement;
    });

    const hrefs = Array.from(preview.querySelectorAll('a[href]')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('https://example.com/page');
    expect(hrefs.some((h) => /^\s*javascript:/i.test(h ?? ''))).toBe(false);
  });

  it.each([
    ['https://example.com/a', 'https://example.com/a'],
    ['mailto:someone@example.com', 'mailto:someone@example.com'],
    ['/relative/path', '/relative/path'],
    ['#anchor', '#anchor'],
    ['javascript:alert(1)', ''],
    [' javascript:alert(1)', ''],
    ['data:text/html,x', ''],
    ['vbscript:x', ''],
  ])('safeMarkdownUrl(%j) is %j', (input, expected) => {
    expect(safeMarkdownUrl(input)).toBe(expected);
  });

  it('every MDEditor in the app passes the safe preview options', () => {
    // Vitest runs from the web app root.
    const srcRoot = join(process.cwd(), 'src');
    const offenders: string[] = [];
    let seen = 0;
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) {
          if (name !== '__tests__' && name !== 'node_modules') walk(path);
          continue;
        }
        if (!/\.(tsx|jsx)$/.test(name)) continue;
        const source = readFileSync(path, 'utf8');
        for (const match of source.matchAll(/<MDEditor\b[\s\S]*?\/>/g)) {
          seen += 1;
          if (!match[0].includes('previewOptions={SAFE_MARKDOWN_PREVIEW_OPTIONS}')) {
            offenders.push(path);
          }
        }
      }
    };
    walk(srcRoot);
    // MarkdownEditor and CardEditor each render one.
    expect(seen).toBeGreaterThanOrEqual(2);
    expect(offenders).toEqual([]);
  });
});
