/**
 * FR-023: the app's font comes from its own build. A page load reaches no font host, so no third
 * party learns the app's address or who opens it.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const WEB = join(__dirname, '..', '..');
const FONT_HOSTS = /fonts\.googleapis\.com|fonts\.gstatic\.com/;

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === '__tests__') continue;
      out.push(...sources(p));
    } else if (/\.(ts|tsx|css|html)$/.test(name)) {
      out.push(p);
    }
  }
  return out;
}

describe('the app serves its own font', () => {
  it('index.html and the sources name no font host', () => {
    const files = [join(WEB, 'index.html'), ...sources(join(WEB, 'src'))];
    const hits = files.filter((f) => FONT_HOSTS.test(readFileSync(f, 'utf8')));
    expect(hits).toEqual([]);
  });

  it('DM Sans is declared from the bundled files, and loaded first', () => {
    const css = readFileSync(join(WEB, 'src', 'fonts.css'), 'utf8');
    expect(css).toMatch(/font-family: 'DM Sans';/);
    const urls = [...css.matchAll(/url\('([^']+)'\)/g)].map((m) => m[1]);
    expect(urls.length).toBe(4);
    for (const u of urls) {
      // A path relative to the stylesheet, so Vite resolves the file and emits it as an asset; a
      // bare package name is copied through unresolved and the browser gets index.html.
      expect(u.startsWith('../node_modules/@fontsource-variable/dm-sans/files/')).toBe(true);
      expect(existsSync(join(WEB, 'src', u))).toBe(true);
    }
    const entry = readFileSync(join(WEB, 'src', 'index.tsx'), 'utf8');
    expect(entry.indexOf("import './fonts.css'")).toBeGreaterThan(-1);
  });
});
