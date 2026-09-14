# Facet browser tests

Specs here drive a real Chrome against a running Facet. They are the counterpart to the
vitest suite in `../tests/`, which renders components under jsdom with `src/api/api`
replaced by a mock that resolves every call with `{ data: {} }`.

That difference is the point. The jsdom suite asserts on what the app *asks for*; it cannot
see a changed response shape, a 401, a CORS rejection, or an endpoint that no longer exists.
It also cannot exercise the three things that decide whether a deployed Facet works at all:

- **Runtime config injection.** `src/config/runtime.ts` reads `window.__AGIENCE_CONFIG__`,
  written at deploy time, and falls back to `localhost:8081/8080/8085`. That object chooses
  which Mantle, Origin and Crystal the build talks to.
- **The IdP handoff.** With `idpUri` set, Facet has no login page — it deep-links to Origin,
  which returns the token in the URL fragment. A cross-origin redirect carrying a fragment
  is outside what jsdom models.
- **Radix and TipTap.** Portals, focus traps and contenteditable need real layout, a real
  focus model and real pointer events.

## Naming

Files must end in `.e2e.ts`. Vitest's default `include` matches `*.{test,spec}.*` anywhere
under the project root, so a spec named `*.spec.ts` here would be collected by `npm test`
as well and fail. The suffix is the whole isolation mechanism; see `playwright.config.ts`.

## Running

| Command | What it does |
|---|---|
| `npm run test:e2e` | Headless run. Starts a dev server on 5173 unless one is up. |
| `npm run test:e2e:ui` | UI Mode: pick a spec, watch it run, step backward through it, re-run on save. |
| `npm run test:e2e -- --headed` | Watch it happen in a visible Chrome window. |
| `npm run test:e2e -- --debug` | Step through with the Playwright Inspector. |

Point at something already running instead of starting a dev server:

```
FACET_E2E_BASE_URL=https://my.agience.ai npm run test:e2e
```

## Driving the browser from Claude Code

The specs above are the regression net. For exploring — reproducing a report, confirming a fix
once, reading what the app actually asks the backend for — Claude drives a real Chrome through the
**Playwright MCP server**, which shares this project's browser and locator syntax, so a session
converts into a spec here without rewriting it.

⛔ **THE SERVER IS CONFIGURED AT USER SCOPE, SO NO REPOSITORY CARRIES IT.** It lives under
`mcpServers.playwright` in `~/.claude.json` — not pushed, not visible to another machine, and not
restorable from any checkout. This block is the whole of it:

```json
"playwright": {
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@playwright/mcp@latest", "--browser", "chrome", "--caps", "devtools"]
}
```

`--browser chrome` drives the installed Google Chrome rather than Playwright's bundled Chromium,
matching `channel: 'chrome'` in `playwright.config.ts` — one browser for both paths. Headed is the
default, so the window is visible while it works. Adding or changing the entry takes effect only
after the session restarts; the config is read at startup.

⚠ **THE PUBLISHED TOOL LIST OVERSTATES WHAT THE SERVER EXPOSES.** Measured against the running
server: **24 tools by default, 44 with every capability enabled.** `--caps devtools` adds tracing,
video, recording and highlighting. Absent in every combination — `browser_verify_*`,
`browser_cookie_*`, `browser_localstorage_*`, `browser_storage_state`, `browser_route`. Storage and
cookies are reachable through `browser_evaluate`, and request interception through
`browser_run_code_unsafe`, which executes arbitrary code in the Playwright process and is
RCE-equivalent by its own description. Read the surface from `tools/list`, never from a README.

⛔ **THE BROWSER RUNS ON THE WORKSTATION, NEVER ON `astra`.** That box terminates TLS for every
`agience.ai` name on 1 GB of RAM with a disk above 85% used; a Chromium there risks all five names,
not one. Point a local browser at the deployed site instead.

## What it needs running

A browser test needs something to test. Neither of these survives the session that started it —
`agience.py start` runs in the foreground, so a node launched as a child of a shell dies with it.
For a node that outlives the terminal, use the tray application or the node's scheduled task.

| | |
|---|---|
| the platform | `python package/install/cli/agience.py start` in `agience-observe` — origin 8080, mantle 8082, crystal 8085, ember 8091, all on 127.0.0.1 |
| this app | `npm run dev -- --port 5173 --strictPort` |

⚠ **`public/config.js` decides where the app points, not `src/config/runtime.ts`.** `index.html`
loads it, it sets `window.__AGIENCE_CONFIG__`, and `getRuntimeConfig()` prefers that over every
`import.meta.env` default — so the values in `runtime.ts` are a fallback that a browser never
reaches. Change the wrong one and nothing happens.

Its local-dev branch addresses the app's own origin (`originUri: '/'`, `mantleUri: '/api'`) and the
dev server proxies onward, mirroring `_fleet/conf.d/my.agience.ai.caddy`. Absolute loopback URLs
there do not work: neither origin nor mantle sends CORS headers, and neither needs to, because no
deployment makes a cross-origin request. Crystal is deliberately not proxied, matching the deployed
block, which has no route for it either.

## Does every endpoint this app calls exist?

The jsdom suite cannot answer that: `tests/utils/apiMock.js` replaces `src/api/api` and answers
every verb with `{data: {}}`, so a path nothing serves passes exactly like one that works. The
answer comes from a live node instead:

```
cd agience-cloud && python deploy/facet_contract_drift.py
```

It reads every call site in `src/api/`, routes each to the plane that owns it using the rules in
`src/api/api.ts`, and compares against what mantle, origin and crystal publish — then **probes**
each candidate before reporting it, because a path absent from a document may still be served. It
exits non-zero when a call site 404s at its own service. `deploy/test_facet_contract_drift.py`
gates the comparison itself and needs no node.

Run against a deployed node with `--base mantle=https://mantle.agience.ai`; a locally installed
node is built from the working trees and a deployed one is not, so the two can disagree.

## Writing one without writing one

`npx playwright codegen http://localhost:5173` opens Chrome with a recorder attached and
writes the code as you click. `--target playwright-test -o e2e/thing.e2e.ts` saves it
straight here.

## Failure artifacts

Traces, screenshots and video land in `test-results/`, the HTML report in
`playwright-report/`; both are gitignored. Open a trace — a DOM snapshot per step, with
network, console and a timeline — with `npx playwright show-trace <file>`.
