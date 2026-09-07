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

// Resolve a cross-repo build input across layouts so the same config builds in
// the standalone agience-facet repo and in the monorepo: env override, then
// vendored under ./vendor (standalone; populated by scripts/vendor-build-inputs.mjs),
// then monorepo-relative ../.. (facet sits at <repo>/src/facet there).
function firstExisting(paths: Array<string | undefined>): string | undefined {
  return paths.find((p): p is string => !!p && existsSync(p))
}

const buildInfoPath = firstExisting([
  process.env.FACET_BUILD_INFO,
  resolve(__dirname, 'vendor/build_info.json'),
  resolve(__dirname, '../../build_info.json'),
])

const buildInfoRaw = (buildInfoPath ? readFileSync(buildInfoPath, 'utf-8') : '{"version":"0.0.0-dev"}').replace(/^\uFEFF/, '')
const buildInfo = JSON.parse(buildInfoRaw)
const APP_VERSION: string = String(buildInfo.version ?? '')
const APP_BUILD_TIME: string = new Date().toISOString()
let APP_GIT_SHA = ''
try { APP_GIT_SHA = (process.env.GIT_SHA || execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()) } catch { /* not a git repo */ }

function discoverContentTypeRoots() {
  // facet/vite.config.ts -> __dirname = <repo>/src/facet
  //
  // Build-time scope is core primitives only (package/types) — a synchronous
  // bootstrap so first paint has the platform chrome. Facet does not scan the
  // chorus persona ui/ trees: server-owned types (and their viewers) are fetched
  // at runtime from the platform (GET /types/all → ContentTypesProvider). Facet
  // must not know about specific servers (they live in different instances).
  // The primitives are owned by agience-crystal (`src/types`).
  // Standalone they are vendored to ./vendor (scripts/vendor-build-inputs.mjs).
  // Missing -> [] (no primitives baked in; everything resolves at runtime via GET /types/all).
  const root = firstExisting([
    process.env.FACET_TYPES_ROOT,
    resolve(__dirname, 'vendor/package/types'),
    // Workspace fallback: <workspace>/agience-crystal/src/types, resolved relative to this
    // tree's actual location at agience-chorus/src/astra/web.
    resolve(__dirname, '../../../../agience-crystal/src/types'),
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
  ],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    env: {
      VITE_MANTLE_URI: 'http://localhost:8081',
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


