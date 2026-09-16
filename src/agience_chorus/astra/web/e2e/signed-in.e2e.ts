import { test, expect, type Page } from '@playwright/test';
import { readFileSync, existsSync, readdirSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath } from 'url';

/**
 * Signing in, and what the app learns from the platform once it has.
 *
 * ⚠ THE INTERESTING FAILURES ARE ALL BEHIND THE LOGIN. `ContentTypesProvider` mounts INSIDE
 * `LoginProtected` (`src/App.tsx`), so an unauthenticated page never hydrates the type registry —
 * which is how a dead `/types/all` went unnoticed for as long as it did: the route a tester reaches
 * first is the one route that never makes the call. Reaching the workspace is a precondition for
 * the assertions below, not the point of them.
 *
 * Credentials come from the environment, defaulting to a synthetic account created for this suite
 * alone. It is a username with NO EMAIL ADDRESS — registered that way deliberately, so the
 * registration path could not attempt a verification send to an address that cannot receive one.
 * It owns nothing and is not the operator of any node.
 *
 * ⚠ THESE ARE NODE-LOCAL AND THE ACCOUNT MUST EXIST ON THE NODE UNDER TEST. Measured 2026-09-15:
 * the previous defaults belonged to a throwaway origin that no longer runs, and against the real
 * node every test here failed at the sign-in step — which reads as a broken login rather than as a
 * missing fixture. Recreate with:
 *
 *   curl -X POST http://127.0.0.1:8080/auth/password/register -H 'Content-Type: application/json' \
 *     -d "{\"username\":\"e2e-facet\",\"name\":\"Facet E2E\",\"password\":\"$FACET_E2E_PASSWORD\"}"
 *
 * ⛔ THE PASSWORD HAS NO DEFAULT, AND THAT IS DELIBERATE. It used to fall back to a literal, which
 * put a working credential in a PUBLIC repository — `agience-chorus` is public, so a default here
 * is published. A test that cannot run without an environment variable is a smaller problem than a
 * password anyone can read, and the failure below says exactly what to set.
 */
const EMAIL = process.env.FACET_E2E_EMAIL ?? 'e2e-facet';

const PASSWORD = process.env.FACET_E2E_PASSWORD;
if (!PASSWORD) {
  throw new Error(
    'FACET_E2E_PASSWORD is not set. This suite signs in as the node-local `e2e-facet` account; ' +
    'set the variable to that account\'s password, or register it with the curl above. ' +
    'There is deliberately no default — this repository is public.',
  );
}

const HERE = dirname(fileURLToPath(import.meta.url));

/**
 * The content types compiled into the bundle, read the way `vite.config.ts` reads them.
 *
 * ⛔ THIS SET IS THE WHOLE REASON THE TEST BELOW MEANS ANYTHING. Facet compiles crystal's core
 * primitives in at build time, so a registry that never hydrated STILL ANSWERS for a good number
 * of real MIME types — measured 2026-09-14, 21 of them, including
 * `application/vnd.agience.prompt+json`, which reads like a persona-owned type and is not. An
 * assertion naming a type from this set passes against a completely dead `/types/all`. The
 * assertion has to be about types that can ONLY have arrived at runtime, and which those are is a
 * fact about the trees on the day — so it is computed, never written down.
 */
function compiledInContentTypes(): Set<string> {
  // The same five-up path `discoverContentTypeRoots` uses. A wrong level there silently fell back
  // to a stale committed snapshot; here it would silently empty this set and make every published
  // type look runtime-only — the failure direction that manufactures a passing test.
  const root = resolve(HERE, '../../../../../../agience-crystal/src/types');
  if (!existsSync(root)) {
    throw new Error(`build-time type root not found at ${root} — this test cannot tell compiled-in types from hydrated ones`);
  }

  const found = new Set<string>();
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, entry.name);
      if (entry.isDirectory()) { walk(p); continue; }
      if (entry.name !== 'type.json') continue;
      try {
        const raw = readFileSync(p, 'utf-8').replace(/^﻿/, '');
        const ct = JSON.parse(raw)?.content_type;
        if (typeof ct === 'string') found.add(ct.toLowerCase());
      } catch { /* a malformed definition is the build's problem, not this test's */ }
    }
  };
  walk(root);

  if (found.size === 0) {
    throw new Error(`no type.json definitions under ${root} — the comparison below would be vacuous`);
  }
  return found;
}

/** Sign in through the real form, the way a person does. */
async function signIn(page: Page) {
  await page.goto('/');

  // A node that has not been set up sends every route to the wizard. That is a different condition
  // from a failed sign-in, and worth saying out loud rather than timing out on a selector that is
  // never going to appear.
  if (page.url().includes('/setup')) {
    throw new Error('this node reports needs_setup — run the wizard, or point the suite at a configured node');
  }

  // ⚠ ADDRESSED BY id, NOT BY ROLE. The username input has only a placeholder for a name, and the
  // password input is `type="password"`, which carries no `textbox` role at all — a role query for
  // it matches nothing and fails as a timeout that reads like a broken login.
  await page.locator('#identifier').fill(EMAIL);
  await page.locator('#identifier').press('Enter');

  // The form takes the identifier first and only then offers the methods that identity has.
  const password = page.locator('#password');
  await expect(password, 'the account was not recognised at the identifier step').toBeVisible();
  await password.fill(PASSWORD);
  await password.press('Enter');

  await expect(page, 'sign-in did not leave the login page').not.toHaveURL(/\/login/, { timeout: 15_000 });
}

