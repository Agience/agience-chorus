import { defineConfig, devices } from '@playwright/test'

// Browser-level tests for Facet. Distinct from the vitest suite in `tests/`, which runs
// components under jsdom with the API module mocked: these drive a real Chrome against a
// real build, so they see layout, focus, cross-origin redirects and actual network traffic.
//
// Specs are named `*.e2e.ts`, not `*.spec.ts`. Vitest's default `include` matches
// `*.{test,spec}.*` anywhere under the root, so the `.e2e.ts` suffix is what keeps the two
// runners from collecting each other's files — `npm test` and `npm run test:e2e` stay
// disjoint without either config having to exclude the other.

const PORT = Number(process.env.FACET_E2E_PORT ?? 5173)

// Point at an already-running target (a deployed Facet, or a dev server you started
// yourself) by setting FACET_E2E_BASE_URL. When it is set, no dev server is started here.
const EXTERNAL_TARGET = process.env.FACET_E2E_BASE_URL
const BASE_URL = EXTERNAL_TARGET ?? `http://localhost:${PORT}`

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',

  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    // Traces open with `npx playwright show-trace <file>`: a DOM snapshot per step,
    // plus network, console and a timeline.
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    testIdAttribute: 'data-testid',
  },

  projects: [
    {
      name: 'chrome',
      // `channel: 'chrome'` drives the installed Google Chrome rather than Playwright's
      // bundled Chromium — the same browser the MCP server is configured to use, so a
      // session driven interactively and a committed spec exercise the same engine.
      use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    },
  ],

  // `--strictPort` because the config hard-codes the URL above: without it vite silently
  // moves to the next free port and the runner waits on a port nothing is serving.
  webServer: EXTERNAL_TARGET
    ? undefined
    : {
        command: `npm run dev -- --port ${PORT} --strictPort`,
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
})
