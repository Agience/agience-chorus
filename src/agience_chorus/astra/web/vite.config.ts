import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { existsSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'
import { contentTypesPlugin } from './plugins/content-types-plugin'
import { buildInfo } from './plugins/build-info'

// Get __dirname equivalent in ES modules
const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

function firstExisting(paths: Array<string | undefined>): string | undefined {
  return paths.find((p): p is string => !!p && existsSync(p))
}

// Where the dev proxy sends what it takes. These are the ports `agience.py start` serves on, not
// the 8081 that mantle and crystal each declare as their own developer default — that port serves
// nothing under this installer.
const DEV_ORIGIN = process.env.VITE_DEV_ORIGIN ?? 'http://127.0.0.1:8080'

// The footer shows the platform release this build is for and the agience-chorus commit it was
// built from, both as they appear on GitHub [John, 2026-11-09; replaces 2026-09-13's own cadence
// for the facet]. `plugins/build-info.ts` is the one place either is read; `package.json`'s
// `version` is not displayed anywhere. A build that is not a platform release shows `dev`.
const BUILD = buildInfo(process.env)
const APP_BUILD_TIME: string = new Date().toISOString()

function discoverContentTypeRoots() {
  // facet/vite.config.ts -> __dirname = <repo>/src/facet
  //
  // Build-time scope is core primitives only — a synchronous bootstrap so first paint has the
  // platform chrome. Facet does not scan the chorus persona ui/ trees: server-owned types (and
  // their viewers) are fetched at runtime from the platform (GET /types/all →
  // ContentTypesProvider). Facet must not know about specific servers (they live in different
  // instances). Missing -> [] — no primitives baked in, everything resolves at runtime.
  //
  // ⛔ COUNT THE LEVELS AGAINST THE REAL PATH, NOT AGAINST A REMEMBERED ONE. This tree sits at
  // `agience-chorus/src/agience_chorus/astra/web`, so the workspace root is FIVE up. A four-up
  // path resolves to `agience-chorus/agience-crystal`, which exists nowhere — measured 2026-09-13,
  // both this fallback and `scripts/vendor-build-inputs.mjs` had it wrong in the same way, and the
  // build quietly used a committed snapshot instead: 57 files against crystal's 59, two
  // `behaviors.json` already diverged, and no gate anywhere compared them.
  const root = firstExisting([
    resolve(__dirname, '../../../../../agience-crystal/src/crystal/types'),
  ])
  return root ? [root] : []
}

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(BUILD.release),
    __APP_BUILD_TIME__: JSON.stringify(APP_BUILD_TIME),
    __APP_GIT_SHA__: JSON.stringify(BUILD.sha),
  },
  plugins: [
    react({
      // Enable SVG as React components
      // Include .jsx for component tests
      include: '**/*.{js,jsx,tsx}',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    }) as unknown as any,
    // Reads types/**/{type.json,presentation.json}, resolves inheritance,
    // exposes as the virtual module `virtual:content-types`.
    contentTypesPlugin(discoverContentTypeRoots()),
    // ⭐ `/version.json` IS GENERATED, from what the footer shows: the release (`dev` when the
    // build is not one), the commit and the build time. A hand-kept copy is a second answer to
    // "what is deployed" that nothing refreshes.
    //
    // ⚠ NOTHING IN THIS TREE READS IT, which is exactly why it rotted: no screen went blank and no
    // test failed. It stays published rather than deleted because it is a public URL and this
    // repository cannot prove what outside it polls that URL; generated, it is at worst harmless
    // and at best correct.
    //
    // ⛔ THERE MUST BE NO `public/version.json`. Vite copies `public/` over the build output, so a
    // file there would silently win and restore the stale value with no warning anywhere.
    {
      name: 'agience-version-json',
      apply: 'build',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'version.json',
          source: JSON.stringify(
            { version: BUILD.release || 'dev', build_time: APP_BUILD_TIME, git_sha: BUILD.sha },
            null,
            2,
          ) + '\n',
        })
      },
    },
  ],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    env: {
      VITE_MANTLE_URI: 'http://localhost:8082',
      VITE_CLIENT_ID: 'test-client-id',
    },
  },
  base: '/',
  // Load .env files from root directory (parent of facet/)
  envDir: resolve(__dirname, '..'),
  // Allow selected non-VITE_ env vars (STREAM_*, FRONTEND_*) to be exposed to import.meta.env
  envPrefix: ['VITE_', 'STREAM_', 'FRONTEND_'],
  // Handle SVG imports
  assetsInclude: ['**/*.svg'],
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
      'react': resolve(__dirname, './node_modules/react'),
      'react/jsx-runtime': resolve(__dirname, './node_modules/react/jsx-runtime.js'),
      'react/jsx-dev-runtime': resolve(__dirname, './node_modules/react/jsx-dev-runtime.js'),
      'react-dom': resolve(__dirname, './node_modules/react-dom'),
      'lucide-react': resolve(__dirname, './node_modules/lucide-react'),
      'sonner': resolve(__dirname, './node_modules/sonner'),
    },
  },
  server: {
    host: true,  // bind to 0.0.0.0 so home.agience.ai (→ 127.0.0.1) is reachable

    // ⭐ ORIGIN IS REACHED THROUGH THE DEV SERVER, SAME-ORIGIN. `public/config.js` sets
    // `originUri: '/'` for local development, so the web app's calls to Origin, and Origin's own
    // pages (sign-in, passkeys, the account page) with the assets they load from `/web/`, all go
    // through this proxy, and Origin's session cookie lands on this host. Deployed, Origin has a
    // host of its own (`origin.<base>`), and the app's host serves none of these paths.
    //
    // ⛔ EVERY KEY IS A REGEX, AND THE ANCHORS ARE LOAD-BEARING. A plain string key is a PREFIX
    // match, so `'/setup'` would also capture the SPA's own `/setup` route and hand it to Origin.
    // The web app keeps `/setup`, `/auth/callback` (where Origin returns its sign-in code to this
    // app), `/reset-password` and `/verify-email`; `/login` is Origin's sign-in page, and the web
    // app's own sign-in route is reached by in-app navigation.
    //
    // ⚠ `/auth/authorizer/*` IS NOT EXCEPTED HERE, and must not be. Facet's own client decides that
    // split before the request leaves the browser (`src/api/api.ts:isOriginAuthPath`), so such a
    // call is already addressed elsewhere.
    proxy: {
      '^/auth/(?!callback(?:$|[/?]))': { target: DEV_ORIGIN, changeOrigin: true },
      '^/setup/': { target: DEV_ORIGIN, changeOrigin: true },
      // Both services serve `/system/*`; Mantle's half is reached at Mantle's own address
      // (`onMantle` in `api.ts`), so anything at this host's root is Origin's.
      '^/system/': { target: DEV_ORIGIN, changeOrigin: true },
      '^/\\.well-known/':{ target: DEV_ORIGIN, changeOrigin: true },
      '^/version$': { target: DEV_ORIGIN, changeOrigin: true },
      // Origin's own pages and their assets.
      '^/web/': { target: DEV_ORIGIN, changeOrigin: true },
      '^/(?:login|passkey|account|logout)(?:$|[/?])': { target: DEV_ORIGIN, changeOrigin: true },
      // No `/api` rule: Mantle is reached at its own address (`public/config.js`), deployed and
      // here alike, and answers this origin cross-origin (`MANTLE_CORS_ORIGINS`; review 7, F1).
    },

    watch: {
      // Ignore common directories that shouldn't trigger reloads
      ignored: [
        '**/node_modules/**',
        '**/.git/**',
        '**/.vscode/**',
        '**/dist/**',
        '**/.DS_Store',
        '**/*.log',
        '**/package-lock.json',
      ],
    },
  },
})
