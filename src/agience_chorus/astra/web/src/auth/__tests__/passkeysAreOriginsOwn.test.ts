/**
 * Review 7, F1: a passkey ceremony happens only on Origin's own pages, never in this web app. Origin
 * verifies every assertion against its own address, so a ceremony here could never complete, and a
 * page the web app (or Mantle, behind it) serves must never be one Origin trusts for one.
 *
 * And the web app reaches Mantle at Mantle's own address: nothing it ships calls `/api` on its own
 * host, which no longer proxies to Mantle.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { originSignInUrl } from '../originSignIn';

const SRC = join(__dirname, '..', '..');

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === '__tests__' || name === 'legacy-lumen-ui') continue;
      out.push(...sources(p));
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\./.test(name)) {
      out.push(p);
    }
  }
  return out;
}

describe('passkeys are Origin\'s own', () => {
  afterEach(() => {
    delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__;
  });

  it('runs no WebAuthn ceremony in the web app', () => {
    const hits = sources(SRC).filter((f) => /navigator\.credentials\.(get|create)/.test(
      readFileSync(f, 'utf8')));
    expect(hits).toEqual([]);
  });

  it('calls none of Origin\'s passkey ceremony routes from the web app', () => {
    const hits = sources(SRC).filter((f) =>
      /\/auth\/passkey\/(login-complete|register-options|register-complete)/.test(
        readFileSync(f, 'utf8')));
    expect(hits).toEqual([]);
  });

  it('sends a passkey sign-in to Origin\'s own sign-in page, with a state to come back on', () => {
    (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__ = {
      originUri: 'https://origin.agience.ai', mantleUri: 'https://mantle.agience.ai',
    };
    const url = new URL(originSignInUrl('ada@example.com'));
    expect(url.origin).toBe('https://origin.agience.ai');
    expect(url.pathname).toBe('/login');
    expect(url.searchParams.get('redirect_uri')).toBe(`${window.location.origin}/`);
    expect(url.searchParams.get('state')).toBeTruthy();
    expect(url.searchParams.get('login_hint')).toBe('ada@example.com');
  });

  it('ships no runtime config that reaches Mantle through the app\'s own /api', () => {
    const cfg = readFileSync(join(SRC, '..', 'public', 'config.js'), 'utf8');
    expect(cfg).not.toMatch(/mantleUri:\s*['"]\/api['"]/);
  });
});
