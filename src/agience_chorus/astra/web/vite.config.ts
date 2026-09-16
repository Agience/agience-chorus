import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { readFileSync, existsSync } from 'fs'
import { execSync } from 'child_process'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'
import { contentTypesPlugin } from './plugins/content-types-plugin'

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
const DEV_MANTLE = process.env.VITE_DEV_MANTLE ?? 'http://127.0.0.1:8082'

// ⭐ FACET VERSIONS ON ITS OWN CADENCE, AND `package.json` IS THE ONE PLACE THAT NUMBER IS WRITTEN
// [John, 2026-09-13]. This tree ships inside agience-chorus but does not follow chorus's release
// number — the UI is bumped when the UI ships.
//
// ⚠ `__APP_VERSION__` IS WHAT THE RUNNING APP DISPLAYS, so a second file carrying a version is a
// second answer to "what is deployed". There was one: a hand-edited `vendor/build_info.json` that
// nothing produced and nothing refreshed. It reached 0.3.2 while `package.json` still said 0.0.0,
// and no gate compared them. 0.3.2 is carried forward here so the displayed version does not walk
// backwards across this change.
//
// Read from disk rather than imported: an import would pull package.json into the module graph and
// ship its dependency list to the browser.
const pkgRaw = readFileSync(resolve(__dirname, 'package.json'), 'utf-8').replace(/^\uFEFF/, '')
const APP_VERSION: string = String(JSON.parse(pkgRaw).version ?? '')
const APP_BUILD_TIME: string = new Date().toISOString()
let APP_GIT_SHA = ''
try { APP_GIT_SHA = (process.env.GIT_SHA || execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()) } catch { /* not a git repo */ }

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
    resolve(__dirname, '../../../../../agience-crystal/src/types'),
  ])
  return root ? [root] : []
}

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
    __APP_BUILD_TIME__: JSON.stringify(APP_BUILD_TIME),
    __APP_GIT_SHA__: JSON.stringify(APP_GIT_SHA),
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
    // ⭐ `/version.json` IS GENERATED, BECAUSE THE HAND-MAINTAINED ONE WAS A THIRD ANSWER TO "WHAT
    // IS DEPLOYED" AND HAD BEEN WRONG FOR SIX MONTHS. `public/version.json` was copied verbatim
    // into every build; measured 2026-09-15 it said `0.1.23` / `2026-03-16` while `package.json`
    // said 0.3.2, and it was live at `https://my.agience.ai/version.json`. It is the same failure
    // the `__APP_VERSION__` note above describes for `vendor/build_info.json` — a second file
    // carrying a version that nothing regenerates — in a third place.
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
            { version: APP_VERSION, build_time: APP_BUILD_TIME, git_sha: APP_GIT_SHA },
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

    // ⭐ THE DEV SERVER PROXIES WHAT CADDY PROXIES, AND FOR THE SAME REASON.
    // `_fleet/conf.d/my.agience.ai.caddy` keeps `originUri` and `mantleUri` on the app's own host
    // and proxies outward, so the browser never makes a cross-origin request and no service needs
    // CORS. Without the same arrangement here the browser talks straight to 8080 and 8082 and is
    // refused: measured 2026-09-13, a fresh `/login` issued four requests and the browser blocked
    // all four — "No 'Access-Control-Allow-Origin' header is present" — while still rendering a
    // plausible login form, because the fallback for "cannot reach /auth/providers" looks like a
    // working page.
    //
    // ⚠ THE RULES BELOW MIRROR THAT CADDY BLOCK AND MUST KEEP MIRRORING IT. `/api` strips its
    // prefix and everything else does not, exactly as `handle_path` and `handle` do there. A dev
    // proxy that routes differently from production is a dev environment that cannot reproduce a
    // production bug — and worse, one that manufactures bugs of its own.
    //
    // ⚠ `/auth/authorizer/*` IS NOT EXCEPTED HERE, and must not be. Facet's own client decides that
    // split before the request leaves the browser (`src/api/api.ts:isOriginAuthPath`), so such a
    // call is already addressed to `/api/…` and never matches `/auth`. The Caddy block carries this
    // same warning: an exception here would be a second, silently diverging copy of the rule.
    // ⛔ EVERY KEY IS A REGEX, AND THE TRAILING SLASH IN IT IS LOAD-BEARING. A plain string key is
    // a PREFIX match, so `'/setup'` also captures the SPA's own `/setup` route and hands it to
    // Origin, which answers 404 — measured here 2026-09-13, the wizard route died the moment the
    // proxy was added. Caddy's `handle /setup/*` does not match bare `/setup`, so the app keeps it;
    // these anchored patterns reproduce that, and `/version` is exact because Caddy's `handle
    // /version` is exact.
    proxy: {
      '^/auth/': { target: DEV_ORIGIN, changeOrigin: true },
      '^/setup/': { target: DEV_ORIGIN, changeOrigin: true },
      // ⭐ `/system/*` AT THE ROOT IS ORIGIN'S HALF OF IT. Both services serve `/system/*`, which
      // is why `api.ts` exports `onOrigin`/`onMantle` instead of deriving it from the path — but
      // once both are reached through one host the distinction survives anyway: mantle's half
      // arrives under `/api/system/…` and is handled by the rule below, so anything still at the
      // root is origin's. Measured 2026-09-13: without this, `GET /system/settings` answered 200
      // with `index.html`, and the deployed block has the same gap.
      '^/system/': { target: DEV_ORIGIN, changeOrigin: true },
      '^/\\.well-known/': { target: DEV_ORIGIN, changeOrigin: true },
      '^/version$': { target: DEV_ORIGIN, changeOrigin: true },
      '^/api/': {
        target: DEV_MANTLE,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ''),
      },
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
