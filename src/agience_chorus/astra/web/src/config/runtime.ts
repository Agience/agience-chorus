type RuntimeConfig = {
  mantleUri: string;
  originUri: string;
  crystalUri: string;
  clientId: string;
  title: string;
  favicon: string;
  /**
   * The IdP's login surface (e.g. `https://origin.agience.ai`). Set this when this
   * deployment is a **service provider**: the app has no login page of its own and
   * deep-links to Origin, which returns the token in the URL fragment.
   * Empty (the default) means this deployment is the IdP login surface and renders
   * the login form itself. One login screen for the whole platform.
   */
  idpUri: string;
};

const DEFAULT_CONFIG: RuntimeConfig = {
  mantleUri:
    import.meta.env.VITE_MANTLE_URI ||
    'http://localhost:8081',
  originUri: import.meta.env.VITE_ORIGIN_URI || 'http://localhost:8080',
  crystalUri: import.meta.env.VITE_CRYSTAL_URI || 'http://localhost:8085',
  clientId: import.meta.env.VITE_CLIENT_ID || 'agience-client',
  title: import.meta.env.VITE_TITLE || 'Agience',
  favicon: import.meta.env.VITE_FAVICON || '/favicon.png',
  idpUri: import.meta.env.VITE_IDP_URI || '',
};

function normalizeString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

export function getRuntimeConfig(): RuntimeConfig {
  const runtimeConfig = window.__AGIENCE_CONFIG__;

  if (!runtimeConfig) {
    return DEFAULT_CONFIG;
  }

  return {
    mantleUri: normalizeString(
      runtimeConfig.mantleUri ?? runtimeConfig.backendUri,
      DEFAULT_CONFIG.mantleUri,
    ),
    originUri: normalizeString(runtimeConfig.originUri, DEFAULT_CONFIG.originUri),
    crystalUri: normalizeString(runtimeConfig.crystalUri, DEFAULT_CONFIG.crystalUri),
    clientId: normalizeString(runtimeConfig.clientId, DEFAULT_CONFIG.clientId),
    title: normalizeString(runtimeConfig.title, DEFAULT_CONFIG.title),
    favicon: normalizeString(runtimeConfig.favicon, DEFAULT_CONFIG.favicon),
    idpUri: normalizeString(runtimeConfig.idpUri, DEFAULT_CONFIG.idpUri),
  };
}

export function applyDocumentConfig(): void {
  const config = getRuntimeConfig();
  document.title = config.title;

  let favicon = document.querySelector<HTMLLinkElement>('link[data-agience-favicon]');
  if (!favicon) {
    favicon = document.createElement('link');
    favicon.rel = 'icon';
    favicon.setAttribute('data-agience-favicon', 'true');
    document.head.appendChild(favicon);
  }

  favicon.href = config.favicon;
}