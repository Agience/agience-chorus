# Agience Facet

**An observation plane.**

Facet is the plane observations appear on — the platform's web frontend, the user-facing product
application. It is the React + TypeScript (Vite + Tailwind) application users interact with: the artifact
browser, search, collections, and the commit surface. Its runtime configuration is **injected at deploy
time** (`window.__AGIENCE_CONFIG__`, with localhost fallbacks), so a single build deploys anywhere.

Distinct from `www.agience.ai` (the marketing site) — Facet is the product UI.

## Layout

| Path | Purpose |
|---|---|
| `src/` | Application source: components, config (`config/runtime.ts`), product copy. |
| `index.html`, `vite.config.*`, `tailwind.config.js` | Build + styling. |
| `nginx.conf`, `Dockerfile` | Container serving. |
| `CLA.md`, `COMMERCIAL_LICENSE.md`, `COLOR_SCHEME.md` | Contribution, commercial, and design docs. |

## License

AGPL-3.0 (see [LICENSE](LICENSE)) — Facet is a platform service, dual-tracked with a commercial option.
Commercial licensing: connect@agience.ai.
