// window.__AGIENCE_CONFIG__ — the runtime config the SPA reads. Keys must match
// `src/config/runtime.ts`.
//
// This file is served as-is when the facet is mounted by the host (`crystal/web_serve.py`), which
// runs no entrypoint script. In the nginx container it is OVERWRITTEN at startup by
// `docker/40-runtime-config.sh` from container env; the derivation below is then irrelevant, which
// is correct — an operator who states the URIs outranks any convention.
//
// ── WHY THE URIS ARE DERIVED RATHER THAN BAKED ────────────────────────────────────────────────
// A node serves its services as siblings under one base: `workspace.home.agience.ai` sits beside
// `origin.home.agience.ai` and `mantle.home.agience.ai`, under one wildcard certificate. That is
// not this file's invention — `agience-cloud/scripts/service_common.sh` derives `CRYSTAL_URI` as
// `https://crystal.${CRYSTAL_HOST_DOMAIN}` and `crystal/host.py` routes by stripping the same base
// off the Host header. Deriving here reads the convention the node already runs on, so a facet
// served at a new name needs no per-deployment file and cannot be shipped pointing at the node it
// was built beside.
//
// ⚠ A DERIVED URI IS A DEFAULT, NEVER AN ASSERTION THAT THE SERVICE IS THERE. `crystal.<base>` in
// particular resolves on this node to the persona host, which does not serve the op-dispatch
// surface (`crystal/main.py` does, and is not what runs here) — so op calls fail at their own
// address rather than being silently rerouted. That is the honest failure; see the note in
// `src/api/api.ts`.
(function () {
  'use strict';

  // The platform's first-party OAuth client. `agience-client` is Origin's built-in
  // `PLATFORM_CLIENT_ID` default and what every node in `_fleet/peers` enrols.
  //
  // ⛔ THIS FILE SAID `platform`, AND NO AUTHORITY HAS EVER KNOWN THAT NAME. Measured against the
  // live home authority 2026-08-27: `/auth/authorize?client_id=platform` -> 400, and
  // `client_id=agience-client` -> 403 (the redirect_uri allowlist, a separate fix). Origin refuses
  // a client_id that is neither in `PLATFORM_CLIENT_IDS` nor registered in `oauth_clients`, so the
  // sign-in never reached a login page.
  var CLIENT_ID = 'agience-client';

  // A host of the form `<facet>.<base>` where `<base>` itself carries a dot — the shape every
  // deployed node uses. Bare hostnames, `localhost` and IP literals do not match and fall through
  // to the local-dev ports below, which is the whole of the local/deployed distinction.
  var host = window.location.hostname || '';
  var sibling = /^[^.]+\.([^.]+\..+)$/.exec(host);
  var isIp = /^[0-9.]+$/.test(host) || host.indexOf(':') !== -1;

  var config;
  if (sibling && !isIp) {
    var base = window.location.protocol + '//';
    config = {
      originUri: base + 'origin.' + sibling[1],
      mantleUri: base + 'mantle.' + sibling[1],
      crystalUri: base + 'crystal.' + sibling[1],
      clientId: CLIENT_ID,
      title: 'Agience',
      favicon: '/favicon.png',
    };
  } else {
    // Local dev: `npm run dev` on :5173 against services on loopback.
    config = {
      originUri: 'http://localhost:8080',
      mantleUri: 'http://localhost:8081',
      crystalUri: 'http://localhost:8085',
      clientId: CLIENT_ID,
      title: 'Agience',
      favicon: '/favicon.png',
    };
  }

  // An already-present config wins: a deployment that states its URIs is never second-guessed.
  window.__AGIENCE_CONFIG__ = window.__AGIENCE_CONFIG__ || Object.freeze(config);
})();