test.describe('signed in', () => {
  test('a password sign-in reaches the workspace', async ({ page }) => {
    await signIn(page);
    await expect(page.getByPlaceholder(/find something/i)).toBeVisible();
  });

  test('the catalogue is requested from the gateway, and answers', async ({ page }) => {
    // The registry is Crystal's: personas publish into it with `POST /register` and `/types/all`
    // reads that cache. Mantle carries a types service of its own that nothing populates, so a
    // call routed there answers an empty catalogue on every node — which reads as "this node has
    // no types" rather than as a call aimed at the wrong service.
    const calls: Array<{ url: string; status: number; type: string; count: number }> = [];

    // ⚠ A REQUEST THAT FAILS AT THE NETWORK LAYER FIRES NO `response` EVENT, so watching only for
    // responses cannot tell "the app never asked" from "the app asked and the connection failed".
    // Observed 2026-09-15 under `--workers=4`: four browser contexts reaching one gateway, and this
    // assertion reported the app as never having asked. Serially it passes every time. The two are
    // different faults with different fixes, and the message has to say which one happened.
    const failed: string[] = [];
    page.on('requestfailed', (req) => {
      if (req.url().includes('/types/all')) {
        failed.push(`${req.url()} — ${req.failure()?.errorText ?? 'unknown'}`);
      }
    });

    page.on('response', async (res) => {
      if (!res.url().includes('/types/all')) return;
      let count = -1;
      try {
        const body = await res.json();
        count = Array.isArray(body) ? body.length : (body?.types?.length ?? -1);
      } catch { /* not JSON — the status and content-type below say why */ }
      calls.push({ url: res.url(), status: res.status(), type: res.headers()['content-type'] ?? '', count });
    });

    await signIn(page);
    await page.waitForLoadState('networkidle');

    expect(
      failed,
      'the catalogue was requested and the request FAILED before any response — the gateway was '
      + 'unreachable or the connection was dropped, which is not the same as the app not asking',
    ).toEqual([]);
    expect(calls.length, 'the app never asked for the type catalogue').toBeGreaterThan(0);

    for (const c of calls) {
      expect(c.url, 'the catalogue was requested through the store, which never populates one').not.toContain('/api/types/all');
      expect(c.status, `catalogue request failed: ${c.status} ${c.url}`).toBe(200);
      expect(c.type, `the catalogue answered with the SPA shell: ${c.type}`).toContain('application/json');
      expect(c.count, `the catalogue was empty, so the app kept its build-time primitives: ${c.url}`).toBeGreaterThan(0);
    }
  });

  test('every type the platform publishes resolves in the registry', async ({ page }) => {
    // ⚠ DEV-SERVER ONLY, AND DELIBERATELY SKIPPED RATHER THAN SOFTENED. Reading the registry means
    // importing the module the app imported, which exists as a source URL only while vite is
    // serving. Against a built target that import 404s into the SPA fallback and throws a parse
    // error — a failure about the harness wearing the costume of a failure about the app.
    test.skip(!!process.env.FACET_E2E_BASE_URL,
      'registry inspection needs the dev server; set no FACET_E2E_BASE_URL to run it');

    const compiledIn = compiledInContentTypes();

    // ⚠ THE CATALOGUE IS READ FROM THE APP'S OWN RESPONSE, NOT FETCHED AGAIN HERE. `api.ts` routes
    // `/types/*` to `CRYSTAL_URI` from the runtime config, so a relative `fetch('/types/all')` in
    // the page addresses the dev server instead of the gateway and answers with something that is
    // not the catalogue — measured here, an empty body that failed to parse. Constructing the URL a
    // second time is re-implementing the routing this suite exists to check.
    // A SET, BECAUSE THE CALL HAPPENS MORE THAN ONCE. React's StrictMode double-mounts effects in
    // development, so `ContentTypesProvider` fetches the catalogue twice and a list accumulates
    // every type twice over — harmless to the comparison, but it doubles the count in the failure
    // message, and a diagnostic that reports 72 of something when there are 36 is one a reader has
    // to distrust.
    const published = new Set<string>();
    page.on('response', async (res) => {
      if (!res.url().includes('/types/all') || res.status() !== 200) return;
      try {
        const body = await res.json();
        const list = Array.isArray(body) ? body : (body?.types ?? []);
        for (const t of list) if (t?.content_type) published.add(t.content_type);
      } catch { /* the test above is the one that reports a non-JSON catalogue */ }
    });

    await signIn(page);
    await page.waitForLoadState('networkidle');

    expect(published.size, 'the app received no type catalogue to compare against').toBeGreaterThan(0);

    // The types that can only have come from the platform. If this set is empty the comparison
    // proves nothing, and saying so is the point — a vacuous assertion that reports success is
    // indistinguishable from a working one.
    const runtimeOnly = [...published].filter((ct) => !compiledIn.has(ct.toLowerCase()));
    expect(
      runtimeOnly.length,
      `every published type is also compiled in (published ${published.size}, compiled-in ${compiledIn.size}) — this test cannot distinguish a hydrated registry from a dead one`,
    ).toBeGreaterThan(0);

    const unresolved: string[] = await page.evaluate(async (wanted: string[]) => {
      const reg = await import('/src/registry/content-types.ts');
      return wanted.filter((ct) => !reg.getContentTypeById(ct));
    }, runtimeOnly);

    expect(
      unresolved,
      `types the platform publishes and the registry does not hold — the catalogue did not reach the registry (${runtimeOnly.length} runtime-only types checked)`,
    ).toEqual([]);
  });
});
