import { test, expect, type Request, type Response } from '@playwright/test';

/**
 * What the app asks for before anyone touches it, and what comes back.
 *
 * Every defect this file exists for was invisible to the jsdom suite, because that suite replaces
 * `src/api/api` with a mock that answers every verb `{data: {}}` — the shape the author intended,
 * never the shape the server has. These assertions need a real browser and a real node.
 *
 * ⛔ AN API PATH ANSWERED WITH HTML IS THE FAILURE THAT HIDES. Every host serving this app ends in
 * an SPA fallback (`try_files {path} /index.html`), so a request to a path with no route does not
 * 404 — it returns `index.html` at 200. Axios then fails to parse it, leaves `data` as a string,
 * and the caller reads `undefined` off it. Measured twice in one week: `/types/all` and
 * `/system/settings` both answered 200-with-HTML in production, and no error surfaced anywhere.
 */

/** Requests the app makes of a service, as opposed to fetching its own assets. */
const API_PATH = /\/(api|auth|setup|system|types|artifacts|grants|version)(\/|$|\?)/;

/** Vite's dev-server plumbing, which is not the app talking to a service. */
const DEV_NOISE = /\/@(vite|react-refresh|fs|id)|\/node_modules\/|\.(ts|tsx|js|css|svg|png|woff2?)(\?|$)/;

function isApiCall(req: Request): boolean {
  const url = req.url();
  return API_PATH.test(url) && !DEV_NOISE.test(url);
}

test.describe('booting the app', () => {
  test('no service call is answered with HTML', async ({ page }) => {
    const htmlForJson: string[] = [];

    page.on('response', async (res: Response) => {
      if (!isApiCall(res.request())) return;
      const type = res.headers()['content-type'] ?? '';
      if (type.includes('text/html')) {
        htmlForJson.push(`${res.status()} ${type} — ${res.request().method()} ${res.url()}`);
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    expect(
      htmlForJson,
      'a service path answered with the SPA shell: the route does not exist and the fallback took it',
    ).toEqual([]);
  });

  test('every service call succeeds', async ({ page }) => {
    const failed: string[] = [];

    page.on('response', (res: Response) => {
      if (!isApiCall(res.request())) return;
      // 401 is a real answer before sign-in — it means the service was reached and declined.
      // A 4xx that is NOT 401, or any 5xx, means the call did not land where it was aimed.
      const status = res.status();
      if (status >= 400 && status !== 401) {
        failed.push(`${status} ${res.request().method()} ${res.url()}`);
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    expect(failed, 'service calls the app makes on load must reach a route that exists').toEqual([]);
  });

  test('the console is clean on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Every CORS refusal, failed fetch and unhandled rejection lands here. On 2026-09-13 this
    // page logged eight of them — four blocked requests, doubled — while rendering a login form
    // that looked entirely correct.
    expect(errors, 'the app logged errors while loading').toEqual([]);
  });

  test('the shell renders rather than a blank page', async ({ page }) => {
    await page.goto('/');
    // Not a screenshot assertion: a page can paint convincingly while every call behind it failed,
    // which is exactly what happened here. This only asserts the app mounted at all; the tests
    // above are what decide whether it is actually working.
    await expect(page.locator('#root, body > div').first()).toBeVisible();
  });
});
