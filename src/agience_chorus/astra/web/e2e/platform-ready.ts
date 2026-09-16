/**
 * Refuse to start until the platform behind the app is actually serving.
 *
 * ⛔ A COLD PLATFORM FAILS THESE TESTS AS IF THE APP WERE BROKEN. Observed twice on 2026-09-15,
 * both times within a minute of restarting the stack: `no service call is answered with HTML`,
 * `every service call succeeds` and `the console is clean on load` all went red, and the signed-in
 * catalogue test reported *"the app never asked for the type catalogue"*. Nothing was wrong with
 * Facet. Crystal had come up with an empty registry and the personas had not finished registering —
 * which the host's watchdog completes on a 30-second tick, so the suite was racing it.
 *
 * ⚠ THE FAILURE MESSAGES POINTED AT THE APP, WHICH IS WHY THIS EXISTS. A test naming a symptom in
 * the browser, when the cause is a service that has not finished starting, sends a reader to read
 * Facet's source. Both times I re-ran the suite and it passed, which is the other half of the
 * problem: a green re-run teaches you to re-run rather than to look.
 *
 * So the readiness of the platform is checked ONCE, before any test, and a platform that is not
 * ready fails here — naming the service and what it reported — rather than fifty lines into a
 * browser assertion.
 *
 * ⚠ THIS IS A PRECONDITION, NOT A RETRY. It waits for a stack that is still starting; it does not
 * paper over one that is broken. When the wait runs out it says which check never passed, and the
 * suite does not run at all — a suite that cannot trust its fixture should not report on the app.
 */
import type { FullConfig } from '@playwright/test';

const GATEWAY = process.env.FACET_E2E_GATEWAY ?? 'http://127.0.0.1:8085';
const ORIGIN = process.env.FACET_E2E_ORIGIN ?? 'http://127.0.0.1:8080';
const STORE = process.env.FACET_E2E_STORE ?? 'http://127.0.0.1:8082';

/** How long a cold stack is given. The persona re-registration watchdog ticks every 30s. */
const READY_TIMEOUT_MS = Number(process.env.FACET_E2E_READY_TIMEOUT_MS ?? 75_000);
const POLL_MS = 2_000;

type Check = { name: string; url: string; ok: (res: Response) => Promise<string | null> };

const CHECKS: Check[] = [
  {
    name: 'origin publishes its key set',
    url: `${ORIGIN}/.well-known/jwks.json`,
    // Origin is proved by its keys, not by its port: an authority that is listening but publishes
    // no key set is one no peer could verify.
    async ok(res) {
      if (!res.ok) return `HTTP ${res.status}`;
      const body = await res.json().catch(() => null);
      const keys = body?.keys;
      return Array.isArray(keys) && keys.length > 0 ? null : 'no keys in the JWKS';
    },
  },
  {
    name: 'the store answers',
    url: `${STORE}/status`,
    async ok(res) {
      return res.ok ? null : `HTTP ${res.status}`;
    },
  },
  {
    name: 'the gateway holds a populated registry',
    url: `${GATEWAY}/health`,
    // ⛔ THE ONE THAT ACTUALLY RACES. Crystal answers /health the moment it binds, with
    // `personas_known: 0`, and the app then hydrates from an empty catalogue and falls back to its
    // build-time primitives — which is indistinguishable, from the browser, from a broken gateway.
    async ok(res) {
      if (!res.ok) return `HTTP ${res.status}`;
      const body = await res.json().catch(() => null);
      const personas = body?.personas_known ?? 0;
      const types = body?.types_known ?? 0;
      if (personas < 1) return `personas_known is ${personas} — the host has not registered yet`;
      if (types < 1) return `types_known is ${types} — the catalogue is empty`;
      return null;
    },
  },
];

async function probe(check: Check): Promise<string | null> {
  try {
    const res = await fetch(check.url, { signal: AbortSignal.timeout(5_000) });
    return await check.ok(res);
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  let last: Record<string, string | null> = {};

  for (;;) {
    const results = await Promise.all(CHECKS.map(probe));
    last = Object.fromEntries(CHECKS.map((c, i) => [c.name, results[i]]));
    if (results.every((r) => r === null)) return;

    if (Date.now() >= deadline) {
      const failing = CHECKS
        .map((c, i) => (results[i] ? `  · ${c.name} (${c.url}): ${results[i]}` : null))
        .filter(Boolean)
        .join('\n');
      throw new Error(
        `the platform is not ready after ${Math.round(READY_TIMEOUT_MS / 1000)}s, so these tests `
        + `would report a cold stack as an application fault:\n${failing}\n\n`
        + `Start the node (the Agience tray supervises it) and re-run. If it IS running, the check `
        + `above names the service that is not answering — that is where to look, not in Facet.`,
      );
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
}

/** Exposed so the readiness logic itself can be exercised without a running platform. */
export const _internals = { CHECKS, probe };
